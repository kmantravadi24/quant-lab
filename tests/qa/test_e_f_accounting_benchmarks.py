"""Suites E and F: Investment Lab accounting, benchmarks and comparisons.

The ledger is re-audited from first principles: every fill's cash effect is
recomputed from its own recorded shares, price and fee, and deposits are
replayed independently (tests/qa/reference.py).
"""

import io
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from fixtures.app import metrics, render, view
from fixtures.synthetic import make_data

from qa import reference as ref
from quantlab.analytics.flows import investor_cash_flows, money_weighted_return
from quantlab.data import SyntheticProvider
from quantlab.execution import ExecutionConfig
from quantlab.portfolio.compare import (
    allocation_drift,
    analysis_record,
    benchmark_specs,
    compare_portfolios,
)
from quantlab.portfolio.spec import PortfolioSpec, contribution_schedule, simulate_portfolio
from quantlab.reporting import csv_bytes

COSTS = ExecutionConfig(slippage_bps=7, fee_bps=3, fixed_fee=0.25)


@pytest.fixture(scope="module")
def market():
    return SyntheticProvider(21).fetch(["AAA", "BBB", "CCC"], "2016-01-01", "2021-12-31")


@pytest.fixture(scope="module")
def long_market():
    return SyntheticProvider(8).fetch(["AAA", "BBB"], "1985-01-01", "2024-12-31")  # 40 years


CASES = [
    PortfolioSpec({"AAA": 1.0}, 10_000, 0.0, "M", None, "lump sum"),
    PortfolioSpec({"AAA": 0.6, "BBB": 0.4}, 10_000, 200.0, "W", None, "weekly"),
    PortfolioSpec({"AAA": 0.6, "BBB": 0.4}, 10_000, 500.0, "M", "A", "monthly annual"),
    PortfolioSpec({"AAA": 0.4, "BBB": 0.3, "CCC": 0.2}, 5_000, 1_500.0, "Q", "Q", "quarterly reserve"),
    PortfolioSpec({"AAA": 0.34, "BBB": 0.33, "CCC": 0.33}, 2_000, 300.0, "M", "M", "monthly monthly"),
]
IDS = [c.name for c in CASES]


# ================================================================= Suite E: accounting


@pytest.mark.parametrize("spec", CASES, ids=IDS)
@pytest.mark.parametrize("fractional", [True, False], ids=["fractional", "whole-shares"])
def test_e01_every_fill_reconciles_cash_from_first_principles(spec, fractional, market):
    cfg = ExecutionConfig(slippage_bps=7, fee_bps=3, fixed_fee=0.25, fractional_shares=fractional)
    result = simulate_portfolio(spec, market, cfg)
    deposits = {d: v for d, v in result.cash_flows.items() if v}
    replay = ref.replay_cash(spec.initial_amount, deposits, result.trades.to_dict("records"))
    assert len(replay) == len(result.trades) > 0
    for expected, recorded in replay:  # cash before + deposits + sales - purchases - fees = cash after
        assert recorded == pytest.approx(expected, abs=1e-6)
        assert recorded >= -1e-9  # the account is never overdrawn
    # Each fill obeys the engine's stated price and fee conventions.
    t = result.trades
    sign = np.where(t["side"] == "BUY", 1.0, -1.0)
    np.testing.assert_allclose(t["fill_price"], t["reference_price"] * (1 + sign * 7e-4), rtol=1e-12)
    np.testing.assert_allclose(t["notional"], t["shares"] * t["fill_price"], rtol=1e-12)
    np.testing.assert_allclose(t["fee"], t["notional"] * 3e-4 + 0.25, rtol=1e-12)
    np.testing.assert_allclose(t["reference_price"],
                               [market.open.loc[d, k] for d, k in zip(t["date"], t["ticker"], strict=True)])  # fmt: skip
    if not fractional:
        assert (t["shares"] == t["shares"].round()).all()
    # Value is conserved around every deposit: equity moves only through prices, costs and deposits.
    closes = market.close[result.holdings.columns]
    np.testing.assert_allclose(result.equity, result.cash + (result.holdings * closes).sum(axis=1), rtol=1e-12)
    costs = (t["fee"] + t["slippage_cost"]).sum()
    marked_gain = result.equity.iloc[-1] - spec.initial_amount - result.cash_flows.sum()
    price_pnl = sum(
        (result.holdings[k].shift(1).fillna(0) * (market.close[k] - market.close[k].shift(1)).fillna(0)).sum()
        + sum(row["shares"] * (1 if row["side"] == "BUY" else -1)
              * (market.close.loc[row["date"], k] - row["reference_price"])
              for _, row in t[t["ticker"] == k].iterrows())
        for k in result.holdings.columns
    )  # fmt: skip
    assert marked_gain == pytest.approx(price_pnl - costs, rel=1e-8, abs=1e-5)


