"""Robustness sweeps: parameters, transaction costs, subperiods."""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import replace

import pandas as pd

from quantlab.analytics.metrics import performance_summary
from quantlab.backtesting.engine import BacktestResult, backtest_strategy
from quantlab.data.models import MarketData
from quantlab.execution.costs import ExecutionConfig
from quantlab.research.trials import TrialRegistry
from quantlab.strategies.base import Strategy


def evaluate(
    result: BacktestResult,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    benchmark: pd.Series | None = None,
    risk_free: float = 0.0,
) -> dict[str, float]:
    """Summary statistics of a backtest restricted to [start, end].

    The backtest itself runs on the full history so indicators are warmed up
    using only *earlier* data; restricting the evaluation window is what keeps
    the out-of-sample period untouched during development.
    """
    r = result.returns.loc[start:end]
    b = None if benchmark is None else benchmark.loc[start:end]
    trades = result.trades
    if len(trades):
        mask = pd.Series(True, index=trades.index)
        if start is not None:
            mask &= trades["date"] >= pd.Timestamp(start)
        if end is not None:
            mask &= trades["date"] <= pd.Timestamp(end)
        trades = trades[mask]
    return performance_summary(
        r, b, risk_free=risk_free, turnover=result.turnover.loc[start:end], trades=trades
    )


def parameter_grid(
    factory: Callable[..., Strategy],
    grid: dict[str, list],
    data: MarketData,
    config: ExecutionConfig | None = None,
    start: str | None = None,
    end: str | None = None,
    period_label: str = "development",
    registry: TrialRegistry | None = None,
) -> pd.DataFrame:
    """Evaluate every valid parameter combination on [start, end]; one row per combination.

    Combinations the strategy rejects (ValueError, e.g. fast >= slow) are skipped.
    Every evaluated combination is recorded in ``registry``.
    """
    rows = []
    keys = list(grid)
    for values in itertools.product(*(grid[k] for k in keys)):
        params = dict(zip(keys, values, strict=True))
        try:
            strategy = factory(**params)
        except ValueError:
            continue
        stats = evaluate(backtest_strategy(strategy, data, config), start, end)
        rows.append({**params, **stats})
        if registry is not None:
            registry.record(strategy.name, params, period_label, sharpe=stats["sharpe"])
    return pd.DataFrame(rows)


def cost_sensitivity(
    strategy: Strategy,
    data: MarketData,
    cost_levels_bps: list[float],
    base: ExecutionConfig | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Re-run a strategy with total one-way cost (slippage + fee) set to each level, in bps."""
    base = base or ExecutionConfig()
    rows = []
    for bps in cost_levels_bps:
        cfg = replace(base, slippage_bps=bps / 2, fee_bps=bps / 2)
        stats = evaluate(backtest_strategy(strategy, data, cfg), start, end)
        rows.append({"cost_bps": bps, **stats})
    return pd.DataFrame(rows).set_index("cost_bps")


def subperiod_table(
    results: dict[str, BacktestResult], periods: list[tuple[str, str]], metrics: list[str]
) -> pd.DataFrame:
    """Selected metrics for each named backtest in each subperiod."""
    rows = []
    for start, end in periods:
        for name, result in results.items():
            stats = evaluate(result, start, end)
            rows.append({"period": f"{start} to {end}", "strategy": name}
                        | {m: stats[m] for m in metrics})  # fmt: skip
    return pd.DataFrame(rows).set_index(["period", "strategy"])
