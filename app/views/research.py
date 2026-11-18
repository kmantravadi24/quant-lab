import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from components import theme
from components.common import ROOT, downloads, figure, header, load_data, show, stats_table

from quantlab.analytics import metrics as m
from quantlab.backtesting import backtest_strategy
from quantlab.execution import ExecutionConfig
from quantlab.reporting import csv_bytes
from quantlab.research import (
    TrialRegistry,
    bootstrap_ci,
    chronological_split,
    cost_sensitivity,
    evaluate,
    parameter_grid,
)
from quantlab.strategies import BuyAndHold, TrendFollowing

# Each improvement row states its own subtraction (QA-013, QA-014). Positive favours trend.
HOW = {
    "max_drawdown": "trend - buy & hold (drawdowns are negative: shallower is +)",
    "es_95": "buy & hold - trend (a smaller loss is +)",
    "downside_deviation": "buy & hold - trend (smaller is +)",
    "cagr": "trend - buy & hold",
    "sharpe": "trend - buy & hold",
}
HOW_LAB = {
    "Max drawdown (shallower is +)": HOW["max_drawdown"],
    "1-day ES 95% (smaller is +)": HOW["es_95"],
    "CAGR": HOW["cagr"],
}

header("Research & Reporting", "A published study you can check, and a lab for testing how fragile a result is.")
data = load_data()
t_study, t_lab, t_repro = st.tabs(["Published study", "Validation lab", "Reproducibility"])

results_dir = ROOT / "experiments" / "results"
record_path = next(iter(sorted(results_dir.glob("trend_vs_buyhold_*.json"))), None)
# Public copies ship no real-data record; fall back to the synthetic pipeline-check run.
if record_path is None:
    record_path = next(iter(sorted(results_dir.glob("SYNTHETIC_trend_vs_buyhold_*.json"))), None)
manifest_path = ROOT / "experiments" / "MANIFEST.json"

