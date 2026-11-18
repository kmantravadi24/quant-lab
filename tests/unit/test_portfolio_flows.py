"""Investment Lab foundation: contributions, fixed-weight portfolios, TWR and MWR.

Expected values are worked by hand in the comments or produced by an
independent method (a unitised fund, SciPy's root finder), never by calling the
code under test twice.
"""

import math
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from fixtures.synthetic import make_data, perturb_after
from scipy.optimize import brentq

from quantlab.analytics import metrics as m
from quantlab.analytics.flows import (
    flow_summary,
    investor_cash_flows,
    money_weighted_return,
)
from quantlab.backtesting import backtest_strategy, run_backtest
from quantlab.data import SyntheticProvider
from quantlab.execution import ExecutionConfig, size_cash_deployment
from quantlab.portfolio import PortfolioSpec, contribution_schedule, simulate_portfolio
from quantlab.strategies import BuyAndHold, FixedWeights
from quantlab.strategies.fixed_weights import period_starts

FREE = ExecutionConfig(initial_capital=1000.0, slippage_bps=0, fee_bps=0)


def unitised_returns(result) -> np.ndarray:
    """Independent TWR: run the portfolio as a fund that issues units at the flow boundary.

    Unit price before a deposit = equity at the open / units outstanding. The
    deposit buys units at that price. The daily return is the change in the
    closing unit price. No formula from the engine is reused.
    """
    units = result.config.initial_capital  # start at a unit price of 1
    price_prev, out = 1.0, []
    for i in range(len(result.equity)):
        deposit = result.cash_flows.iloc[i]
        if deposit:
            units += deposit / (result.equity_before_flow.iloc[i] / units)
        price = result.equity.iloc[i] / units
        out.append(price / price_prev - 1)
        price_prev = price
    return np.array(out)


def one_asset(open_, close):
    data = make_data({"A": close}, {"A": open_})  # sessions 2024-01-01 .. 04 (Mon-Thu)
    d = data.dates
    weights = pd.DataFrame({"A": [1.0, 1.0]}, index=[d[0], d[2]])
    flows = pd.Series({d[2]: 500.0})
    return data, run_backtest(data, weights, FREE, cash_flows=flows, cash_only=pd.DatetimeIndex([d[2]]))


# ----------------------------------------------------------------- time-weighted return


def test_contribution_day_with_an_overnight_fall_and_an_intraday_rise():
    #          d0     d1     d2                      d3
    # open    100    100     99  (-10% overnight)   108.9
    # close   100    110    108.9 (+10% intraday)   119.79 (+10%)
    # d1: 1000 buys 10 shares at 100 -> close 1100.
    # d2 open: holdings 10 x 99 = 990 (overnight leg 990/1100 = 0.90). Deposit 500 -> 1490.
    #    close: 10 x 108.9 + 500 cash = 1589 (intraday leg 1589/1490 = 1.066443).
    #    day return = 0.90 x 1.066443 - 1 = -4.0201%  (the deposit sat in cash during the rebound)
    # d3 open: the 500 buys 500/108.9 = 4.591368 shares; close 14.591368 x 119.79 = 1747.90.
    data, res = one_asset([100, 100, 99, 108.9], [100, 110, 108.9, 119.79])
    np.testing.assert_allclose(res.equity, [1000, 1100, 1589, 1747.9])
    assert res.equity_before_flow.iloc[2] == pytest.approx(990.0)
    assert res.holdings["A"].iloc[3] == pytest.approx(10 + 500 / 108.9)
    expected = [0.0, 0.10, 0.90 * (1589 / 1490) - 1, 0.10]
    np.testing.assert_allclose(res.returns, expected, atol=1e-12)
    assert res.returns.iloc[2] == pytest.approx(-0.040201, abs=1e-6)
    # The rejected shortcut (E - C) / E_prev - 1 would give -1.0% and hide the cash drag.
    assert pytest.approx(-0.01) == (1589 - 500) / 1100 - 1
    assert abs(res.returns.iloc[2] - (-0.01)) > 0.03
    np.testing.assert_allclose(res.returns, unitised_returns(res), atol=1e-12)
    assert m.total_return(res.returns) == pytest.approx(1.1 * 0.90 * (1589 / 1490) * 1.1 - 1)


