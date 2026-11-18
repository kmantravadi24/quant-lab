"""Rolling z-score mean reversion (long-only)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quantlab.data.models import MarketData
from quantlab.strategies.base import (
    StrategyOutput,
    apply_cutoff,
    decisions_on_change,
    per_asset,
)


@dataclass(frozen=True)
class MeanReversion:
    """Buy when price is unusually far below its trailing mean; exit when it recovers.

    z_t = (P_t - mean(P_{t-L+1..t})) / std(P_{t-L+1..t}),  sample std (ddof=1).
    Enter long when z_t <= -entry_z; exit when z_t >= -exit_z. While z is
    undefined (warm-up, missing price, zero variance) the state is held.

    Why a large |z| does not imply a profitable reversion: a z-score measures
    distance from a *trailing* mean, and that mean is itself a moving target.
    If the price is a random walk (or its drift just changed), the "deviation"
    is the new level, not a displacement from equilibrium. Reversion needs a
    stationary process, which price levels of broad ETFs generally are not, and
    even a real effect must exceed costs.
    """

    lookback: int = 20
    entry_z: float = 2.0
    exit_z: float = 0.0
    tickers: tuple[str, ...] | None = None
    name: str = "mean_reversion"

    def __post_init__(self) -> None:
        if self.lookback < 2:
            raise ValueError("lookback must be >= 2")
        if self.entry_z <= self.exit_z:
            raise ValueError("entry_z must exceed exit_z")

    def generate(self, data: MarketData, as_of: str | pd.Timestamp | None = None) -> StrategyOutput:
        data = apply_cutoff(data, as_of)
        tickers = list(self.tickers) if self.tickers else data.tickers
        close = data.close[tickers]

        def zscore(s: pd.Series) -> pd.Series:
            roll = s.rolling(self.lookback, min_periods=self.lookback)
            std = roll.std(ddof=1)
            return (s - roll.mean()) / std.where(std > 0)

        z = per_asset(close, zscore)

        signal = pd.DataFrame(0.0, index=close.index, columns=tickers)
        for t in tickers:  # explicit state machine: causal by construction
            held = False
            out = np.zeros(len(close))
            for i, zi in enumerate(z[t].to_numpy()):
                if not np.isnan(zi):
                    if not held and zi <= -self.entry_z:
                        held = True
                    elif held and zi >= -self.exit_z:
                        held = False
                out[i] = float(held)
            signal[t] = out
        daily = (signal / len(tickers)).reindex(columns=data.tickers, fill_value=0.0)
        return StrategyOutput(
            weights=decisions_on_change(daily),
            signals=signal.reindex(columns=data.tickers, fill_value=0.0),
            diagnostics={"zscore": z},
        )
