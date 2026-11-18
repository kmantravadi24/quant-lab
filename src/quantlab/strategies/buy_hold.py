"""Buy-and-hold benchmark: one decision, then no further trading."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from quantlab.data.models import MarketData
from quantlab.strategies.base import StrategyOutput, apply_cutoff


@dataclass(frozen=True)
class BuyAndHold:
    """Buy fixed weights once and let them drift.

    The single decision is made at the close of the first session on which every
    selected instrument has a price (or ``start`` if later) and is filled at the
    next open, under exactly the same cost model as any other strategy.
    """

    weights: dict[str, float] = field(default_factory=lambda: {"SPY": 1.0})
    start: str | None = None
    name: str = "buy_and_hold"

    def generate(self, data: MarketData, as_of: str | pd.Timestamp | None = None) -> StrategyOutput:
        data = apply_cutoff(data, as_of)
        tickers = list(self.weights)
        missing = [t for t in tickers if t not in data.tickers]
        if missing:
            raise KeyError(f"Tickers not in dataset: {missing}")
        valid = data.close[tickers].notna().all(axis=1)
        if self.start is not None:
            valid &= data.close.index >= pd.Timestamp(self.start)
        signals = pd.DataFrame(0.0, index=data.dates, columns=data.tickers)
        weights = pd.DataFrame(columns=data.tickers, dtype=float)
        if valid.any():
            first = valid.idxmax()
            row = pd.Series(0.0, index=data.tickers)
            row[tickers] = [self.weights[t] for t in tickers]
            weights = row.to_frame(first).T
            signals.loc[first:, tickers] = 1.0
        return StrategyOutput(weights=weights, signals=signals)
