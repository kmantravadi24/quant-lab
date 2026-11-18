"""Suite Q: the Future Wealth engine, checked against independent references.

The account simulation is compared with ``reference.reference_wealth``, a plain-Python
ledger that shares no code with the engine (it solves the rebalancing cost by bisection,
the engine by fixed-point iteration). Goal, percentile and inflation calculations are
re-derived by brute force. Every test is offline and seeded.
"""

import math
import time
import tracemalloc
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from qa import reference as ref
from quantlab.data import SyntheticProvider
from quantlab.forecast import (
    WealthPlan,
    build_model,
    decomposition,
    deterministic_value,
    goal_probabilities,
    monthly_returns,
    quantile_interval,
    required_contribution,
    required_contribution_deterministic,
    simulate_wealth,
    summary,
)
from quantlab.forecast.engine import MAX_STORED_VALUES, check_size
from quantlab.portfolio.spec import PortfolioSpec

TICKERS = ["AAA", "BBB", "CCC"]


class Scripted:
    """A return 'model' that replays given paths: (paths, months, assets)."""

    def __init__(self, paths: np.ndarray, tickers=TICKERS):
        self.paths = np.asarray(paths, dtype=float)
        self.tickers = list(tickers)

    def start(self, n_paths, rng):
        assert n_paths == self.paths.shape[0]
        self.m = 0

    def draw(self, rng):
        out = self.paths[:, self.m, :]
        self.m += 1
        return out

    def describe(self):
        return {"model": "scripted", "tickers": self.tickers}


def plan(**kw):
    base = dict(weights={"AAA": 0.5, "BBB": 0.3}, initial_amount=10_000.0, contribution=500.0,
                frequency="M", contribution_growth=0.0, rebalance="A", cost_bps=10.0,
                annual_fee=0.003, cash_yield=0.02, inflation=0.025, horizon_years=2.0)  # fmt: skip
    base.update(kw)
    return WealthPlan(**base)


def random_paths(n_paths, months, seed=0, scale=0.05):
    rng = np.random.default_rng(seed)
    return np.clip(rng.normal(0.006, scale, (n_paths, months, len(TICKERS))), -0.6, 2.0)


@pytest.fixture(scope="module")
def history():
    data = SyntheticProvider(7).fetch(TICKERS, "1995-01-01", "2024-12-31")
    return monthly_returns(data.close)


# ----------------------------------------------------------------- account arithmetic


@pytest.mark.parametrize("rebalance", [None, "M", "Q", "A"])
@pytest.mark.parametrize("frequency, growth", [("M", 0.0), ("Q", 0.05), ("A", 0.1)])
def test_q01_engine_matches_the_independent_ledger(rebalance, frequency, growth):
    p = plan(rebalance=rebalance, frequency=frequency, contribution_growth=growth, horizon_years=3.0)
    paths = random_paths(6, p.months, seed=hash((rebalance, frequency)) % 1000)
    result = simulate_wealth(p, Scripted(paths), n_paths=6, seed=1)
    for i in range(6):
        expected = ref.reference_wealth(p.to_dict(), paths[i].tolist(), TICKERS)
        assert result.values[i] == pytest.approx(expected["values"], rel=1e-10, abs=1e-8)
        assert result.total_costs[i] == pytest.approx(expected["costs"], rel=1e-9, abs=1e-9)
        assert result.total_fees[i] == pytest.approx(expected["fees"], rel=1e-10)
    assert result.contributed[-1] == pytest.approx(expected["deposits"])


@settings(max_examples=60, deadline=None, derandomize=True)
@given(st.integers(0, 10_000), st.sampled_from([None, "M", "Q", "A"]), st.floats(0, 200),
       st.floats(0, 0.03), st.floats(-0.01, 0.06), st.floats(0.0, 1.0), st.floats(0.0, 1.0))  # fmt: skip
