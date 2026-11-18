import math

import numpy as np
import pandas as pd
import pytest

from quantlab.research import (
    TrialRegistry,
    bonferroni,
    bootstrap_ci,
    calendar_subperiods,
    chronological_split,
    holm,
    resample_indices,
)
from quantlab.risk import (
    apply_scenario,
    covariance_matrix,
    exposure_breakdown,
    portfolio_volatility,
    risk_contributions,
    scenario_summary,
    validate_weights,
)
from quantlab.simulations import simulate

# ---------------------------------------------------------------- risk


def test_two_asset_portfolio_volatility_closed_form():
    cov = pd.DataFrame([[0.04, 0.006], [0.006, 0.09]], index=["A", "B"], columns=["A", "B"])
    w = pd.Series({"A": 0.6, "B": 0.4})
    # 0.36*0.04 + 0.16*0.09 + 2*0.24*0.006 = 0.03168
    assert portfolio_volatility(w, cov) == pytest.approx(math.sqrt(0.03168))
    rc = risk_contributions(w, cov)
    assert rc["vol_contribution"].sum() == pytest.approx(math.sqrt(0.03168))  # Euler
    assert rc.loc["A", "vol_contribution"] == pytest.approx(
        0.6 * (0.6 * 0.04 + 0.4 * 0.006) / math.sqrt(0.03168)
    )
    assert rc["pct_of_risk"].sum() == pytest.approx(1.0)
    assert rc.loc["B", "standalone_vol"] == pytest.approx(0.3)


def test_covariance_annualization_and_missing_rows():
    r = pd.DataFrame({"A": [0.01, -0.01, 0.02, np.nan], "B": [0.0, 0.01, -0.01, 0.05]})
    cov = covariance_matrix(r, periods=252)
    assert cov.loc["A", "A"] == pytest.approx(np.var([0.01, -0.01, 0.02], ddof=1) * 252)
    with pytest.raises(ValueError):
        covariance_matrix(r.iloc[:1])


def test_weight_constraints():
    validate_weights(pd.Series({"A": 0.5, "B": 0.3}))
    for bad in ({"A": 0.8, "B": 0.3}, {"A": -0.1, "B": 0.5}, {"A": np.nan}):
        with pytest.raises(ValueError):
            validate_weights(pd.Series(bad))
    with pytest.raises(ValueError):
        validate_weights(pd.Series({"A": 0.5}), allow_cash=False)
    exp = exposure_breakdown(pd.Series({"A": 0.5, "B": 0.3}), value=1000)
    assert exp.loc["CASH", "value"] == pytest.approx(200)


def test_stress_scenarios():
    holdings = pd.Series({"SPY": 60_000.0, "TLT": 40_000.0})
    out = apply_scenario(holdings, {"SPY": -0.20})
    assert out.loc["SPY", "pnl"] == pytest.approx(-12_000)
    assert out.loc["TLT", "pnl"] == 0
    assert out["contribution_pct"].sum() == pytest.approx(-0.12)
    table = scenario_summary(holdings, {"eq": {"SPY": -0.2}, "both": {"SPY": -0.2, "TLT": 0.1}})
    assert table.loc["both", "value_after"] == pytest.approx(92_000)
    assert table.loc["eq", "pnl_pct"] == pytest.approx(-0.12)
    with pytest.raises(KeyError):
        apply_scenario(holdings, {"GLD": -0.1})
    with pytest.raises(ValueError):
        apply_scenario(holdings, {"SPY": -1.5})


# ---------------------------------------------------------------- bootstrap


def test_resampling_index_structure():
    rng = np.random.default_rng(0)
    idx = resample_indices(100, 50, "block", 10, rng)
    assert len(idx) == 50 and idx.min() >= 0 and idx.max() < 100
    assert (np.diff(idx.reshape(5, 10), axis=1) == 1).all()  # contiguous blocks
    idx = resample_indices(100, 5000, "stationary", 10, rng)
    assert idx.min() >= 0 and idx.max() < 100
    cont = (np.diff(idx) % 100 == 1).mean()
    assert 0.85 < cont < 0.95  # about 1 - 1/10 of steps continue a block
    with pytest.raises(ValueError):
        resample_indices(10, 5, "nope", 2, rng)


def test_bootstrap_ci_reproducible_and_calibrated():
    x = pd.Series(np.random.default_rng(5).normal(0.1, 1.0, 400))
    a = bootstrap_ci(x, lambda s: s.mean(), n_boot=1000, method="iid", seed=3)
    b = bootstrap_ci(x, lambda s: s.mean(), n_boot=1000, method="iid", seed=3)
    assert (a.lower, a.upper) == (b.lower, b.upper)
    assert a.estimate == pytest.approx(x.mean())
    # For i.i.d. data the interval should match mean +/- 1.96 * s/sqrt(n).
    se = x.std(ddof=1) / math.sqrt(len(x))
    assert a.lower == pytest.approx(x.mean() - 1.96 * se, abs=0.25 * se)
    assert a.upper == pytest.approx(x.mean() + 1.96 * se, abs=0.25 * se)


