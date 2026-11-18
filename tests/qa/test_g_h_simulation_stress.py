"""Suites G and H: Monte Carlo correctness and model risk; stress-test arithmetic.

Nothing here asserts that a simulated frequency equals a real-world probability.
The tests check that the simulator does what it says, and that its outputs move
with the modelling assumptions.
"""

import math

import numpy as np
import pandas as pd
import pytest
from fixtures.app import metrics, render, view

from quantlab.research.bootstrap import resample_indices
from quantlab.risk import apply_scenario, portfolio_returns, scenario_summary
from quantlab.simulations import simulate

METHODS = ["iid", "block", "stationary"]


@pytest.fixture(scope="module")
def clustered():
    """Returns with volatility clustering: calm and turbulent regimes that persist."""
    rng = np.random.default_rng(12)
    regime, out = 0, []
    for _ in range(3000):
        if rng.random() < 0.01:
            regime = 1 - regime
        out.append(rng.normal(0.0004, 0.006 if regime == 0 else 0.025))
    return pd.Series(out, index=pd.bdate_range("2012-01-02", periods=3000))


# ================================================================= Suite G


@pytest.mark.parametrize("method", METHODS)
def test_g01_shape_determinism_and_validity(method, clustered):
    a = simulate(clustered, horizon=120, n_paths=400, initial_value=50_000, method=method, block=15, seed=5)
    b = simulate(clustered, horizon=120, n_paths=400, initial_value=50_000, method=method, block=15, seed=5)
    assert a.paths.shape == (400, 121) and (a.paths[:, 0] == 50_000).all()
    np.testing.assert_array_equal(a.paths, b.paths)  # bit-identical for the same seed
    assert a.summary() == b.summary()
    other = simulate(clustered, horizon=120, n_paths=400, initial_value=50_000, method=method, block=15, seed=6)
    assert not np.array_equal(a.paths, other.paths)
    assert np.isfinite(a.paths).all() and (a.paths > 0).all()
    bands = a.percentile_bands()
    ordered = bands[["p5", "p25", "p50", "p75", "p95"]].to_numpy()
    assert (np.diff(ordered, axis=1) >= -1e-9).all()  # percentiles never cross
    assert len(bands) == 121 and (bands.iloc[0] == 50_000).all()


@pytest.mark.parametrize("method", METHODS)
def test_g02_every_simulated_step_is_an_observed_return_compounded_correctly(method, clustered):
    sample = clustered.iloc[:500]
    res = simulate(sample, horizon=40, n_paths=60, initial_value=1.0, method=method, block=8, seed=3)
    steps = res.paths[:, 1:] / res.paths[:, :-1] - 1.0
    observed = np.sort(sample.to_numpy())
    nearest = np.abs(observed[np.searchsorted(observed, steps.ravel()).clip(0, len(observed) - 1)] - steps.ravel())
    left = np.abs(observed[(np.searchsorted(observed, steps.ravel()) - 1).clip(0)] - steps.ravel())
    assert np.minimum(nearest, left).max() < 1e-12  # nothing is invented: only historical days
    np.testing.assert_allclose(res.terminal, np.prod(1.0 + steps, axis=1), rtol=1e-12)
    # Independent drawdown: brute force on each path.
    brute = [min(p[j] / p[: j + 1].max() - 1 for j in range(len(p))) for p in res.paths]
    np.testing.assert_allclose(res.max_drawdowns(), brute, atol=1e-12)
    assert (res.max_drawdowns() <= 0).all() and (res.max_drawdowns() > -1).all()


def test_g03_block_methods_preserve_runs_of_consecutive_days():
    rng = np.random.default_rng(0)
    for method, block in (("block", 10), ("stationary", 10)):
        idx = resample_indices(1000, 5000, method, block, rng)
        consecutive = (np.diff(idx) % 1000 == 1).mean()
        assert consecutive > 0.85, method  # about 1 - 1/10
    assert (np.diff(resample_indices(1000, 5000, "iid", 1, rng)) % 1000 == 1).mean() < 0.01


def test_g04_event_counts_and_probabilities_are_exact_arithmetic(clustered):
    res = simulate(clustered, horizon=252, n_paths=1000, seed=1)
    drawdowns = res.max_drawdowns()
    assert res.prob_drawdown_worse_than(-0.20) == (drawdowns < -0.20).sum() / 1000
    assert res.prob_terminal_below(res.initial_value) == (res.terminal < res.initial_value).sum() / 1000
    summary = res.summary()
    assert summary["prob_loss"] == res.prob_terminal_below(res.initial_value)
    assert summary["p5_terminal"] <= summary["median_terminal"] <= summary["p95_terminal"]
    assert res.prob_drawdown_worse_than(-0.999) == 0.0 and res.prob_drawdown_worse_than(0.0) <= 1.0