with t_study:
    if record_path is None:
        st.info("No study record in this copy. Results computed on the private reference data are not "
                "published (redistribution rights not established). Run "
                "`python experiments/trend_vs_buyhold.py` on data you are licensed to use.")
    else:
        rec = json.loads(record_path.read_text())
        cfg, res = rec["config"], rec["results"]
        synthetic = bool(rec["data"].get("synthetic"))
        spy = res["assets"][cfg["primary_asset"]]
        asset_label = f"{cfg['primary_asset']} (simulated series)" if synthetic else cfg["primary_asset"]
        st.markdown(f"#### {cfg['question']}" + (" (synthetic-data run)" if synthetic else ""))
        if synthetic:
            st.warning(
                "**SYNTHETIC-DATA STUDY: pipeline check only.** This record was produced by "
                "`python experiments/trend_vs_buyhold.py --synthetic` on simulated random-walk prices "
                f"that merely carry the names {', '.join(rec['data']['tickers'])}. They are not market "
                "data, so these numbers say nothing about the real instruments or about whether the rule "
                "works. Results computed on the private reference data are not published "
                "(redistribution rights not established)."
            )
        else:
            st.warning(
                "**Read as a historical finding.** The evaluation period (2013 onward) was held back "
                "while the rule was fixed, but it has since been examined twice (the original run and "
                "an audit). It is no longer untouched data, and nothing here is a forecast. The study "
                "always uses its own frozen dataset, not the dataset selected in the sidebar."
            )
        oos = {(r.get("name") or r.get("index")): r for r in spy["out_of_sample"]}
        show_keys = ["cagr", "volatility", "sharpe", "max_drawdown", "es_95", "downside_deviation", "trade_count"]
        table = stats_table({"Trend 50/200": {k: oos["trend_50_200"][k] for k in show_keys},
                             "Buy and hold": {k: oos["buy_and_hold"][k] for k in show_keys}})  # fmt: skip
        left, right = st.columns([3, 2])
        with left:
            st.markdown(f"**{asset_label}, evaluation period {spy['split']['test'][0]} to {spy['split']['test'][1]}**")
            st.dataframe(table, width="stretch")
            ci = pd.DataFrame(spy["improvement_intervals"])
            ci = ci.rename(columns={ci.columns[0]: "metric"}).set_index("metric")
            shown = pd.DataFrame({
                "Status": list(ci["role"]),
                "Computed as": [HOW.get(i, "trend - buy & hold") for i in ci.index],
                "Improvement": [f"{v:+.3f}" if i == "sharpe" else f"{v:+.2%}" for i, v in ci["estimate"].items()],
                "Interval": [f"{lo:+.3f} to {hi:+.3f}" if i == "sharpe" else f"{lo:+.2%} to {hi:+.2%}"
                             for i, lo, hi in zip(ci.index, ci["lower"], ci["upper"], strict=True)],
                "Level": [f"{c:.1%}" for c in ci["confidence"]],
                "Excl. 0": ["yes" if e else "no" for e in ci["excludes_zero"]],
            }, index=[i.replace("_", " ") for i in ci.index])  # fmt: skip
            st.dataframe(shown, width="stretch")
            st.caption("Improvement is oriented so that **positive always favours trend following**. "
                       "For return-type rows it is trend minus buy-and-hold; for loss-type rows "
                       "(expected shortfall, downside deviation) it is buy-and-hold minus trend, "
                       "because a smaller loss is better. 'Computed as' states each row's "
                       "subtraction. 'Excl. 0' says whether the interval excludes zero. Only rows marked *confirmatory* were "
                       "specified in advance and adjusted for testing three metrics; *exploratory* "
                       "rows are descriptive and are not significance tests.")  # fmt: skip
        with right:
            # Generated from the record, never typed in: the numbers cannot drift from it.
            t, b = oos["trend_50_200"], oos["buy_and_hold"]
            years = (pd.Timestamp(spy["split"]["test"][1]) - pd.Timestamp(spy["split"]["test"][0])).days / 365.25
            same_dd = abs(t["max_drawdown"] - b["max_drawdown"]) < 1e-6
            dd = (f"identical for both ({t['max_drawdown']:.1%})" if same_dd else
                  f"{t['max_drawdown']:.1%} for trend vs {b['max_drawdown']:.1%} for buy and hold")  # fmt: skip
            st.markdown(
                "**What it found**\n\n"
                f"- The largest loss was {dd}.\n"
                f"- 1-day expected shortfall (95%): {t['es_95']:.2%} for trend vs {b['es_95']:.2%}.\n"
                f"- Annual return (CAGR): {t['cagr']:.2%} vs {b['cagr']:.2%}, a difference of "
                f"{(t['cagr'] - b['cagr']) * 100:+.1f} points.\n"
                f"- The rule traded {t['trade_count'] / years:.1f} times a year on average.\n\n"
                + ("**Conclusion:** none is drawn. The prices are simulated, so this run only shows "
                   "that the study pipeline works end to end; it is not evidence for or against the "
                   "rule on any real market." if synthetic else
                   "**Conclusion:** the evidence does not support the claim that this rule improved "
                   f"downside risk over {spy['split']['test'][0][:4]} to {spy['split']['test'][1][:4]}.")
            )  # fmt: skip
        with st.expander("Protocol: what was fixed in advance"):
            ex = cfg["execution"]
            st.table(pd.DataFrame({"Setting": {
                "Rule": f"long when SMA({cfg['primary_params']['fast']}) > SMA({cfg['primary_params']['slow']}), else cash (not tuned)",
                "Development period": f"{spy['split']['development'][0]} to {spy['split']['development'][1]}",
                "Evaluation period": f"{spy['split']['test'][0]} to {spy['split']['test'][1]}",
                "Timing": "signal at close of T, fill at open of T+1",
                "Costs": f"{ex['slippage_bps']} bps slippage + {ex['fee_bps']} bps fee per trade",
                "Confirmatory metrics": ", ".join(cfg["primary_metrics"]) + " (Bonferroni across the three)",
                "Uncertainty": f"paired stationary bootstrap, mean block {cfg['bootstrap']['block']} sessions, "
                               f"{cfg['bootstrap']['n_boot']} resamples, seed {cfg['bootstrap']['seed']}",
                "Evaluations logged": f"{res['trials_evaluated']} ({res['distinct_configurations']} distinct); "
                                      f"{res['configurations_selected_using_out_of_sample_data']} chosen using evaluation-period data",
            }}))  # fmt: skip
        with st.expander("Dataset"):
            d = rec["data"]
            st.table(pd.DataFrame({"Value": {
                "Provider": d["source"], "Retrieved": d["retrieved_at"], "Instruments": ", ".join(d["tickers"]),
                "Coverage": f"{d['start']} to {d['end']}", "Adjustment": d["adjustment"],
                "Close-price fingerprint": res["data_fingerprint_close"],
            }}))  # fmt: skip
        with st.expander("Limitations"):
            st.markdown(
                "- **Small sample for drawdowns:** only a handful of market falls in the evaluation period.\n"
                "- **Hindsight in the choice of rule and assets:** 50/200 is famous because of the history used for development; the ETFs were chosen knowing they survived.\n"
                "- **Data:** provider-adjusted prices are revised over time and are not traded quotes.\n"
                "- **Simplifications:** cash earns nothing, flat cost model, long-only.\n"
                "- **Bootstrap:** resamples realized returns and assumes the period is representative."
            )
        report = ROOT / "reports" / f"{'SYNTHETIC_' if synthetic else ''}trend_vs_buyhold.md"
        with st.expander("Full result tables (development period, other assets, robustness)"):
            st.markdown(report.read_text() if report.exists() else "Report file not found.")
        files = {"Experiment record (JSON)": (record_path.read_bytes(), record_path.name)}
        if report.exists():
            files["Result tables (Markdown)"] = (report.read_bytes(), report.name)
        if (ROOT / "RESEARCH.md").exists():
            files["Research write-up (Markdown)"] = ((ROOT / "RESEARCH.md").read_bytes(), "RESEARCH.md")
        downloads(files, "study")