def test_contribution_day_with_an_overnight_rise_and_an_intraday_fall():
    # d2 open 121 (+10% overnight): holdings 1210; deposit 500 -> 1710.
    #    close 108.9 (-10% intraday): 1089 + 500 = 1589. Day = 1.10 x (1589/1710) - 1 = +2.2164%.
    data, res = one_asset([100, 100, 121, 108.9], [100, 110, 108.9, 119.79])
    assert res.equity_before_flow.iloc[2] == pytest.approx(1210.0)
    assert res.returns.iloc[2] == pytest.approx(1.10 * (1589 / 1710) - 1)
    assert res.returns.iloc[2] == pytest.approx(0.022164, abs=1e-6)
    np.testing.assert_allclose(res.returns, unitised_returns(res), atol=1e-12)


def test_time_weighted_return_does_not_depend_on_the_size_of_the_contribution():
    """Flow-neutral means the amount deposited cannot change the return of fully invested days."""
    data = make_data({"A": [100, 110, 99, 120, 132, 125]}, {"A": [100, 100, 104, 110, 125, 130]})
    d = data.dates
    weights = pd.DataFrame({"A": [1.0]}, index=[d[0]])
    base = run_backtest(data, weights, FREE)
    for amount in (1.0, 500.0, 1e6):
        res = run_backtest(data, weights, FREE, cash_flows=pd.Series({d[3]: amount}))
        np.testing.assert_allclose(res.returns, unitised_returns(res), atol=1e-12)
        # Before the deposit the two runs are identical; after it, uninvested cash dilutes.
        np.testing.assert_array_equal(res.returns.iloc[:3], base.returns.iloc[:3])
        assert res.cash.iloc[-1] == pytest.approx(amount)  # never deployed: no decision followed


def test_no_contribution_runs_are_bit_identical_to_the_previous_engine_behaviour():
    data = SyntheticProvider(4).fetch(["SPY", "TLT"], "2019-01-01", "2021-12-31")
    cfg = ExecutionConfig(slippage_bps=3, fee_bps=2)
    old = backtest_strategy(BuyAndHold({"SPY": 0.6, "TLT": 0.4}), data, cfg)
    new = backtest_strategy(FixedWeights({"SPY": 0.6, "TLT": 0.4}), data, cfg)
    pd.testing.assert_series_equal(old.equity, new.equity)  # exact, not approximate
    pd.testing.assert_series_equal(old.returns, new.returns)
    pd.testing.assert_frame_equal(old.trades, new.trades)
    # The original return definition still holds exactly when there is no flow.
    legacy = old.equity / old.equity.shift(1).fillna(cfg.initial_capital) - 1.0
    pd.testing.assert_series_equal(new.returns, legacy.rename("returns"))
    assert new.cash_flows.sum() == 0 and new.equity_before_flow.isna().all()
    # An explicitly empty or all-zero flow series is the same thing.
    plan = FixedWeights({"SPY": 0.6, "TLT": 0.4}).generate(data)
    zero = run_backtest(data, plan.weights, cfg, cash_flows=pd.Series(0.0, index=data.dates[:3]))
    pd.testing.assert_series_equal(zero.equity, old.equity)


# ----------------------------------------------------------------- money-weighted return


def test_money_weighted_return_closed_form_cases():
    flows = pd.Series({pd.Timestamp("2020-01-01"): -1000.0, pd.Timestamp("2021-12-31"): 1210.0})
    # 730 days at actual/365 is exactly two years: 1000 x (1 + r)^2 = 1210 -> r = 10%.
    result = money_weighted_return(flows)
    assert result.ok and result.span_days == 730 and result.rate == pytest.approx(0.10, abs=1e-10)
    loss = pd.Series({pd.Timestamp("2020-01-01"): -1000.0, pd.Timestamp("2020-12-31"): 500.0})
    assert money_weighted_return(loss).rate == pytest.approx(-0.5, abs=1e-9)  # 365 days
    flat = pd.Series({pd.Timestamp("2020-01-01"): -1000.0, pd.Timestamp("2020-07-01"): -500.0,
                      pd.Timestamp("2021-01-01"): 1500.0})  # fmt: skip
    assert money_weighted_return(flat).rate == pytest.approx(0.0, abs=1e-10)