@pytest.mark.parametrize("spec", CASES, ids=IDS)
def test_e02_time_weighted_return_is_flow_neutral_and_money_weighted_uses_dated_flows(spec, market):
    result = simulate_portfolio(spec, market, COSTS)
    twr = ref.unitised_returns(result.equity.tolist(), result.equity_before_flow.tolist(),
                               result.cash_flows.tolist(), spec.initial_amount)  # fmt: skip
    np.testing.assert_allclose(result.returns, twr, atol=1e-12)
    flows = investor_cash_flows(result)
    start = flows.index[0]
    assert flows.iloc[0] == -spec.initial_amount and flows.iloc[-1] == pytest.approx(result.equity.iloc[-1])
    expected_days = contribution_schedule(result.equity.index, spec.contribution, spec.contribution_frequency)
    assert list(flows.index[1:-1]) == list(expected_days.index)
    assert (flows.iloc[1:-1] == -spec.contribution).all()
    reference = ref.xirr([((d - start).days, float(v)) for d, v in flows.items()])
    assert money_weighted_return(flows).rate == pytest.approx(reference, rel=1e-7, abs=1e-9)


def test_e03_doubling_every_amount_doubles_values_and_leaves_returns_unchanged(market):
    """Deposits must not look like performance: scale the money, the returns do not move."""
    base = PortfolioSpec({"AAA": 0.6, "BBB": 0.4}, 10_000, 500.0, "M", "A")
    double = PortfolioSpec({"AAA": 0.6, "BBB": 0.4}, 20_000, 1_000.0, "M", "A")
    free = ExecutionConfig(slippage_bps=5, fee_bps=2)  # proportional costs only
    one, two = simulate_portfolio(base, market, free), simulate_portfolio(double, market, free)
    np.testing.assert_allclose(two.equity, 2 * one.equity, rtol=1e-10)
    np.testing.assert_allclose(two.returns, one.returns, atol=1e-12)
    # A bigger contribution into the same holdings changes the money, not the daily returns
    # on fully invested days (it does add cash drag on the days the deposit waits).
    bigger = simulate_portfolio(PortfolioSpec({"AAA": 0.6, "BBB": 0.4}, 10_000, 5_000.0, "M", "A"), market, free)
    quiet = bigger.cash_flows.eq(0) & bigger.cash_flows.shift(1).fillna(0).eq(0)
    assert bigger.equity.iloc[-1] > 3 * one.equity.iloc[-1]
    assert (bigger.returns[quiet] - one.returns[quiet]).abs().max() < 0.02


