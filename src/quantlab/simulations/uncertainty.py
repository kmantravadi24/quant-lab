"""How much a Monte Carlo answer can be trusted, measured rather than asserted (QA-030).

Two different uncertainties affect a simulated probability:

1. **Sampling error** from using a finite number of paths. It shrinks as
   1/sqrt(paths) and is quantified here with a Wilson score interval.
2. **Model error**: which history is resampled and how. It does NOT shrink with
   more paths. :func:`sensitivity` re-runs the same question over different
   lookback windows and resampling methods so the spread can be seen.

Neither turns a simulated frequency into a forecast of the real future.
"""

from __future__ import annotations

import math

import pandas as pd

from quantlab.simulations.monte_carlo import simulate

Z95 = 1.959963984540054


def wilson_interval(p: float, n: int, z: float = Z95) -> tuple[float, float]:
    """95% Wilson score interval for a proportion ``p`` observed in ``n`` independent paths."""
    if n <= 0 or not 0.0 <= p <= 1.0:
        raise ValueError("need n > 0 and 0 <= p <= 1")
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    low = 0.0 if p == 0.0 else max(0.0, centre - half)
    high = 1.0 if p == 1.0 else min(1.0, centre + half)
    return low, high


def standard_error(p: float, n: int) -> float:
    """Binomial standard error of a simulated proportion."""
    if n <= 0:
        raise ValueError("n must be positive")
    return math.sqrt(max(p * (1 - p), 0.0) / n)


def lookback_windows(n_obs: int, periods: int = 252) -> dict[str, int]:
    """Standard lookbacks (3, 5, 10 years, all) that fit in ``n_obs`` daily returns."""
    out = {f"Last {y} years": y * periods for y in (3, 5, 10) if y * periods < n_obs}
    out[f"All {n_obs / periods:.1f} years"] = n_obs
    return out


def sensitivity(
    returns: pd.Series,
    horizon: int,
    n_paths: int,
    initial_value: float,
    seed: int,
    drawdown_level: float = -0.20,
    lookbacks: dict[str, int] | None = None,
    methods: tuple[tuple[str, float], ...] = (("iid", 1), ("block", 21), ("stationary", 21)),
) -> pd.DataFrame:
    """The same question asked under different histories and resampling methods.

    One row per (lookback, method). Each probability carries its Wilson interval,
    which reflects path-count noise only; the spread BETWEEN rows is model risk.
    """
    clean = returns.dropna()
    lookbacks = lookbacks or lookback_windows(len(clean))
    rows = []
    for label, n_obs in lookbacks.items():
        sample = clean.iloc[-n_obs:]
        for method, block in methods:
            res = simulate(sample, horizon, n_paths, initial_value, method, block, seed)
            p_loss = res.prob_terminal_below(initial_value)
            p_dd = res.prob_drawdown_worse_than(drawdown_level)
            lo_l, hi_l = wilson_interval(p_loss, n_paths)
            lo_d, hi_d = wilson_interval(p_dd, n_paths)
            rows.append({
                "lookback": label, "sample_start": res.sample_start, "sample_end": res.sample_end,
                "observations": res.n_sample, "method": method,
                "block": None if method == "iid" else block,
                "prob_loss": p_loss, "prob_loss_low": lo_l, "prob_loss_high": hi_l,
                "prob_drawdown": p_dd, "prob_drawdown_low": lo_d, "prob_drawdown_high": hi_d,
                "median_terminal": float(pd.Series(res.terminal).median()),
            })  # fmt: skip
    return pd.DataFrame(rows)