def test_q01b_property_engine_equals_reference(seed, rebalance, cost, fee, cash_yield, wa, wb):
    total = wa + wb
    weights = {"AAA": wa / max(1.0, total), "BBB": wb / max(1.0, total)}
    p = plan(weights=weights, rebalance=rebalance, cost_bps=cost, annual_fee=fee, cash_yield=cash_yield,
             horizon_years=1.5)  # fmt: skip
    paths = random_paths(2, p.months, seed, scale=0.15)
    result = simulate_wealth(p, Scripted(paths), n_paths=2, seed=0)
    for i in range(2):
        expected = ref.reference_wealth(p.to_dict(), paths[i].tolist(), TICKERS)["values"]
        assert result.values[i] == pytest.approx(expected, rel=1e-9, abs=1e-7)


def test_q02_ledger_reconciles_at_every_month_and_path(history):
    p = plan(horizon_years=10.0, rebalance="Q", contribution_growth=0.03)
    result = simulate_wealth(p, build_model("block_bootstrap", history), 500, 3, ledger=True)
    book = result.ledger
    identity = book.deposits - book.costs - book.fees + book.market + book.interest
    assert np.abs(identity - result.values).max() <= 1e-9 * result.values.max()
    assert np.array_equal(book.cash + book.holdings.sum(axis=2), result.values)
    assert (book.cash >= -1e-9).all() and (book.holdings >= -1e-9).all()  # no borrowing, no shorting
    assert np.allclose(book.deposits[0], result.contributed)  # deposits are the same on every path


def test_q03_zero_return_market_returns_exactly_what_was_paid_in_less_costs():
    p = plan(cost_bps=0.0, annual_fee=0.0, cash_yield=0.0, horizon_years=5.0)
    zero = np.zeros((3, p.months, 3))
    result = simulate_wealth(p, Scripted(zero), 3, 0)
    assert result.terminal == pytest.approx([p.total_contributed()] * 3, rel=1e-13)
    assert (result.twr_total == 0).all() and (result.twr_max_drawdown == 0).all()
    costly = simulate_wealth(replace(p, cost_bps=25.0), Scripted(zero), 3, 0)
    assert costly.terminal == pytest.approx(p.total_contributed() - costly.total_costs, rel=1e-12)
    s = summary(result)
    assert s["p_below_contributions"] == 0.0 and s["median_gain"] == pytest.approx(0.0, abs=1e-7)


def test_q04_all_cash_portfolio_never_trades_and_earns_the_cash_rate():
    p = plan(weights={"AAA": 0.0}, cost_bps=50.0, cash_yield=0.04, horizon_years=3.0)
    paths = random_paths(4, p.months, 9, scale=0.3)  # wild markets: irrelevant to cash
    result = simulate_wealth(p, Scripted(paths), 4, 0)
    assert (result.total_costs == 0).all() and (result.total_fees == 0).all()
    r = 1.04 ** (1 / 12) - 1
    expected = p.initial_amount * (1 + r) ** p.months + sum(
        d * (1 + r) ** (p.months - m + 1) for m, d in enumerate(p.contribution_schedule(), start=1))
    assert result.terminal == pytest.approx([expected] * 4, rel=1e-12)
    assert len(set(result.terminal.round(9))) == 1  # identical on every path


def test_q05_zero_contributions_and_no_rebalancing_let_holdings_drift():
    p = plan(contribution=0.0, rebalance=None, cost_bps=0.0, annual_fee=0.0, cash_yield=0.0,
             weights={"AAA": 0.6, "BBB": 0.4}, horizon_years=2.0)  # fmt: skip
    paths = random_paths(5, p.months, 4)
    result = simulate_wealth(p, Scripted(paths), 5, 0)
    growth = np.prod(1 + paths, axis=1)  # (paths, assets)
    expected = p.initial_amount * (0.6 * growth[:, 0] + 0.4 * growth[:, 1])
    assert result.terminal == pytest.approx(expected, rel=1e-12)
    assert result.contributed[-1] == p.initial_amount