with t_lab:
    st.info("**Exploratory.** Use this to see how sensitive a trend rule is to its settings on the "
            "dataset in the sidebar. Anything found here is a hypothesis, not a validated result: "
            "you are choosing settings after seeing outcomes.")  # fmt: skip
    c = st.columns(4)
    asset = c[0].selectbox("Asset", data.tickers)
    sub = data.select([asset])
    if len(sub.dates) < 756:
        st.error(f"{asset} has {len(sub.dates)} sessions. A development / evaluation split needs at "
                 "least three years (756): load more history.")  # fmt: skip
        st.stop()
    default_split = sub.dates[int(len(sub.dates) * 0.6)].date()
    dev_end = c[1].date_input("Development period ends", default_split,
                              min_value=sub.dates[252].date(), max_value=sub.dates[-253].date())  # fmt: skip
    fast = c[2].number_input("Fast average", 2, 400, 50)
    slow = c[3].number_input("Slow average", 3, 600, 200)
    if fast >= slow:
        st.error("The fast window must be shorter than the slow window.")
        st.stop()
    split = chronological_split(sub.dates, str(dev_end))
    cfg = ExecutionConfig()
    st.caption(f"Development {split.development[0].date()} to {split.development[1].date()} | "
               f"Evaluation {split.test[0].date()} to {split.test[1].date()} | split by date, never "
               "shuffled | 2 bps slippage + 1 bps fee per trade")  # fmt: skip
    strategy = TrendFollowing(int(fast), int(slow), (asset,))
    with st.spinner("Running backtests and resampling..."):
        trend = backtest_strategy(strategy, sub, cfg)
        bench = backtest_strategy(BuyAndHold({asset: 1.0}), sub, cfg)
        registry = TrialRegistry()
        grid = parameter_grid(
            lambda fast, slow: TrendFollowing(fast, slow, (asset,)),
            {"fast": [10, 20, 50, 100], "slow": [100, 150, 200, 250]},
            sub, cfg, *split.development, registry=registry,
        )  # fmt: skip
        costs = cost_sensitivity(strategy, sub, [0, 3, 10, 25, 50], cfg, *split.test)

    st.subheader("1. The same rule in two periods")
    cols = {}
    for label, (a, b) in (("development", split.development), ("evaluation", split.test)):
        cols[f"Trend, {label}"] = evaluate(trend, a, b)
        cols[f"Buy & hold, {label}"] = evaluate(bench, a, b)
    st.dataframe(stats_table(cols), width="stretch", height=530)

    st.subheader("2. Parameter sensitivity (development period only)")
    metric = st.radio("Metric", ["sharpe", "max_drawdown", "cagr"], horizontal=True,
                      format_func={"sharpe": "Sharpe ratio", "max_drawdown": "Max drawdown", "cagr": "CAGR"}.get)  # fmt: skip
    pivot = grid.pivot(index="fast", columns="slow", values=metric)
    pivot.index, pivot.columns = [f"fast {i}" for i in pivot.index], [f"slow {c}" for c in pivot.columns]
    fmt = ".2f" if metric == "sharpe" else ".1%"
    grid_fig = figure(height=300, x_title="Slow average", y_title="Fast average")
    grid_fig.add_trace(go.Heatmap(
        z=pivot.values, x=list(pivot.columns), y=list(pivot.index),
        colorscale=[[0, theme.SURFACE], [1, theme.ACCENT]], colorbar=dict(thickness=12),
        text=pivot.map(lambda v: "" if pd.isna(v) else format(v, fmt)).values, texttemplate="%{text}",
    ))  # fmt: skip
    grid_fig.update_layout(hovermode="closest", margin=dict(t=20))
    show(grid_fig)
    st.caption(f"{registry.count} settings were tried to fill this grid. The best cell is the one "
               "most likely to be flattered by luck; a broad plateau of similar values is more "
               "convincing than a single peak. The evaluation period was not used.")  # fmt: skip

    st.subheader("3. Does it survive higher trading costs? (evaluation period)")
    st.dataframe(costs[["cagr", "sharpe", "max_drawdown", "turnover"]].rename(
        columns={"cagr": "CAGR", "sharpe": "Sharpe", "max_drawdown": "Max drawdown", "turnover": "Turnover / year"})
        .rename_axis("Cost per trade (bps)").style.format({"CAGR": "{:.2%}", "Sharpe": "{:.2f}",
                                                           "Max drawdown": "{:.2%}", "Turnover / year": "{:.2f}"}),
        width="stretch")  # fmt: skip

    st.subheader("4. How sure can we be? (evaluation period)")
    pair = pd.DataFrame({"s": trend.returns, "b": bench.returns}).loc[split.test[0] : split.test[1]]
    n_boot = st.select_slider("Resamples", [200, 500, 1000, 2000], 500)
    tests = {
        "Max drawdown (shallower is +)": lambda d: m.max_drawdown(d["s"]) - m.max_drawdown(d["b"]),
        "1-day ES 95% (smaller is +)": lambda d: m.historical_es(d["b"]) - m.historical_es(d["s"]),
        "CAGR": lambda d: m.cagr(d["s"]) - m.cagr(d["b"]),
    }
    rows = {}
    with st.spinner("Bootstrapping..."):
        for name, fn in tests.items():
            r = bootstrap_ci(pair, fn, n_boot=n_boot, method="stationary", block=63, seed=1)
            rows[name] = {"Computed as": HOW_LAB[name], "Improvement (+ favours trend)": f"{r.estimate:+.2%}",
                          "95% interval": f"{r.lower:+.2%} to {r.upper:+.2%}",
                          "Interval excludes zero": "yes" if r.excludes_zero else "no"}  # fmt: skip
    st.dataframe(pd.DataFrame(rows).T, width="stretch")
    st.caption("Positive always favours trend following; 'Computed as' gives each row's subtraction "
               "(for expected shortfall, a positive loss, it is buy & hold minus trend). "
               "Block bootstrap (blocks of about 63 sessions, seed 1) with strategy and benchmark "
               "resampled together. It assumes the period is representative of the future. Three "
               "intervals are shown without adjustment, so one of them excluding zero is weak evidence.")  # fmt: skip
    downloads({"Parameter grid (CSV)": (csv_bytes(grid, index=False), "parameter_grid.csv"),
               "Cost sensitivity (CSV)": (csv_bytes(costs), "cost_sensitivity.csv")}, "lab")  # fmt: skip