def test_money_weighted_return_matches_an_independent_root_finder():
    rng = np.random.default_rng(3)
    for _ in range(25):
        dates = pd.to_datetime("2015-01-01") + pd.to_timedelta(np.sort(rng.integers(0, 3000, 8)), "D")
        dates = pd.DatetimeIndex(dates).unique()
        amounts = -rng.uniform(100, 1000, len(dates))
        amounts[-1] = -amounts[:-1].sum() * rng.uniform(0.3, 3.0)  # final value
        flows = pd.Series(amounts, index=dates)
        years = np.array([(d - dates[0]).days for d in dates]) / 365.0
        reference = brentq(lambda r, a=amounts, y=years: np.sum(a / (1 + r) ** y), -0.9999, 1e4,
                           xtol=1e-13)  # fmt: skip
        got = money_weighted_return(flows)
        assert got.ok and got.rate == pytest.approx(reference, abs=1e-9)


@pytest.mark.parametrize(
    "amounts, dates, status",
    [
        ([-1000.0], ["2020-01-01"], "too_few_flows"),
        ([-1000.0, 1100.0], ["2020-01-01", "2020-01-01"], "too_few_flows"),  # net to one flow
        ([-1000.0, -500.0], ["2020-01-01", "2020-06-01"], "no_sign_change"),  # nothing came back
        ([-1000.0, 3000.0, -2100.0], ["2020-01-01", "2021-01-01", "2022-01-01"], "not_unique"),
    ],
)
def test_money_weighted_return_refuses_to_report_an_undefined_rate(amounts, dates, status):
    result = money_weighted_return(pd.Series(amounts, index=pd.to_datetime(dates)))
    assert result.status == status and math.isnan(result.rate) and not result.ok


def test_money_weighted_return_same_day_and_total_loss():
    day = pd.Timestamp("2020-01-01")
    same_day = pd.Series([-1000.0, 1100.0], index=[day, day + pd.Timedelta(hours=5)])
    assert money_weighted_return(same_day).status == "zero_span"
    # A portfolio that ends at zero has no finite rate above -100%.
    wiped = pd.Series({day: -1000.0, pd.Timestamp("2021-01-01"): 0.0})
    assert money_weighted_return(wiped).status == "too_few_flows"


def test_investor_flows_and_summary_for_the_worked_example():
    data, res = one_asset([100, 100, 99, 108.9], [100, 110, 108.9, 119.79])
    flows = investor_cash_flows(res)
    d = data.dates
    assert flows.to_dict() == pytest.approx({d[0]: -1000.0, d[2]: -500.0, d[3]: 1747.9})
    # 1000 invested for 3 days and 500 for 1 day grow to 1747.90:
    reference = brentq(lambda r: 1000 * (1 + r) ** (3 / 365) + 500 * (1 + r) ** (1 / 365) - 1747.9,
                       0, 1e12)  # fmt: skip
    summary = flow_summary(res)
    assert summary["money_weighted_annual"] == pytest.approx(reference, rel=1e-8)
    assert summary["money_weighted_status"] == "ok" and summary["span_days"] == 3
    assert summary["total_invested"] == 1500 and summary["gain"] == pytest.approx(247.9)
    assert summary["time_weighted_total"] == pytest.approx(1.1 * 0.9 * (1589 / 1490) * 1.1 - 1)
    # The two measures answer different questions and differ here.
    # Annualising three days gives an astronomically large rate; the period figure is the
    # meaningful one, and it solves 1000 (1+p) + 500 (1+p)^(1/3) = 1747.9.
    assert summary["money_weighted_annual"] > 1e9
    period = brentq(lambda p: 1000 * (1 + p) + 500 * (1 + p) ** (1 / 3) - 1747.9, 0, 1)
    assert summary["money_weighted_period"] == pytest.approx(period, rel=1e-8)
    assert period != pytest.approx(summary["time_weighted_total"], abs=1e-3)


# ----------------------------------------------------------------- deploying contributions


def test_cash_reserve_is_kept_when_a_contribution_is_deployed():
    # Target 80% A, 20% cash. 1000 -> 8 shares at 100, 200 cash. d2: deposit 500 -> cash 700.
    # d3 open 108.9: equity 8 x 108.9 + 700 = 1571.2; reserve 20% = 314.24; spare 385.76
    # -> buy 385.76 / 108.9 = 3.542332 shares; cash left 314.24.
    data = make_data({"A": [100, 110, 108.9, 119.79]}, {"A": [100, 100, 99, 108.9]})
    d = data.dates
    weights = pd.DataFrame({"A": [0.8, 0.8]}, index=[d[0], d[2]])
    res = run_backtest(data, weights, FREE, cash_flows=pd.Series({d[2]: 500.0}),
                       cash_only=pd.DatetimeIndex([d[2]]))  # fmt: skip
    assert res.holdings["A"].iloc[1] == pytest.approx(8.0) and res.cash.iloc[2] == pytest.approx(700)
    assert res.holdings["A"].iloc[3] == pytest.approx(8 + 385.76 / 108.9)
    assert res.cash.iloc[3] == pytest.approx(314.24)
    assert list(res.trades["side"]) == ["BUY", "BUY"]  # a deployment never sells


