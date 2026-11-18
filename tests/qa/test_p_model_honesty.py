"""Suite P (remediation): model honesty (QA-030, QA-021) and explanations."""

import numpy as np
import pandas as pd
import pytest
from fixtures.app import metrics, render, texts, view
from scipy.stats import binomtest

from quantlab.data import SyntheticProvider
from quantlab.simulations import (
    lookback_windows,
    sensitivity,
    simulate,
    standard_error,
    wilson_interval,
)


@pytest.mark.parametrize("k, n", [(0, 1000), (3, 1000), (166, 1000), (3320, 20000), (1000, 1000), (50, 100)])
def test_p01_wilson_interval_matches_scipy(k, n):
    low, high = wilson_interval(k / n, n)
    ref = binomtest(k, n).proportion_ci(method="wilson")
    assert low == pytest.approx(ref.low, abs=1e-12) and high == pytest.approx(ref.high, abs=1e-12)
    assert 0.0 <= low <= k / n <= high <= 1.0


def test_p02_sampling_error_shrinks_with_paths_but_model_error_does_not():
    """QA-030: path-count noise shrinks as 1/sqrt(n); the lookback effect stays."""
    assert standard_error(0.2, 4000) == pytest.approx(standard_error(0.2, 1000) / 2)
    rng = np.random.default_rng(3)
    calm = rng.normal(0.0004, 0.006, 1500)
    stormy = rng.normal(0.0002, 0.02, 1000)  # the older part of the history is volatile
    history = pd.Series(np.concatenate([stormy, calm]), index=pd.bdate_range("2000-01-03", periods=2500))
    table = sensitivity(history, 252, 2000, 100_000.0, 1, -0.20, {"Recent 3y": 756, "All": 2500},
                        (("iid", 1), ("stationary", 21)))  # fmt: skip
    assert list(table["lookback"]) == ["Recent 3y", "Recent 3y", "All", "All"]
    recent = table.loc[table["lookback"] == "Recent 3y", "prob_drawdown"].max()
    full = table.loc[table["lookback"] == "All", "prob_drawdown"].min()
    widest = (table["prob_drawdown_high"] - table["prob_drawdown_low"]).max()
    assert full - recent > 3 * widest  # model choice moves the answer far beyond sampling noise
    assert (table["prob_drawdown_low"] <= table["prob_drawdown"]).all()
    assert (table["prob_drawdown"] <= table["prob_drawdown_high"]).all()


def test_p03_lookback_windows_fit_the_history():
    assert list(lookback_windows(5000)) == ["Last 3 years", "Last 5 years", "Last 10 years", "All 19.8 years"]
    assert list(lookback_windows(800)) == ["Last 3 years", "All 3.2 years"]
    assert list(lookback_windows(300).values()) == [300]


def test_p04_sensitivity_rows_reproduce_a_direct_simulation():
    r = SyntheticProvider(5).fetch(["A"], "2010-01-01", "2020-12-31").close["A"].pct_change().dropna()
    table = sensitivity(r, 126, 500, 50_000.0, 9, -0.2, {"x": 756}, (("block", 21),))
    direct = simulate(r.iloc[-756:], 126, 500, 50_000.0, "block", 21, 9)
    assert table.loc[0, "prob_loss"] == direct.prob_terminal_below(50_000.0)
    assert table.loc[0, "prob_drawdown"] == direct.prob_drawdown_worse_than(-0.2)


def test_p05_monte_carlo_page_shows_ranges_sensitivity_and_limits(monkeypatch):
    at = render(view("monte_carlo"), monkeypatch)
    assert not at.exception and not at.error
    deltas = {m.label: m.delta for m in at.metric}
    for label in ("Paths ending below start", "Paths falling 20% or more"):
        assert deltas[label].endswith(" (95%)") and "–" in deltas[label]
    page = texts(at)
    assert "Not a forecast." in page and "not probabilities about the real future" in page
    assert "MODEL: FIXED WEIGHTS" in page and "a lump sum, no contributions" in page
    table = next(d.value for d in at.dataframe if "History sampled" in d.value.columns)
    assert set(table["Resampling"]) == {"Independent days", "Random-length blocks", "Fixed-length blocks"}
    assert table["History sampled"].nunique() >= 2
    assert "None of these rows is the 'right' one." in page
    assert "Whether that makes simulated drawdowns milder or harsher depends on the history" in page


def test_p06_monte_carlo_headline_range_is_the_wilson_interval(monkeypatch):
    at = render(view("monte_carlo"), monkeypatch)
    value = metrics(at)["Paths falling 20% or more"]
    p = float(value.rstrip("%")) / 100
    low, high = wilson_interval(p, 1000)  # default path count
    delta = next(m.delta for m in at.metric if m.label == "Paths falling 20% or more")
    assert delta == f"{low:.1%}–{high:.1%} (95%)"


def test_p07_contribution_timing_is_described_accurately():
    """QA-021 (fixed): every place that states the rule mentions the same-open exception."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    invest = (root / "app" / "views" / "invest.py").read_text()
    method = (root / "docs" / "methodology.md").read_text()
    compare = (root / "src" / "quantlab" / "portfolio" / "compare.py").read_text()
    assert "so each waits one session in cash" not in invest
    assert "The contribution therefore waits one session in cash |" not in method
    for text in (invest, method, compare):
        assert "order decided at the previous close" in text


def test_p08_risk_page_explains_diversification_correlation_and_cash(monkeypatch):
    at = render(view("risk"), monkeypatch)
    shown = metrics(at)
    for label in ("Effective holdings", "Diversification ratio", "Average correlation", "Cash"):
        assert label in shown and "nan" not in shown[label].lower()
    page = texts(at)
    assert "20% cash scales volatility, VaR and ES down by 20% exactly" in page
    assert "ES** is the average of those larger losses" in page