def test_g05_cash_dilutes_risk_proportionally_and_all_cash_is_flat():
    rng = np.random.default_rng(2)
    assets = pd.DataFrame(rng.normal(0.0005, 0.012, (800, 2)), columns=["A", "B"])
    full = portfolio_returns(assets, pd.Series({"A": 0.6, "B": 0.4}))
    half = portfolio_returns(assets, pd.Series({"A": 0.3, "B": 0.2}))  # the other half is cash
    np.testing.assert_allclose(half, full / 2, atol=1e-15)
    flat = simulate(portfolio_returns(assets, pd.Series({"A": 0.0, "B": 0.0})), 50, 20, 1000.0)
    assert (flat.paths == 1000.0).all() and flat.summary()["prob_loss"] == 0.0
    a = simulate(full, 252, 500, seed=4)
    b = simulate(half, 252, 500, seed=4)
    assert b.max_drawdowns().mean() > a.max_drawdowns().mean()  # shallower with cash


def test_g06_invalid_inputs_are_refused():
    good = pd.Series([0.01, -0.02, 0.005])
    for bad in (pd.Series([0.01]), pd.Series([0.1, -1.0]), pd.Series([0.1, -1.5]), pd.Series([np.nan, np.nan])):
        with pytest.raises(ValueError):
            simulate(bad)
    with pytest.raises(ValueError):
        simulate(good, method="magic")
    with pytest.raises(ValueError):
        simulate(good, method="block", block=10)  # block longer than the sample


def test_g07_ui_export_summary_is_reproducible_from_the_same_inputs(monkeypatch):
    def fingerprint(at):
        return next(c.value for c in at.caption if "Run fingerprint" in c.value)

    one, two = render(view("monte_carlo"), monkeypatch), render(view("monte_carlo"), monkeypatch)
    assert fingerprint(one) == fingerprint(two) and metrics(one) == metrics(two)
    assert not one.exception
    note = " ".join(i.value for i in one.info)
    assert "not probabilities about the real future" in note


def test_g08_model_risk_drawdown_frequency_depends_on_the_resampling_method(clustered):
    """Sensitivity, not truth: on returns with volatility clustering, the estimated frequency
    of a 20% drawdown changes materially with the resampling method."""
    paths = 2000

    def frequency(method, block, seed):
        res = simulate(clustered, horizon=252, n_paths=paths, method=method, block=block, seed=seed)
        return res.prob_drawdown_worse_than(-0.20)

    iid = [frequency("iid", 1, s) for s in range(4)]
    long_blocks = [frequency("stationary", 63, s) for s in range(4)]
    # Binomial standard error of one estimate at this path count.
    p = np.mean(long_blocks)
    standard_error = math.sqrt(p * (1 - p) / paths)
    # The two methods disagree by far more than sampling noise. The DIRECTION is a property
    # of the data, not a law: here blocks give fewer deep drawdowns, on the real SPY sample in
    # docs/qa/QA_REPORT.md they give more. Either way the answer depends on the assumption.
    assert abs(np.mean(long_blocks) - np.mean(iid)) > 3 * standard_error / math.sqrt(4)
    assert np.std(long_blocks) < 5 * standard_error  # seeds agree within sampling noise
    assert np.std(iid) < 5 * standard_error


def test_g09_more_paths_narrow_the_spread_across_seeds_at_the_expected_rate(clustered):
    """Convergence of the simulation (not predictive validity): quadrupling the paths roughly
    halves the seed-to-seed spread of an estimated frequency."""
    def spread(paths):
        values = [simulate(clustered, 126, paths, seed=s).prob_terminal_below(100_000.0) for s in range(12)]
        return float(np.std(values)), float(np.mean(values))

    small, p = spread(250)
    large, _ = spread(4000)
    assert large < small
    theory = math.sqrt(p * (1 - p) / 4000)
    assert 0.3 * theory < large < 3.0 * theory


# ================================================================= Suite H


def test_h01_reference_scenario_loss_is_14665():
    holdings = pd.Series({"SPY": 20_000.0, "QQQ": 20_000.0, "BND": 33_300.0, "CASH": 26_700.0})
    out = apply_scenario(holdings, {"SPY": -0.30, "QQQ": -0.35, "BND": -0.05})
    assert out["pnl"].to_dict() == pytest.approx({"SPY": -6000.0, "QQQ": -7000.0, "BND": -1665.0, "CASH": 0.0})
    assert out["pnl"].sum() == pytest.approx(-14_665.0)
    assert out["value_after"].sum() == pytest.approx(85_335.0)
    assert out["contribution_pct"].sum() == pytest.approx(-0.14665)
    assert out.loc["CASH", "value_after"] == 26_700.0  # cash is untouched


