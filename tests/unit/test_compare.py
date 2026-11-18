"""Investment Lab: fair comparison, drift, diversification measures and saved files."""

import math

import numpy as np
import pandas as pd
import pytest
from fixtures.synthetic import make_data

from quantlab.analytics.flows import flow_summary
from quantlab.data import InsufficientHistoryError, SyntheticProvider
from quantlab.execution import ExecutionConfig
from quantlab.portfolio.compare import (
    SCHEMA,
    allocation_drift,
    analysis_record,
    benchmark_specs,
    common_window,
    compare_portfolios,
    data_fingerprint,
    load_portfolio_file,
    portfolio_file,
    reproduction_status,
)
from quantlab.portfolio.spec import PortfolioSpec, simulate_portfolio
from quantlab.risk import diversification_ratio, effective_holdings

FREE = ExecutionConfig(initial_capital=1000.0, slippage_bps=0, fee_bps=0)


@pytest.fixture(scope="module")
def market():
    return SyntheticProvider(5).fetch(["AAA", "BBB", "CCC"], "2019-01-01", "2021-12-31")


def late_start(n=200, missing=50):
    nan = np.nan
    rng = np.random.default_rng(1)
    a = (100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))).tolist()
    b = [nan] * missing + (50 * np.exp(np.cumsum(rng.normal(0, 0.01, n - missing)))).tolist()
    return make_data({"OLD": a, "NEW": b})


def test_common_window_starts_when_every_instrument_has_a_price():
    data = late_start()
    window = common_window(data, ["OLD", "NEW"])
    assert window.dates[0] == data.dates[50] and len(window.dates) == 150
    assert not window.close.iloc[0].isna().any()
    assert common_window(data, ["OLD"]).dates[0] == data.dates[0]  # only what is actually held
    with pytest.raises(InsufficientHistoryError, match="at least 60"):
        common_window(late_start(n=100, missing=60), ["OLD", "NEW"])
    with pytest.raises(ValueError):
        common_window(data, [])
    with pytest.raises(KeyError):
        common_window(data, ["ZZZ"])


def test_every_portfolio_in_a_comparison_shares_one_window_calendar_and_funding():
    data = late_start()
    a = PortfolioSpec({"OLD": 1.0}, 1000, 50, "M", None, "old only")
    b = PortfolioSpec({"OLD": 0.5, "NEW": 0.5}, 1000, 50, "M", "M", "mixed")
    comparison = compare_portfolios(data, {"old only": a, "mixed": b}, FREE)
    # "old only" could have used 50 more sessions; it is held to the common window instead.
    for result in comparison.results.values():
        assert result.equity.index.equals(comparison.data.dates)
        assert result.equity.index[0] == data.dates[50]
    assert comparison.window == (data.dates[50], data.dates[-1])
    paid = [s["total_invested"] for s in comparison.stats.values()]
    assert paid[0] == paid[1] == 1000 + comparison.results["mixed"].cash_flows.sum()
    assert comparison.contributed().iloc[-1] == paid[0]
    assert list(comparison.values().columns) == ["old only", "mixed"]
    np.testing.assert_allclose(comparison.growth_of_one()["mixed"].iloc[-1],
                               1 + comparison.stats["mixed"]["time_weighted_total"])  # fmt: skip
    with pytest.raises(ValueError, match="same funding plan"):
        compare_portfolios(data, {"a": a, "b": PortfolioSpec({"OLD": 1.0}, 2000, 50)}, FREE)
    with pytest.raises(ValueError):
        compare_portfolios(data, {}, FREE)


def test_comparison_statistics_equal_a_direct_simulation(market):
    spec = PortfolioSpec({"AAA": 0.6, "BBB": 0.3}, 10_000, 250, "M", "Q", "p")
    cfg = ExecutionConfig(slippage_bps=4, fee_bps=2)
    comparison = compare_portfolios(market, {"p": spec}, cfg, risk_free=0.02)
    direct = simulate_portfolio(spec, market.select(["AAA", "BBB"]), cfg)
    pd.testing.assert_series_equal(comparison.results["p"].equity, direct.equity)
    stats, flows = comparison.stats["p"], flow_summary(direct)
    for key in ("final_value", "time_weighted_annual", "money_weighted_annual", "total_invested"):
        assert stats[key] == pytest.approx(flows[key])
    fees = direct.trades["fee"].sum() + direct.trades["slippage_cost"].sum()
    assert stats["trading_cost"] == pytest.approx(fees)
    assert stats["trading_cost_pct_of_invested"] == pytest.approx(fees / flows["total_invested"])
    assert stats["worst_day"] == direct.returns.min() and stats["cash_weight_target"] == pytest.approx(0.1)
    assert comparison.fingerprint == data_fingerprint(market.select(["AAA", "BBB"]))


