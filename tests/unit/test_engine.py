"""Backtesting engine: timeline, accounting and constraint tests.

Expected values are computed by hand in the comments, never by calling the
engine a second time.
"""

import numpy as np
import pandas as pd
import pytest
from fixtures.synthetic import make_data, perturb_after

from quantlab.backtesting import backtest_strategy, run_backtest
from quantlab.data import SyntheticProvider
from quantlab.execution import ExecutionConfig, Order
from quantlab.portfolio import ConstraintViolation, Portfolio
from quantlab.strategies import (
    BuyAndHold,
    CrossSectionalMomentum,
    FixedWeights,
    MeanReversion,
    TrendFollowing,
)

FREE = ExecutionConfig(slippage_bps=0, fee_bps=0)
OPEN = {"A": [10.0, 11.0, 12.0, 13.0]}
CLOSE = {"A": [10.5, 11.5, 12.5, 13.5]}


def weights_at(data, i, **w):
    return pd.DataFrame([w], index=[data.dates[i]])


def test_next_open_execution_and_no_same_bar_fill():
    data = make_data(CLOSE, OPEN)
    res = run_backtest(data, weights_at(data, 0, A=1.0), FREE)
    assert len(res.trades) == 1
    trade = res.trades.iloc[0]
    # Decision at close of day 0 -> fill at the OPEN of day 1 (11.0), not day 0's close (10.5).
    assert trade["decision_date"] == data.dates[0]
    assert trade["date"] == data.dates[1]
    assert trade["fill_price"] == pytest.approx(11.0)
    shares = 100_000 / 11.0
    assert trade["shares"] == pytest.approx(shares)
    # Day 0: still all cash. Then marked at each close.
    expected = [100_000, shares * 11.5, shares * 12.5, shares * 13.5]
    np.testing.assert_allclose(res.equity.to_numpy(), expected)
    assert (res.trades["date"] > res.trades["decision_date"]).all()


def test_decision_on_last_session_never_trades():
    data = make_data(CLOSE, OPEN)
    res = run_backtest(data, weights_at(data, 3, A=1.0), FREE)
    assert res.trades.empty
    np.testing.assert_allclose(res.equity.to_numpy(), 100_000)


def test_cash_accounting_with_costs():
    data = make_data(CLOSE, OPEN)
    cfg = ExecutionConfig(slippage_bps=10, fee_bps=5)
    res = run_backtest(data, weights_at(data, 0, A=0.5), cfg)
    shares = 50_000 / 11.0  # sized on the reference open
    fill = 11.0 * 1.001  # 10 bps adverse slippage
    notional = shares * fill  # 50,050
    fee = notional * 0.0005  # 25.025
    t = res.trades.iloc[0]
    assert t["fill_price"] == pytest.approx(fill)
    assert t["notional"] == pytest.approx(50_050.0)
    assert fee == pytest.approx(25.025)
    assert t["fee"] == pytest.approx(fee)
    assert t["slippage_cost"] == pytest.approx(shares * 0.011)
    assert res.cash.iloc[1] == pytest.approx(100_000 - 50_050.0 - 25.025)
    assert res.equity.iloc[1] == pytest.approx(49_924.975 + shares * 11.5)


def test_round_trip_sell_proceeds_and_realized_pnl():
    data = make_data(CLOSE, OPEN)
    cfg = ExecutionConfig(slippage_bps=10, fee_bps=5)
    w = pd.DataFrame({"A": [0.5, 0.0]}, index=data.dates[:2])
    res = run_backtest(data, w, cfg)
    shares = 50_000 / 11.0
    cash_after_buy = 100_000 - 50_050.0 - 25.025
    sell_notional = shares * 12.0 * 0.999  # sold at day-2 open less slippage
    sell_fee = sell_notional * 0.0005
    assert res.cash.iloc[2] == pytest.approx(cash_after_buy + sell_notional - sell_fee)
    assert res.holdings["A"].iloc[2] == 0.0
    assert res.equity.iloc[3] == pytest.approx(res.cash.iloc[2])  # flat after exit
    realized = sell_notional - sell_fee - (50_050.0 + 25.025)
    assert res.trades.iloc[1]["realized_pnl"] == pytest.approx(realized)


def test_full_allocation_never_borrows_to_pay_costs():
    data = make_data(CLOSE, OPEN)
    cfg = ExecutionConfig(slippage_bps=10, fee_bps=5, fixed_fee=1.0)
    res = run_backtest(data, weights_at(data, 0, A=1.0), cfg)
    # Shares are scaled so that shares*open*(1.001)*(1.0005) + 1 == 100,000.
    shares = (100_000 - 1.0) / (11.0 * 1.001 * 1.0005)
    assert res.holdings["A"].iloc[1] == pytest.approx(shares, rel=1e-9)
    assert res.cash.min() >= 0
    assert res.cash.iloc[1] == pytest.approx(0.0, abs=1e-4)