@pytest.mark.parametrize("frequency, per_year", [("W", 52), ("M", 12), ("Q", 4)])
def test_e04_contribution_calendar_and_next_session_investment(frequency, per_year, market):
    spec = PortfolioSpec({"AAA": 1.0}, 10_000, 100.0, frequency)
    result = simulate_portfolio(spec, market, ExecutionConfig(slippage_bps=0, fee_bps=0))
    days = result.cash_flows[result.cash_flows > 0].index
    years = (market.dates[-1] - market.dates[0]).days / 365.25
    assert abs(len(days) / years - per_year) < 1.5
    key = {"W": lambda d: d.isocalendar()[:2], "M": lambda d: (d.year, d.month),
           "Q": lambda d: (d.year, d.quarter)}[frequency]  # fmt: skip
    sessions = list(market.dates)
    for day in days:
        i = sessions.index(day)
        assert key(sessions[i]) != key(sessions[i - 1])  # first session of its period
        earlier_order = result.trades[(result.trades["date"] == day)
                                      & (result.trades["decision_date"] < day)]  # fmt: skip
        if len(earlier_order):
            # QA-021: an order decided earlier fills this very open and is sized on equity that
            # already includes the deposit, so the money is invested the same day. No information
            # from the day is used. QA-021 (fixed): the documentation now states this exception.
            assert result.cash.loc[day] == pytest.approx(0.0, abs=1e-6)
            continue
        assert result.cash.loc[day] == pytest.approx(100.0)  # arrived, not yet invested
        fill = result.trades[result.trades["decision_date"] == day]
        if i + 1 < len(sessions):
            assert list(fill["date"]) == [sessions[i + 1]]  # bought at the next session's open
            assert fill["reference_price"].iloc[0] == market.open.loc[sessions[i + 1], "AAA"]
            assert result.cash.loc[sessions[i + 1]] == pytest.approx(0.0, abs=1e-6)


def test_e05_missing_price_on_deployment_day_keeps_the_money_in_cash():
    nan = np.nan
    dates = pd.bdate_range("2024-01-29", "2024-03-08")
    prices = [100.0] * len(dates)
    opens = list(prices)
    first_feb = list(dates).index(pd.Timestamp("2024-02-01"))
    opens[first_feb + 1] = nan  # no opening price on the session after the contribution
    data = make_data({"A": prices}, {"A": opens}, dates=dates)
    result = simulate_portfolio(PortfolioSpec({"A": 1.0}, 1000, 100.0, "M"), data,
                                ExecutionConfig(slippage_bps=0, fee_bps=0))  # fmt: skip
    assert result.cash.loc[dates[first_feb + 1]] == pytest.approx(100.0)
    assert not (result.trades["date"] == dates[first_feb + 1]).any()  # no fill was invented
    assert (result.unfilled["date"] == dates[first_feb + 1]).any()  # and the miss is logged
    march = result.trades[result.trades["decision_date"] == pd.Timestamp("2024-03-01")]
    assert march["notional"].sum() == pytest.approx(200.0)  # invested with the next deposit


def test_e06_annual_versus_no_rebalancing_dates_drift_and_cost(market):
    weights = {"AAA": 0.5, "BBB": 0.5}
    never = simulate_portfolio(PortfolioSpec(weights, 10_000), market, COSTS)
    annual = simulate_portfolio(PortfolioSpec(weights, 10_000, rebalance="A"), market, COSTS)
    assert len(never.trades) == 2
    rebalance_days = sorted(set(annual.trades["decision_date"]))[1:]
    assert [d.year for d in rebalance_days] == [2017, 2018, 2019, 2020, 2021]
    assert all(d == market.dates[market.dates.year == d.year][0] for d in rebalance_days)
    assert annual.trades["fee"].sum() > never.trades["fee"].sum()
    spec = PortfolioSpec(weights, 10_000, rebalance="A")
    assert allocation_drift(annual, spec).mean() < allocation_drift(never, PortfolioSpec(weights, 10_000)).mean()


def test_e07_forty_year_horizon_stays_consistent(long_market):
    spec = PortfolioSpec({"AAA": 0.7, "BBB": 0.3}, 10_000, 250.0, "M", "A")
    result = simulate_portfolio(spec, long_market, COSTS)
    assert len(result.equity) > 10_000 and result.cash_flows.gt(0).sum() == 479
    closes = long_market.close[result.holdings.columns]
    np.testing.assert_allclose(result.equity, result.cash + (result.holdings * closes).sum(axis=1), rtol=1e-11)
    assert result.cash.min() >= -1e-6 and np.isfinite(result.returns).all()
    replay = ref.replay_cash(10_000, {d: v for d, v in result.cash_flows.items() if v},
                             result.trades.to_dict("records"))  # fmt: skip
    assert max(abs(a - b) for a, b in replay) < 1e-5
    assert money_weighted_return(investor_cash_flows(result)).ok


