"""Suite D: independent verification of the financial mathematics.

Expected values come from tests/qa/reference.py (plain Python) or from hand
arithmetic in the comments. Property tests use Hypothesis with derandomised,
reproducible examples; a failure prints a minimal counter-example.
"""

import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from qa import reference as ref
from quantlab.analytics import metrics as m
from quantlab.analytics.flows import money_weighted_return
from quantlab.data.transforms import cumulative_returns, log_returns, simple_returns
from quantlab.risk import (
    covariance_matrix,
    diversification_ratio,
    effective_holdings,
    portfolio_returns,
    portfolio_variance,
    portfolio_volatility,
    risk_contributions,
)

TOL = 1e-12
PROP = settings(max_examples=150, derandomize=True, deadline=None)
daily = st.floats(min_value=-0.2, max_value=0.2, allow_nan=False, allow_infinity=False)
series = st.lists(daily, min_size=3, max_size=120)


def weights_strategy(n):
    return st.lists(st.floats(0.0, 1.0, allow_nan=False), min_size=n, max_size=n).filter(
        lambda w: sum(w) > 0.05
    ).map(lambda w: [x / max(1.0, sum(w)) for x in w])


# ----------------------------------------------------------------- hand-worked values


def test_d01_returns_and_compounding_by_hand():
    prices = pd.Series([100.0, 110.0, 99.0, 108.9])
    simple = simple_returns(prices).dropna().tolist()
    assert simple == pytest.approx([0.10, -0.10, 0.10])
    assert m.total_return(pd.Series(simple)) == pytest.approx(108.9 / 100 - 1)  # 8.9%, not 10%
    assert sum(log_returns(prices).dropna()) == pytest.approx(math.log(1.089))
    assert cumulative_returns(pd.Series(simple)).tolist() == pytest.approx([0.10, -0.01, 0.089])


def test_d02_volatility_cagr_sharpe_by_hand():
    r = [0.01, -0.02, 0.03, 0.00]
    # mean 0.005; squared deviations 0.000025 + 0.000625 + 0.000625 + 0.000025 = 0.0013
    # sample variance 0.0013 / 3; stdev 0.0208167
    stdev = math.sqrt(0.0013 / 3)
    assert m.volatility(pd.Series(r)) == pytest.approx(stdev * math.sqrt(252))
    growth = 1.01 * 0.98 * 1.03 * 1.00
    assert m.cagr(pd.Series(r)) == pytest.approx(growth ** (252 / 4) - 1)
    assert m.sharpe(pd.Series(r)) == pytest.approx(0.005 / stdev * math.sqrt(252))
    excess_mean = 0.005 - 0.0252 / 252  # rf of 2.52% a year is exactly 1 bp a day
    assert m.sharpe(pd.Series(r), risk_free=0.0252) == pytest.approx(excess_mean / stdev * math.sqrt(252))


def test_d03_two_asset_covariance_volatility_and_contributions_by_hand():
    a, b = [0.01, -0.01, 0.02, 0.00], [0.00, 0.01, -0.01, 0.02]
    # means 0.005 and 0.005; cov = sum((a-0.005)(b-0.005))/3
    cov_ab = sum((x - 0.005) * (y - 0.005) for x, y in zip(a, b, strict=True)) / 3
    var_a = sum((x - 0.005) ** 2 for x in a) / 3
    frame = pd.DataFrame({"A": a, "B": b})
    cov = covariance_matrix(frame, periods=1)
    assert cov.loc["A", "B"] == pytest.approx(cov_ab) and cov.loc["A", "A"] == pytest.approx(var_a)
    assert frame.corr().loc["A", "B"] == pytest.approx(cov_ab / var_a)  # equal variances here
    w = pd.Series({"A": 0.6, "B": 0.4})
    variance = 0.36 * var_a + 0.16 * var_a + 2 * 0.24 * cov_ab
    assert portfolio_variance(w, cov) == pytest.approx(variance)
    sigma = math.sqrt(variance)
    rc = risk_contributions(w, cov)
    assert rc.loc["A", "vol_contribution"] == pytest.approx(0.6 * (0.6 * var_a + 0.4 * cov_ab) / sigma)
    assert rc["vol_contribution"].sum() == pytest.approx(sigma)
    assert rc["pct_of_risk"].sum() == pytest.approx(1.0)


def test_d04_var_and_expected_shortfall_by_hand():
    r = pd.Series([-0.05, -0.03, -0.01, 0.00, 0.01, 0.02, 0.02, 0.03, 0.04, 0.06, 0.07])
    # 11 points: the 10% quantile sits exactly on the second smallest (-3%).
    assert m.historical_var(r, 0.90) == pytest.approx(0.03)
    # QA-020 (fixed): the 10% tail holds -5% and -3%; the observation exactly on the quantile
    # belongs to the tail, so ES = 4%. Before the fix 1 - 0.90 = 0.09999999999999998 put the
    # quantile a hair below -3% and ES came out as 5%.
    assert m.historical_es(r, 0.90) == pytest.approx(0.04)
    # 5% quantile: position 0.5 between -5% and -3% -> -4%; only -5% lies at or below it.
    assert m.historical_var(r, 0.95) == pytest.approx(0.04)
    assert m.historical_es(r, 0.95) == pytest.approx(0.05)


