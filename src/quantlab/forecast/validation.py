"""Walk-forward evaluation of forecast distributions, with no look-ahead.

At each forecast origin (the end of month i) a model is fitted on months up to and
including i ONLY (a rolling window of the last L months, or all months so far), and
it forecasts the distribution of the portfolio's cumulative return over the next h
months. The forecast is then scored against what actually happened in months
i+1 .. i+h. The portfolio is the plan's target weights, rebalanced monthly, with
cash earning 0% (the wealth plan's contributions are known in advance and add no
forecasting content, so the evaluation isolates the market model).

Scores (all computed from the forecast ensemble):

* interval coverage   share of outcomes inside the central 50% and 90% intervals
* PIT                 probability integral transform; uniform if calibrated
                      (reported as a Kolmogorov-Smirnov distance from uniform)
* CRPS                continuous ranked probability score, a proper scoring rule
                      for the whole distribution (lower is better)
* Brier score         for the probability of a loss over the horizon (lower is better)
* pinball loss        quantile loss at 5%, 50%, 95%
* median error        |log(1 + median forecast) - log(1 + outcome)|

Each model is compared with the Gaussian baseline by a Diebold-Mariano test on the
CRPS differences, using a Newey-West variance with h - 1 lags because h-month
outcomes from monthly origins overlap, the Harvey-Leybourne-Newbold small-sample
correction and t p-values. With fewer than ``MIN_INDEPENDENT`` non-overlapping
outcomes no test is attempted: overlapping long-horizon outcomes make the variance
estimate unreliable, and a simulation check (Suite R) showed false "wins" there.
A model is said to beat the baseline only if
its mean CRPS is lower AND the test rejects equality at 5% after a Holm adjustment for
the several models tested against the same baseline.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from quantlab.forecast._stats import norm_cdf, t_cdf
from quantlab.forecast.returns import build_model
from quantlab.research import holm

BASELINE = "gaussian_iid"
PERIODS = (
    ("before 2007-07", None, "2007-06-30"),
    ("2007-07 to 2009-06 (financial crisis)", "2007-07-01", "2009-06-30"),
    ("2009-07 to 2019-12", "2009-07-01", "2019-12-31"),
    ("2020 onward", "2020-01-01", None),
)


def crps_ensemble(samples: np.ndarray, outcome: float) -> float:
    """CRPS of an ensemble: E|X - y| - 0.5 E|X - X'| (exact for the empirical distribution)."""
    x = np.sort(np.asarray(samples, dtype=float))
    n = len(x)
    first = np.abs(x - outcome).mean()
    weights = 2 * np.arange(1, n + 1) - n - 1
    second = 2.0 * (weights * x).sum() / (n * n)  # = E|X - X'|
    return float(first - 0.5 * second)


def pinball(q_value: float, outcome: float, q: float) -> float:
    diff = outcome - q_value
    return float(max(q * diff, (q - 1) * diff))


MIN_INDEPENDENT = 20  # no claim is made with fewer non-overlapping outcomes than this


def diebold_mariano(diff: np.ndarray, lags: int, horizon: int | None = None) -> tuple[float, float]:
    """Mean loss difference over its Newey-West standard error, two-sided p-value.

    With ``horizon`` the Harvey-Leybourne-Newbold (1997) small-sample correction is applied
    and the p-value uses a t distribution with n - 1 degrees of freedom; otherwise normal.
    """
    d = np.asarray(diff, dtype=float)
    n = len(d)
    if n < 3:
        return float("nan"), float("nan")
    e = d - d.mean()
    var = (e @ e) / n
    for k in range(1, min(lags, n - 1) + 1):
        var += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    if var <= 0:
        return float("nan"), float("nan")
    stat = d.mean() / math.sqrt(var / n)
    if horizon is None:
        return float(stat), float(2 * (1 - norm_cdf(abs(stat))))
    h = horizon
    factor = (n + 1 - 2 * h + h * (h - 1) / n) / n
    if factor <= 0:
        return float("nan"), float("nan")
    stat *= math.sqrt(factor)
    return float(stat), float(2 * (1 - t_cdf(abs(stat), n - 1)))


