"""Round-2 audit: regression tests for confirmed defects, plus independent cross-checks.

The cross-checks deliberately avoid quantlab's own code paths: plain Python
loops, the standard library, and SciPy.
"""

import math

import numpy as np
import pandas as pd
import pytest
from fixtures.synthetic import make_data
from scipy import stats

from quantlab.analytics import metrics as m
from quantlab.backtesting import backtest_strategy, run_backtest
from quantlab.data import CachedProvider, SyntheticProvider
from quantlab.execution import ExecutionConfig, Order, size_orders
from quantlab.portfolio import ConstraintViolation, Portfolio
from quantlab.simulations import simulate
from quantlab.strategies import (
    BuyAndHold,
    CrossSectionalMomentum,
    MeanReversion,
    TrendFollowing,
)

# ------------------------------------------------------------------ defect 1
# Fixed fees larger than a sale's proceeds drove cash negative; the resulting
# negative equity then produced negative targets and a ConstraintViolation crash.


def test_sale_smaller_than_its_fixed_fee_is_skipped_and_logged():
    data = make_data({"A": [10.0] * 5})
    cfg = ExecutionConfig(initial_capital=100.0, slippage_bps=0, fee_bps=0, fixed_fee=30.0)
    w = pd.DataFrame({"A": [0.5, 0.0]}, index=data.dates[[0, 2]])
    res = run_backtest(data, w, cfg)
    # Day 1: buy. 50 of stock would need 50 + 30 fee = 80 <= 100, so it fills: cash 20.
    assert res.cash.iloc[1] == pytest.approx(20.0)
    # Day 3: selling 5 shares raises 50 - 30 = 20 > 0, so it fills: cash 40.
    assert res.cash.iloc[3] == pytest.approx(40.0)
    # Now a position worth less than the fee: it must be left alone, not sold at a loss of cash.
    cfg = ExecutionConfig(initial_capital=100.0, slippage_bps=0, fee_bps=0, fixed_fee=60.0)
    w = pd.DataFrame({"A": [0.3, 0.0]}, index=data.dates[[0, 2]])
    res = run_backtest(data, w, cfg)
    assert res.holdings["A"].iloc[-1] == pytest.approx(3.0)  # 30 of stock, still held
    assert res.cash.min() >= 0
    assert list(res.unfilled["reason"]) == ["sale proceeds below fixed fee; order dropped"]


def test_ledger_refuses_a_sale_whose_fee_overdraws_cash():
    pf = Portfolio(cash=1.0, shares={"A": 1.0})
    cfg = ExecutionConfig(slippage_bps=0, fee_bps=0, fixed_fee=50.0)
    with pytest.raises(ConstraintViolation):
        pf.execute(Order("A", "SELL", 1.0, 10.0), cfg)


def test_sizing_never_sells_more_than_held_or_targets_negative_shares():
    cfg = ExecutionConfig(slippage_bps=0, fee_bps=0)
    orders, _ = size_orders({"A": 0.5}, {"A": 2.0}, {"A": 10.0}, -100.0, -120.0, cfg)
    assert [(o.side, o.shares) for o in orders] == [("SELL", 2.0)]


@pytest.mark.parametrize("seed", range(40))
def test_randomized_accounting_invariants_with_gaps_and_fixed_fees(seed):
    rng = np.random.default_rng(seed)
    n = 60
    close, open_ = {}, {}
    for t in "ABC":
        c = 50 * np.exp(np.cumsum(rng.normal(0, 0.03, n)))
        o = c * np.exp(rng.normal(0, 0.01, n))
        gone = rng.random(n) < 0.08
        close[t] = np.where(gone, np.nan, c).tolist()
        open_[t] = np.where(gone | (rng.random(n) < 0.03), np.nan, o).tolist()
    close["A"][0] = open_["A"][0] = 50.0
    data = make_data(close, open_)
    rows = sorted(rng.choice(n, size=12, replace=False))
    w = rng.dirichlet(np.ones(4), size=12)[:, :3]
    w[rng.random(w.shape) < 0.3] = 0
    weights = pd.DataFrame(w, index=data.dates[rows], columns=list("ABC"))
    cfg = ExecutionConfig(
        initial_capital=float(rng.choice([500, 1e5])),
        slippage_bps=float(rng.choice([0, 5, 50])),
        fee_bps=float(rng.choice([0, 2, 30])),
        fixed_fee=float(rng.choice([0, 1, 25])),
        fractional_shares=bool(rng.integers(2)),
    )
    res = run_backtest(data, weights, cfg)  # must not raise
    marked = (res.holdings * data.close.ffill()).sum(axis=1)
    np.testing.assert_allclose(res.equity, res.cash + marked, rtol=1e-10, atol=1e-8)
    assert res.cash.min() >= -1e-9
    assert (res.holdings.to_numpy() >= 0).all()
    assert (res.trades["date"] > res.trades["decision_date"]).all()
    for _, tr in res.trades.iterrows():  # never a fill on a date without an open
        assert not np.isnan(data.open.loc[tr["date"], tr["ticker"]])


