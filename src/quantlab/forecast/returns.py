"""Joint models of future MONTHLY asset returns for wealth forecasting.

Every model takes a table of historical monthly simple returns (rows = months,
columns = the instruments a plan holds, all complete) and draws future months for
all instruments TOGETHER, so the correlation between assets is preserved:

* ``IIDBootstrap``      each future month is a randomly chosen historical month
                        (the whole cross-section of that month). Keeps fat tails and
                        cross-correlation; discards any dependence between months.
* ``BlockBootstrap``    stationary bootstrap (Politis & Romano): runs of consecutive
                        historical months with random lengths of mean ``block``. Keeps
                        some serial dependence (momentum, volatility clustering).
* ``EWMAFiltered``      filtered historical simulation: historical shocks are
                        standardised by an EWMA volatility estimate and re-scaled by the
                        CURRENT volatility, which then evolves with the simulated
                        returns. Conditional on today's volatility; most informative
                        for short horizons. EWMA has no mean reversion, so at long
                        horizons the volatility drifts: treat long-horizon EWMA output
                        as a sensitivity, not a better forecast.
* ``GaussianIID``       baseline: monthly LOG returns jointly normal with the window's
                        mean vector and covariance. Thin tails by construction.

None of these knows the future. Each says "if the future resembles this window in
this specific way, outcomes would be spread like this".

Sampling is generated month by month (``draw``), so memory does not grow with the
horizon beyond one month of draws.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

MIN_MONTHS = 24
FLOOR = -0.99  # a long position cannot lose more than everything in one month


def monthly_returns(close: pd.DataFrame, tickers: list[str] | None = None) -> pd.DataFrame:
    """Calendar-month simple returns from daily (adjusted) closes.

    The month's last available close is its value. Only instruments in ``tickers``
    (default: all) are used, and only months where every one of them has a value in
    both that month and the previous one. A final month whose last observation is more
    than 4 calendar days before the month's end is treated as incomplete and dropped.
    """
    frame = close[tickers] if tickers is not None else close
    frame = frame.dropna(how="any")
    if frame.empty:
        return pd.DataFrame(columns=frame.columns, dtype=float)
    month_end = frame.groupby(frame.index.to_period("M")).last()
    last_day = frame.index[-1]
    if (last_day.to_period("M").end_time.normalize() - last_day.normalize()).days > 4:
        month_end = month_end.iloc[:-1]
    returns = month_end.pct_change().iloc[1:]
    returns.index = returns.index.to_timestamp(how="end").normalize()
    return returns.dropna(how="any")


def _check(returns: pd.DataFrame) -> np.ndarray:
    values = np.asarray(returns, dtype=float)
    if values.ndim != 2 or values.shape[1] == 0:
        raise ValueError("Monthly returns must be a table with at least one instrument")
    if len(values) < MIN_MONTHS:
        raise ValueError(f"At least {MIN_MONTHS} months of history are needed, got {len(values)}")
    if not np.isfinite(values).all():
        raise ValueError("Monthly returns contain missing or non-finite values")
    if (values <= -1).any():
        raise ValueError("A monthly return of -100% or worse cannot be compounded")
    return values


@dataclass
class ReturnModel:
    """Base class. ``draw`` returns an array (paths, assets) for the next month."""

    returns: pd.DataFrame
    name: str = field(default="", init=False)
    description: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self.values = _check(self.returns)
        self.tickers = [str(c) for c in self.returns.columns]

    @property
    def window(self) -> tuple[str, str, int]:
        idx = self.returns.index
        return str(idx[0].date()), str(idx[-1].date()), len(idx)

    def start(self, n_paths: int, rng: np.random.Generator) -> None:  # pragma: no cover
        raise NotImplementedError

    def draw(self, rng: np.random.Generator) -> np.ndarray:  # pragma: no cover
        raise NotImplementedError

    def sample(self, n_paths: int, n_months: int, seed: int) -> np.ndarray:
        """All draws at once, shape (paths, months, assets). For tests and small runs."""
        rng = np.random.default_rng(seed)
        self.start(n_paths, rng)
        return np.stack([self.draw(rng) for _ in range(n_months)], axis=1)

    def describe(self) -> dict:
        start, end, n = self.window
        return {
            "model": self.name,
            "description": self.description,
            "tickers": self.tickers,
            "window_start": start,
            "window_end": end,
            "window_months": n,
            **self.params(),
        }

    def params(self) -> dict:
        return {}


@dataclass
class IIDBootstrap(ReturnModel):
    def __post_init__(self) -> None:
        super().__post_init__()
        self.name = "iid_bootstrap"
        self.description = "Independent historical months (whole cross-section of each month)"

    def start(self, n_paths: int, rng: np.random.Generator) -> None:
        self.n_paths = n_paths

    def draw(self, rng: np.random.Generator) -> np.ndarray:
        return self.values[rng.integers(0, len(self.values), self.n_paths)]


@dataclass
class BlockBootstrap(ReturnModel):
    block: float = 12.0  # mean run length in months

    def __post_init__(self) -> None:
        super().__post_init__()
        if not np.isfinite(self.block) or self.block < 1:
            raise ValueError("block must be a finite number >= 1")
        self.name = "block_bootstrap"
        self.description = (
            f"Stationary bootstrap: runs of consecutive historical months, "
            f"mean length {self.block:g}"
        )

    def params(self) -> dict:
        return {"block_months": self.block}

    def start(self, n_paths: int, rng: np.random.Generator) -> None:
        self.position = rng.integers(0, len(self.values), n_paths)
        self.first = True

    def draw(self, rng: np.random.Generator) -> np.ndarray:
        n = len(self.values)
        if self.first:
            self.first = False
        else:
            restart = rng.random(len(self.position)) < 1.0 / self.block
            fresh = rng.integers(0, n, len(self.position))
            self.position = np.where(restart, fresh, (self.position + 1) % n)
        return self.values[self.position]


@dataclass
class EWMAFiltered(ReturnModel):
    lam: float = 0.97  # monthly decay (RiskMetrics' monthly value)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not (np.isfinite(self.lam) and 0.5 <= self.lam < 1.0):
            raise ValueError("lam must be in [0.5, 1)")
        self.name = "ewma_filtered"
        self.description = (
            f"Filtered historical simulation: historical shocks re-scaled by "
            f"EWMA volatility (lambda {self.lam:g}), conditional on today"
        )
        values = self.values
        self.mu = values.mean(axis=0)
        dev = values - self.mu
        var = dev.var(axis=0, ddof=1)
        var = np.where(var > 0, var, 1e-12)
        sig2 = np.empty_like(values)
        current = var.copy()  # initialised at the window variance: uses only the window
        for t in range(len(values)):
            sig2[t] = current
            current = self.lam * current + (1 - self.lam) * dev[t] ** 2
        self.shocks = dev / np.sqrt(sig2)
        self.current_var = current  # forecast variance for the first future month
        self.long_run_var = var

    def params(self) -> dict:
        return {
            "lambda": self.lam,
            "current_vol_annual": (np.sqrt(self.current_var * 12)).round(6).tolist(),
            "window_vol_annual": (np.sqrt(self.long_run_var * 12)).round(6).tolist(),
        }

    def start(self, n_paths: int, rng: np.random.Generator) -> None:
        self.var = np.tile(self.current_var, (n_paths, 1))

    def draw(self, rng: np.random.Generator) -> np.ndarray:
        z = self.shocks[rng.integers(0, len(self.shocks), len(self.var))]
        r = self.mu + np.sqrt(self.var) * z
        r = np.maximum(r, FLOOR)
        self.var = self.lam * self.var + (1 - self.lam) * (r - self.mu) ** 2
        return r


@dataclass
class GaussianIID(ReturnModel):
    def __post_init__(self) -> None:
        super().__post_init__()
        self.name = "gaussian_iid"
        self.description = (
            "Baseline: jointly normal monthly log returns (window mean and covariance)"
        )
        logs = np.log1p(self.values)
        self.mean = logs.mean(axis=0)
        self.cov = np.atleast_2d(np.cov(logs, rowvar=False, ddof=1))
        vals, vecs = np.linalg.eigh(self.cov)
        self.factor = vecs * np.sqrt(np.clip(vals, 0.0, None))  # cov = factor @ factor.T

    def start(self, n_paths: int, rng: np.random.Generator) -> None:
        self.n_paths = n_paths

    def draw(self, rng: np.random.Generator) -> np.ndarray:
        z = rng.standard_normal((self.n_paths, len(self.mean)))
        return np.expm1(self.mean + z @ self.factor.T)


MODELS = {
    "iid_bootstrap": IIDBootstrap,
    "block_bootstrap": BlockBootstrap,
    "ewma_filtered": EWMAFiltered,
    "gaussian_iid": GaussianIID,
}
LABELS = {
    "iid_bootstrap": "Historical months, independent",
    "block_bootstrap": "Historical runs of months (block bootstrap)",
    "ewma_filtered": "Volatility-adjusted history (EWMA)",
    "gaussian_iid": "Normal distribution (baseline)",
}
SUITABILITY = {
    "iid_bootstrap": "Any horizon as a baseline; understates runs of bad months.",
    "block_bootstrap": "Medium and long horizons (3 to 20 years): keeps multi-month runs.",
    "ewma_filtered": "Short horizons (up to about 1 to 2 years): conditions on today's volatility, "
    "which says little about 10 years from now.",
    "gaussian_iid": "Reference only: normal tails understate crashes.",
}


def build_model(name: str, returns: pd.DataFrame, **params) -> ReturnModel:
    if name not in MODELS:
        raise ValueError(f"Unknown model {name!r}; choose from {sorted(MODELS)}")
    return MODELS[name](returns, **params)