def test_benchmarks_are_simple_and_funded_identically():
    spec = PortfolioSpec({"AAA": 0.5, "BBB": 0.3, "CCC": 0.0}, 5000, 100, "Q", "A", "mine")
    bench = benchmark_specs(spec)
    assert list(bench) == ["100% AAA", "Equal weight", "Same weights, never rebalanced"]
    assert bench["100% AAA"].weights == {"AAA": 1.0} and bench["100% AAA"].rebalance is None
    assert bench["Equal weight"].weights == {"AAA": 0.5, "BBB": 0.5}  # held instruments only
    assert bench["Same weights, never rebalanced"].weights == spec.weights
    for b in bench.values():
        assert (b.initial_amount, b.contribution, b.contribution_frequency) == (5000, 100, "Q")
    never = benchmark_specs(PortfolioSpec({"AAA": 0.6, "BBB": 0.4}, 5000))
    assert "Same weights, rebalanced annually" in never
    assert never["Same weights, rebalanced annually"].rebalance == "A"
    # One instrument, no cash: rebalancing cannot change it, so no duplicate is offered (QA-001).
    assert benchmark_specs(PortfolioSpec({"AAA": 1.0}, 5000)) == {}


def test_allocation_drift_by_hand():
    # 5 A + 5 B bought at 100. B rises to 120: weights 500/1100 and 600/1100, so the largest
    # gap from the 50% targets is 600/1100 - 0.5 = 4.545%.
    dates = pd.DatetimeIndex(["2024-01-30", "2024-01-31", "2024-02-01", "2024-02-02"])
    data = make_data({"A": [100.0] * 4, "B": [100, 120, 120, 120]},
                     {"A": [100.0] * 4, "B": [100, 100, 120, 120]}, dates=dates)  # fmt: skip
    spec = PortfolioSpec({"A": 0.5, "B": 0.5}, 1000)
    drift = allocation_drift(simulate_portfolio(spec, data, FREE), spec)
    assert list(drift.index) == list(dates[1:])  # measured from the first invested session
    np.testing.assert_allclose(drift, [600 / 1100 - 0.5] * 3)
    monthly = PortfolioSpec({"A": 0.5, "B": 0.5}, 1000, rebalance="M")
    rebalanced = allocation_drift(simulate_portfolio(monthly, data, FREE), monthly)
    assert rebalanced.iloc[-1] == pytest.approx(0.0, abs=1e-12)  # traded back on 2 February
    # A cash target counts too: 80% target fully invested shows no gap, an idle deposit does.
    reserve = PortfolioSpec({"A": 0.8}, 1000)
    np.testing.assert_allclose(allocation_drift(simulate_portfolio(reserve, data, FREE), reserve), 0, atol=1e-12)


def test_diversification_measures_by_hand():
    assert effective_holdings(pd.Series([0.25] * 4)) == pytest.approx(4.0)
    assert effective_holdings(pd.Series([0.5, 0.25, 0.25])) == pytest.approx(1 / 0.375)
    assert effective_holdings(pd.Series([0.4, 0.2, 0.2])) == pytest.approx(1 / 0.375)  # cash ignored
    assert effective_holdings(pd.Series([1.0, 0.0])) == pytest.approx(1.0)
    assert math.isnan(effective_holdings(pd.Series([0.0, 0.0])))
    names = ["A", "B"]
    w = pd.Series([0.5, 0.5], index=names)
    independent = pd.DataFrame([[0.04, 0.0], [0.0, 0.04]], index=names, columns=names)
    assert diversification_ratio(w, independent) == pytest.approx(math.sqrt(2))
    identical = pd.DataFrame([[0.04, 0.04], [0.04, 0.04]], index=names, columns=names)
    assert diversification_ratio(w, identical) == pytest.approx(1.0)
    assert diversification_ratio(pd.Series([1.0, 0.0], index=names), independent) == pytest.approx(1.0)
    assert math.isnan(diversification_ratio(pd.Series([0.0, 0.0], index=names), independent))