# ------------------------------------------------------------------ defect 2
# Rolling windows over the union calendar: one missing close blanked the
# indicator for a full window and forced the strategy into cash.


def test_single_missing_close_does_not_knock_out_the_signal():
    full = np.linspace(100, 200, 300).tolist()
    gap = list(full)
    gap[250] = np.nan
    a, b = make_data({"A": full}), make_data({"A": gap})
    trend = TrendFollowing(20, 50)
    assert trend.generate(a).signals["A"].equals(trend.generate(b).signals["A"])
    assert len(trend.generate(b).weights) == 1  # one entry, no spurious exit and re-entry
    z = MeanReversion(20, 1.0, 0.0).generate(b).diagnostics["zscore"]["A"]
    assert z.iloc[60:].notna().all()
    score = CrossSectionalMomentum(20, top_n=1).generate(b).diagnostics["score"]["A"]
    assert score.iloc[60:].notna().all()


def test_signal_expires_after_a_long_gap():
    prices = np.linspace(100, 200, 120).tolist() + [np.nan] * 30  # asset stops trading
    sig = TrendFollowing(20, 50).generate(make_data({"A": prices, "B": [10.0] * 150})).signals["A"]
    assert sig.iloc[119] == 1 and sig.iloc[124] == 1  # carried for 5 sessions
    assert (sig.iloc[125:] == 0).all()  # then no signal


# ------------------------------------------------------------------ defect 3


def test_cache_returns_columns_in_requested_order(tmp_path):
    cached = CachedProvider(SyntheticProvider(1), tmp_path, max_age_hours=1)
    cached.fetch(["B", "A"], "2024-01-01", "2024-02-01")
    assert cached.fetch(["A", "B"], "2024-01-01", "2024-02-01").tickers == ["A", "B"]
    assert cached.fetch(["B", "A"], "2024-01-01", "2024-02-01").tickers == ["B", "A"]


# ------------------------------------------------------------------ independent checks


def reference_trend_backtest(open_, close, fast, slow, capital, slip, fee):
    """All-in / all-out SMA crossover written with plain loops, sharing no code with the engine."""
    n = len(close)
    signal = []
    for i in range(n):
        if i < slow - 1:
            signal.append(0)
        else:
            f = sum(close[i - fast + 1 : i + 1]) / fast
            s = sum(close[i - slow + 1 : i + 1]) / slow
            signal.append(1 if f > s else 0)
    cash, shares, equity = capital, 0.0, []
    for i in range(n):
        if i > 0 and signal[i - 1] != (1 if shares > 0 else 0):
            if signal[i - 1] == 1:
                shares, cash = cash / (open_[i] * (1 + slip) * (1 + fee)), 0.0
            else:
                cash, shares = shares * open_[i] * (1 - slip) * (1 - fee), 0.0
        equity.append(cash + shares * close[i])
    return equity


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_engine_matches_independent_reference_backtest(seed):
    data = SyntheticProvider(seed, annual_vol=0.25).fetch(["X"], "2015-01-01", "2020-12-31")
    cfg = ExecutionConfig(initial_capital=50_000, slippage_bps=7, fee_bps=3)
    res = backtest_strategy(TrendFollowing(15, 40), data, cfg)
    ref = reference_trend_backtest(
        data.open["X"].tolist(), data.close["X"].tolist(), 15, 40, 50_000, 7e-4, 3e-4
    )
    assert len(res.trades) >= 10
    np.testing.assert_allclose(res.equity.to_numpy(), ref, rtol=1e-9)