def test_deployment_pays_costs_out_of_the_new_cash_and_never_overdraws():
    data = make_data({"A": [100, 110, 108.9, 119.79]}, {"A": [100, 100, 99, 108.9]})
    d = data.dates
    cfg = ExecutionConfig(initial_capital=1000.0, slippage_bps=10, fee_bps=5, fixed_fee=1.0)
    weights = pd.DataFrame({"A": [1.0, 1.0]}, index=[d[0], d[2]])
    res = run_backtest(data, weights, cfg, cash_flows=pd.Series({d[2]: 500.0}),
                       cash_only=pd.DatetimeIndex([d[2]]))  # fmt: skip
    # Cash before the deployment: what the first (scaled) purchase left, about 0, plus 500.
    spare = res.cash.iloc[2]
    shares = (spare - 1.0) / (108.9 * 1.001 * 1.0005)  # after the fixed fee, slippage and fee
    assert res.trades.iloc[1]["shares"] == pytest.approx(shares, rel=1e-9)
    assert res.cash.min() >= 0 and res.cash.iloc[3] == pytest.approx(0.0, abs=1e-6)


def test_integer_shares_leave_the_remainder_in_cash():
    cfg = ExecutionConfig(slippage_bps=0, fee_bps=0, fractional_shares=False)
    orders, _ = size_cash_deployment({"A": 0.5, "B": 0.5}, 1.0, {"A": 30.0, "B": 7.0}, 1000.0, 100.0, cfg)
    assert {o.ticker: o.shares for o in orders} == {"A": 1, "B": 7}  # 50 each -> 1 x 30, 7 x 7
    none, _ = size_cash_deployment({"A": 1.0}, 1.0, {"A": 30.0}, 1000.0, 20.0, cfg)
    assert none == []  # 20 cannot buy one share
    reserve, _ = size_cash_deployment({"A": 0.5}, 0.5, {"A": 10.0}, 1000.0, 400.0, FREE)
    assert reserve == []  # cash is already below the 50% reserve: nothing to invest


def test_a_deployment_with_no_price_stays_in_cash_and_is_logged():
    nan = np.nan
    data = make_data({"A": [100, 100, 100, nan, 100]}, {"A": [100, 100, 100, nan, 100]})
    d = data.dates
    weights = pd.DataFrame({"A": [1.0, 1.0]}, index=[d[0], d[2]])
    res = run_backtest(data, weights, FREE, cash_flows=pd.Series({d[2]: 500.0}),
                       cash_only=pd.DatetimeIndex([d[2]]))  # fmt: skip
    assert len(res.trades) == 1 and res.cash.iloc[-1] == pytest.approx(500.0)  # not carried forward
    assert list(res.unfilled["date"]) == [d[3]]
    np.testing.assert_allclose(res.returns, unitised_returns(res), atol=1e-12)


# ----------------------------------------------------------------- rebalancing


def two_assets():
    dates = pd.DatetimeIndex(["2024-01-30", "2024-01-31", "2024-02-01", "2024-02-02"])
    return make_data({"A": [100.0] * 4, "B": [100, 120, 120, 120]},
                     {"A": [100.0] * 4, "B": [100, 100, 120, 120]}, dates=dates)  # fmt: skip