def test_saved_portfolio_file_round_trip_and_reproduction_status(market):
    specs = {"core": PortfolioSpec({"AAA": 0.6, "BBB": 0.4}, 8000, 200, "M", "A", "core"),
             "alt": PortfolioSpec({"CCC": 0.9}, 8000, 200, "M", None, "alt")}  # fmt: skip
    cfg = ExecutionConfig(initial_capital=8000, slippage_bps=3, fee_bps=1.5)
    first = compare_portfolios(market, specs, cfg, 0.01)
    saved = portfolio_file(specs, cfg, 0.01, first.fingerprint, {"start": "x", "end": "y"})
    assert saved["schema"] == SCHEMA and set(saved) == {"schema", "portfolios", "execution",
                                                        "risk_free", "saved_with"}  # fmt: skip
    import json

    loaded_specs, loaded_cfg, loaded_rf = load_portfolio_file(json.loads(json.dumps(saved)))
    assert loaded_specs == specs and loaded_cfg == cfg and loaded_rf == 0.01
    again = compare_portfolios(market, loaded_specs, loaded_cfg, loaded_rf)
    assert again.stats == first.stats  # identical numbers on the same dataset
    assert reproduction_status(saved, again.fingerprint) == (
        True, "Same dataset as when the file was saved: results reproduce exactly.")  # fmt: skip
    other = SyntheticProvider(6).fetch(["AAA", "BBB", "CCC"], "2019-01-01", "2021-12-31")
    changed = compare_portfolios(other, loaded_specs, loaded_cfg, loaded_rf)
    same, message = reproduction_status(saved, changed.fingerprint)
    assert not same and "Different dataset" in message and first.fingerprint in message
    assert reproduction_status({"schema": SCHEMA}, "abc")[0] is False


@pytest.mark.parametrize(
    "payload, reason",
    [
        ({}, "schema"),
        ({"schema": "something/else", "portfolios": {}}, "schema"),
        ({"schema": SCHEMA, "portfolios": {}}, "no portfolios"),
        ({"schema": SCHEMA, "portfolios": {"a": {"weights": {"A": 1.5}}}}, "leverage"),
        ({"schema": SCHEMA, "portfolios": {"a": {"weights": {"A": -0.2}}}}, "long-only"),
        ({"schema": SCHEMA, "portfolios": {"a": {}}}, "malformed"),
        ({"schema": SCHEMA, "portfolios": {str(i): {"weights": {"A": 1.0}} for i in range(4)}}, "three"),
        ({"schema": SCHEMA, "portfolios": {"a": {"weights": {f"T{i}": 0.05 for i in range(11)}}}}, "10"),
        ([1, 2], "schema"),
    ],
)
def test_bad_portfolio_files_are_rejected_with_a_reason(payload, reason):
    with pytest.raises(ValueError, match=reason):
        load_portfolio_file(payload)


def test_analysis_record_is_complete_and_free_of_personal_fields(market):
    spec = PortfolioSpec({"AAA": 1.0}, 1000, 0.0, "M", None, "solo")
    comparison = compare_portfolios(market, {"solo": spec, **benchmark_specs(spec)}, FREE)
    record = analysis_record(comparison, {"outcome": "cached"})
    assert record["schema"] == SCHEMA and record["data"]["synthetic"] is True
    assert record["data"]["fingerprint"] == comparison.fingerprint
    assert record["window"]["sessions"] == len(market.dates) and "next session's open" in record["timing"]
    assert record["results"]["solo"]["final_value"] == comparison.stats["solo"]["final_value"]
    assert record["data_status"] == {"outcome": "cached"}
    assert any("not executable" in n for n in record["notes"])
    text = str(record).lower()
    for forbidden in ("email", "account", "password", "token"):
        assert forbidden not in text