def test_q06_increasing_contributions_follow_the_schedule():
    p = plan(contribution=200.0, contribution_growth=0.05, frequency="M", horizon_years=3.0)
    schedule = p.contribution_schedule()
    assert schedule[:12] == [200.0] * 12 and schedule[12:24] == pytest.approx([210.0] * 12)
    assert schedule[24:] == pytest.approx([220.5] * 12)
    q = plan(contribution=300.0, frequency="Q", contribution_growth=0.1, horizon_years=2.0)
    assert [m for m, d in enumerate(q.contribution_schedule(), 1) if d] == [1, 4, 7, 10, 13, 16, 19, 22]
    assert q.contribution_schedule()[12] == pytest.approx(330.0)
    assert q.total_contributed() == pytest.approx(10_000 + 4 * 300 + 4 * 330)


def test_q07_monthly_rebalancing_without_costs_is_exactly_the_fixed_weight_portfolio():
    p = plan(rebalance="M", cost_bps=0.0, annual_fee=0.0, cash_yield=0.0, horizon_years=4.0,
             contribution_growth=0.04)  # fmt: skip
    paths = random_paths(3, p.months, 11)
    result = simulate_wealth(p, Scripted(paths), 3, 0)
    w = np.array([0.5, 0.3, 0.0])
    for i in range(3):
        port = paths[i] @ w  # cash part earns 0
        value = p.initial_amount
        for m, d in enumerate(p.contribution_schedule(), start=1):
            value = (value + d) * (1 + port[m - 1])
        assert result.terminal[i] == pytest.approx(value, rel=1e-12)
        assert result.twr_total[i] == pytest.approx(np.prod(1 + port) - 1, rel=1e-12)


def test_q08_transaction_costs_solve_the_cost_equation_and_only_ever_reduce_wealth():
    from quantlab.forecast.engine import _rebalance

    rng = np.random.default_rng(5)
    hold, cash, w = rng.uniform(0, 1000, (50, 3)), rng.uniform(0, 1000, 50), np.array([0.5, 0.2, 0.1])
    new_hold, new_cash, cost = _rebalance(hold, cash, w, 0.004)
    after = new_cash + new_hold.sum(axis=1)
    residual = cash + hold.sum(axis=1) - after - 0.004 * np.abs(after[:, None] * w - hold).sum(axis=1)
    assert np.abs(residual).max() < 1e-9 and np.allclose(new_hold, after[:, None] * w)
    assert np.allclose(cost, cash + hold.sum(axis=1) - after) and (cost >= 0).all()
    paths = random_paths(20, 60, 2)
    finals = [simulate_wealth(plan(cost_bps=c, horizon_years=5.0), Scripted(paths), 20, 0).terminal for c in (0, 10, 50, 200)]
    assert all((a >= b - 1e-9).all() for a, b in zip(finals, finals[1:], strict=False))


def test_q09_severe_crash_scenarios():
    p = plan(weights={"AAA": 1.0}, contribution=0.0, cost_bps=0.0, annual_fee=0.0, rebalance=None, horizon_years=1.0)
    flat = np.zeros((2, p.months, 3))
    half = simulate_wealth(p, Scripted(flat), 2, 0, shock=-0.5, shock_month=1)
    assert half.terminal == pytest.approx([5_000.0, 5_000.0]) and half.twr_max_drawdown == pytest.approx([-0.5, -0.5])
    wiped = simulate_wealth(p, Scripted(flat), 2, 0, shock=-1.0)
    assert (wiped.values[:, 1:] == 0).all() and (wiped.values >= 0).all()
    later = simulate_wealth(replace(p, contribution=100.0), Scripted(flat), 2, 0, shock=-0.4, shock_month=6)
    # five deposits of 100 plus 10,000 are hit; the six later deposits are not
    assert later.terminal[0] == pytest.approx((10_000 + 6 * 100) * 0.6 + 6 * 100)
    crash = np.zeros((1, p.months, 3))
    crash[0, 0, 0] = -0.99  # the worst a single month can be
    assert simulate_wealth(p, Scripted(crash), 1, 0).terminal[0] == pytest.approx(100.0)