def test_e08_displayed_values_equal_engine_values_and_exports(monkeypatch):
    at = render(view("invest"), monkeypatch)
    names = ["SYN1", "SYN2", "SYN3", "SYN4", "SYN5"]
    data = SyntheticProvider(7).fetch(names, "2005-01-01")
    a = PortfolioSpec({"SYN1": 0.6, "SYN2": 0.4}, 10_000.0, 500.0, "M", "A", "Portfolio A")
    b = PortfolioSpec({n: 0.2 for n in names}, 10_000.0, 500.0, "M", None, "Portfolio B")
    cfg = ExecutionConfig(initial_capital=10_000.0, slippage_bps=2.0, fee_bps=1.0)
    comparison = compare_portfolios(data, {"Portfolio A": a, "Portfolio B": b, **benchmark_specs(a)}, cfg)
    stats = comparison.stats["Portfolio A"]
    shown = metrics(at)
    assert shown["Final value"] == f"{stats['final_value']:,.0f}"
    assert shown["Gain"] == f"{stats['final_value'] - stats['total_invested']:,.0f}"
    record = analysis_record(comparison)
    assert record["results"]["Portfolio A"]["final_value"] == comparison.results["Portfolio A"].equity.iloc[-1]
    exported = pd.read_csv(io.BytesIO(csv_bytes(comparison.values(), "date")), index_col="date")
    np.testing.assert_allclose(exported["Portfolio A"], comparison.results["Portfolio A"].equity, rtol=1e-12)
    assert record["portfolios"]["Portfolio A"]["weights"] == {"SYN1": 0.6, "SYN2": 0.4}


def test_e09_adjusted_price_model_is_a_stated_limitation_not_an_accounting_error(market):
    """Whole shares vs fractional: both reconcile; they differ only by idle cash."""
    spec = PortfolioSpec({"AAA": 0.6, "BBB": 0.4}, 10_000, 500.0, "M", "A")
    frac = simulate_portfolio(spec, market, ExecutionConfig(slippage_bps=0, fee_bps=0))
    whole = simulate_portfolio(spec, market, ExecutionConfig(slippage_bps=0, fee_bps=0, fractional_shares=False))
    assert whole.cash.iloc[-1] >= frac.cash.iloc[-1] and whole.cash.iloc[5:].max() < 2_000
    assert abs(whole.equity.iloc[-1] / frac.equity.iloc[-1] - 1) < 0.01
    assert "total-return-oriented" not in market.metadata.adjustment  # synthetic data says so itself
    from quantlab.data import ADJUSTED_OHLC

    assert "not executable historical quotes" in ADJUSTED_OHLC


# ================================================================= Suite F: benchmarks


def test_f01_benchmarks_are_built_independently_and_labelled_accurately(market):
    spec = PortfolioSpec({"AAA": 0.6, "BBB": 0.4}, 10_000, 500.0, "M", "A", "mine")
    bench = benchmark_specs(spec)
    comparison = compare_portfolios(market, {"mine": spec, **bench}, COSTS)
    assert list(comparison.stats) == ["mine", "100% AAA", "Equal weight", "Same weights, never rebalanced"]
    solo = simulate_portfolio(PortfolioSpec({"AAA": 1.0}, 10_000, 500.0, "M"), market.select(["AAA", "BBB"]),
                              COSTS, own_calendar=False)  # fmt: skip
    pd.testing.assert_series_equal(comparison.results["100% AAA"].equity, solo.equity)
    held = comparison.results["100% AAA"].holdings
    assert held["BBB"].eq(0).all() and held["AAA"].iloc[-1] > 0  # the label is literally true
    equal = comparison.results["Equal weight"].target_weights.iloc[0]
    assert equal["AAA"] == equal["BBB"] == 0.5
    never = comparison.results["Same weights, never rebalanced"]
    assert set(never.trades["side"]) == {"BUY"}  # buys contributions, never sells to rebalance
    assert len({s["total_invested"] for s in comparison.stats.values()}) == 1  # identical funding
    assert len({r.equity.index[0] for r in comparison.results.values()}) == 1  # one window
    assert len({r.config for r in comparison.results.values()}) == 1  # one cost model
    finals = [s["final_value"] for s in comparison.stats.values()]
    assert len(set(np.round(finals, 6))) == 4  # four genuinely different outcomes


