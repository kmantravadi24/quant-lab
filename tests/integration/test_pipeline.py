"""End-to-end: data -> strategy -> backtest -> analytics -> research -> record, offline."""

import json

import numpy as np

from quantlab.analytics import performance_summary
from quantlab.backtesting import backtest_strategy
from quantlab.data import SyntheticProvider
from quantlab.execution import ExecutionConfig
from quantlab.reporting import markdown_table, save_experiment
from quantlab.research import (
    TrialRegistry,
    bootstrap_ci,
    chronological_split,
    cost_sensitivity,
    evaluate,
    parameter_grid,
)
from quantlab.risk import covariance_matrix, portfolio_returns
from quantlab.simulations import simulate
from quantlab.strategies import BuyAndHold, TrendFollowing


def test_full_research_pipeline(tmp_path):
    data = SyntheticProvider(4).fetch(["SPY", "TLT"], "2012-01-01", "2020-12-31")
    cfg = ExecutionConfig()
    split = chronological_split(data.dates, "2017-12-31")
    dev_start, dev_end = split.development

    registry = TrialRegistry()
    grid = parameter_grid(
        lambda fast, slow: TrendFollowing(fast, slow, tickers=("SPY",)),
        {"fast": [20, 50, 100], "slow": [100, 200]},
        data, cfg, dev_start, dev_end, registry=registry,
    )  # fmt: skip
    assert len(grid) == 5  # (100, 100) is invalid and skipped
    assert registry.count == 5

    trend = backtest_strategy(TrendFollowing(50, 200, tickers=("SPY",)), data, cfg)
    bench = backtest_strategy(BuyAndHold({"SPY": 1.0}), data, cfg)
    stats = evaluate(trend, *split.test, benchmark=bench.returns)
    assert {"sharpe", "max_drawdown", "beta", "turnover", "win_rate"} <= set(stats)
    assert 0 <= stats["beta"] <= 1.0001  # long-or-cash in the benchmark asset

    costs = cost_sensitivity(TrendFollowing(50, 200, tickers=("SPY",)), data, [0, 10, 50], cfg)
    assert costs["total_return"].is_monotonic_decreasing

    ci = bootstrap_ci(trend.returns, lambda r: r.mean() * 252, n_boot=100)
    assert ci.lower <= ci.estimate <= ci.upper

    rets = (data.close / data.close.shift(1) - 1).dropna()
    port = portfolio_returns(rets, covariance_matrix(rets).index.to_series().map(lambda _: 0.5))
    mc = simulate(port, horizon=21, n_paths=100)
    assert np.isfinite(list(mc.summary().values())).all()

    path = save_experiment(
        "pipeline_test",
        {"fast": 50, "slow": 200, "split": split.to_dict()},
        data.metadata.to_dict(),
        {"stats": stats, "grid": grid, "trials": registry.count},
        tmp_path,
    )
    record = json.loads(path.read_text())
    assert record["data"]["synthetic"] is True
    assert record["results"]["trials"] == 5
    assert "| fast |" in markdown_table(grid[["fast", "slow", "sharpe"]].set_index("fast"))
    assert performance_summary(bench.returns)["n_obs"] == len(data.dates)
