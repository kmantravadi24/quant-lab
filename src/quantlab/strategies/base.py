"""Strategy interface.

A strategy turns market observations into *target portfolio weights*. It never
touches cash, fills or performance: that is the backtesting engine's job.

Timing contract
---------------
A row of ``weights`` dated T is a decision made *after the close of session T*
using observations dated <= T only. The engine executes it no earlier than the
open of the next session. Only decision dates appear in ``weights``; between
decisions the portfolio drifts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

import pandas as pd

from quantlab.data.models import MarketData


@dataclass(frozen=True)
class StrategyOutput:
    weights: pd.DataFrame  # index: decision dates; columns: tickers; each row sums to <= 1
    signals: pd.DataFrame  # daily, interpretable signal per ticker (full calendar)
    diagnostics: dict[str, pd.DataFrame] = field(default_factory=dict)
    # Decision dates on which spare cash is invested at the target mix WITHOUT rebalancing
    # existing holdings (used for contributions). Empty for ordinary strategies.
    cash_only: pd.DatetimeIndex = field(default_factory=lambda: pd.DatetimeIndex([]))


class Strategy(Protocol):
    name: str

    def generate(self, data: MarketData, as_of: str | pd.Timestamp | None = None) -> StrategyOutput:
        """Compute decisions using observations on or before ``as_of`` (default: all)."""
        ...


def apply_cutoff(data: MarketData, as_of: str | pd.Timestamp | None) -> MarketData:
    return data if as_of is None else data.truncate(as_of)


def per_asset(
    close: pd.DataFrame, fn: Callable[[pd.Series], pd.Series], max_stale: int = 5
) -> pd.DataFrame:
    """Apply ``fn`` to each asset's own observed closes, then align to the shared calendar.

    Rolling a window over the union calendar would let one missing price blank
    an indicator for a whole window. Here each indicator is computed on the
    asset's own sessions. On a session where the asset has no price, the value
    from its last observation is carried forward (past information only) for at
    most ``max_stale`` sessions; after that it is NaN, i.e. "no signal".
    """
    out = {}
    for ticker in close.columns:
        own = fn(close[ticker].dropna())
        carried = own.reindex(close.index, method="ffill", limit=max_stale)
        observed = close[ticker].notna()
        out[ticker] = own.reindex(close.index).where(observed, carried)
    return pd.DataFrame(out, index=close.index)


def decisions_on_change(daily_target: pd.DataFrame) -> pd.DataFrame:
    """Keep only the dates on which the daily target differs from the previous session.

    The portfolio starts in cash, so the implicit target before the first
    session is all-zero; nothing is emitted until the first non-zero target.
    """
    previous = daily_target.shift(1).fillna(0.0)
    changed = (daily_target != previous).any(axis=1)
    return daily_target.loc[changed]
