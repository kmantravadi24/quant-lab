"""Resampling for time series.

Daily returns are close to serially uncorrelated but their *volatility* is
strongly autocorrelated (clustering). Resampling single days independently
destroys that structure and understates the uncertainty of path-dependent
statistics such as drawdown. Block resampling keeps short-range dependence
inside each block.

Assumptions: the series is (approximately) stationary over the sample, and
dependence decays within a few block lengths. Neither holds exactly for markets;
intervals are therefore indicative, not exact.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd


def iid_indices(n: int, size: int, rng: np.random.Generator) -> np.ndarray:
    return rng.integers(0, n, size=size)


def moving_block_indices(n: int, size: int, block: int, rng: np.random.Generator) -> np.ndarray:
    """Concatenate randomly chosen contiguous blocks of fixed length (no wrap-around)."""
    if not 1 <= block <= n:
        raise ValueError("block length must be in [1, n]")
    starts = rng.integers(0, n - block + 1, size=-(-size // block))
    return (starts[:, None] + np.arange(block)[None, :]).ravel()[:size]


def stationary_indices(n: int, size: int, block: float, rng: np.random.Generator) -> np.ndarray:
    """Politis-Romano stationary bootstrap: geometric blocks of mean ``block``, circular."""
    if block < 1:
        raise ValueError("mean block length must be >= 1")
    idx = np.empty(size, dtype=np.int64)
    idx[0] = rng.integers(0, n)
    jump = rng.random(size) < 1.0 / block
    fresh = rng.integers(0, n, size=size)
    for i in range(1, size):
        idx[i] = fresh[i] if jump[i] else (idx[i - 1] + 1) % n
    return idx


def resample_indices(
    n: int, size: int, method: str, block: float, rng: np.random.Generator
) -> np.ndarray:
    if method == "iid":
        return iid_indices(n, size, rng)
    if method == "block":
        return moving_block_indices(n, size, int(block), rng)
    if method == "stationary":
        return stationary_indices(n, size, block, rng)
    raise ValueError(f"Unknown bootstrap method: {method}")


@dataclass(frozen=True)
class BootstrapResult:
    estimate: float  # statistic on the original sample
    lower: float
    upper: float
    confidence: float
    distribution: np.ndarray
    method: str
    block: float
    n_boot: int
    seed: int

    @property
    def excludes_zero(self) -> bool:
        return bool(self.lower > 0 or self.upper < 0)

    def to_dict(self) -> dict:
        return {
            "estimate": self.estimate, "lower": self.lower, "upper": self.upper,
            "confidence": self.confidence, "method": self.method, "block": self.block,
            "n_boot": self.n_boot, "seed": self.seed,
        }  # fmt: skip


def bootstrap_ci(
    data: pd.Series | pd.DataFrame,
    statistic: Callable[[pd.Series | pd.DataFrame], float],
    n_boot: int = 2000,
    method: str = "stationary",
    block: float = 21,
    confidence: float = 0.95,
    seed: int = 0,
) -> BootstrapResult:
    """Percentile bootstrap interval for ``statistic``.

    Pass a DataFrame (e.g. strategy and benchmark returns) to resample rows
    jointly, preserving the cross-sectional pairing; ``statistic`` then receives
    a DataFrame and can return a difference.
    """
    clean = data.dropna()
    n = len(clean)
    if n < 2:
        raise ValueError("Need at least two observations to bootstrap")
    rng = np.random.default_rng(seed)
    dist = np.empty(n_boot)
    for b in range(n_boot):
        sample = clean.iloc[resample_indices(n, n, method, block, rng)]
        dist[b] = statistic(sample.reset_index(drop=True))
    tail = (1 - confidence) / 2
    lower, upper = np.nanquantile(dist, [tail, 1 - tail])
    return BootstrapResult(
        estimate=float(statistic(clean.reset_index(drop=True))),
        lower=float(lower), upper=float(upper), confidence=confidence,
        distribution=dist, method=method, block=block, n_boot=n_boot, seed=seed,
    )  # fmt: skip