def test_monthly_rebalance_trades_back_to_target_at_the_next_open():
    # Jan 31 open: 5 A + 5 B. B rises to 120 -> equity 1100, weights 45.5% / 54.5%.
    # Feb 1 is the first session of a new month: decision at its close.
    # Feb 2 open: target 550 each -> A 5.5 shares (buy 0.5), B 4.58333 (sell 0.41667).
    data = two_assets()
    res = backtest_strategy(FixedWeights({"A": 0.5, "B": 0.5}, rebalance="M"), data, FREE)
    d = data.dates
    assert list(res.target_weights.index) == [d[0], d[2]]
    np.testing.assert_allclose(res.holdings.loc[d[2]], [5.0, 5.0])  # not yet traded on Feb 1
    np.testing.assert_allclose(res.holdings.loc[d[3]], [5.5, 550 / 120])
    np.testing.assert_allclose(res.weights.loc[d[3]], [0.5, 0.5])
    assert list(res.trades["date"]) == [d[1], d[1], d[3], d[3]]
    assert (res.trades["date"] > res.trades["decision_date"]).all()
    drifting = backtest_strategy(FixedWeights({"A": 0.5, "B": 0.5}), data, FREE)
    np.testing.assert_allclose(drifting.holdings.loc[d[3]], [5.0, 5.0])  # never rebalanced
    assert len(drifting.trades) == 2


def test_rebalance_with_costs_is_funded_by_the_sale_and_scaled_to_fit():
    # 10 bps fee. Sell 0.416667 B at 120 -> 50.00 less 0.05 fee = 49.95 available.
    # Buying 0.5 A would cost 50.05, so it is scaled: 49.95 / (100 x 1.001) = 0.499001 shares.
    cfg = ExecutionConfig(initial_capital=1000.0, slippage_bps=0, fee_bps=10)
    res = backtest_strategy(FixedWeights({"A": 0.5, "B": 0.5}, rebalance="M"), two_assets(), cfg)
    start_a = (500 / 100) / 1.001 * (1 - 1e-12)  # the opening buys were scaled for the fee too
    eq_open = start_a * 100 + (500 / 100 / 1.001) * 120 + res.cash.iloc[2]
    sell_b = start_a - 0.5 * eq_open / 120
    available = res.cash.iloc[2] + sell_b * 120 * (1 - 0.001)
    assert res.trades.iloc[2]["side"] == "SELL" and res.trades.iloc[2]["shares"] == pytest.approx(sell_b)
    assert res.trades.iloc[3]["shares"] == pytest.approx(available / (100 * 1.001), rel=1e-9)
    assert res.cash.min() >= 0 and res.cash.iloc[3] == pytest.approx(0.0, abs=1e-6)


def test_period_starts_follow_the_real_exchange_calendar():
    pytest.importorskip("exchange_calendars")
    from fixtures.live import sessions

    dates = pd.DatetimeIndex(sessions("2025-12-15", "2026-04-10"))
    months = period_starts(dates, "M")
    # 1 January 2026 is a holiday, so the year's first session is 2 January.
    assert [str(d.date()) for d in months] == ["2026-01-02", "2026-02-02", "2026-03-02", "2026-04-01"]
    assert [str(d.date()) for d in period_starts(dates, "Q")] == ["2026-01-02", "2026-04-01"]
    assert [str(d.date()) for d in period_starts(dates, "A")] == ["2026-01-02"]
    weeks = period_starts(dates, "W")
    assert str(weeks[0].date()) == "2025-12-22" and pd.Timestamp("2026-01-20") in weeks  # MLK Monday
    assert pd.Timestamp("2026-01-19") not in dates
    assert len(period_starts(dates[:1], "M")) == 0
    with pytest.raises(ValueError):
        period_starts(dates, "D")
    schedule = contribution_schedule(dates, 250.0, "M")
    assert list(schedule.index) == list(months) and (schedule == 250.0).all()
    assert contribution_schedule(dates, 0.0, "M").empty


def test_a_period_start_is_known_without_any_future_date():
    dates = pd.bdate_range("2024-01-02", "2024-06-28")
    full = period_starts(dates, "M")
    for cut in (30, 61, 100):
        partial = period_starts(dates[:cut], "M")
        assert list(partial) == [d for d in full if d <= dates[cut - 1]]


# ----------------------------------------------------------------- the portfolio as a whole


@pytest.fixture(scope="module")
def market():
    return SyntheticProvider(11).fetch(["SPY", "QQQ", "TLT"], "2018-01-01", "2020-06-30")