def test_q10_persistently_negative_markets():
    p = plan(weights={"AAA": 1.0}, cost_bps=0.0, annual_fee=0.0, rebalance="M", horizon_years=3.0)
    down = np.full((4, p.months, 3), -0.02)
    result = simulate_wealth(p, Scripted(down), 4, 0)
    assert (result.terminal < p.total_contributed()).all()
    assert summary(result)["p_below_contributions"] == 1.0
    assert result.twr_max_drawdown == pytest.approx([0.98**p.months - 1] * 4, rel=1e-12)
    assert result.twr_total == pytest.approx([0.98**p.months - 1] * 4, rel=1e-12)


@pytest.mark.parametrize("bad", [
    {"initial_amount": float("nan")}, {"contribution": float("inf")}, {"contribution": -1.0},
    {"weights": {"AAA": 0.8, "BBB": 0.4}}, {"weights": {"AAA": float("nan")}}, {"weights": {"AAA": -0.1}},
    {"frequency": "W"}, {"rebalance": "D"}, {"cost_bps": -1.0}, {"cost_bps": float("nan")},
    {"annual_fee": 0.5}, {"inflation": float("inf")}, {"horizon_years": 0.0}, {"horizon_years": 51.0},
    {"horizon_years": float("nan")}, {"initial_amount": 0.0, "contribution": 0.0}, {"contribution_growth": 2.0},
    {"cash_yield": True},
])  # fmt: skip
def test_q11_invalid_plans_are_refused(bad):
    with pytest.raises(ValueError):
        plan(**bad)


def test_q11b_invalid_simulation_inputs_are_refused(history):
    model = build_model("iid_bootstrap", history)
    for kwargs in ({"shock": 0.1}, {"shock": float("nan")}, {"shock": -1.5}, {"shock": -0.2, "shock_month": 999},
                   {"n_paths": 0}, {"n_paths": 2.5}):  # fmt: skip
        with pytest.raises(ValueError):
            simulate_wealth(plan(), model, **{"n_paths": 10, **kwargs})
    with pytest.raises(ValueError, match="no history"):
        simulate_wealth(plan(weights={"ZZZ": 1.0}), model, 10)
    bad = history.copy()
    bad.iloc[3, 0] = np.nan
    for frame in (bad, history.iloc[:10], history.assign(AAA=-1.0)):
        with pytest.raises(ValueError):
            build_model("block_bootstrap", frame)
    with pytest.raises(ValueError):
        build_model("crystal_ball", history)
    for params in ({"block": 0.5}, {"block": float("nan")}):
        with pytest.raises(ValueError):
            build_model("block_bootstrap", history, **params)
    with pytest.raises(ValueError):
        build_model("ewma_filtered", history, lam=1.0)


def test_q12_fixed_seed_reproducibility_and_common_random_numbers(history):
    model = build_model("ewma_filtered", history)
    a = simulate_wealth(plan(horizon_years=5.0), model, 300, 7)
    b = simulate_wealth(plan(horizon_years=5.0), model, 300, 7)
    c = simulate_wealth(plan(horizon_years=5.0), model, 300, 8)
    assert np.array_equal(a.values, b.values) and not np.array_equal(a.values, c.values)
    # Same seed, different contribution: the SAME markets (identical time-weighted returns).
    p = plan(horizon_years=5.0, rebalance="M", cost_bps=0.0, annual_fee=0.0, cash_yield=0.0)
    low = simulate_wealth(replace(p, contribution=200.0), model, 300, 7)
    high = simulate_wealth(replace(p, contribution=1000.0), model, 300, 7)
    assert np.allclose(low.twr_total, high.twr_total, rtol=1e-12)
    assert (high.terminal > low.terminal).all()