def portfolio_path(returns: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Cumulative return of a monthly-rebalanced portfolio; returns (..., months, assets)."""
    return np.prod(1 + returns @ weights, axis=-1) - 1


def walk_forward(
    returns: pd.DataFrame,
    weights: dict[str, float],
    models: dict[str, dict],
    horizons: tuple[int, ...] = (1, 12),
    windows: dict[str, int | None] | None = None,
    n_paths: int = 1000,
    step: int = 1,
    min_months: int = 60,
    seed: int = 7,
) -> pd.DataFrame:
    """One row per (origin, horizon, window, model) with the forecast and its scores.

    ``windows`` maps a label to a rolling length in months, or None for an expanding window.
    Only data up to the origin month is passed to the model: the outcome rows are never seen.
    """
    windows = windows or {"rolling 60 months": 60, "rolling 120 months": 120, "expanding": None}
    tickers = [t for t, w in weights.items() if w > 0]
    data = returns[tickers].dropna(how="any")
    w = np.array([weights[t] for t in tickers])
    values = data.to_numpy()
    dates = data.index
    rows = []
    for h in horizons:
        for i in range(min_months - 1, len(data) - h, step):
            realized = float(np.prod(1 + values[i + 1 : i + 1 + h] @ w) - 1)
            for label, length in windows.items():
                start = 0 if length is None else i + 1 - length
                if start < 0:
                    continue
                train = data.iloc[start : i + 1]  # strictly up to and including the origin
                for name, params in models.items():
                    model = build_model(name, train, **params)
                    sims = portfolio_path(model.sample(n_paths, h, seed + i), w)
                    q05, q25, q50, q75, q95 = np.percentile(sims, [5, 25, 50, 75, 95])
                    rows.append(
                        {
                            "origin": dates[i],
                            "horizon": h,
                            "step": step,
                            "window": label,
                            "model": name,
                            "train_months": len(train),
                            "realized": realized,
                            "q05": q05,
                            "q25": q25,
                            "q50": q50,
                            "q75": q75,
                            "q95": q95,
                            "pit": float((sims <= realized).mean()),
                            "crps": crps_ensemble(sims, realized),
                            "p_loss": float((sims < 0).mean()),
                            "loss": float(realized < 0),
                            "pinball_05": pinball(q05, realized, 0.05),
                            "pinball_50": pinball(q50, realized, 0.5),
                            "pinball_95": pinball(q95, realized, 0.95),
                            "median_log_error": abs(math.log1p(q50) - math.log1p(realized)),
                        }
                    )
    return pd.DataFrame(rows)


def ks_uniform(pit: np.ndarray) -> float:
    u = np.sort(np.asarray(pit, dtype=float))
    n = len(u)
    if n == 0:
        return float("nan")
    grid = np.arange(1, n + 1) / n
    return float(max(np.max(grid - u), np.max(u - (grid - 1 / n))))


def score_table(forecasts: pd.DataFrame, baseline: str = BASELINE) -> pd.DataFrame:
    """Aggregate scores per (horizon, window, model), with the test against the baseline."""
    out = []
    for (h, window, model), g in forecasts.groupby(["horizon", "window", "model"], sort=False):
        inside90 = (g["realized"] >= g["q05"]) & (g["realized"] <= g["q95"])
        inside50 = (g["realized"] >= g["q25"]) & (g["realized"] <= g["q75"])
        base = forecasts[
            (forecasts["horizon"] == h)
            & (forecasts["window"] == window)
            & (forecasts["model"] == baseline)
        ].set_index("origin")
        mine = g.set_index("origin")
        common = mine.index.intersection(base.index)
        diff = (mine.loc[common, "crps"] - base.loc[common, "crps"]).to_numpy()
        step = int(g["step"].iloc[0]) if "step" in g else 1
        overlap = max(math.ceil(h / step) - 1, 0)  # outcomes overlap for this many lags
        if model != baseline:
            stat, p = diebold_mariano(diff, overlap, horizon=overlap + 1)
        else:
            stat, p = float("nan"), float("nan")
        span = (g["origin"].max().to_period("M") - g["origin"].min().to_period("M")).n
        brier = float(((g["p_loss"] - g["loss"]) ** 2).mean())
        base_brier = (
            float(((base["p_loss"] - base["loss"]) ** 2).mean()) if len(base) else float("nan")
        )
        crps, base_crps = (
            float(g["crps"].mean()),
            float(base["crps"].mean()) if len(base) else float("nan"),
        )
        out.append(
            {
                "horizon": h,
                "window": window,
                "model": model,
                "forecasts": len(g),
                "independent_outcomes": span // max(h, 1) + 1,
                "first_origin": str(g["origin"].min().date()),
                "last_origin": str(g["origin"].max().date()),
                "coverage_90": float(inside90.mean()),
                "coverage_50": float(inside50.mean()),
                "pit_ks": ks_uniform(g["pit"].to_numpy()),
                "crps": crps,
                "crps_skill_vs_baseline": 1 - crps / base_crps if base_crps else float("nan"),
                "dm_stat": stat,
                "dm_p": p,
                "brier_loss": brier,
                "brier_skill_vs_baseline": 1 - brier / base_brier if base_brier else float("nan"),
                "pinball_05": float(g["pinball_05"].mean()),
                "pinball_95": float(g["pinball_95"].mean()),
                "median_log_error": float(g["median_log_error"].mean()),
            }
        )
    table = pd.DataFrame(out)
    # Several models are tested against one baseline: Holm-adjust within each (horizon, window).
    table["dm_p_holm"] = float("nan")
    for _, g in table.groupby(["horizon", "window"], sort=False):
        tested = g[g["model"] != baseline]
        ok = tested["dm_p"].notna()
        if ok.any():
            table.loc[tested.index[ok], "dm_p_holm"] = holm(tested.loc[ok, "dm_p"].tolist())
    better = table["crps_skill_vs_baseline"] > 0
    table["testable"] = table["independent_outcomes"] >= MIN_INDEPENDENT
    significant = (table["dm_p_holm"] < 0.05) & table["testable"]
    table["beats_baseline"] = (table["model"] != baseline) & better & significant
    table["worse_than_baseline"] = (table["model"] != baseline) & ~better & significant
    return table


def period_coverage(forecasts: pd.DataFrame) -> pd.DataFrame:
    """90% interval coverage by market period, to show where calibration breaks down."""
    rows = []
    for label, start, end in PERIODS:
        mask = pd.Series(True, index=forecasts.index)
        if start:
            mask &= forecasts["origin"] >= pd.Timestamp(start)
        if end:
            mask &= forecasts["origin"] <= pd.Timestamp(end)
        part = forecasts[mask]
        for (h, window, model), g in part.groupby(["horizon", "window", "model"], sort=False):
            inside = (g["realized"] >= g["q05"]) & (g["realized"] <= g["q95"])
            rows.append(
                {
                    "period": label,
                    "horizon": h,
                    "window": window,
                    "model": model,
                    "forecasts": len(g),
                    "coverage_90": float(inside.mean()),
                }
            )
    return pd.DataFrame(rows)


def calibration_bins(forecasts: pd.DataFrame, bins: int = 5) -> pd.DataFrame:
    """Reliability of the loss probability: forecast vs observed frequency per bin."""
    rows = []
    edges = np.linspace(0, 1, bins + 1)
    for (h, window, model), g in forecasts.groupby(["horizon", "window", "model"], sort=False):
        idx = np.clip(np.digitize(g["p_loss"], edges[1:-1]), 0, bins - 1)
        for b in range(bins):
            part = g[idx == b]
            if len(part):
                rows.append(
                    {
                        "horizon": h,
                        "window": window,
                        "model": model,
                        "bin": f"{edges[b]:.1f}-{edges[b + 1]:.1f}",
                        "forecasts": len(part),
                        "mean_forecast": float(part["p_loss"].mean()),
                        "observed": float(part["loss"].mean()),
                    }
                )
    return pd.DataFrame(rows)


def conclusions(scores: pd.DataFrame, baseline: str = BASELINE) -> list[str]:
    """Plain statements following the pre-stated decision rule; no model is favoured."""
    lines = []
    for (h, window), g in scores.groupby(["horizon", "window"], sort=False):
        winners = g[g["beats_baseline"]]["model"].tolist()
        losers = g[g["worse_than_baseline"]]["model"].tolist()
        others = [m for m in g["model"] if m != baseline and m not in winners + losers]
        n_ind = int(g["independent_outcomes"].min())
        text = f"{h}-month horizon, {window} ({n_ind} non-overlapping outcomes): "
        if not g["testable"].all():
            cov = g.set_index("model")["coverage_90"]
            lines.append(
                text + f"too few independent outcomes (fewer than {MIN_INDEPENDENT}) to "
                "test any model against the baseline; no claim is made. 90% interval "
                "coverage, for information: "
                + ", ".join(f"{m} {v:.0%}" for m, v in cov.items())
                + "."
            )
            continue
        if winners:
            text += (
                f"{', '.join(winners)} had a significantly lower CRPS than the normal baseline. "
            )
        if losers:
            verb = "is" if len(losers) == 1 else "are"
            text += f"{', '.join(losers)} {verb} significantly WORSE than the normal baseline. "
        if others:
            text += (
                f"{', '.join(others)} did not differ significantly from the normal baseline; "
                "the extra complexity is not supported by this evidence. "
            )
        cov = g.set_index("model")["coverage_90"]
        text += "90% interval coverage: " + ", ".join(f"{m} {v:.0%}" for m, v in cov.items()) + "."
        lines.append(text)
    return lines


def summarise_record(record: dict) -> dict:
    """What a stored validation record says, per horizon, for display next to projections.

    Returns the data period, whether the data were synthetic, and for each horizon the
    range of mean 90%-interval coverage across models, how many model/baseline tests could
    be run, and which (model, portfolio, window) cells beat or lost to the baseline.
    """
    scores = pd.concat(
        [pd.DataFrame(r["scores"]).assign(portfolio=name) for name, r in record["results"].items()],
        ignore_index=True,
    )
    windows = [r["monthly_window"] for r in record["results"].values()]
    baseline = record.get("protocol", {}).get("baseline", BASELINE)
    horizons = {}
    for h, g in scores.groupby("horizon"):
        coverage = g.groupby("model")["coverage_90"].mean()
        tested = g[(g["model"] != baseline) & g["testable"]]
        horizons[int(h)] = {
            "coverage_90_low": float(coverage.min()),
            "coverage_90_high": float(coverage.max()),
            "tests_run": int(len(tested)),
            "tests_possible": int((g["model"] != baseline).sum()),
            "wins": [
                f"{r.model} ({r.portfolio}, {r.window})"
                for r in g[g["beats_baseline"]].itertuples()
            ],
            "losses": [
                f"{r.model} ({r.portfolio}, {r.window})"
                for r in g[g["worse_than_baseline"]].itertuples()
            ],
        }
    return {
        "synthetic": bool(record.get("synthetic")),
        "first_month": min(w[0] for w in windows)[:7],
        "last_month": max(w[1] for w in windows)[:7],
        "horizons": horizons,
    }