def test_bootstrap_degenerate_and_paired():
    const = pd.Series([0.01] * 50)
    res = bootstrap_ci(const, lambda s: s.mean(), n_boot=50)
    assert res.lower == res.upper == pytest.approx(0.01)
    # Paired resampling: an exact +1% daily edge must survive every resample.
    b = pd.Series(np.random.default_rng(2).normal(0, 0.01, 300))
    pair = pd.DataFrame({"s": b + 0.01, "b": b})
    diff = bootstrap_ci(pair, lambda d: (d["s"] - d["b"]).mean(), n_boot=200, block=10)
    assert diff.lower == pytest.approx(0.01) and diff.excludes_zero
    with pytest.raises(ValueError):
        bootstrap_ci(pd.Series([1.0]), lambda s: s.mean())


def test_block_bootstrap_is_wider_for_autocorrelated_data():
    rng = np.random.default_rng(8)
    e = rng.normal(0, 1, 2000)
    x = np.empty(2000)
    x[0] = e[0]
    for i in range(1, 2000):  # AR(1), phi = 0.8
        x[i] = 0.8 * x[i - 1] + e[i]
    s = pd.Series(x)
    iid = bootstrap_ci(s, lambda v: v.mean(), n_boot=400, method="iid", seed=1)
    blk = bootstrap_ci(s, lambda v: v.mean(), n_boot=400, method="stationary", block=40, seed=1)
    assert (blk.upper - blk.lower) > 1.5 * (iid.upper - iid.lower)


# ---------------------------------------------------------------- monte carlo


def test_monte_carlo_reproducible_under_fixed_seed():
    r = pd.Series(np.random.default_rng(0).normal(0.0005, 0.01, 500))
    a, b = simulate(r, 60, 200, seed=9), simulate(r, 60, 200, seed=9)
    np.testing.assert_array_equal(a.paths, b.paths)
    assert not np.array_equal(a.paths, simulate(r, 60, 200, seed=10).paths)
    assert a.paths.shape == (200, 61) and (a.paths[:, 0] == 100_000).all()


@pytest.mark.parametrize("method", ["iid", "block", "stationary"])
def test_monte_carlo_constant_returns_have_a_known_answer(method):
    res = simulate(pd.Series([0.01] * 30), horizon=10, n_paths=50, initial_value=1000,
                   method=method, block=5)  # fmt: skip
    np.testing.assert_allclose(res.terminal, 1000 * 1.01**10)
    assert res.prob_terminal_below(1000) == 0.0
    np.testing.assert_allclose(res.max_drawdowns(), 0.0)
    bands = res.percentile_bands()
    np.testing.assert_allclose(bands["p5"], bands["p95"])


def test_monte_carlo_two_point_distribution():
    # Returns are +10% or -10% with equal probability; horizon 2.
    # Terminal wealth: 1.21 (p=.25), 0.99 (p=.5), 0.81 (p=.25); E = 1.0; P(loss) = .75
    res = simulate(pd.Series([0.1, -0.1]), horizon=2, n_paths=40_000, initial_value=1.0, seed=1)
    assert set(np.round(res.terminal, 6)) == {1.21, 0.99, 0.81}
    assert res.terminal.mean() == pytest.approx(1.0, abs=0.005)
    assert res.prob_terminal_below(1.0) == pytest.approx(0.75, abs=0.01)
    # Max drawdown worse than -10%: only the down-down path (p = .25).
    assert res.prob_drawdown_worse_than(-0.15) == pytest.approx(0.25, abs=0.01)


def test_monte_carlo_input_validation():
    with pytest.raises(ValueError):
        simulate(pd.Series([0.01]))
    with pytest.raises(ValueError):
        simulate(pd.Series([0.01, -1.0]))
    with pytest.raises(ValueError):
        simulate(pd.Series([0.01, 0.02]), horizon=0)


# ---------------------------------------------------------------- research discipline


def test_chronological_split_is_ordered_and_disjoint():
    idx = pd.bdate_range("2010-01-01", "2020-12-31")
    split = chronological_split(idx, "2015-12-31", "2017-12-31")
    assert split.development[1] < split.validation[0] <= split.validation[1] < split.test[0]
    s = pd.Series(1.0, index=idx)
    parts = [split.slice(s, p) for p in ("development", "validation", "test")]
    assert sum(len(p) for p in parts) == len(idx)
    with pytest.raises(ValueError):
        chronological_split(idx, "2030-01-01")
    assert calendar_subperiods(idx, 5)[0] == ("2010-01-01", "2014-12-31")


def test_multiple_testing_adjustments():
    p = [0.01, 0.04, 0.03]
    assert bonferroni(p) == pytest.approx([0.03, 0.12, 0.09])
    # Holm: 0.01*3 = .03; 0.03*2 = .06; 0.04*1 = .04 -> monotone -> .06
    assert holm(p) == pytest.approx([0.03, 0.06, 0.06])
    reg = TrialRegistry()
    reg.record("trend", {"fast": 10, "slow": 50}, "dev", sharpe=0.5)
    reg.record("trend", {"fast": 10, "slow": 50}, "test", sharpe=0.4)
    reg.record("trend", {"fast": 20, "slow": 50}, "dev", sharpe=0.3)
    assert reg.count == 3 and reg.distinct_configurations() == 2