def test_integer_share_buy_and_hold():
    data = make_data(CLOSE, OPEN)
    cfg = ExecutionConfig(slippage_bps=0, fee_bps=0, fractional_shares=False)
    res = backtest_strategy(BuyAndHold({"A": 1.0}), data, cfg)
    # floor(100000 / 11) = 9090 shares, 10 left in cash.
    assert res.holdings["A"].iloc[-1] == 9090
    assert res.cash.iloc[-1] == pytest.approx(10.0)
    assert res.equity.iloc[-1] == pytest.approx(10.0 + 9090 * 13.5)
    assert len(res.trades) == 1  # buy once, never trade again


def test_buy_and_hold_total_return_matches_price_ratio():
    data = make_data(CLOSE, OPEN)
    res = backtest_strategy(BuyAndHold({"A": 1.0}), data, FREE)
    # Bought at day-1 open (11), held to day-3 close (13.5).
    assert res.equity.iloc[-1] / 100_000 == pytest.approx(13.5 / 11.0)


@pytest.mark.parametrize("bad", [{"A": 1.2}, {"A": -0.1}, {"A": 0.7, "B": 0.5}, {"A": np.nan}])
def test_leverage_shorts_and_nan_weights_rejected(bad):
    data = make_data({"A": [10.0] * 4, "B": [10.0] * 4})
    with pytest.raises(ValueError):
        run_backtest(data, weights_at(data, 0, **bad), FREE)


def test_unknown_ticker_and_non_session_decision_rejected():
    data = make_data(CLOSE, OPEN)
    with pytest.raises(ValueError):
        run_backtest(data, weights_at(data, 0, ZZZ=1.0), FREE)
    off_calendar = pd.DataFrame({"A": [1.0]}, index=[pd.Timestamp("1999-01-01")])
    with pytest.raises(ValueError):
        run_backtest(data, off_calendar, FREE)


def test_portfolio_rejects_overdraft_and_oversell():
    cfg = FREE
    pf = Portfolio(cash=100.0)
    with pytest.raises(ConstraintViolation):
        pf.execute(Order("A", "BUY", 11.0, 10.0), cfg)  # needs 110
    pf.execute(Order("A", "BUY", 5.0, 10.0), cfg)
    assert pf.cash == pytest.approx(50.0)
    with pytest.raises(ConstraintViolation):
        pf.execute(Order("A", "SELL", 6.0, 10.0), cfg)  # holds only 5
    assert pf.equity({"A": 12.0}) == pytest.approx(50.0 + 5 * 12.0)


def test_missing_open_carries_order_forward_without_fabricating_a_trade():
    nan = np.nan
    data = make_data(
        close={"A": [10.0] * 5, "B": [20.0, nan, 25.0, nan, 25.0]},
        open_={"A": [10.0] * 5, "B": [20.0, nan, 25.0, nan, 25.0]},
    )
    res = run_backtest(data, weights_at(data, 0, A=0.5, B=0.5), FREE)
    d = data.dates
    a, b = res.trades[res.trades.ticker == "A"], res.trades[res.trades.ticker == "B"]
    assert list(a["date"]) == [d[1]] and a.iloc[0]["shares"] == pytest.approx(5000)
    # B had no price on day 1: no trade that day, logged, filled at the day-2 open instead.
    assert list(b["date"]) == [d[2]] and b.iloc[0]["shares"] == pytest.approx(2000)
    assert list(res.unfilled["date"]) == [d[1]] and list(res.unfilled["ticker"]) == ["B"]
    assert res.holdings.loc[d[1], "B"] == 0
    # Day 3: B has no close -> marked at its last price (25) and flagged stale.
    assert res.stale_marks.loc[d[3], "B"]
    assert res.positions.loc[d[3], "B"] == pytest.approx(50_000)
    assert not res.stale_marks["A"].any()


def test_insufficient_history_produces_no_trades():
    data = SyntheticProvider(3).fetch(["SPY"], "2020-01-01", "2020-05-29")  # ~107 sessions
    res = backtest_strategy(TrendFollowing(50, 200), data)
    assert res.target_weights.empty and res.trades.empty
    np.testing.assert_allclose(res.equity.to_numpy(), 100_000)


