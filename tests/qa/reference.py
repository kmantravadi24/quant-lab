"""Independent reference implementations for the QA suite.

Plain Python (loops, ``math``, ``statistics``), deliberately sharing no code
with quantlab, so an agreement between the two is evidence and not a tautology.
"""

from __future__ import annotations

import math
import statistics
from fractions import Fraction


def compound(returns: list[float]) -> float:
    wealth = 1.0
    for r in returns:
        wealth *= 1.0 + r
    return wealth - 1.0


def annualised_vol(returns: list[float], periods: int = 252) -> float:
    return statistics.stdev(returns) * math.sqrt(periods)


def cagr(returns: list[float], periods: int = 252) -> float:
    return (1.0 + compound(returns)) ** (periods / len(returns)) - 1.0


def sharpe(returns: list[float], rf: float = 0.0, periods: int = 252) -> float:
    excess = [r - rf / periods for r in returns]
    return statistics.mean(excess) / statistics.stdev(excess) * math.sqrt(periods)


def covariance(xs: list[float], ys: list[float]) -> float:
    mx, my = statistics.mean(xs), statistics.mean(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / (len(xs) - 1)


def cov_matrix(columns: list[list[float]], periods: int = 252) -> list[list[float]]:
    return [[covariance(a, b) * periods for b in columns] for a in columns]


def portfolio_vol(weights: list[float], cov: list[list[float]]) -> float:
    n = len(weights)
    return math.sqrt(sum(weights[i] * cov[i][j] * weights[j] for i in range(n) for j in range(n)))


def risk_contributions(weights: list[float], cov: list[list[float]]) -> list[float]:
    sigma = portfolio_vol(weights, cov)
    n = len(weights)
    return [weights[i] * sum(cov[i][j] * weights[j] for j in range(n)) / sigma for i in range(n)]


def quantile(values: list[float], q: float) -> float:
    """Linear-interpolation quantile (the 'type 7' definition)."""
    ordered = sorted(values)
    position = q * (len(ordered) - 1)
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (position - low) * (ordered[high] - ordered[low])


def var_es(returns: list[float], confidence: float = 0.95) -> tuple[float, float]:
    # The tail probability is taken as an exact decimal (Fraction of the decimal string),
    # independently of how the library rounds it.
    p = float(1 - Fraction(str(confidence)))
    cut = quantile(returns, p)
    tail = [r for r in returns if r <= cut]
    return -cut, -sum(tail) / len(tail)


def max_drawdown(returns: list[float]) -> tuple[float, int]:
    """(deepest fall from the running peak, longest run of sessions below a peak)."""
    wealth, peak, worst, run, longest = 1.0, 1.0, 0.0, 0, 0
    for r in returns:
        wealth *= 1.0 + r
        peak = max(peak, wealth)
        fall = wealth / peak - 1.0
        worst = min(worst, fall)
        run = run + 1 if fall < 0 else 0
        longest = max(longest, run)
    return worst, longest


def xirr(flows: list[tuple[int, float]]) -> float:
    """Annual rate solving sum CF / (1+r)^(days/365) = 0, by bisection in log space."""

    def npv(rate: float) -> float:
        return sum(cf / (1.0 + rate) ** (days / 365.0) for days, cf in flows)

    low, high = -0.999999, 1e12
    for _ in range(600):
        mid = (low + high) / 2.0
        if (npv(mid) > 0) == (npv(low) > 0):
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def unitised_returns(equity, before_flow, flows, initial: float) -> list[float]:
    """Time-weighted daily returns from a unit-price fund that issues units at each deposit."""
    units, previous, out = initial, 1.0, []
    for value, pre, deposit in zip(equity, before_flow, flows, strict=True):
        if deposit:
            units += deposit / (pre / units)
        price = value / units
        out.append(price / previous - 1.0)
        previous = price
    return out


def replay_cash(initial: float, deposits: dict, trades: list[dict]) -> list[tuple[float, float]]:
    """Recompute cash after every fill from first principles.

    Returns (expected cash after, recorded cash after) per fill. A deposit dated
    d is added before any fill dated d or later.
    """
    cash, pending, out = initial, sorted(deposits.items()), []
    for trade in trades:
        while pending and pending[0][0] <= trade["date"]:
            cash += pending.pop(0)[1]
        gross = trade["shares"] * trade["fill_price"]
        cash += -(gross + trade["fee"]) if trade["side"] == "BUY" else gross - trade["fee"]
        out.append((cash, trade["cash_after"]))
    return out


def reference_wealth(plan: dict, path: list[list[float]], tickers: list[str],
                     shock: float | None = None, shock_month: int = 1) -> dict:  # fmt: skip
    """Plain-Python monthly ledger for ONE path, written independently of the engine.

    Event order per month: deposit, trade (rebalance solved by bisection / buy-only
    deployment), optional shock, market and cash interest, fee, valuation.
    """
    step = {"M": 1, "Q": 3, "A": 12}
    w = [float(plan["weights"].get(t, 0.0)) for t in tickers]
    invested = sum(w)
    c = plan["cost_bps"] / 10_000
    cash_rate = (1 + plan["cash_yield"]) ** (1 / 12) - 1
    keep = (1 - plan["annual_fee"]) ** (1 / 12)
    cash, hold = float(plan["initial_amount"]), [0.0] * len(tickers)
    values, deposits_total, costs, fees = [cash], cash, 0.0, 0.0
    for m in range(1, len(path) + 1):
        deposit = 0.0
        if (m - 1) % step[plan["frequency"]] == 0:
            deposit = plan["contribution"] * (1 + plan["contribution_growth"]) ** ((m - 1) // 12)
        cash += deposit
        deposits_total += deposit
        rebalance = plan["rebalance"] is not None and (m - 1) % step[plan["rebalance"]] == 0
        if rebalance:
            total = cash + sum(hold)
            lo, hi = 0.0, total
            for _ in range(200):  # f(x) = x + c * sum|w_i x - h_i| - total is increasing in x
                mid = (lo + hi) / 2
                if mid + c * sum(abs(wi * mid - hi_) for wi, hi_ in zip(w, hold, strict=False)) > total:
                    hi = mid
                else:
                    lo = mid
            after = (lo + hi) / 2
            costs += total - after
            hold = [wi * after for wi in w]
            cash = after - sum(hold)
        elif invested > 0:
            total = cash + sum(hold)
            spare = max(cash - (1 - invested) * total, 0.0)
            bought = spare / (1 + c)
            hold = [h + bought * wi / invested for h, wi in zip(hold, w, strict=False)]
            cash -= spare
            costs += spare - bought
        if shock is not None and m == shock_month:
            hold = [h * (1 + shock) for h in hold]
        hold = [h * (1 + r) for h, r in zip(hold, path[m - 1], strict=False)]
        cash *= 1 + cash_rate
        fees += sum(hold) * (1 - keep)
        hold = [h * keep for h in hold]
        values.append(cash + sum(hold))
    return {"values": values, "deposits": deposits_total, "costs": costs, "fees": fees}