def test_f02_single_asset_portfolio_gets_no_duplicate_of_itself():
    """QA-001 (fixed): with one holding and no cash, every former benchmark was the portfolio
    itself. Without other instruments to compare against, none is offered."""
    spec = PortfolioSpec({"AAA": 1.0}, 10_000, 500.0, "M", None, "solo")
    assert benchmark_specs(spec) == {}
    assert benchmark_specs(replace(spec, rebalance="A")) == {}  # rebalancing one asset is a no-op


def test_f02b_benchmarks_are_distinct_from_the_portfolio_and_each_other(market):
    spec = PortfolioSpec({"AAA": 1.0}, 10_000, 500.0, "M", None, "solo")
    bench = benchmark_specs(spec, universe=["AAA", "BBB"])
    assert list(bench) == ["Equal weight, all loaded instruments", "100% BBB"]
    comparison = compare_portfolios(market, {"solo": spec, **bench}, COSTS)
    finals = [round(s["final_value"], 6) for s in comparison.stats.values()]
    assert len(finals) == 3 and len(set(finals)) == len(finals)
    # With cash, rebalancing matters, so the maintenance alternative is genuinely different.
    with_cash = PortfolioSpec({"AAA": 0.8}, 10_000, 500.0, "M", "A", "cash")
    assert "Same weights, never rebalanced" in benchmark_specs(with_cash)
    # A two-asset portfolio keeps the familiar three, all different (see f01).
    mixed = PortfolioSpec({"AAA": 0.5, "BBB": 0.5}, 10_000, 0.0, "M", None, "half")
    assert "Equal weight" not in benchmark_specs(mixed)  # it IS equal weight already
    many = benchmark_specs(spec, universe=["AAA", "BBB", "CCC", "DDD", "EEE"])
    assert len(many) == 3  # capped, so the comparison stays readable


def test_f03_chart_series_reconcile_with_the_statistics_table(market):
    spec = PortfolioSpec({"AAA": 0.5, "BBB": 0.5}, 10_000, 250.0, "M", "Q", "p")
    comparison = compare_portfolios(market, {"p": spec, **benchmark_specs(spec)}, COSTS)
    values, growth = comparison.values(), comparison.growth_of_one()
    for name, stats in comparison.stats.items():
        assert values[name].iloc[-1] == pytest.approx(stats["final_value"])
        assert growth[name].iloc[-1] - 1 == pytest.approx(stats["time_weighted_total"])
        drawdown = (growth[name] / growth[name].cummax().clip(lower=1.0) - 1).min()
        assert drawdown == pytest.approx(stats["max_drawdown"])
    assert comparison.contributed().iloc[-1] == pytest.approx(comparison.stats["p"]["total_invested"])
    assert list(values.columns) == list(comparison.stats)  # user's portfolio first, in order


def test_f04_ui_orders_user_portfolios_first_and_hides_duplicate_names(monkeypatch):
    at = render(view("invest"), monkeypatch, p_il_on_C=True)
    table = next(d.value for d in at.dataframe if "Final value" in d.value.index)
    assert list(table.columns[:3]) == ["Portfolio A", "Portfolio B", "Portfolio C"]
    assert len(set(table.columns)) == len(table.columns)
    clash = render(view("invest"), monkeypatch, p_il_name_B="100% SYN1")
    options = next(m for m in clash.multiselect).options
    assert "100% SYN1" not in options  # a benchmark with a taken name is not offered twice