with t_repro:
    st.markdown(
        """
**Reproduce the published study**

```bash
python experiments/trend_vs_buyhold.py --verify   # re-runs and compares with the stored record
```

`--verify` writes nothing into the repository. It prints how many numeric results were compared and
the largest difference. With the original frozen dataset the difference is zero.

**What makes a run reproducible here**

- Every experiment writes a record: configuration, its hash, data provenance and fingerprint, package versions, the git commit and whether the working tree was clean.
- Random numbers always come from an explicit seed.
- The dataset manifest lists a checksum for every data file.
"""
    )
    if manifest_path.exists():
        man = json.loads(manifest_path.read_text())
        ds = man["dataset"]
        st.table(pd.DataFrame({"Value": {
            "Dataset": ds["path"], "Provider": ds["provider"], "Retrieved": ds["retrieved_at"],
            "Coverage": " to ".join(ds["coverage"]), "Sessions": f"{ds['sessions']:,}",
            "Close fingerprint": ds["close_fingerprint"],
            "Present in this installation": "yes" if (ROOT / ds["path"]).exists() else "no (results will be re-downloaded and may differ slightly)",
            "Redistribution rights": man["rights"]["status"],
        }}))  # fmt: skip
        st.caption(man["rights"]["note"])
        st.caption(man["without_the_private_dataset"])
        downloads({"Dataset manifest (JSON)": (manifest_path.read_bytes(), "MANIFEST.json")}, "manifest")
    if record_path is not None:
        env = json.loads(record_path.read_text())["environment"]
        st.markdown("**Environment of the stored record**")
        st.table(pd.DataFrame({"Value": {k: str(v) for k, v in env.items()}}))
