import math
import statistics

import numpy as np
import pandas as pd
import pytest

from quantlab.analytics import metrics as m

R = pd.Series([0.10, -0.10, 0.05])


def test_total_return_and_cagr():
    assert m.total_return(R) == pytest.approx(1.1 * 0.9 * 1.05 - 1)  # 0.0395
    # With periods == n the annualized growth equals the total return.
    assert m.cagr(R, periods=3) == pytest.approx(0.0395)
    # Two "years" of three periods each: (1.0395)^(3/6) - 1
    assert m.cagr(pd.concat([R, pd.Series([0.0, 0.0, 0.0])]), periods=3) == pytest.approx(
        math.sqrt(1.0395) - 1
    )


def test_volatility_and_sharpe_against_stdlib():
    sd = statistics.stdev(R)  # sample stdev, ddof=1
    assert m.volatility(R, periods=4) == pytest.approx(sd * 2)
    rf = 0.02
    excess = [r - rf / 4 for r in R]
    expected = statistics.mean(excess) / statistics.stdev(excess) * 2
    assert m.sharpe(R, risk_free=rf, periods=4) == pytest.approx(expected)


def test_sortino_by_hand():
    # Downside deviation: sqrt(mean([0, 0.1^2, 0])) = 0.1/sqrt(3); annualized x sqrt(4)
    dd = 0.1 / math.sqrt(3) * 2
    assert m.downside_deviation(R, periods=4) == pytest.approx(dd)
    assert m.sortino(R, periods=4) == pytest.approx((0.05 / 3) * 4 / dd)


def test_drawdown_depth_and_duration():
    # wealth: 1.10, 0.99, 1.0395 -> trough 0.99/1.10 - 1 = -10%; under water for 2 sessions
    assert m.max_drawdown(R) == pytest.approx(-0.10)
    assert m.max_drawdown_duration(R) == 2
    assert m.calmar(R, periods=3) == pytest.approx(0.0395 / 0.10)
    # A loss on the very first day is a drawdown from initial capital.
    assert m.max_drawdown(pd.Series([-0.2, 0.1])) == pytest.approx(-0.2)
    assert m.max_drawdown(pd.Series([0.01, 0.02])) == 0.0


def test_beta_alpha_tracking_error_information_ratio():
    rng = np.random.default_rng(1)
    b = pd.Series(rng.normal(0, 0.01, 500))
    r = 0.0002 + 1.5 * b  # exact linear relation
    assert m.beta(r, b) == pytest.approx(1.5)
    assert m.alpha(r, b) == pytest.approx(0.0002 * 252)
    assert m.tracking_error(b, b) == pytest.approx(0.0)
    assert math.isnan(m.information_ratio(b, b))
    active = r - b
    expected_ir = active.mean() * 252 / (active.std(ddof=1) * math.sqrt(252))
    assert m.information_ratio(r, b) == pytest.approx(expected_ir)


def test_alignment_with_different_start_dates():
    idx = pd.bdate_range("2024-01-01", periods=6)
    bench = pd.Series([0.01, -0.01, 0.02, 0.0, 0.01, -0.02], index=idx)
    strat = (2 * bench).iloc[2:]  # strategy starts two sessions later
    r, b = m.align(strat, bench)
    assert list(r.index) == list(idx[2:]) == list(b.index)
    assert m.beta(strat, bench) == pytest.approx(2.0)


def test_var_and_expected_shortfall():
    r = pd.Series(np.arange(-4, 6) / 100)  # -4% ... +5%, ten observations
    # 5% quantile by linear interpolation: -0.04 + 0.45 * 0.01 = -0.0355
    assert m.historical_var(r, 0.95) == pytest.approx(0.0355)
    assert m.historical_es(r, 0.95) == pytest.approx(0.04)
    assert m.historical_es(r, 0.80) == pytest.approx(0.035)  # mean of -4% and -3%
    assert m.historical_es(r, 0.95) >= m.historical_var(r, 0.95)


def test_undefined_statistics_are_nan_not_numbers():
    flat = pd.Series([0.0] * 10)
    empty = pd.Series([], dtype=float)
    assert math.isnan(m.sharpe(flat)) and math.isnan(m.sortino(flat))
    assert math.isnan(m.calmar(flat)) and math.isnan(m.beta(flat, flat))
    assert m.volatility(flat) == 0.0 and m.max_drawdown(flat) == 0.0
    for fn in (m.total_return, m.cagr, m.volatility, m.sharpe, m.max_drawdown, m.historical_var):
        assert math.isnan(fn(empty)), fn.__name__
    assert math.isnan(m.sharpe(pd.Series([0.01])))  # one observation: no variance estimate
    assert math.isnan(m.cagr(pd.Series([0.1, -1.0])))  # wiped out
    assert math.isnan(m.sharpe(pd.Series([0.01] * 5)))  # constant positive: zero variance


def test_nan_returns_are_dropped_not_zero_filled():
    assert m.total_return(pd.Series([0.1, np.nan, 0.1])) == pytest.approx(0.21)
    assert m.volatility(pd.Series([0.1, np.nan, -0.1]), periods=1) == pytest.approx(
        statistics.stdev([0.1, -0.1])
    )


def test_every_summary_statistic_has_a_definition():
    s = m.performance_summary(R, R, turnover=pd.Series([0.0] * 3),
                              trades=pd.DataFrame(columns=["side", "realized_pnl"]))  # fmt: skip
    alias = {"var_95": "var", "es_95": "expected_shortfall"}
    for key in s:
        if key in ("n_obs", "downside_deviation"):
            continue
        assert alias.get(key, key) in m.DEFINITIONS, key
