"""Suite N (remediation): one portfolio definition across every page (QA-026, QA-024, QA-010).

A fixed-weight risk estimate and an account-level simulation are different models; these
tests check that both are fed the SAME portfolio, that each page names its model, and
that the numbers each page shows are what the shared library computes.
"""

import re

import pandas as pd
import pytest
from fixtures.app import metrics, render, texts, view

from quantlab.data import SyntheticProvider
from quantlab.reporting.format import format_value
from quantlab.risk import estimate_risk, holding_returns

LAB = {"Portfolio A": {"weights": {"SYN1": 0.6, "SYN2": 0.4}, "initial_amount": 10_000.0,
                       "contribution": 500.0, "contribution_frequency": "M", "rebalance": "A",
                       "name": "Portfolio A"},
       "Defensive": {"weights": {"SYN3": 0.3}, "initial_amount": 10_000.0, "contribution": 500.0,
                     "contribution_frequency": "M", "rebalance": None, "name": "Defensive"}}  # fmt: skip


def test_n01_investment_lab_publishes_its_portfolios_for_the_other_pages(monkeypatch):
    at = render(view("invest"), monkeypatch)
    published = at.session_state["lab_portfolios"]
    assert list(published) == ["Portfolio A", "Portfolio B"]
    assert published["Portfolio A"]["weights"] == {"SYN1": 0.6, "SYN2": 0.4}


@pytest.mark.parametrize("page", ["risk", "monte_carlo", "stress"])
def test_n02_every_page_offers_and_defaults_to_the_lab_portfolio(page, monkeypatch):
    at = render(view(page), monkeypatch, lab_portfolios=LAB)
    assert not at.exception and not at.error
    box = next(b for b in at.selectbox if b.key == "p_portfolio")
    assert box.options == ["Custom weights (below)", "Investment Lab: Portfolio A", "Investment Lab: Defensive"]
    assert box.value == "Investment Lab: Portfolio A"
    assert "Target weights from the Investment Lab: SYN1 60.0%, SYN2 40.0%; cash 0.0%" in texts(at)
    assert not [n for n in at.number_input if str(n.key).startswith("p_w_")]  # no second definition


def test_n03_risk_page_numbers_are_the_shared_estimate_for_that_portfolio(monkeypatch):
    at = render(view("risk"), monkeypatch, lab_portfolios=LAB, p_portfolio="Investment Lab: Defensive")
    assert not at.exception and "MODEL: FIXED WEIGHTS" in texts(at)
    caption = next(c.value for c in at.caption if "Historical estimate on" in c.value)
    assert "Defensive" in caption and "cash 70.0%" in texts(at)
    start, end = re.search(r"(\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})", caption).groups()
    # Recompute independently: the app's synthetic data (seed 7, five instruments from 2005),
    # the page's own window, and the weights published by the Investment Lab.
    data = SyntheticProvider(seed=7).fetch(["SYN1", "SYN2", "SYN3", "SYN4", "SYN5"], "2005-01-01")
    weights = pd.Series({"SYN3": 0.3})
    returns = holding_returns(data.close, weights).loc[start:end]
    expected = estimate_risk(returns, weights).summary()
    assert metrics(at)["Volatility (annual)"] == format_value("volatility", expected["volatility_annual"])
    assert metrics(at)["Max drawdown"] == format_value("max_drawdown", expected["max_drawdown"])


def test_n04_lab_risk_insights_can_inspect_any_portfolio_and_compares_all(monkeypatch):
    at = render(view("invest"), monkeypatch)
    pick = next(b for b in at.selectbox if b.key == "il_risk_pick")
    assert pick.options[:2] == ["Portfolio A", "Portfolio B"] and len(pick.options) >= 3
    side = next(d.value for d in at.dataframe if "Estimated volatility (fixed weights)" in d.value.index)
    assert list(side.columns) == pick.options  # every compared portfolio, same order
    pick.set_value("Portfolio B").run()
    assert not at.exception
    assert any("Portfolio B's estimated volatility" in m.value for m in at.markdown)


def test_n05_lab_estimate_and_risk_page_agree_on_the_same_window():
    """Same weights + same window => identical estimate, because it is one implementation."""
    data = SyntheticProvider(7).fetch(["AAA", "BBB", "CCC"], "2015-01-01", "2020-12-31")
    w = pd.Series({"AAA": 0.5, "BBB": 0.3})
    lab = estimate_risk(holding_returns(data.close, w), w).summary()
    risk_page = estimate_risk(holding_returns(data.close, w.reindex(data.tickers).fillna(0.0)), w)
    assert lab["volatility_annual"] == risk_page.summary()["volatility_annual"]
    assert format_value("volatility", lab["volatility_annual"]).endswith("%")
    assert list(risk_page.weights.index) == ["AAA", "BBB"]  # CCC unheld, never in the model


def test_n06_custom_weights_remain_available_and_are_labelled(monkeypatch):
    at = render(view("risk"), monkeypatch, lab_portfolios=LAB, p_portfolio="Custom weights (below)",
                p_w_SYN1=50.0, p_w_SYN2=0.0, p_w_SYN3=0.0, p_w_SYN4=0.0, p_w_SYN5=0.0)  # fmt: skip
    assert not at.exception
    assert "Custom weights" in next(c.value for c in at.caption if "Historical estimate on" in c.value)
    assert "Cash 50.0%" in texts(at)


def test_n07_a_lab_portfolio_holding_an_unloaded_instrument_is_refused_clearly(monkeypatch):
    lab = {"Elsewhere": {**LAB["Portfolio A"], "weights": {"XYZ": 1.0}, "name": "Elsewhere"}}
    at = render(view("risk"), monkeypatch, lab_portfolios=lab)
    assert any("XYZ, which is not in the loaded dataset" in e.value for e in at.error)
    assert not at.exception