SPECS = [
    PortfolioSpec({"SPY": 0.6, "TLT": 0.4}, 10_000, 0.0),
    PortfolioSpec({"SPY": 0.6, "TLT": 0.4}, 10_000, 500.0, "M"),
    PortfolioSpec({"SPY": 0.5, "QQQ": 0.2, "TLT": 0.2}, 10_000, 250.0, "W", "Q"),
    PortfolioSpec({"SPY": 0.7}, 5_000, 1_000.0, "Q", "A"),
    PortfolioSpec({"SPY": 0.34, "QQQ": 0.33, "TLT": 0.33}, 2_000, 300.0, "M", "M"),
]


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: f"{s.contribution:g}{s.contribution_frequency}-{s.rebalance}")
@pytest.mark.parametrize("fractional", [True, False])
def test_funded_portfolio_invariants(spec, fractional, market):
    cfg = ExecutionConfig(slippage_bps=5, fee_bps=2, fixed_fee=0.5, fractional_shares=fractional)
    res = simulate_portfolio(spec, market, cfg)
    closes = market.close[res.holdings.columns]
    marked = (res.holdings * closes).sum(axis=1)
    np.testing.assert_allclose(res.equity, res.cash + marked, rtol=1e-12)  # accounting identity
    assert res.cash.min() >= -1e-6 and (res.holdings.to_numpy() >= 0).all()
    assert (marked <= res.equity + 1e-6).all()  # never leveraged
    assert (res.trades["date"] > res.trades["decision_date"]).all()
    # Every unit of cash is explained: initial + contributions +/- recorded fills.
    signed = np.where(res.trades.side == "BUY", -1.0, 1.0) * res.trades.notional - res.trades.fee
    assert res.cash.iloc[-1] == pytest.approx(spec.initial_amount + res.cash_flows.sum() + signed.sum(), abs=1e-6)
    np.testing.assert_allclose(res.returns, unitised_returns(res), atol=1e-12)  # flow-neutral TWR
    expected = contribution_schedule(res.equity.index, spec.contribution, spec.contribution_frequency)
    assert res.cash_flows.sum() == pytest.approx(expected.sum())
    summary = flow_summary(res)
    assert summary["final_value"] == pytest.approx(res.equity.iloc[-1])
    assert summary["money_weighted_status"] == "ok"
    if spec.contribution == 0:  # one deposit, one final value: MWR equals the calendar-time CAGR
        years = summary["span_days"] / 365
        assert summary["money_weighted_annual"] == pytest.approx(
            (res.equity.iloc[-1] / spec.initial_amount) ** (1 / years) - 1, abs=1e-9)  # fmt: skip


def test_contributions_are_invested_at_the_next_open_not_the_same_day(market):
    spec = PortfolioSpec({"SPY": 1.0}, 10_000, 500.0, "M")
    res = simulate_portfolio(spec, market, ExecutionConfig(slippage_bps=0, fee_bps=0))
    days = res.cash_flows[res.cash_flows > 0].index
    assert len(days) == 29  # February 2018 to June 2020
    for day in days[:6]:
        nxt = res.equity.index[res.equity.index.get_loc(day) + 1]
        assert res.cash.loc[day] == pytest.approx(500.0)  # waits one session in cash
        assert res.cash.loc[nxt] == pytest.approx(0.0, abs=1e-6)
        fills = res.trades[res.trades.date == nxt]
        assert list(fills["decision_date"]) == [day] and list(fills["side"]) == ["BUY"]
        assert fills["notional"].iloc[0] == pytest.approx(500.0, rel=1e-9)


def test_rebalancing_keeps_weights_near_target_and_no_rebalancing_lets_them_drift(market):
    weights = {"SPY": 0.5, "TLT": 0.5}
    free = ExecutionConfig(slippage_bps=0, fee_bps=0)
    monthly = simulate_portfolio(PortfolioSpec(weights, 10_000, rebalance="M"), market, free)
    never = simulate_portfolio(PortfolioSpec(weights, 10_000), market, free)
    assert len(never.trades) == 2 and len(monthly.trades) > 40
    fills = monthly.trades.groupby("date").size().index[1:]
    opens = market.open[["SPY", "TLT"]]
    for day in fills[:8]:  # at the rebalancing open, each holding is exactly half of equity
        value = monthly.holdings.loc[day] * opens.loc[day]
        np.testing.assert_allclose(value / value.sum(), [0.5, 0.5], atol=1e-9)
    invested = never.equity.index[2:]  # after the opening purchase
    drift = (never.weights.loc[invested, "SPY"] - 0.5).abs().max()
    assert drift > 0.02 and (monthly.weights.loc[invested, "SPY"] - 0.5).abs().max() < drift