def test_buy_and_hold_cagr_is_the_price_ratio_annualized():
    data = SyntheticProvider(5).fetch(["X"], "2016-01-01", "2020-12-31")
    res = backtest_strategy(BuyAndHold({"X": 1.0}), data, ExecutionConfig(100_000, 0, 0))
    o, c = data.open["X"], data.close["X"]
    assert res.equity.iloc[-1] == pytest.approx(100_000 * c.iloc[-1] / o.iloc[1])
    held = res.returns.iloc[2:]  # sessions after the purchase day
    expected = (c.iloc[-1] / c.iloc[1]) ** (252 / len(held)) - 1
    assert m.cagr(held) == pytest.approx(expected)
    assert m.cagr(pd.Series([0.0004] * 300)) == pytest.approx(1.0004**252 - 1)


def test_ratios_against_plain_python_and_scipy():
    r = pd.Series(np.random.default_rng(3).standard_t(4, 750) * 0.01 + 0.0004)
    rf, n = 0.03, len(r)
    ex = [x - rf / 252 for x in r]
    mean = sum(ex) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in ex) / (n - 1))
    downside = math.sqrt(sum(min(x, 0.0) ** 2 for x in ex) / n)
    assert m.sharpe(r, rf) == pytest.approx(mean / sd * math.sqrt(252))
    assert m.sortino(r, rf) == pytest.approx(mean * 252 / (downside * math.sqrt(252)))
    assert m.volatility(r) == pytest.approx(stats.tstd(r) * math.sqrt(252))

    b = pd.Series(np.random.default_rng(4).normal(0.0003, 0.01, n))
    y = 0.7 * b + r * 0.3
    fit = stats.linregress(b, y)  # OLS: slope is beta, intercept is per-period alpha at rf = 0
    assert m.beta(y, b) == pytest.approx(fit.slope)
    assert m.alpha(y, b) == pytest.approx(fit.intercept * 252)


def test_drawdown_var_and_es_against_brute_force():
    r = pd.Series(np.random.default_rng(6).normal(0.0002, 0.012, 600))
    wealth = np.cumprod(1 + r.to_numpy())
    worst = min(wealth[j] / max(1.0, wealth[: j + 1].max()) - 1 for j in range(len(wealth)))
    assert m.max_drawdown(r) == pytest.approx(worst)
    for conf in (0.95, 0.99):
        q = stats.scoreatpercentile(r, 100 * (1 - conf))  # linear interpolation
        assert m.historical_var(r, conf) == pytest.approx(-q)
        tail = [x for x in r if x <= q]
        assert m.historical_es(r, conf) == pytest.approx(-sum(tail) / len(tail))
        assert m.historical_es(r, conf) >= m.historical_var(r, conf)


def test_portfolio_return_is_the_weighted_sum_of_asset_returns():
    data = SyntheticProvider(9).fetch(["A", "B"], "2020-01-01", "2020-12-31")
    res = backtest_strategy(BuyAndHold({"A": 0.6, "B": 0.4}), data, ExecutionConfig(1e5, 0, 0))
    asset_r = data.close / data.close.shift(1) - 1
    prior_w = res.weights.shift(1)
    implied = (prior_w * asset_r).sum(axis=1).iloc[2:]  # sessions after the purchase day
    pd.testing.assert_series_equal(res.returns.iloc[2:], implied, check_names=False, rtol=1e-9)


def test_monte_carlo_same_seed_same_statistics_across_methods():
    r = pd.Series(np.random.default_rng(1).normal(0.0004, 0.01, 800))
    for method in ("iid", "block", "stationary"):
        a = simulate(r, 120, 300, method=method, block=10, seed=77)
        b = simulate(r, 120, 300, method=method, block=10, seed=77)
        assert a.summary() == b.summary()
        np.testing.assert_array_equal(a.paths, b.paths)


# ------------------------------------------------------------------ research integrity


def test_development_grid_cannot_see_the_out_of_sample_period():
    """Rewriting every price after the split date must leave the development grid unchanged."""
    from fixtures.synthetic import perturb_after

    from quantlab.research import chronological_split, parameter_grid

    data = SyntheticProvider(2).fetch(["X"], "2014-01-01", "2020-12-31")
    split = chronological_split(data.dates, "2018-06-29")
    grid = {"fast": [10, 20], "slow": [50, 100]}

    def run(d):
        return parameter_grid(lambda fast, slow: TrendFollowing(fast, slow), grid, d,
                              ExecutionConfig(), *split.development)  # fmt: skip

    pd.testing.assert_frame_equal(run(data), run(perturb_after(data, split.development[1])))
