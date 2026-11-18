"""Fixed target weights with an optional calendar rebalancing policy."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quantlab.data.models import MarketData
from quantlab.strategies.base import StrategyOutput, apply_cutoff

PERIODS = {"W": "W", "M": "M", "Q": "Q", "A": "Y"}
WEIGHT_TOL = 1e-9


def validate_long_only_weights(weights: dict[str, float]) -> None:
    """Long-only target weights summing to at most 1; the remainder is cash."""
    if not weights:
        raise ValueError("At least one instrument weight is required")
    values = np.array(list(weights.values()), dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Weights must be finite numbers")
    if (values < 0).any():
        raise ValueError("Negative weights are not supported (long-only)")
    if values.sum() > 1 + WEIGHT_TOL:
        raise ValueError(f"Weights sum to {values.sum():.6f} > 1: leverage is not supported")


def period_starts(dates: pd.DatetimeIndex, frequency: str) -> pd.DatetimeIndex:
    """First session of each new week / month / quarter / year, excluding the first session.

    A session is recognised as a period start by comparing it with the session
    before it, so only past dates are needed: there is no reliance on knowing
    where a period will end.
    """
    if frequency not in PERIODS:
        raise ValueError(f"frequency must be one of {sorted(PERIODS)}")
    if len(dates) < 2:
        return pd.DatetimeIndex([])
    period = pd.DatetimeIndex(dates).to_period(PERIODS[frequency])
    return pd.DatetimeIndex(dates[1:][period[1:] != period[:-1]])


@dataclass(frozen=True)
class FixedWeights:
    """Hold constant target weights; the rest is cash.

    Decisions (all taken after a session's close and executed at the next open):

    * Initial purchase: the first session on which every held instrument has a
      price (or ``start`` if later).
    * ``rebalance`` in {None, "M", "Q", "A"}: on the first session of each new
      month / quarter / year the whole portfolio is traded back to target.
    * ``deploy`` in {None, "W", "M", "Q"}: on the first session of each new
      period, spare cash (for example that day's contribution) is invested at
      the target mix without selling anything. If a rebalance falls on the same
      session, the rebalance covers it.

    The weights are constants and the decision dates depend only on the trading
    calendar, so nothing here can use future prices. With no rebalancing and no
    deployment this is exactly a buy-and-hold of the same weights.
    """

    weights: dict[str, float]
    rebalance: str | None = None
    deploy: str | None = None
    start: str | None = None
    name: str = "fixed_weights"

    def __post_init__(self) -> None:
        validate_long_only_weights(self.weights)
        if self.rebalance not in (None, "M", "Q", "A"):
            raise ValueError("rebalance must be None, 'M', 'Q' or 'A'")
        if self.deploy not in (None, "W", "M", "Q"):
            raise ValueError("deploy must be None, 'W', 'M' or 'Q'")

    def generate(self, data: MarketData, as_of: str | pd.Timestamp | None = None) -> StrategyOutput:
        data = apply_cutoff(data, as_of)
        held = [t for t, w in self.weights.items() if w > 0]
        missing = [t for t in self.weights if t not in data.tickers]
        if missing:
            raise KeyError(f"Tickers not in dataset: {missing}")
        signals = pd.DataFrame(0.0, index=data.dates, columns=data.tickers)
        empty = pd.DataFrame(columns=data.tickers, dtype=float)
        valid = data.close[held].notna().all(axis=1) if held else pd.Series(False, index=data.dates)
        if self.start is not None:
            valid &= data.close.index >= pd.Timestamp(self.start)
        if not valid.any():
            return StrategyOutput(weights=empty, signals=signals)
        first = valid.idxmax()
        later = data.dates[data.dates > first]

        def starts(frequency: str | None) -> pd.DatetimeIndex:
            if frequency is None:
                return pd.DatetimeIndex([])
            return period_starts(data.dates, frequency).intersection(later)

        rebalances, deployments = starts(self.rebalance), starts(self.deploy)
        decision_dates = pd.DatetimeIndex([first]).union(rebalances).union(deployments)
        row = pd.Series(0.0, index=data.tickers)
        row[list(self.weights)] = [self.weights[t] for t in self.weights]
        weights = pd.DataFrame([row.to_numpy()] * len(decision_dates), index=decision_dates,
                               columns=data.tickers)  # fmt: skip
        signals.loc[first:, held] = 1.0
        return StrategyOutput(
            weights=weights, signals=signals, cash_only=deployments.difference(rebalances)
        )