def test_rewriting_the_future_cannot_change_a_funded_portfolio_s_past(market):
    spec = PortfolioSpec({"SPY": 0.6, "TLT": 0.4}, 10_000, 500.0, "M", "Q")
    cutoff = market.dates[400]
    base = simulate_portfolio(spec, market)
    shocked = simulate_portfolio(spec, perturb_after(market, cutoff))
    pd.testing.assert_series_equal(base.equity.loc[:cutoff], shocked.equity.loc[:cutoff])
    pd.testing.assert_series_equal(base.returns.loc[:cutoff], shocked.returns.loc[:cutoff])
    pd.testing.assert_series_equal(base.cash_flows, shocked.cash_flows)  # the plan is price-free
    plan, plan2 = spec.strategy().generate(market), spec.strategy().generate(market, as_of=cutoff)
    pd.testing.assert_frame_equal(plan.weights.loc[:cutoff], plan2.weights)
    assert list(plan.cash_only[plan.cash_only <= cutoff]) == list(plan2.cash_only)


def test_instruments_that_start_later_delay_the_first_purchase_but_not_the_deposits():
    nan = np.nan
    dates = pd.bdate_range("2024-01-29", "2024-03-08")
    late = [nan] * 10 + [50.0] * (len(dates) - 10)
    data = make_data({"A": [100.0] * len(dates), "B": late}, dates=dates)
    res = simulate_portfolio(PortfolioSpec({"A": 0.5, "B": 0.5}, 1000, 100.0, "M"), data, FREE)
    first_b = dates[10]
    assert res.trades["date"].min() == dates[11]  # decided when both had a price, filled next open
    assert res.target_weights.index[0] == first_b
    assert res.cash.loc[dates[5]] == pytest.approx(1100.0)  # February's deposit waited in cash
    assert res.holdings.loc[:first_b].to_numpy().sum() == 0  # nothing bought, nothing invented


# ----------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "kwargs",
    [
        {"weights": {}},
        {"weights": {"A": -0.1, "B": 0.5}},
        {"weights": {"A": 0.7, "B": 0.4}},
        {"weights": {"A": float("nan")}},
        {"weights": {"A": float("inf")}},
        {"weights": {"A": 1.0}, "initial_amount": 0},
        {"weights": {"A": 1.0}, "contribution": -50},
        {"weights": {"A": 1.0}, "contribution_frequency": "D"},
        {"weights": {"A": 1.0}, "rebalance": "W"},
    ],
)
def test_invalid_portfolio_specifications_are_rejected(kwargs):
    with pytest.raises(ValueError):
        PortfolioSpec(**kwargs)


def test_engine_rejects_invalid_cash_flows_and_cash_only_dates():
    data = make_data({"A": [10.0] * 5})
    d = data.dates
    weights = pd.DataFrame({"A": [1.0]}, index=[d[0]])
    for bad in (pd.Series({d[1]: -5.0}), pd.Series({d[1]: np.nan}), pd.Series({d[1]: np.inf}),
                pd.Series({pd.Timestamp("1999-01-04"): 5.0}), pd.Series([1.0, 2.0], index=[d[1], d[1]])):  # fmt: skip
        with pytest.raises(ValueError):
            run_backtest(data, weights, FREE, cash_flows=bad)
    with pytest.raises(ValueError, match="cash-only"):
        run_backtest(data, weights, FREE, cash_only=pd.DatetimeIndex([d[2]]))
    with pytest.raises(KeyError):
        simulate_portfolio(PortfolioSpec({"ZZZ": 1.0}), data)
    with pytest.raises(KeyError):
        FixedWeights({"ZZZ": 1.0}).generate(data)


def test_specification_round_trip_and_cash_only_portfolio():
    spec = PortfolioSpec({"SPY": 0.6, "TLT": 0.25}, 25_000, 400.0, "Q", "A", "my plan")
    assert spec.cash_weight == pytest.approx(0.15) and spec.tickers == ["SPY", "TLT"]
    again = PortfolioSpec.from_dict({**spec.to_dict(), "unknown_field": 1})
    assert again == spec and replace(spec, name="x") != spec
    data = make_data({"A": [10.0, 11.0, 12.0]})
    cash = simulate_portfolio(PortfolioSpec({"A": 0.0}, 1000), data, FREE)
    assert cash.trades.empty and (cash.equity == 1000).all() and (cash.returns == 0).all()