@pytest.mark.parametrize("shocks", [
    {"A": 0.10, "B": -0.20}, {"A": -0.5, "B": -0.5, "C": -0.5}, {"A": 4.0}, {"C": -1.0}, {}, {"B": 0.0},
])  # fmt: skip
def test_h02_scenario_pnl_equals_the_sum_of_holding_pnl(shocks):
    holdings = pd.Series({"A": 40_000.0, "B": 25_000.0, "C": 0.0, "CASH": 35_000.0})
    detail = apply_scenario(holdings, shocks)
    by_hand = sum(holdings[k] * v for k, v in shocks.items())
    summary = scenario_summary(holdings, {"s": shocks}).loc["s"]
    assert detail["pnl"].sum() == pytest.approx(by_hand)
    assert summary["pnl"] == pytest.approx(by_hand) and summary["value_before"] == 100_000.0
    assert summary["value_after"] == pytest.approx(100_000.0 + by_hand)
    assert summary["pnl_pct"] == pytest.approx(by_hand / 100_000.0)
    assert (detail["value_after"] >= 0).all()  # a long holding cannot go below zero
    assert detail.loc["C", "pnl"] == 0.0 and detail.loc["CASH", "pnl"] == 0.0  # no exposure, no effect


def test_h03_missing_instrument_and_excess_loss_are_refused():
    holdings = pd.Series({"A": 100.0})
    with pytest.raises(KeyError):
        apply_scenario(holdings, {"ZZZ": -0.1})
    with pytest.raises(ValueError):
        apply_scenario(holdings, {"A": -1.01})


def test_h04_non_finite_shocks_are_rejected_with_a_named_reason():
    """QA-009 (fixed): NaN is not silently 'no shock'; infinity is not a price move."""
    holdings = pd.Series({"A": 100.0, "B": 50.0})
    with pytest.raises(ValueError, match="Shock for A is not a finite number"):
        apply_scenario(holdings, {"A": float("nan")})
    assert apply_scenario(holdings, {"A": -0.5})["pnl"].sum() == -50.0  # finite shocks unchanged


@pytest.mark.parametrize("shock", [float("nan"), float("inf"), float("-inf")])
def test_h04b_non_finite_shocks_are_rejected(shock):
    with pytest.raises(ValueError):
        apply_scenario(pd.Series({"A": 100.0}), {"A": shock})
    with pytest.raises(ValueError):
        scenario_summary(pd.Series({"A": 100.0}), {"s": {"A": shock}})


def test_h05_zero_value_portfolio_is_refused_not_nan():
    """QA-019 (fixed): a percentage effect on a portfolio worth nothing is undefined, so the
    library refuses it instead of returning NaN."""
    for bad in (pd.Series({"A": 0.0}), pd.Series({"A": -10.0}), pd.Series({"A": float("nan")})):
        with pytest.raises(ValueError):
            apply_scenario(bad, {"A": -0.5})
    with pytest.raises(ValueError, match="no value"):
        scenario_summary(pd.Series({"A": 0.0, "CASH": 0.0}), {"s": {"A": -0.5}})
    cash_only = scenario_summary(pd.Series({"A": 0.0, "CASH": 100.0}), {"s": {"A": -0.5}})
    assert cash_only.loc["s", "pnl_pct"] == 0.0  # all cash: defined, and nothing is lost


def test_h06_stress_page_labels_scenarios_as_hypothetical_and_reconciles(monkeypatch):
    at = render(view("stress"), monkeypatch)
    assert not at.exception and not at.error
    assert any("Every scenario here is hypothetical" in w.value for w in at.warning)
    page = " ".join(str(w.value) for w in at.warning) + " ".join(c.value for c in at.caption)
    assert "nothing on this page models how assets actually move together" in page
    summary = next(d.value for d in at.dataframe if "Gain / loss (%)" in d.value.columns)
    # Default: 20% in each of five instruments, 100,000. Broad sell-off -10% -> -10,000.
    assert summary.loc["Broad sell-off", "Gain / loss"] == pytest.approx(-10_000.0)
    assert summary.loc["SYN1 crash", "Gain / loss"] == pytest.approx(-6_000.0)  # 20,000 x -30%
    assert summary.loc["SYN5 shock", "Gain / loss"] == pytest.approx(-4_000.0)  # 20,000 x -20%
    detail = next(d.value for d in at.dataframe if "Effect on portfolio" in d.value.columns)
    assert detail["Gain / loss"].sum() == pytest.approx(-10_000.0)
    assert (summary["Value before"] == 100_000.0).all()
