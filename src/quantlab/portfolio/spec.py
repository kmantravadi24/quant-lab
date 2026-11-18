"""A hypothetical portfolio: what to hold, how it is funded, and how it is maintained."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace

import pandas as pd

from quantlab.backtesting.engine import BacktestResult, run_backtest
from quantlab.data.cleaning import InsufficientHistoryError
from quantlab.data.models import MarketData
from quantlab.execution.costs import ExecutionConfig
from quantlab.strategies.fixed_weights import (
    FixedWeights,
    period_starts,
    validate_long_only_weights,
)


@dataclass(frozen=True)
class PortfolioSpec:
    """Long-only target weights (the remainder is cash), funding and rebalancing policy.

    Contains no account or personal information: it is safe to save and share.
    """

    weights: dict[str, float]
    initial_amount: float = 100_000.0
    contribution: float = 0.0  # added at the open of the first session of each period
    contribution_frequency: str = "M"  # W, M or Q
    rebalance: str | None = None  # None (never), M, Q or A
    name: str = "portfolio"

    def __post_init__(self) -> None:
        validate_long_only_weights(self.weights)
        for name in ("initial_amount", "contribution"):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be a finite number")
        if not self.initial_amount > 0:
            raise ValueError("initial_amount must be positive")
        if self.contribution < 0:
            raise ValueError("contribution cannot be negative (withdrawals are not supported)")
        if self.contribution_frequency not in ("W", "M", "Q"):
            raise ValueError("contribution_frequency must be 'W', 'M' or 'Q'")
        if self.rebalance not in (None, "M", "Q", "A"):
            raise ValueError("rebalance must be None, 'M', 'Q' or 'A'")

    @property
    def cash_weight(self) -> float:
        return max(0.0, 1.0 - sum(self.weights.values()))

    @property
    def tickers(self) -> list[str]:
        return [t for t, w in self.weights.items() if w > 0]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> PortfolioSpec:
        known = {k: payload[k] for k in cls.__dataclass_fields__ if k in payload}
        return cls(**known)

    def strategy(self) -> FixedWeights:
        deploy = self.contribution_frequency if self.contribution > 0 else None
        return FixedWeights(dict(self.weights), self.rebalance, deploy, name=self.name)


def contribution_schedule(dates: pd.DatetimeIndex, amount: float, frequency: str) -> pd.Series:
    """Contributions on the first session of each new period after the first session."""
    if amount <= 0:
        return pd.Series(dtype=float)
    starts = period_starts(pd.DatetimeIndex(dates), frequency)
    return pd.Series(float(amount), index=starts, name="contribution")


def simulate_portfolio(
    spec: PortfolioSpec,
    data: MarketData,
    config: ExecutionConfig | None = None,
    own_calendar: bool = True,
) -> BacktestResult:
    """Run the portfolio through the transaction engine.

    With ``own_calendar=True`` the sessions simulated are those on which at
    least one held instrument trades. With ``False`` every session in ``data``
    is used, so several portfolios can be compared on one identical calendar.
    ``config`` supplies costs; its ``initial_capital`` is replaced by
    ``spec.initial_amount``.
    """
    if len(data.dates) == 0:  # QA-016: an empty dataset is an error, not an empty result
        raise InsufficientHistoryError("The dataset has no sessions to simulate")
    universe = data.select(spec.tickers) if (spec.tickers and own_calendar) else data
    if len(universe.dates) == 0:
        raise InsufficientHistoryError("The held instruments have no sessions to simulate")
    cfg = replace(config or ExecutionConfig(), initial_capital=float(spec.initial_amount))
    plan = spec.strategy().generate(universe)
    flows = contribution_schedule(universe.dates, spec.contribution, spec.contribution_frequency)
    return run_backtest(
        universe, plan.weights, cfg, name=spec.name, cash_flows=flows, cash_only=plan.cash_only
    )