def test_flat_market():
    data = make_data({"A": [100.0] * 60, "B": [100.0] * 60})
    for strat in (TrendFollowing(5, 20), MeanReversion(10, 1.0, 0.0)):
        res = backtest_strategy(strat, data)
        assert res.trades.empty, strat.name
        np.testing.assert_allclose(res.equity.to_numpy(), 100_000)
    res = backtest_strategy(BuyAndHold({"A": 1.0}), data, FREE)
    np.testing.assert_allclose(res.equity.to_numpy(), 100_000)
    np.testing.assert_allclose(res.returns.to_numpy(), 0.0, atol=1e-15)


STRATEGIES = [
    BuyAndHold({"SPY": 0.6, "TLT": 0.4}),
    FixedWeights({"SPY": 0.5, "QQQ": 0.2, "TLT": 0.2}, rebalance="M", deploy="W"),
    TrendFollowing(20, 50),
    MeanReversion(10, 1.0, 0.0),
    CrossSectionalMomentum(lookback=60, top_n=2),
    CrossSectionalMomentum(lookback=60, top_n=2, weighting="inverse_vol", rebalance="W"),
]


@pytest.fixture(scope="module")
def market():
    return SyntheticProvider(11).fetch(["SPY", "QQQ", "TLT"], "2018-01-01", "2020-06-30")


@pytest.mark.parametrize("strategy", STRATEGIES, ids=lambda s: f"{s.name}")
def test_future_perturbation_does_not_change_the_past(strategy, market):
    cutoff = market.dates[400]
    shocked = perturb_after(market, cutoff)
    assert not shocked.close.loc[cutoff:].iloc[1:].equals(market.close.loc[cutoff:].iloc[1:])

    base_out, shock_out = strategy.generate(market), strategy.generate(shocked)
    pd.testing.assert_frame_equal(base_out.weights.loc[:cutoff], shock_out.weights.loc[:cutoff])
    pd.testing.assert_frame_equal(base_out.signals.loc[:cutoff], shock_out.signals.loc[:cutoff])
    assert len(base_out.weights.loc[:cutoff]) > 0

    base, shock = backtest_strategy(strategy, market), backtest_strategy(strategy, shocked)
    pd.testing.assert_series_equal(base.equity.loc[:cutoff], shock.equity.loc[:cutoff])
    pd.testing.assert_frame_equal(base.holdings.loc[:cutoff], shock.holdings.loc[:cutoff])
    past = lambda r: r.trades[r.trades.date <= cutoff].reset_index(drop=True)  # noqa: E731
    pd.testing.assert_frame_equal(past(base), past(shock))


@pytest.mark.parametrize("strategy", STRATEGIES, ids=lambda s: f"{s.name}")
def test_truncated_history_gives_identical_decisions(strategy, market):
    cutoff = market.dates[400]
    full = strategy.generate(market).weights.loc[:cutoff]
    truncated = strategy.generate(market, as_of=cutoff).weights
    pd.testing.assert_frame_equal(full, truncated)


@pytest.mark.parametrize("strategy", STRATEGIES, ids=lambda s: f"{s.name}")
@pytest.mark.parametrize("fractional", [True, False])
def test_accounting_identity_and_no_leverage(strategy, market, fractional):
    cfg = ExecutionConfig(slippage_bps=5, fee_bps=2, fixed_fee=1.0, fractional_shares=fractional)
    res = backtest_strategy(strategy, market, cfg)
    assert len(res.trades) > 0
    # Independent valuation straight from the dataset's closes.
    marked = (res.holdings * market.close).sum(axis=1)
    np.testing.assert_allclose(res.equity.to_numpy(), (res.cash + marked).to_numpy(), rtol=1e-12)
    assert res.cash.min() >= -1e-6  # never borrows
    assert (res.holdings.to_numpy() >= 0).all()  # never short
    assert (marked <= res.equity + 1e-6).all()  # gross exposure <= 100%
    assert (res.trades["date"] > res.trades["decision_date"]).all()
    # Cash only changes through recorded fills.
    signed = np.where(res.trades.side == "BUY", -1.0, 1.0) * res.trades.notional - res.trades.fee
    assert res.cash.iloc[-1] == pytest.approx(100_000 + signed.sum(), abs=1e-6)


def test_strategy_and_benchmark_share_one_calendar(market):
    strat = backtest_strategy(TrendFollowing(20, 50), market)
    bench = backtest_strategy(BuyAndHold({"SPY": 1.0}), market)
    assert strat.returns.index.equals(bench.returns.index)
    assert strat.returns.index.equals(market.dates)


def test_higher_costs_never_help(market):
    cheap = backtest_strategy(TrendFollowing(20, 50), market, FREE)
    dear = backtest_strategy(TrendFollowing(20, 50), market, ExecutionConfig(50, 50))
    assert dear.equity.iloc[-1] < cheap.equity.iloc[-1]
