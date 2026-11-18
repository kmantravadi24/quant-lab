"""Cross-sectional momentum."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quantlab.data.models import MarketData
from quantlab.data.transforms import simple_returns
from quantlab.strategies.base import StrategyOutput, apply_cutoff, per_asset

_PERIOD = {"W": "W", "M": "M", "Q": "Q"}


@dataclass(frozen=True)
class CrossSectionalMomentum:
    """Hold the ``top_n`` assets ranked by trailing return.

    score_T = P_{T-skip} / P_{T-skip-lookback} - 1, ranked descending.
    Decisions are made at the close of the *first* session of each new
    week/month/quarter. That date is identifiable using past data only, unlike
    "the last session of the month", which on the final month of a dataset
    depends on where the sample happens to end.

    Selection bias warning: the universe (SPY, QQQ, IWM, TLT, GLD by default)
    was chosen today, with knowledge of which ETFs survived and became large.
    Results are conditional on that hindsight and overstate what an investor
    choosing a universe in the past could have expected.
    """

    lookback: int = 126
    skip: int = 0
    top_n: int = 2
    rebalance: str = "M"  # W, M or Q
    weighting: str = "equal"  # equal or inverse_vol
    name: str = "cross_sectional_momentum"

    def __post_init__(self) -> None:
        if self.rebalance not in _PERIOD:
            raise ValueError("rebalance must be W, M or Q")
        if self.weighting not in ("equal", "inverse_vol"):
            raise ValueError("weighting must be 'equal' or 'inverse_vol'")
        if self.lookback < 1 or self.skip < 0 or self.top_n < 1:
            raise ValueError("invalid lookback/skip/top_n")

    def generate(self, data: MarketData, as_of: str | pd.Timestamp | None = None) -> StrategyOutput:
        data = apply_cutoff(data, as_of)
        close = data.close
        score = per_asset(
            close, lambda s: s.shift(self.skip) / s.shift(self.skip + self.lookback) - 1.0
        )

        def trailing_vol(s: pd.Series) -> pd.Series:
            return simple_returns(s).rolling(self.lookback, min_periods=self.lookback).std(ddof=1)

        vol = per_asset(close, trailing_vol)

        period = close.index.to_period(_PERIOD[self.rebalance])
        is_rebalance = np.r_[False, period[1:] != period[:-1]]

        rows: dict[pd.Timestamp, pd.Series] = {}
        for date in close.index[is_rebalance]:
            s = score.loc[date].dropna()
            if self.weighting == "inverse_vol":
                s = s[vol.loc[date].reindex(s.index) > 0]
            if len(s) < self.top_n:
                continue  # insufficient history: make no decision rather than a partial one
            # Stable sort with ticker tie-break keeps the ranking deterministic.
            chosen = s.sort_index().sort_values(ascending=False, kind="stable").index[: self.top_n]
            w = pd.Series(0.0, index=close.columns)
            if self.weighting == "equal":
                w[chosen] = 1.0 / self.top_n
            else:
                inv = 1.0 / vol.loc[date, chosen]
                w[chosen] = inv / inv.sum()
            rows[date] = w
        weights = (
            pd.DataFrame(rows).T if rows else pd.DataFrame(columns=close.columns, dtype=float)
        )
        signals = (
            weights.gt(0).astype(float).reindex(close.index).ffill().fillna(0.0)
            if rows
            else pd.DataFrame(0.0, index=close.index, columns=close.columns)
        )
        return StrategyOutput(weights=weights, signals=signals, diagnostics={"score": score})
