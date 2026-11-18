"""Walk-forward validation of the Future Wealth return models.

Run:  python experiments/forecast_validation.py              (frozen snapshot, private data)
      python experiments/forecast_validation.py --synthetic  (offline pipeline check only)

Question: are the forecast distributions calibrated, and does any model beat the
simple normal baseline, when each forecast uses only data available at its origin?

The protocol below is fixed before running and hashed into the result file name.
These monthly returns come from the same snapshot used by the trend study (backlog
QA-033): they are not unseen data in general, but every forecast here is made from
data strictly before its outcome, and no setting was tuned on the outcomes.
Nothing here is evidence of a profitable predictive edge.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from quantlab.data import SyntheticProvider
from quantlab.data.providers import load_dataset
from quantlab.forecast import monthly_returns
from quantlab.forecast import validation as v
from quantlab.portfolio.compare import data_fingerprint
from quantlab.reporting.experiment import environment

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = {
    "question": "Are the Future Wealth return models calibrated out of sample, and does any "
    "beat a normal (Gaussian i.i.d.) baseline?",
    "portfolios": {
        "SPY": {"SPY": 1.0},
        "equal_SPY_QQQ_IWM": {"SPY": 1 / 3, "QQQ": 1 / 3, "IWM": 1 / 3},
    },
    "models": {
        "iid_bootstrap": {},
        "block_bootstrap": {"block": 12},
        "ewma_filtered": {"lam": 0.97},
        "gaussian_iid": {},
    },
    "baseline": "gaussian_iid",
    "horizons_months": [1, 12, 36],
    "windows": {"rolling 60 months": 60, "rolling 120 months": 120, "expanding": None},
    "min_months": 60,
    "n_paths": 1000,
    "origin_step_months": 1,
    "seed": 20261117,
    "decision_rule": "A model beats the baseline only if its mean CRPS is lower and a "
    "Diebold-Mariano test (Newey-West variance with h-1 lags, Harvey-Leybourne-Newbold "
    "small-sample correction, t p-values) rejects equality at 5% after Holm adjustment across "
    "the models tested at that portfolio, horizon and window. No test is attempted with fewer "
    "than 20 non-overlapping outcomes.",
    "history_of_this_protocol": "The minimum-outcome rule and the small-sample correction were "
    "added after the --synthetic pipeline check produced false 'wins' at 36 months on i.i.d. "
    "normal data, and before the real snapshot was evaluated.",
}


def protocol_hash(protocol: dict) -> str:
    return hashlib.sha256(json.dumps(protocol, sort_keys=True).encode()).hexdigest()[:12]


def load(synthetic: bool):
    if synthetic:
        return SyntheticProvider(11).fetch(["SPY", "QQQ", "IWM"], "1993-01-01", "2026-10-30")
    folders = sorted((ROOT / "experiments" / "data").glob("*"))
    if not folders:
        sys.exit("The frozen snapshot (experiments/data) is not present; use --synthetic.")
    return load_dataset(folders[0])


def md_table(frame: pd.DataFrame, columns: list[str], percent: set[str]) -> list[str]:
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for _, row in frame.iterrows():
        cells = []
        for c in columns:
            x = row[c]
            if isinstance(x, float):
                cells.append("n/a" if pd.isna(x) else (f"{x:.1%}" if c in percent else f"{x:.4f}"))
            else:
                cells.append(str(x))
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()
    data = load(args.synthetic)
    tag = protocol_hash(PROTOCOL)
    started = datetime.now(UTC)
    results, report = {}, []
    for label, weights in PROTOCOL["portfolios"].items():
        returns = monthly_returns(data.close, list(weights))
        forecasts = v.walk_forward(
            returns,
            weights,
            PROTOCOL["models"],
            tuple(PROTOCOL["horizons_months"]),
            PROTOCOL["windows"],
            PROTOCOL["n_paths"],
            PROTOCOL["origin_step_months"],
            PROTOCOL["min_months"],
            PROTOCOL["seed"],
        )
        scores = v.score_table(forecasts, PROTOCOL["baseline"])
        periods = v.period_coverage(forecasts)
        bins = v.calibration_bins(forecasts)
        lines = v.conclusions(scores, PROTOCOL["baseline"])
        results[label] = {
            "monthly_window": [
                str(returns.index[0].date()),
                str(returns.index[-1].date()),
                len(returns),
            ],
            "scores": scores.to_dict(orient="records"),
            "period_coverage": periods.to_dict(orient="records"),
            "loss_probability_reliability": bins.to_dict(orient="records"),
            "conclusions": lines,
        }
        report += [
            f"## Portfolio: {label}",
            "",
            f"Monthly returns {returns.index[0].date()} to {returns.index[-1].date()} "
            f"({len(returns)} months). {len(forecasts):,} forecasts scored.",
            "",
        ]
        report += md_table(
            scores,
            [
                "horizon",
                "window",
                "model",
                "forecasts",
                "independent_outcomes",
                "coverage_90",
                "coverage_50",
                "pit_ks",
                "crps",
                "crps_skill_vs_baseline",
                "dm_p_holm",
                "brier_skill_vs_baseline",
            ],
            {"coverage_90", "coverage_50", "crps_skill_vs_baseline", "brier_skill_vs_baseline"},
        )
        report += (
            ["", "**Conclusions (pre-stated decision rule):**", ""]
            + [f"- {x}" for x in lines]
            + [""]
        )
        crisis = periods[
            periods["period"].str.contains("crisis") & (periods["window"] == "rolling 120 months")
        ]
        if len(crisis):
            report += [
                "90% interval coverage during the 2007-2009 crisis (rolling 120-month window):",
                "",
            ]
            report += md_table(
                crisis, ["horizon", "model", "forecasts", "coverage_90"], {"coverage_90"}
            ) + [""]
    all_scores = pd.concat(
        [pd.DataFrame(results[k]["scores"]).assign(portfolio=k) for k in results], ignore_index=True
    )
    wins = all_scores[all_scores["beats_baseline"]]
    losses = all_scores[all_scores["worse_than_baseline"]]
    tested = all_scores[(all_scores["model"] != PROTOCOL["baseline"]) & all_scores["testable"]]
    coverage = all_scores.groupby(["horizon", "model"])["coverage_90"].mean().unstack()
    untested = int((all_scores["model"] != PROTOCOL["baseline"]).sum()) - len(tested)
    overall = [
        "## Overall reading",
        "",
        f"- {len(tested)} model-versus-baseline tests were possible ({untested} "
        "more had too few independent outcomes and were not attempted).",
        "- Significantly better than the normal baseline: "
        + (
            ", ".join(
                f"{r.model} ({r.portfolio}, {r.horizon}m, {r.window})" for r in wins.itertuples()
            )
            or "none"
        )
        + ".",
        "- Significantly worse: "
        + (
            ", ".join(
                f"{r.model} ({r.portfolio}, {r.horizon}m, {r.window})" for r in losses.itertuples()
            )
            or "none"
        )
        + ".",
        "- Holm adjustment is applied within each portfolio, horizon and window, not across the "
        f"whole table of {len(tested)} tests: an isolated win should be read as weak evidence; a "
        "pattern that repeats across windows and portfolios is stronger.",
        "- Mean 90% interval coverage by horizon (all windows and portfolios): "
        + "; ".join(
            f"{h} month{'s' if h > 1 else ''}: " + ", ".join(f"{m} {c:.0%}" for m, c in row.items())
            for h, row in coverage.iterrows()
        )
        + ".",
        "",
    ]
    report = overall + report
    record = {
        "protocol": PROTOCOL,
        "protocol_hash": tag,
        "synthetic": args.synthetic,
        "generated_at": started.isoformat(timespec="seconds"),
        "data": {**data.metadata.to_dict(), "fingerprint": data_fingerprint(data)},
        "environment": environment(),
        "results": results,
    }
    suffix = "_synthetic" if args.synthetic else ""
    out = ROOT / "experiments" / "results" / f"forecast_validation_{tag}{suffix}.json"
    out.write_text(json.dumps(record, indent=1, default=str))
    head = [
        "# Forecast validation: walk-forward calibration of the Future Wealth models",
        "",
        f"Protocol hash `{tag}`; data fingerprint `{record['data']['fingerprint']}` "
        f"({'SYNTHETIC' if args.synthetic else record['data'].get('source')}); generated "
        f"{record['generated_at']}. Record: `{out.relative_to(ROOT)}`.",
        "",
        f"**Question.** {PROTOCOL['question']}",
        "",
        f"**Decision rule (fixed in advance).** {PROTOCOL['decision_rule']}",
        "",
        "**Reading the table.** coverage_90 should be near 90% and coverage_50 near 50%; pit_ks "
        "is the distance of the PIT values from uniform (0 is perfect); crps is lower-is-better; "
        "skills are 1 - model/baseline (positive is better than the normal baseline). "
        "'independent_outcomes' counts non-overlapping horizons: 12- and 36-month results rest on "
        "few independent observations and are weak evidence either way.",
        "",
        "**Data caveat.** The snapshot was used before for the trend study (QA-033). Each forecast "
        "uses only months up to its origin; no setting was tuned on outcomes. This measures "
        "calibration, not a trading edge.",
        "",
    ]
    name = f"forecast_validation{suffix}.md"
    (ROOT / "reports" / name).write_text("\n".join(head + report) + "\n")
    print(f"wrote {out.relative_to(ROOT)} and reports/{name}")
    for label in results:
        print(f"\n== {label}")
        for line in results[label]["conclusions"]:
            print(" -", line)


if __name__ == "__main__":
    main()
