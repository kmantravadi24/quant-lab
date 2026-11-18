"""Goals, milestones, required contributions and plan comparisons.

Two different questions are answered separately:

* ``reach``: the probability that the account is worth at least the goal at ANY
  month end within the horizon (first passage, checked at month ends only).
* ``hold``: the probability that it is worth at least the goal at the END.

``reach >= hold`` always. A goal can be stated in today's money (``real=True``):
then it is compared with values deflated by the plan's inflation rate.

Every probability comes with a 95% Wilson interval. That interval is Monte Carlo
SAMPLING noise only (a finite number of paths); it says nothing about whether the
return model is right. Model uncertainty is shown by re-running under other models
and windows (see ``sensitivity``).
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from quantlab.forecast._stats import binom_ppf
from quantlab.forecast.engine import WealthResult, simulate_wealth
from quantlab.forecast.plan import WealthPlan
from quantlab.forecast.returns import ReturnModel, build_model
from quantlab.simulations.uncertainty import wilson_interval

MILESTONES = (100_000, 250_000, 500_000, 1_000_000)


def quantile_interval(values: np.ndarray, q: float, level: float = 0.95) -> tuple[float, float]:
    """Distribution-free confidence interval for the q-quantile from order statistics.

    The number of draws below the true quantile is Binomial(n, q); the interval runs
    between the order statistics at that binomial's (1 - level)/2 and (1 + level)/2 points.
    """
    x = np.sort(np.asarray(values, dtype=float))
    n = len(x)
    lo = binom_ppf((1 - level) / 2, n, q)
    hi = binom_ppf((1 + level) / 2, n, q) + 1
    return float(x[max(lo - 1, 0)]), float(x[min(hi - 1, n - 1)])


def _series(result: WealthResult, real: bool) -> np.ndarray:
    return result.real_values() if real else result.values


def goal_probabilities(result: WealthResult, goal: float, real: bool = False) -> dict:
    """Reach-by-horizon and hold-at-end probabilities, with first-passage timing."""
    if not (np.isfinite(goal) and goal > 0):
        raise ValueError("goal must be a positive number")
    values = _series(result, real)[:, 1:]  # month ends 1..months
    hit = values >= goal
    reached = hit.any(axis=1)
    held = hit[:, -1]
    n = result.n_paths
    first = np.where(reached, hit.argmax(axis=1) + 1, -1)  # month number of first passage
    p_reach, p_hold = float(reached.mean()), float(held.mean())
    by_year = {}
    for y in range(1, int(np.ceil(result.months / 12)) + 1):
        cutoff = min(12 * y, result.months)
        by_year[y] = float(((first > 0) & (first <= cutoff)).mean())
    times = np.sort(np.where(first > 0, first, np.inf))
    median_month = times[(n - 1) // 2] if n else np.inf
    return {
        "goal": goal,
        "real": real,
        "p_reach": p_reach,
        "p_reach_interval": wilson_interval(p_reach, n),
        "p_hold": p_hold,
        "p_hold_interval": wilson_interval(p_hold, n),
        "p_reached_then_lost": float((reached & ~held).mean()),
        "median_months_to_goal": None if not np.isfinite(median_month) else int(median_month),
        "p_reached_by_year": by_year,
    }


def summary(result: WealthResult, goal: float | None = None, real_goal: bool = False) -> dict:
    """Headline numbers with sampling intervals. All money in nominal terms unless named real."""
    t, tr = result.terminal, result.terminal_real
    total = float(result.contributed[-1])
    n = result.n_paths
    below = float((t < total).mean())
    gains = t - total
    out = {
        "paths": n,
        "months": result.months,
        "total_contributed": total,
        "total_contributed_real": float((result.contributed / result.deflator())[-1]),
        "median_terminal": float(np.median(t)),
        "median_terminal_interval": quantile_interval(t, 0.5),
        "p5_terminal": float(np.percentile(t, 5)),
        "p5_terminal_interval": quantile_interval(t, 0.05),
        "p95_terminal": float(np.percentile(t, 95)),
        "p95_terminal_interval": quantile_interval(t, 0.95),
        "median_terminal_real": float(np.median(tr)),
        "p5_terminal_real": float(np.percentile(tr, 5)),
        "p95_terminal_real": float(np.percentile(tr, 95)),
        "p1_terminal": float(np.percentile(t, 1)),
        "p_below_contributions": below,
        "p_below_contributions_interval": wilson_interval(below, n),
        "median_gain": float(np.median(gains)),
        "p5_gain": float(np.percentile(gains, 5)),
        "median_twr_annual": float(np.median((1 + result.twr_total) ** (12 / result.months) - 1)),
        "median_max_drawdown": float(np.median(result.twr_max_drawdown)),
        "p5_max_drawdown": float(np.percentile(result.twr_max_drawdown, 5)),
        "p_drawdown_worse_than_30pct": float((result.twr_max_drawdown < -0.30).mean()),
        "median_costs": float(np.median(result.total_costs)),
        "median_fees": float(np.median(result.total_fees)),
    }
    if goal is not None:
        out["goal"] = goal_probabilities(result, goal, real_goal)
    return out


def decomposition(result: WealthResult, q: float = 50) -> dict:
    """How much of the q-th percentile ending value is money paid in versus growth."""
    total = float(result.contributed[-1])
    value = float(np.percentile(result.terminal, q))
    return {
        "percentile": q,
        "ending_value": value,
        "deposits": total,
        "growth": value - total,
        "growth_share": (value - total) / value if value > 0 else float("nan"),
        "initial": result.plan.initial_amount,
        "contributions": total - result.plan.initial_amount,
    }


def deterministic_value(plan: WealthPlan, annual_return: float) -> float:
    """Ending value if every month earned exactly the same return (no costs, fees or cash yield).

    Reference arithmetic for 'what the plan does at a stated constant return'. Deposits at the
    start of month m earn (1 + r_m)^(months - m + 1); the initial amount earns (1 + r_m)^months.
    """
    if not np.isfinite(annual_return) or annual_return <= -1:
        raise ValueError("annual_return must be finite and above -100%")
    r = (1 + annual_return) ** (1 / 12) - 1
    n = plan.months
    value = plan.initial_amount * (1 + r) ** n
    for m, d in enumerate(plan.contribution_schedule(), start=1):
        value += d * (1 + r) ** (n - m + 1)
    return float(value)


def required_contribution_deterministic(
    plan: WealthPlan, goal: float, annual_return: float
) -> float:
    """Contribution per period that reaches ``goal`` at a constant ``annual_return``.

    The ending value is linear in the contribution: V = A + C * B, so C = (goal - A) / B.
    Returns 0 when the initial amount alone gets there.
    """
    if not (np.isfinite(goal) and goal > 0):
        raise ValueError("goal must be a positive number")
    r = (1 + annual_return) ** (1 / 12) - 1
    from_initial = plan.initial_amount * (1 + r) ** plan.months
    per_unit = deterministic_value(
        replace(plan, initial_amount=0.0, contribution=1.0), annual_return
    )
    return max(0.0, (goal - from_initial) / per_unit)


def required_contribution(
    plan: WealthPlan,
    model: ReturnModel,
    goal: float,
    probability: float = 0.5,
    n_paths: int = 2000,
    seed: int = 42,
    real: bool = False,
    tolerance: float = 1.0,
) -> dict:
    """Smallest contribution per period with P(ending value >= goal) >= ``probability``.

    Bisection with common random numbers: every trial contribution faces exactly the same
    simulated markets, so the probability is non-decreasing in the contribution and the search
    is well defined. Result is within ``tolerance`` currency units.
    """
    if not 0 < probability < 1:
        raise ValueError("probability must be between 0 and 1")

    def p_hold(amount: float) -> float:
        if plan.initial_amount == 0 and amount == 0:
            return 0.0  # nothing invested: the goal cannot be held
        trial = replace(plan, contribution=amount)
        return goal_probabilities(simulate_wealth(trial, model, n_paths, seed), goal, real)[
            "p_hold"
        ]

    if p_hold(0.0) >= probability:
        return {"contribution": 0.0, "probability": p_hold(0.0), "bracketed": True}
    hi = max(plan.contribution, 100.0)
    for _ in range(40):
        if p_hold(hi) >= probability:
            break
        hi *= 2
    else:
        return {"contribution": None, "probability": None, "bracketed": False}
    lo = 0.0
    while hi - lo > tolerance:
        mid = (lo + hi) / 2
        if p_hold(mid) >= probability:
            hi = mid
        else:
            lo = mid
    return {"contribution": hi, "probability": p_hold(hi), "bracketed": True}


def compare_plans(
    plans: dict[str, WealthPlan],
    model: ReturnModel,
    n_paths: int = 2000,
    seed: int = 42,
    goal: float | None = None,
    real_goal: bool = False,
) -> dict:
    """Run several plans against the SAME simulated markets (common random numbers).

    Differences between rows are then caused by the decisions in the plans, not by luck.
    """
    out = {}
    for name, plan in plans.items():
        result = simulate_wealth(plan, model, n_paths, seed)
        out[name] = {"plan": plan, "result": result, "summary": summary(result, goal, real_goal)}
    return out


def sensitivity(
    plan: WealthPlan,
    returns,
    models: dict[str, dict],
    lookbacks: dict[str, int],
    n_paths: int = 1000,
    seed: int = 42,
    goal: float | None = None,
) -> list[dict]:
    """Model and history-window sensitivity: the same plan under every (model, lookback) pair.

    ``returns`` are monthly returns of the plan's instruments; ``models`` maps a model name to
    its parameters; ``lookbacks`` maps a label to a number of most recent months.
    """
    rows = []
    for label, n_months in lookbacks.items():
        window = returns.iloc[-n_months:]
        for name, params in models.items():
            model = build_model(name, window, **params)
            s = summary(simulate_wealth(plan, model, n_paths, seed), goal)
            rows.append(
                {
                    "lookback": label,
                    "window_start": model.window[0],
                    "window_end": model.window[1],
                    "window_months": model.window[2],
                    "model": name,
                    **{k: v for k, v in s.items() if not isinstance(v, (tuple, dict))},
                    **(
                        {"p_reach_goal": s["goal"]["p_reach"], "p_hold_goal": s["goal"]["p_hold"]}
                        if goal
                        else {}
                    ),
                }
            )
    return rows
