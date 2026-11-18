"""Monte Carlo by resampling historical returns.

What i.i.d. resampling assumes: each future day is an independent draw from the
empirical distribution of the sampling window. It keeps the historical fat
tails (it reuses real observations) but discards volatility clustering and any
autocorrelation, so simulated drawdowns are typically too mild, and it assumes
the future distribution equals the window's (no structural change). Block
resampling restores short-range dependence but not regime shifts.

Simulated paths describe the *model*, not the future. They are not forecasts.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quantlab.research.bootstrap import resample_indices


@dataclass(frozen=True)
class MonteCarloResult:
    paths: np.ndarray  # shape (n_paths, horizon + 1); column 0 is the initial value
    initial_value: float
    method: str
    block: float
    seed: int
    sample_start: str
    sample_end: str
    n_sample: int

    @property
    def terminal(self) -> np.ndarray:
        return self.paths[:, -1]

    def percentile_bands(self, percentiles=(5, 25, 50, 75, 95)) -> pd.DataFrame:
        bands = np.percentile(self.paths, percentiles, axis=0)
        return pd.DataFrame(bands.T, columns=[f"p{p}" for p in percentiles])

    def max_drawdowns(self) -> np.ndarray:
        """Worst peak-to-trough decline of each path (<= 0)."""
        peaks = np.maximum.accumulate(self.paths, axis=1)
        return (self.paths / peaks - 1.0).min(axis=1)

    def prob_terminal_below(self, threshold: float) -> float:
        return float((self.terminal < threshold).mean())

    def prob_drawdown_worse_than(self, level: float) -> float:
        """Share of paths whose max drawdown is worse than ``level`` (e.g. -0.20)."""
        return float((self.max_drawdowns() < level).mean())

    def summary(self) -> dict[str, float]:
        t = self.terminal
        return {
            "mean_terminal": float(t.mean()),
            "median_terminal": float(np.median(t)),
            "p5_terminal": float(np.percentile(t, 5)),
            "p95_terminal": float(np.percentile(t, 95)),
            "prob_loss": self.prob_terminal_below(self.initial_value),
            "median_max_drawdown": float(np.median(self.max_drawdowns())),
            "p5_max_drawdown": float(np.percentile(self.max_drawdowns(), 5)),
        }


def simulate(
    returns: pd.Series,
    horizon: int = 252,
    n_paths: int = 1000,
    initial_value: float = 100_000.0,
    method: str = "iid",
    block: float = 21,
    seed: int = 42,
) -> MonteCarloResult:
    """Simulate wealth paths by resampling a history of simple portfolio returns.

    ``method``: "iid" (independent days), "block" (moving blocks) or
    "stationary" (random-length blocks). Identical inputs and seed give
    identical output.
    """
    clean = returns.dropna()
    if len(clean) < 2:
        raise ValueError("Need at least two historical returns to resample")
    if horizon < 1 or n_paths < 1:
        raise ValueError("horizon and n_paths must be positive")
    if (clean <= -1).any():
        raise ValueError("Returns of -100% or worse cannot be compounded")
    values = clean.to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    sampled = np.empty((n_paths, horizon))
    for p in range(n_paths):
        sampled[p] = values[resample_indices(len(values), horizon, method, block, rng)]
    paths = np.empty((n_paths, horizon + 1))
    paths[:, 0] = initial_value
    paths[:, 1:] = initial_value * np.cumprod(1.0 + sampled, axis=1)
    return MonteCarloResult(
        paths=paths, initial_value=initial_value, method=method, block=block, seed=seed,
        sample_start=str(clean.index[0])[:10], sample_end=str(clean.index[-1])[:10],
        n_sample=len(clean),
    )  # fmt: skip
