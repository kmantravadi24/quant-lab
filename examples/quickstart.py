"""Use the engine from plain Python, with no dashboard and no network.

    python examples/quickstart.py
"""

from quantlab.analytics import performance_summary
from quantlab.backtesting import backtest_strategy
from quantlab.data import SyntheticProvider
from quantlab.execution import ExecutionConfig
from quantlab.research import bootstrap_ci
from quantlab.simulations import simulate
from quantlab.strategies import BuyAndHold, TrendFollowing

# Swap in CachedProvider(YFinanceProvider()) for real data.
data = SyntheticProvider(seed=1).fetch(["SPY", "TLT"], "2012-01-01", "2023-12-29")
print(f"Dataset: {data.metadata.source}, synthetic={data.metadata.synthetic}, "
      f"{data.metadata.start} to {data.metadata.end}")

config = ExecutionConfig(initial_capital=100_000, slippage_bps=2, fee_bps=1)
trend = backtest_strategy(TrendFollowing(50, 200, tickers=("SPY",)), data, config)
bench = backtest_strategy(BuyAndHold({"SPY": 1.0}), data, config)

stats = performance_summary(trend.returns, bench.returns, turnover=trend.turnover,
                            trades=trend.trades)
for key in ("cagr", "volatility", "sharpe", "max_drawdown", "beta", "turnover", "trade_count"):
    print(f"{key:>14}: {stats[key]:.4f}")

print("\nFirst fills (note date > decision_date):")
print(trend.trades[["decision_date", "date", "side", "shares", "fill_price", "fee"]].head(4))

ci = bootstrap_ci(trend.returns, lambda r: r.mean() * 252, n_boot=500, block=21, seed=0)
print(f"\nMean annual return {ci.estimate:.2%}, 95% interval {ci.lower:.2%} to {ci.upper:.2%}")

mc = simulate(trend.returns, horizon=252, n_paths=1000, seed=42)
print(f"Monte Carlo, 1 year: P(loss) = {mc.summary()['prob_loss']:.1%} (a model property)")
