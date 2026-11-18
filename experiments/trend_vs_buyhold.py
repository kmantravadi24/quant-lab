"""Research study: does trend following improve downside risk versus buy-and-hold?

Run:  python experiments/trend_vs_buyhold.py            (real data, needs network)
      python experiments/trend_vs_buyhold.py --synthetic (offline pipeline check only)

The protocol below was fixed before the out-of-sample period was evaluated.
See RESEARCH.md for the write-up and interpretation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from quantlab.analytics import metrics as m
from quantlab.backtesting import backtest_strategy
from quantlab.data import CachedProvider, DataError, SyntheticProvider, YFinanceProvider
from quantlab.execution import ExecutionConfig
from quantlab.reporting import markdown_table, save_experiment
from quantlab.research import (
    TrialRegistry,
    bootstrap_ci,
    calendar_subperiods,
    chronological_split,
    cost_sensitivity,
    evaluate,
    parameter_grid,
    subperiod_table,
)
from quantlab.strategies import BuyAndHold, TrendFollowing

ROOT = Path(__file__).resolve().parents[1]

PROTOCOL = {
    "question": "Does a 50/200 SMA trend-following rule improve downside-risk characteristics "
    "relative to buy-and-hold after realistic transaction costs?",
    "primary_asset": "SPY",
    "secondary_assets": ["QQQ", "IWM"],
    "start": "1993-01-01",
    "end": "2026-10-31",  # exclusive; fixed so the sample does not move between runs
    "dev_end": "2012-12-31",  # development: start..2012; out-of-sample: 2013..end
    "primary_params": {"fast": 50, "slow": 200},  # the textbook pair, fixed ex ante, not tuned
    "grid": {"fast": [20, 50, 100], "slow": [100, 150, 200, 250]},  # sensitivity, dev only
    "execution": asdict(ExecutionConfig(slippage_bps=2.0, fee_bps=1.0)),  # 3 bps one-way
    "cost_levels_bps": [0, 3, 10, 25, 50],
    "risk_free": 0.0,  # cash earns nothing in the engine either: conservative for the strategy
    "bootstrap": {"method": "stationary", "block": 63, "n_boot": 2000, "seed": 20260101},
    # Three primary downside metrics -> Bonferroni: each interval at 1 - 0.05/3.
    "primary_metrics": ["max_drawdown", "es_95", "downside_deviation"],
    "family_alpha": 0.05,
}

# Each statistic is oriented so that a POSITIVE value favours trend following.
IMPROVEMENTS = {
    "max_drawdown": lambda d: m.max_drawdown(d["strategy"]) - m.max_drawdown(d["benchmark"]),
    "es_95": lambda d: m.historical_es(d["benchmark"]) - m.historical_es(d["strategy"]),
    "downside_deviation": lambda d: m.downside_deviation(d["benchmark"])
    - m.downside_deviation(d["strategy"]),
    "cagr": lambda d: m.cagr(d["strategy"]) - m.cagr(d["benchmark"]),
    "sharpe": lambda d: m.sharpe(d["strategy"]) - m.sharpe(d["benchmark"]),
}
SHOW = ["cagr", "volatility", "sharpe", "sortino", "max_drawdown", "max_drawdown_duration",
        "es_95", "downside_deviation", "turnover", "trade_count"]  # fmt: skip
FMT = {k: ".2%" for k in ("cagr", "volatility", "max_drawdown", "es_95", "downside_deviation",
                           "total_return", "estimate", "lower", "upper")}  # fmt: skip
FMT |= {"max_drawdown_duration": ".0f", "trade_count": ".0f", "turnover": ".2f"}


def fingerprint(df: pd.DataFrame) -> str:
    return hashlib.sha256(df.round(6).to_csv().encode()).hexdigest()[:16]


def improvement_intervals(pair: pd.DataFrame, protocol: dict, confirmatory: bool) -> pd.DataFrame:
    """Bootstrap intervals. Only the primary asset's primary metrics are confirmatory.

    Those three are run at the Bonferroni-adjusted level. Everything else (other
    metrics, other assets) is exploratory: plain 95% intervals with no
    multiplicity control, not to be read as significance tests.
    """
    boot = protocol["bootstrap"]
    k = len(protocol["primary_metrics"])
    rows = {}
    for name, stat in IMPROVEMENTS.items():
        primary = confirmatory and name in protocol["primary_metrics"]
        conf = 1 - protocol["family_alpha"] / k if primary else 0.95
        res = bootstrap_ci(pair, stat, confidence=conf, **boot)
        rows[name] = {
            "role": "confirmatory" if primary else "exploratory",
            "estimate": res.estimate, "lower": res.lower, "upper": res.upper,
            "confidence": conf, "excludes_zero": res.excludes_zero,
        }  # fmt: skip
    return pd.DataFrame(rows).T


def show_intervals(table: pd.DataFrame) -> pd.DataFrame:
    """Format interval rows: Sharpe in ratio units, everything else in percent."""
    out = table.copy().astype(object)
    for name in out.index:
        spec = ".3f" if name == "sharpe" else ".2%"
        for col in ("estimate", "lower", "upper"):
            out.loc[name, col] = format(table.loc[name, col], spec)
        out.loc[name, "confidence"] = format(table.loc[name, "confidence"], ".1%")
    return out.rename_axis("improvement")


def study_asset(data, asset: str, protocol: dict, registry: TrialRegistry) -> dict:
    cfg = ExecutionConfig(**protocol["execution"])
    sub = data.select([asset])
    split = chronological_split(sub.dates, protocol["dev_end"])
    strategy = TrendFollowing(**protocol["primary_params"], tickers=(asset,))
    trend = backtest_strategy(strategy, sub, cfg)
    bench = backtest_strategy(BuyAndHold({asset: 1.0}), sub, cfg)
    runs = {"trend_50_200": trend, "buy_and_hold": bench}

    periods = {"development": split.development, "out_of_sample": split.test}
    tables = {}
    for label, (start, end) in periods.items():
        tables[label] = pd.DataFrame(
            {n: evaluate(r, start, end, risk_free=protocol["risk_free"]) for n, r in runs.items()}
        ).T[SHOW]
        registry.record("trend", {"asset": asset, **protocol["primary_params"]}, label)
        registry.record("buy_and_hold", {"asset": asset}, label)

    oos = pd.DataFrame({
        "strategy": trend.returns.loc[split.test[0] : split.test[1]],
        "benchmark": bench.returns.loc[split.test[0] : split.test[1]],
    })  # fmt: skip
    return {
        "split": split,
        "tables": tables,
        "intervals": improvement_intervals(oos, protocol, asset == protocol["primary_asset"]),
        "time_in_market_oos": float(
            (trend.holdings[asset].loc[split.test[0] : split.test[1]] > 0).mean()
        ),
        "runs": runs,
        "data": sub,
        "strategy": strategy,
        "cfg": cfg,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="store_true", help="offline run on fake GBM data")
    parser.add_argument(
        "--verify", action="store_true",
        help="re-run into a temporary folder and compare with the committed record; "
        "nothing in the repository is modified",
    )  # fmt: skip
    args = parser.parse_args()
    out_root = Path(tempfile.mkdtemp(prefix="quantlab_verify_")) if args.verify else ROOT
    protocol = dict(PROTOCOL)
    assets = [protocol["primary_asset"], *protocol["secondary_assets"]]

    if args.synthetic:
        provider, tag = SyntheticProvider(seed=1), "SYNTHETIC_"
    else:
        # Frozen snapshot: the first run downloads and stores the dataset under
        # experiments/data; every later run reads exactly those files, so results do
        # not drift when Yahoo revises adjusted prices. Delete the folder to refresh.
        provider = CachedProvider(YFinanceProvider(), ROOT / "experiments" / "data", float("inf"))
        tag = ""
    try:
        data = provider.fetch(assets, protocol["start"], protocol["end"])
    except DataError as exc:
        sys.exit(
            f"Could not load the study data: {exc}\n"
            "The reference dataset is not part of public copies of this project. Without it the "
            "study downloads the same tickers from Yahoo Finance, which needs an internet "
            "connection and may be rate limited. See docs/DATA.md."
        )
    registry = TrialRegistry()

    studies = {a: study_asset(data, a, protocol, registry) for a in assets}
    main_study = studies[protocol["primary_asset"]]
    split = main_study["split"]

    # Robustness, primary asset. The parameter grid touches the DEVELOPMENT period only.
    grid_registry = TrialRegistry()
    grid = parameter_grid(
        lambda fast, slow: TrendFollowing(fast, slow, tickers=(protocol["primary_asset"],)),
        protocol["grid"], main_study["data"], main_study["cfg"],
        *split.development, registry=grid_registry,
    )  # fmt: skip
    for t in grid_registry.trials:
        registry.record("trend", {"asset": protocol["primary_asset"], **t["params"]}, t["period"])
    for bps in protocol["cost_levels_bps"]:
        registry.record(
            "trend",
            {"asset": protocol["primary_asset"], **protocol["primary_params"], "cost_bps": bps},
            "out_of_sample",
        )
    oos_looks = sum(t["period"] == "out_of_sample" for t in registry.trials)
    bench_dev = main_study["tables"]["development"].loc["buy_and_hold"]
    grid["mdd_better_than_bh"] = grid["max_drawdown"] > bench_dev["max_drawdown"]
    costs = cost_sensitivity(
        main_study["strategy"], main_study["data"], protocol["cost_levels_bps"],
        main_study["cfg"], *split.test,
    )[["cagr", "sharpe", "max_drawdown", "es_95", "turnover"]]  # fmt: skip
    subs = subperiod_table(
        main_study["runs"], calendar_subperiods(main_study["data"].dates, 5),
        ["cagr", "volatility", "max_drawdown", "es_95"],
    )  # fmt: skip

    results = {
        "data_fingerprint_close": fingerprint(data.close),
        "trials_evaluated": registry.count,
        "distinct_configurations": registry.distinct_configurations(),
        "out_of_sample_evaluations": oos_looks,
        "configurations_selected_using_out_of_sample_data": 0,
        "assets": {
            a: {
                "split": s["split"].to_dict(),
                "development": s["tables"]["development"],
                "out_of_sample": s["tables"]["out_of_sample"],
                "improvement_intervals": s["intervals"],
                "time_in_market_oos": s["time_in_market_oos"],
            }
            for a, s in studies.items()
        },
        "dev_parameter_grid": grid,
        "oos_cost_sensitivity": costs,
        "subperiods": subs,
    }
    record = save_experiment(
        f"{tag}trend_vs_buyhold", protocol, data.metadata.to_dict(), results,
        out_root / "experiments" / "results",
    )  # fmt: skip

    # ------------------------------------------------------------------ report
    md = [f"# Trend following vs buy-and-hold: results ({'SYNTHETIC DATA' if tag else 'SPY'})", ""]
    if tag:
        md += ["> **Synthetic GBM data. Pipeline check only; these numbers mean nothing.**", ""]
    md += [
        f"- Record: `{record.relative_to(out_root)}`",
        f"- Data: {data.metadata.source}, {data.metadata.start} to {data.metadata.end}, "
        f"retrieved {data.metadata.retrieved_at}, close fingerprint "
        f"`{results['data_fingerprint_close']}`",
        f"- Adjustment: {data.metadata.adjustment}",
        f"- Costs: {protocol['execution']['slippage_bps']} bps slippage + "
        f"{protocol['execution']['fee_bps']} bps fee per side; signals at close T, "
        "fills at open T+1",
        f"- Evaluations logged: {registry.count} across "
        f"{registry.distinct_configurations()} distinct strategy/asset/parameter/cost "
        f"configurations; {oos_looks} of them looked at the out-of-sample period, all with "
        "parameters fixed in advance. No configuration was chosen using out-of-sample data.",
        "",
    ]
    for asset, s in studies.items():
        role = "primary" if asset == protocol["primary_asset"] else "secondary, exploratory"
        sp = s["split"].to_dict()
        md += [f"## {asset} ({role})", ""]
        for label in ("development", "out_of_sample"):
            key = "test" if label == "out_of_sample" else label
            md += [f"**{label.replace('_', ' ').title()}** ({sp[key][0]} to {sp[key][1]})", "",
                   markdown_table(s["tables"][label], FMT), ""]  # fmt: skip
        md += [
            f"Trend strategy was invested on {s['time_in_market_oos']:.0%} of out-of-sample "
            "sessions.", "",
            "**Out-of-sample difference, trend minus buy-and-hold** (positive favours trend; "
            "only rows marked confirmatory are multiplicity-adjusted tests; "
            f"paired stationary bootstrap, mean block {protocol['bootstrap']['block']} sessions, "
            f"{protocol['bootstrap']['n_boot']} resamples)", "",
            markdown_table(show_intervals(s["intervals"])), "",
        ]  # fmt: skip
    md += [
        "## Robustness (SPY)", "",
        "**Parameter sensitivity, development period only**", "",
        markdown_table(grid[["fast", "slow", "cagr", "sharpe", "max_drawdown", "es_95",
                             "mdd_better_than_bh"]].set_index("fast"), FMT), "",
        f"Buy-and-hold development max drawdown: {bench_dev['max_drawdown']:.2%}. "
        f"{int(grid['mdd_better_than_bh'].sum())} of {len(grid)} parameter pairs had a "
        "shallower drawdown.", "",
        "**Transaction-cost sensitivity, out-of-sample** (total one-way cost)", "",
        markdown_table(costs.rename(index=lambda b: f"{b:g}"), FMT), "",
        "**Five-year subperiods, full sample**", "",
        markdown_table(subs, FMT), "",
    ]  # fmt: skip
    report = out_root / "reports" / f"{tag}trend_vs_buyhold.md"
    report.parent.mkdir(exist_ok=True)
    report.write_text("\n".join(md))
    if args.verify:
        sys.exit(verify(record, results["data_fingerprint_close"]))
    print("\n".join(md))


def _numbers(obj, path=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from _numbers(value, f"{path}/{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from _numbers(value, f"{path}/{i}")
    elif isinstance(obj, float):
        yield path, obj


def verify(new_record: Path, fingerprint: str) -> int:
    """Compare a fresh run with the committed record. Returns a process exit code."""
    committed = ROOT / "experiments" / "results" / new_record.name
    if not committed.exists():
        print(f"FAIL: no committed record named {new_record.name} (protocol changed?)")
        return 1
    old = dict(_numbers(json.loads(committed.read_text())["results"]))
    new = dict(_numbers(json.loads(new_record.read_text())["results"]))
    expected = json.loads((ROOT / "experiments" / "MANIFEST.json").read_text())["dataset"]
    same_data = fingerprint == expected["close_fingerprint"]
    if old.keys() != new.keys():
        print("FAIL: result structure differs from the committed record")
        return 1
    worst = max(abs(old[k] - new[k]) for k in old)
    print(f"dataset fingerprint {fingerprint} "
          f"({'matches' if same_data else 'DIFFERS from'} the original snapshot)")
    print(f"{len(old)} numeric results compared; largest absolute difference {worst:.3g}")
    if worst <= 1e-9:
        print("PASS: the committed record is reproduced")
        return 0
    if not same_data:
        print("PARTIAL: data is not the original snapshot (re-downloaded and since revised by "
              "the provider), so small differences are expected")
        return 0 if worst < 5e-3 else 1
    print("FAIL: same data, different results")
    return 1


if __name__ == "__main__":
    main()