def test_d04b_expected_shortfall_includes_an_observation_exactly_at_the_quantile():
    """QA-020 acceptance: an observation on the quantile is in the tail at every offered level."""
    r = pd.Series([-0.05, -0.03, -0.01, 0.00, 0.01, 0.02, 0.02, 0.03, 0.04, 0.06, 0.07])
    assert m.historical_es(r, 0.90) == pytest.approx(0.04)  # mean of -5% and -3%
    for level in (0.90, 0.95, 0.975, 0.99):  # n chosen so the quantile falls on an observation
        n = round(1 / (1 - level)) * 4 + 1
        grid = pd.Series(np.arange(n) / 1000.0)
        cut = -m.historical_var(grid, level)
        assert m.historical_es(grid, level) == pytest.approx(-grid[grid <= cut + 1e-9].mean())
        assert m.historical_es(grid, level) >= m.historical_var(grid, level)
    # 101 points 0..100: the 1% quantile is exactly the second smallest; both are in the tail.
    hundred = pd.Series(np.arange(101) / 1000 - 0.05)
    assert m.historical_var(hundred, 0.99) == pytest.approx(0.049)
    assert m.historical_es(hundred, 0.99) == pytest.approx(0.0495)
    with pytest.raises(ValueError):
        m.historical_es(r, 1.0)


def test_d05_drawdown_depth_and_duration_by_hand():
    #  wealth: 1.10  0.99  0.891  1.0692  1.1761  1.0585
    r = pd.Series([0.10, -0.10, -0.10, 0.20, 0.10, -0.10])
    assert m.max_drawdown(r) == pytest.approx(0.891 / 1.10 - 1)  # -19%
    assert m.max_drawdown_duration(r) == 3  # sessions 2, 3 and 4 are below the 1.10 peak
    assert m.calmar(r, periods=6) == pytest.approx((1.10 * 0.9 * 0.9 * 1.2 * 1.1 * 0.9 - 1) / 0.19)


def test_d06_xirr_closed_forms():
    day = pd.Timestamp("2020-01-01")
    one_year = pd.Series({day: -1000.0, day + pd.Timedelta(days=365): 1100.0})
    assert money_weighted_return(one_year).rate == pytest.approx(0.10, abs=1e-10)
    # Two equal deposits a year apart, valued a year later: 1000(1+r)^2 + 1000(1+r) = 2310 -> r = 10%
    two = pd.Series({day: -1000.0, day + pd.Timedelta(days=365): -1000.0, day + pd.Timedelta(days=730): 2310.0})
    assert money_weighted_return(two).rate == pytest.approx(0.10, abs=1e-10)
    half = pd.Series({day: -1000.0, day + pd.Timedelta(days=182.5 * 2): 900.0})
    assert money_weighted_return(half).rate == pytest.approx(-0.10, abs=1e-10)


def test_d07_undefined_metrics_are_nan_and_never_a_number():
    flat, one, none = pd.Series([0.0] * 20), pd.Series([0.01]), pd.Series([], dtype=float)
    for fn in (m.sharpe, m.sortino, m.calmar):
        assert math.isnan(fn(flat)), fn.__name__  # zero risk: the ratio is undefined
    assert m.volatility(flat) == 0.0 and m.max_drawdown(flat) == 0.0
    for fn in (m.cagr, m.volatility, m.sharpe, m.max_drawdown, m.historical_var, m.historical_es):
        assert math.isnan(fn(none)), fn.__name__
    assert math.isnan(m.volatility(one)) and math.isnan(m.sharpe(one))
    assert math.isnan(m.beta(flat, flat)) and math.isnan(m.information_ratio(flat, flat))
    assert math.isnan(m.cagr(pd.Series([0.5, -1.0, 0.2])))  # wiped out


# ----------------------------------------------------------------- agreement with the reference


@PROP
@given(series)
def test_d10_return_statistics_match_the_reference(returns):
    s = pd.Series(returns)
    assert m.total_return(s) == pytest.approx(ref.compound(returns), rel=1e-9, abs=TOL)
    assert m.volatility(s) == pytest.approx(ref.annualised_vol(returns), rel=1e-9, abs=TOL)
    if 1.0 + ref.compound(returns) > 0:
        assert m.cagr(s) == pytest.approx(ref.cagr(returns), rel=1e-9, abs=TOL)
    worst, longest = ref.max_drawdown(returns)
    assert m.max_drawdown(s) == pytest.approx(worst, rel=1e-9, abs=TOL)
    assert m.max_drawdown_duration(s) == longest
    assert -1.0 <= m.max_drawdown(s) <= 0.0


@PROP
@given(series.filter(lambda r: len(set(r)) > 2 and max(r) - min(r) > 1e-6), st.floats(0.0, 0.1))
def test_d11_sharpe_matches_the_reference(returns, rf):
    assert m.sharpe(pd.Series(returns), rf) == pytest.approx(ref.sharpe(returns, rf), rel=1e-7, abs=1e-9)


