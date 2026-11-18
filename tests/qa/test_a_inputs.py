"""Suite A: input validation and adversarial behaviour, in the library and in the UI.

Issue IDs refer to docs/qa/MASTER_BACKLOG.md. A strict xfail documents a
confirmed defect: it fails today and will start failing the suite, loudly, the
day the defect is fixed, so the marker gets removed.
"""

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest
from fixtures.app import LIVE_STATE, metrics, render, scripted_live, texts, view
from fixtures.synthetic import make_data

from quantlab.backtesting import run_backtest
from quantlab.data import DataError, InsufficientHistoryError, SyntheticProvider
from quantlab.execution import ExecutionConfig
from quantlab.portfolio.compare import compare_portfolios
from quantlab.portfolio.spec import PortfolioSpec, simulate_portfolio
from quantlab.risk import (
    apply_scenario,
    covariance_matrix,
    diversification_ratio,
    portfolio_volatility,
    risk_contributions,
    validate_weights,
)
from quantlab.simulations import simulate
from quantlab.strategies import CrossSectionalMomentum, MeanReversion, TrendFollowing

ALLOCATION_PAGES = ["risk", "monte_carlo", "stress"]

# ----------------------------------------------------------------- the eight manual cases


def test_a01_invalid_ticker_among_valid_ones_is_named_and_nothing_is_shown(tmp_path, monkeypatch):
    from fixtures.live import sessions

    monkeypatch.syspath_prepend(str(view("overview").parents[1]))
    scripted_live(tmp_path, monkeypatch, {"SPY": sessions("2023-01-03", "2026-11-12")})
    at = render(view("overview"), monkeypatch, **{**LIVE_STATE, "p_tick": "SPY, INVALIDXYZ"})
    assert not at.exception
    error = next(e.value for e in at.error)
    assert "No usable data" in error and "INVALIDXYZ" in error
    assert not at.metric and 'class="ql-badge' not in texts(at)  # nothing is presented as data
    assert any(b.label == "Switch to synthetic demo data" for b in at.button)  # offered, not silent


@pytest.mark.parametrize("name, needle", [
    ("risk", "At least 60 are needed"), ("monte_carlo", "at least 60 are needed"),
    ("invest", "cannot be compared on this dataset"), ("research", "at least three years"),
])  # fmt: skip
def test_a02_insufficient_history_is_explained(name, needle, monkeypatch):
    at = render(view(name), monkeypatch, p_start=date(2024, 11, 20))
    assert not at.exception and any(needle in e.value for e in at.error)
    assert not at.metric  # no statistic is computed from too little data


@pytest.mark.parametrize("name", ALLOCATION_PAGES)
def test_a03_allocation_above_100_percent_is_refused(name, monkeypatch):
    at = render(view(name), monkeypatch, p_w_SYN1=70.0, p_w_SYN2=45.0)
    assert not at.exception
    # 70 + 45 plus the three untouched defaults of 20 each
    assert any("Leverage is not supported" in e.value and "175.0%" in e.value for e in at.error)
    assert not at.metric and not at.dataframe


@pytest.mark.parametrize("name, needle", [("risk", "no market risk to measure"),
                                          ("monte_carlo", "every simulated path is flat")])  # fmt: skip
def test_a04_a05_all_cash_risk_and_monte_carlo(name, needle, monkeypatch):
    cash = {f"p_w_SYN{i}": 0.0 for i in range(1, 6)}
    at = render(view(name), monkeypatch, **cash)
    assert not at.exception and not at.error
    assert any(needle in i.value for i in at.info) and not at.metric


def test_a06_all_cash_stress_test_loses_nothing(monkeypatch):
    cash = {f"p_w_SYN{i}": 0.0 for i in range(1, 6)}
    at = render(view("stress"), monkeypatch, **cash)
    assert not at.exception and not at.error
    summary = next(d.value for d in at.dataframe if "Gain / loss" in d.value.columns
                   and "Value after" in d.value.columns and "Shock" not in d.value.columns)  # fmt: skip
    assert (summary["Gain / loss"] == 0).all() and (summary["Value after"] == 100_000).all()


def test_a07_total_loss_is_valid_and_a08_more_than_total_loss_is_not():
    holdings = pd.Series({"SPY": 60_000.0, "CASH": 40_000.0})
    wiped = apply_scenario(holdings, {"SPY": -1.0})
    assert wiped.loc["SPY", "value_after"] == 0.0 and wiped["pnl"].sum() == -60_000.0
    assert wiped.loc["CASH", "pnl"] == 0.0
    for shock in (-1.0000001, -1.5, -100.0):
        with pytest.raises(ValueError, match="cannot lose more than 100%"):
            apply_scenario(holdings, {"SPY": shock})


# ----------------------------------------------------------------- weights, amounts, numbers


@pytest.mark.parametrize("weights", [{"A": -0.1}, {"A": 0.6, "B": -0.2}, {"A": 1.01},
                                     {"A": 0.7, "B": 0.4}, {"A": float("nan")}, {}])  # fmt: skip