def test_q13_monthly_returns_from_daily_history():
    days = pd.bdate_range("2020-01-01", "2020-06-17")
    close = pd.DataFrame({"AAA": np.linspace(100, 130, len(days)), "BBB": 50.0}, index=days)
    close.iloc[5:10, 1] = np.nan  # a gap in BBB in January
    m = monthly_returns(close)
    assert list(m.index.strftime("%Y-%m")) == ["2020-02", "2020-03", "2020-04", "2020-05"]  # June incomplete
    month_end = close.dropna().groupby(close.dropna().index.to_period("M")).last()
    assert m.loc["2020-03-31", "AAA"] == pytest.approx(month_end["AAA"].iloc[2] / month_end["AAA"].iloc[1] - 1)
    assert (m["BBB"] == 0).all()
    only = monthly_returns(close, ["AAA"])  # unheld instruments do not limit the history
    assert len(only) == 4 and list(only.columns) == ["AAA"]
    assert monthly_returns(close.iloc[:0]).empty


@pytest.mark.parametrize("years", [1 / 12, 1.0, 3.0, 5.0, 10.0, 20.0, 50.0])
def test_q14_extreme_and_standard_horizons(history, years):
    p = plan(horizon_years=years, contribution_growth=0.03)
    result = simulate_wealth(p, build_model("block_bootstrap", history), 200, 1)
    assert result.months == round(12 * years) and np.isfinite(result.values).all()
    assert (result.values >= 0).all()