@PROP
@given(st.lists(daily, min_size=20, max_size=200), st.sampled_from([0.90, 0.95, 0.975, 0.99]))
def test_d12_var_and_expected_shortfall_match_the_reference(returns, confidence):
    var, es = ref.var_es(returns, confidence)
    s = pd.Series(returns)
    assert m.historical_var(s, confidence) == pytest.approx(var, rel=1e-9, abs=TOL)
    assert m.historical_es(s, confidence) == pytest.approx(es, rel=1e-9, abs=TOL)
    assert m.historical_es(s, confidence) >= m.historical_var(s, confidence) - TOL  # ES is never milder
    assert m.historical_var(s, 0.99) >= m.historical_var(s, 0.90) - TOL  # monotone in confidence


@PROP
@given(st.integers(2, 5).flatmap(lambda n: st.tuples(
    st.lists(st.lists(daily, min_size=n, max_size=n), min_size=12, max_size=60), weights_strategy(n))))  # fmt: skip
def test_d13_covariance_and_risk_contribution_invariants(case):
    rows, weights = case
    frame = pd.DataFrame(rows, columns=[f"A{i}" for i in range(len(weights))])
    cov = covariance_matrix(frame)
    matrix = cov.to_numpy()
    columns = [frame[c].tolist() for c in frame.columns]
    np.testing.assert_allclose(matrix, ref.cov_matrix(columns), rtol=1e-9, atol=1e-14)
    np.testing.assert_allclose(matrix, matrix.T, atol=0)  # exactly symmetric
    assert np.linalg.eigvalsh(matrix).min() >= -1e-10 * max(1.0, np.abs(matrix).max())  # PSD
    w = pd.Series(weights, index=frame.columns)
    sigma = portfolio_volatility(w, cov)
    assert sigma == pytest.approx(ref.portfolio_vol(weights, ref.cov_matrix(columns)), rel=1e-8, abs=1e-12)
    # The same volatility must come out of the weighted return series itself.
    direct = (frame * w).sum(axis=1)
    assert sigma == pytest.approx(direct.std(ddof=1) * math.sqrt(252), rel=1e-8, abs=1e-12)
    rc = risk_contributions(w, cov)
    if sigma > 1e-9:
        assert rc["vol_contribution"].sum() == pytest.approx(sigma, rel=1e-9)  # Euler reconciliation
        assert rc["pct_of_risk"].sum() == pytest.approx(1.0, rel=1e-9)
        np.testing.assert_allclose(rc["vol_contribution"], ref.risk_contributions(weights, ref.cov_matrix(columns)),
                                   rtol=1e-7, atol=1e-12)  # fmt: skip
        assert diversification_ratio(w, cov) >= 1.0 - 1e-9  # a mix is never riskier than its parts
    held = [x for x in weights if x > 0]
    assert 1.0 - 1e-9 <= effective_holdings(w) <= len(held) + 1e-9


@PROP
@given(st.lists(st.tuples(st.integers(1, 400), st.floats(10, 5000)), min_size=1, max_size=8),
       st.floats(0.2, 4.0))  # fmt: skip
def test_d14_xirr_matches_the_reference_for_contribution_schedules(deposits, multiple):
    start = pd.Timestamp("2015-01-01")
    days = sorted({0, *(d for d, _ in deposits)})
    amounts = [1000.0] + [a for _, a in deposits][: len(days) - 1]
    end = days[-1] + 200
    flows = [(d, -a) for d, a in zip(days, amounts, strict=False)] + [(end, multiple * sum(amounts[: len(days)]))]
    series_ = pd.Series({start + pd.Timedelta(days=d): cf for d, cf in flows})
    result = money_weighted_return(series_)
    assert result.ok and result.span_days == end
    assert result.rate == pytest.approx(ref.xirr(flows), rel=1e-7, abs=1e-9)
    # The rate must actually solve the equation it claims to solve.
    npv = sum(cf / (1 + result.rate) ** (d / 365.0) for d, cf in flows)
    assert abs(npv) < 1e-6 * sum(abs(cf) for _, cf in flows)


@PROP
@given(st.lists(st.lists(daily, min_size=3, max_size=3), min_size=10, max_size=60), weights_strategy(3))
def test_d15_cash_is_a_zero_return_asset_and_scaling_weights_scales_risk(rows, weights):
    frame = pd.DataFrame(rows, columns=["A", "B", "C"])
    w = pd.Series(weights, index=frame.columns)
    port = portfolio_returns(frame, w)
    np.testing.assert_allclose(port, (frame * w).sum(axis=1), atol=1e-15)
    half = portfolio_returns(frame, w / 2)  # half invested, half cash
    np.testing.assert_allclose(half, port / 2, atol=1e-15)
    cov = covariance_matrix(frame)
    assert portfolio_volatility(w / 2, cov) == pytest.approx(portfolio_volatility(w, cov) / 2, rel=1e-9, abs=1e-14)