def test_a09_invalid_weights_are_rejected_everywhere(weights):
    data = make_data({"A": [10.0] * 80, "B": [10.0] * 80})
    with pytest.raises(ValueError):
        PortfolioSpec(weights)
    if weights:
        with pytest.raises(ValueError):
            validate_weights(pd.Series(weights))
        frame = pd.DataFrame([weights], index=[data.dates[0]])
        with pytest.raises(ValueError):  # the engine refuses, independently of the spec
            run_backtest(data, frame)


@pytest.mark.parametrize("kwargs", [{"contribution": -1.0}, {"initial_amount": 0.0},
                                    {"initial_amount": -100.0}, {"contribution_frequency": "Y"}])  # fmt: skip
def test_a10_invalid_funding_is_rejected(kwargs):
    with pytest.raises(ValueError):
        PortfolioSpec({"A": 1.0}, **kwargs)


@pytest.mark.parametrize("kwargs", [{"initial_capital": 0}, {"initial_capital": -5},
                                    {"slippage_bps": -1}, {"fee_bps": -0.5}, {"fixed_fee": -1}])  # fmt: skip
def test_a11_invalid_execution_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        ExecutionConfig(**kwargs)


@pytest.mark.parametrize("kwargs", [{"initial_capital": float("inf")}, {"initial_capital": float("nan")},
                                    {"slippage_bps": float("nan")}, {"fee_bps": float("inf")},
                                    {"fixed_fee": float("nan")}, {"min_trade_notional": float("inf")}])  # fmt: skip
def test_a11b_nonfinite_execution_settings_are_rejected(kwargs):  # QA-018
    with pytest.raises(ValueError):
        ExecutionConfig(**kwargs)


def test_a09b_nonfinite_weight_is_reported_as_nonfinite():  # QA-018
    for bad in (float("inf"), float("-inf"), float("nan")):
        with pytest.raises(ValueError, match="finite"):
            validate_weights(pd.Series({"A": bad}))
        with pytest.raises(ValueError, match="finite"):
            PortfolioSpec({"A": 0.5}, initial_amount=bad if bad == bad else float("nan"))


def test_a12_ui_weight_and_amount_inputs_cannot_go_below_zero(monkeypatch):
    at = render(view("invest"), monkeypatch)
    bounded = [n for n in at.number_input if str(n.key).startswith(("p_il_w_", "p_il_contrib"))]
    assert len(bounded) == 16 and all(n.min == 0 for n in bounded)
    assert next(n for n in at.number_input if n.key == "p_il_initial").min > 0
    risk = render(view("risk"), monkeypatch)
    assert all(n.min == 0 and n.max == 100 for n in risk.number_input if str(n.key).startswith("p_w_"))


# ----------------------------------------------------------------- tickers


@pytest.mark.parametrize("raw, message", [
    ("", "at least one ticker"), (" , ,", "at least one ticker"),
    ("SPY; DROP TABLE", "Not valid ticker symbols"), ("SPY, <b>x</b>", "Not valid ticker symbols"),
    ("SPY, ../etc", "Not valid ticker symbols"), ("SPY, A B", "Not valid ticker symbols"),
    ("SPY, 😀", "Not valid ticker symbols"), ("TOOLONGTICKERSYMBOL", "Not valid ticker symbols"),
    (",".join(f"T{i}" for i in range(11)), "at most 10"),
])  # fmt: skip
def test_a13_malformed_ticker_input_is_rejected_with_a_reason(raw, message, monkeypatch):
    at = render(view("overview"), monkeypatch, p_syn_tick=raw)
    assert not at.exception and any(message in e.value for e in at.error)
    assert not at.metric


def test_a14_duplicate_and_mixed_case_tickers_are_normalised_visibly(monkeypatch):
    at = render(view("overview"), monkeypatch, p_syn_tick="syn1, SYN2 ,Syn1,syn2")
    assert not at.exception and not at.error
    badge = next(m.value for m in at.markdown if 'class="ql-badge' in m.value)
    assert "SYN1, SYN2 " in badge and badge.count("SYN1") == 1  # upper-cased, de-duplicated, shown
    assert metrics(at)["Instruments"] == "2"


# ----------------------------------------------------------------- strategies and dates


@pytest.mark.parametrize("build", [
    lambda: TrendFollowing(200, 50), lambda: TrendFollowing(50, 50), lambda: TrendFollowing(0, 10),
    lambda: MeanReversion(1), lambda: MeanReversion(20, 1.0, 1.0), lambda: MeanReversion(20, 0.5, 2.0),
    lambda: CrossSectionalMomentum(0), lambda: CrossSectionalMomentum(20, top_n=0),
    lambda: CrossSectionalMomentum(20, rebalance="D"), lambda: CrossSectionalMomentum(20, weighting="x"),
])  # fmt: skip
def test_a15_impossible_strategy_parameters_are_rejected(build):
    with pytest.raises(ValueError):
        build()


def test_a16_reversed_or_empty_evaluation_window_is_refused(monkeypatch):
    at = render(view("backtest"), monkeypatch)
    start = next(d for d in at.date_input if d.label == "Evaluate from")
    start.set_value(date(2024, 12, 31)).run()  # same day as the end: nothing to evaluate
    assert not at.exception
    assert any("must start before it ends" in e.value for e in at.error) and not at.metric


