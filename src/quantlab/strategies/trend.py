"""Moving-average crossover trend following."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quantlab.data.models import MarketData
from quantlab.data.transforms import moving_average
from quantlab.strategies.base import (
    StrategyOutput,
    apply_cutoff,
    decisions_on_change,
    per_asset,
)


@dataclass(frozen=True)
class TrendFollowing:
    """Long an asset while its fast SMA is above its slow SMA, otherwise cash.

    Hypothesis: returns show positive serial dependence at multi-month horizons
    (slow information diffusion, herding, risk-management feedback), so a
    smoothed price above its longer-run average carries information about the
    near-future drift, and in particular long drawdowns tend to unfold slowly
    enough to step aside.

    Limits: lags turning points by construction, is whipsawed in range-bound
    markets, earns nothing while in cash (no interest is modelled), and the
    50/200 pair is a convention, not an optimum.

    Each of the N selected assets owns a 1/N capital slice that is either
    invested or in cash. Until ``slow`` closes exist the signal is 0 (cash).
    """

    fast: int = 50
    slow: int = 200
    tickers: tuple[str, ...] | None = None
    name: str = "trend_following"

    def __post_init__(self) -> None:
        if not 0 < self.fast < self.slow:
            raise ValueError("Require 0 < fast < slow")

    def generate(self, data: MarketData, as_of: str | pd.Timestamp | None = None) -> StrategyOutput:
        data = apply_cutoff(data, as_of)
        tickers = list(self.tickers) if self.tickers else data.tickers
        close = data.close[tickers]
        fast_ma = per_asset(close, lambda s: moving_average(s, self.fast))
        slow_ma = per_asset(close, lambda s: moving_average(s, self.slow))
        # NaN comparisons are False -> no position during warm-up or long data gaps.
        signal = (fast_ma > slow_ma).astype(float)
        daily = (signal / len(tickers)).reindex(columns=data.tickers, fill_value=0.0)
        return StrategyOutput(
            weights=decisions_on_change(daily),
            signals=signal.reindex(columns=data.tickers, fill_value=0.0),
            diagnostics={"fast_ma": fast_ma, "slow_ma": slow_ma},
        )