def test_q14b_resource_guard_refuses_runs_that_would_exhaust_memory():
    with pytest.raises(ValueError, match="stored values"):
        check_size(MAX_STORED_VALUES // 600 + 1, 600, 3)
    with pytest.raises(ValueError, match="too large"):
        check_size(12_000, 600, 50)
    check_size(20_000, 600, 3)  # the dashboard's maximum fits


# ----------------------------------------------------------------- goals and percentiles


def test_q15_goal_probabilities_match_brute_force(history):
    p = plan(horizon_years=10.0, contribution=800.0)
    result = simulate_wealth(p, build_model("block_bootstrap", history), 1500, 2)
    goal = 100_000.0
    g = goal_probabilities(result, goal)
    reach = [any(v >= goal for v in row[1:]) for row in result.values.tolist()]
    hold = [row[-1] >= goal for row in result.values.tolist()]
    assert g["p_reach"] == sum(reach) / len(reach) and g["p_hold"] == sum(hold) / len(hold)
    assert g["p_reach"] >= g["p_hold"] and g["p_reached_then_lost"] == pytest.approx(g["p_reach"] - g["p_hold"])
    firsts = sorted(next((m for m, v in enumerate(row[1:], 1) if v >= goal), math.inf) for row in result.values.tolist())
    median = firsts[(len(firsts) - 1) // 2]
    assert g["median_months_to_goal"] == (None if median == math.inf else median)
    years = list(g["p_reached_by_year"].values())
    assert years == sorted(years) and years[-1] == g["p_reach"]
    assert years[2] == sum(f <= 36 for f in firsts) / len(firsts)
    lo, hi = g["p_reach_interval"]
    assert lo <= g["p_reach"] <= hi


def test_q15b_first_passage_counts_a_goal_touched_then_lost():
    p = plan(weights={"AAA": 1.0}, contribution=0.0, initial_amount=90_000.0, cost_bps=0.0, annual_fee=0.0,
             rebalance=None, horizon_years=0.25)  # fmt: skip
    up_down = np.array([[[0.2, 0, 0], [-0.2, 0, 0], [0.0, 0, 0]]])
    g = goal_probabilities(simulate_wealth(p, Scripted(up_down), 1, 0), 100_000.0)
    assert g["p_reach"] == 1.0 and g["p_hold"] == 0.0 and g["median_months_to_goal"] == 1


def test_q16_percentiles_and_their_intervals():
    rng = np.random.default_rng(0)
    covered = 0
    for _ in range(400):
        x = rng.uniform(size=500)
        lo, hi = quantile_interval(x, 0.05)
        covered += lo <= 0.05 <= hi
    assert 0.92 <= covered / 400 <= 0.99  # distribution-free 95% interval for the 5th percentile
    p = plan(horizon_years=2.0)
    result = simulate_wealth(p, Scripted(random_paths(400, p.months, 3)), 400, 0)
    s = summary(result)
    assert s["median_terminal"] == np.median(result.terminal)
    assert s["p5_terminal"] == np.percentile(result.terminal, 5) and s["p95_terminal"] == np.percentile(result.terminal, 95)
    assert s["p5_terminal_interval"][0] <= s["p5_terminal"] <= s["p5_terminal_interval"][1]


def test_q17_inflation_adjustment():
    p = plan(inflation=0.03, horizon_years=10.0)
    result = simulate_wealth(p, Scripted(random_paths(50, p.months, 1)), 50, 0)
    assert result.terminal_real == pytest.approx(result.terminal / 1.03**10, rel=1e-13)
    assert result.real_values()[:, 6] == pytest.approx(result.values[:, 6] / 1.03**0.5, rel=1e-13)
    none = simulate_wealth(replace(p, inflation=0.0), Scripted(random_paths(50, p.months, 1)), 50, 0)
    assert np.array_equal(none.real_values(), none.values)
    goal = 100_000.0
    real = goal_probabilities(result, goal, real=True)
    assert real["p_hold"] == float((result.terminal / 1.03**10 >= goal).mean())
    assert real["p_hold"] <= goal_probabilities(result, goal)["p_hold"]


def test_q18_deterministic_projection_and_required_contribution():
    p = plan(initial_amount=1_000.0, contribution=500.0, contribution_growth=0.0, horizon_years=10.0)
    r = 1.07 ** (1 / 12) - 1
    annuity_due = 500.0 * ((1 + r) ** 120 - 1) / r * (1 + r)  # textbook closed form
    assert deterministic_value(p, 0.07) == pytest.approx(1_000.0 * 1.07**10 + annuity_due, rel=1e-12)
    assert deterministic_value(replace(p, contribution_growth=0.0), 0.0) == pytest.approx(p.total_contributed())
    need = required_contribution_deterministic(p, 100_000.0, 0.07)
    assert deterministic_value(replace(p, contribution=need), 0.07) == pytest.approx(100_000.0, rel=1e-12)
    assert required_contribution_deterministic(replace(p, initial_amount=200_000.0), 100_000.0, 0.07) == 0.0
    grow = replace(p, contribution_growth=0.05)
    need_g = required_contribution_deterministic(grow, 100_000.0, 0.07)
    assert need_g < need and deterministic_value(replace(grow, contribution=need_g), 0.07) == pytest.approx(100_000.0)


def test_q19_required_contribution_reaches_the_probability_and_no_less_does(history):
    model = build_model("block_bootstrap", history)
    p = plan(horizon_years=10.0, initial_amount=0.0)
    out = required_contribution(p, model, 100_000.0, 0.75, n_paths=600, seed=4, tolerance=1.0)
    assert out["bracketed"] and out["probability"] >= 0.75
    below = goal_probabilities(simulate_wealth(replace(p, contribution=out["contribution"] - 2.0), model, 600, 4), 100_000.0)
    assert below["p_hold"] < 0.75
    probs = [goal_probabilities(simulate_wealth(replace(p, contribution=c), model, 600, 4), 100_000.0)["p_hold"]
             for c in (300, 500, 700, 900)]  # fmt: skip
    assert probs == sorted(probs)  # monotone under common random numbers


def test_q20_deposits_plus_growth_equal_the_ending_value():
    p = plan(horizon_years=5.0)
    result = simulate_wealth(p, Scripted(random_paths(101, p.months, 8)), 101, 0)
    for q in (5, 50, 95):
        d = decomposition(result, q)
        assert d["deposits"] + d["growth"] == pytest.approx(d["ending_value"])
        assert d["initial"] + d["contributions"] == pytest.approx(d["deposits"])


def test_q21_plan_from_an_investment_lab_portfolio():
    spec = PortfolioSpec({"AAA": 0.6, "BBB": 0.3}, 5_000, 250.0, "Q", "Q", "Core")
    p = WealthPlan.from_spec(spec, horizon_years=5.0)
    assert (p.weights, p.initial_amount, p.contribution, p.frequency, p.rebalance) == (
        {"AAA": 0.6, "BBB": 0.3}, 5_000, 250.0, "Q", "Q")
    with pytest.raises(ValueError, match="Weekly"):
        WealthPlan.from_spec(PortfolioSpec({"AAA": 1.0}, 1000, 10.0, "W"))


# ----------------------------------------------------------------- return models


def test_q22_return_models_respect_their_definitions(history):
    iid = build_model("iid_bootstrap", history).sample(300, 12, 1)
    rows = {tuple(r) for r in history.to_numpy().round(12)}
    assert all(tuple(x) in rows for x in iid.reshape(-1, 3).round(12))  # whole historical months
    block = build_model("block_bootstrap", history, block=6.0)
    draws = block.sample(400, 60, 2)
    index = {tuple(r): i for i, r in enumerate(history.to_numpy().round(12))}
    positions = np.vectorize(lambda p, m: index[tuple(draws[p, m].round(12))])(*np.indices(draws.shape[:2]))
    runs = (np.diff(positions, axis=1) % len(history) == 1).mean()
    assert runs == pytest.approx(1 - 1 / 6, abs=0.03)  # continue with probability 1 - 1/block
    gauss = build_model("gaussian_iid", history)
    big = np.log1p(gauss.sample(40_000, 1, 3)[:, 0, :])
    assert big.mean(axis=0) == pytest.approx(np.log1p(history).mean().to_numpy(), abs=0.002)
    assert np.cov(big, rowvar=False) == pytest.approx(np.cov(np.log1p(history), rowvar=False), abs=2e-4)
    ewma = build_model("ewma_filtered", history, lam=0.9)
    values = history.to_numpy().tolist()
    mu = [sum(col) / len(col) for col in zip(*values, strict=False)]
    var = [sum((x - m) ** 2 for x in col) / (len(col) - 1) for col, m in zip(zip(*values, strict=False), mu, strict=False)]
    for t, row in enumerate(values):  # independent re-implementation of the EWMA filter
        for j, x in enumerate(row):
            assert ewma.shocks[t, j] == pytest.approx((x - mu[j]) / math.sqrt(var[j]), rel=1e-10)
            var[j] = 0.9 * var[j] + 0.1 * (x - mu[j]) ** 2
    assert ewma.current_var == pytest.approx(var, rel=1e-10)
    assert (ewma.sample(500, 24, 5) > -1).all()
    for name in ("iid_bootstrap", "block_bootstrap", "ewma_filtered", "gaussian_iid"):
        corr = np.corrcoef(build_model(name, history).sample(4000, 6, 6).reshape(-1, 3), rowvar=False)
        assert corr == pytest.approx(history.corr().to_numpy(), abs=0.06), name  # joint draws keep correlation


def test_q22b_ewma_conditions_on_recent_volatility():
    dates = pd.date_range("2000-01-31", periods=120, freq="ME")
    rng = np.random.default_rng(1)
    calm, wild = rng.normal(0.005, 0.01, 100), rng.normal(0.0, 0.08, 20)
    returns = pd.DataFrame({"AAA": np.concatenate([calm, wild])}, index=dates)
    ewma, iid = build_model("ewma_filtered", returns), build_model("iid_bootstrap", returns)
    assert ewma.sample(5000, 1, 1).std() > 1.5 * iid.sample(5000, 1, 1).std()  # recent storm dominates


# ----------------------------------------------------------------- performance and memory


def test_q23_long_horizon_runtime_and_memory_are_bounded(history):
    p = plan(horizon_years=20.0, weights={"AAA": 0.4, "BBB": 0.3, "CCC": 0.2})
    model = build_model("block_bootstrap", history)
    tracemalloc.start()
    began = time.perf_counter()
    result = simulate_wealth(p, model, 10_000, 1)
    seconds = time.perf_counter() - began
    peak = tracemalloc.get_traced_memory()[1] / 1e6
    tracemalloc.stop()
    assert result.values.shape == (10_000, 241)
    assert seconds < 30 and peak < 200, (seconds, peak)  # measured ~1 s and ~40 MB