def test_a17_single_asset_portfolio_is_handled_end_to_end(monkeypatch):
    at = render(view("invest"), monkeypatch, p_syn_tick="SYN1")
    assert not at.exception and not at.error and "Final value" in metrics(at)
    assert metrics(at)["Effective holdings"] == "1.0 of 1"
    assert metrics(at)["Average correlation"] == "n/a"  # QA-011 (fixed)
    for name in ("risk", "monte_carlo", "stress", "backtest", "strategy", "market"):
        page = render(view(name), monkeypatch, p_syn_tick="SYN1")
        assert not page.exception, name


def test_a17b_undefined_correlation_reads_not_available(monkeypatch):
    """QA-011 (fixed): single holding, or a zero-variance holding, never shows 'nan'."""
    at = render(view("invest"), monkeypatch, p_syn_tick="SYN1")
    assert metrics(at)["Average correlation"] == "n/a"
    assert "nan" not in " ".join(metrics(at).values()).lower()
    from quantlab.reporting.format import format_value
    from quantlab.risk import estimate_risk

    flat = make_data({"A": [10.0] * 80, "B": np.linspace(10, 20, 80).tolist()})
    returns = (flat.close / flat.close.shift(1) - 1).dropna()
    est = estimate_risk(returns, pd.Series({"A": 0.5, "B": 0.5}))
    assert format_value("average_correlation", est.average_correlation()) == "n/a"  # 0/0 is undefined


# ----------------------------------------------------------------- degenerate data


def test_a18_zero_volatility_and_singular_covariance_do_not_produce_fake_numbers():
    flat = make_data({"A": [10.0] * 80, "B": np.linspace(10, 20, 80).tolist()})
    returns = (flat.close / flat.close.shift(1) - 1).dropna()
    cov = covariance_matrix(returns)
    w = pd.Series({"A": 0.5, "B": 0.5})
    assert cov.loc["A", "A"] == 0.0 and portfolio_volatility(w, cov) > 0
    shares = risk_contributions(w, cov)["pct_of_risk"]
    assert shares["A"] == 0.0 and shares["B"] == pytest.approx(1.0)
    dead = pd.Series({"A": 1.0, "B": 0.0})  # all weight on the zero-variance asset
    assert portfolio_volatility(dead, cov) == 0.0
    assert risk_contributions(dead, cov)["pct_of_risk"].isna().all()  # undefined, not 0 or 100%
    assert math.isnan(diversification_ratio(dead, cov))
    twin = make_data({"A": np.linspace(10, 20, 80).tolist(), "B": np.linspace(20, 40, 80).tolist()})
    twin_cov = covariance_matrix((twin.close / twin.close.shift(1) - 1).dropna())
    assert abs(np.linalg.det(twin_cov.to_numpy())) < 1e-12  # singular: perfectly correlated
    assert diversification_ratio(w, twin_cov) == pytest.approx(1.0)


def test_a19_newly_listed_instrument_limits_the_window_and_too_new_is_refused():
    nan = np.nan
    rng = np.random.default_rng(0)
    old = (100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))).tolist()
    data = make_data({"OLD": old, "NEW": [nan] * 250 + old[:50]})
    spec = PortfolioSpec({"OLD": 0.5, "NEW": 0.5}, 1000)
    with pytest.raises(InsufficientHistoryError, match="at least 60"):
        compare_portfolios(data, {"mix": spec})
    result = simulate_portfolio(spec, data)  # a lone simulation waits for the listing
    assert result.holdings.loc[: data.dates[250]].to_numpy().sum() == 0
    assert result.trades["date"].min() == data.dates[251]


def test_a20_empty_dataset_is_refused_by_comparison(monkeypatch):
    data = SyntheticProvider(1).fetch(["A"], "2020-01-01", "2020-12-31").window("2099-01-01", None)
    assert len(data.dates) == 0
    with pytest.raises(DataError):
        compare_portfolios(data, {"x": PortfolioSpec({"A": 1.0})})


def test_a20b_empty_dataset_is_refused_by_the_simulator():  # QA-016
    data = SyntheticProvider(1).fetch(["A"], "2020-01-01", "2020-12-31").window("2099-01-01", None)
    with pytest.raises((DataError, ValueError)):
        simulate_portfolio(PortfolioSpec({"A": 1.0}), data)


def test_a21_oversized_simulation_is_refused_in_the_ui_and_bounded_inputs_in_the_library(monkeypatch):
    at = render(view("monte_carlo"), monkeypatch)
    next(n for n in at.number_input if n.label == "Simulated paths").set_value(20_000)
    next(n for n in at.number_input if n.label == "Horizon (sessions)").set_value(2520)
    at.run()
    assert not at.exception and any("above this app's limit" in e.value for e in at.error)
    assert not at.metric
    for horizon, paths in ((0, 10), (10, 0), (-5, 10)):
        with pytest.raises(ValueError):
            simulate(pd.Series([0.01, -0.01, 0.02]), horizon=horizon, n_paths=paths)
