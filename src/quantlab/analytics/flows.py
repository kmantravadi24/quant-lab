"""Performance of a portfolio that receives external contributions.

Two different questions, two different numbers:

Time-weighted return (TWR)
    How did the portfolio's holdings perform, independent of when money was
    added? The engine values the portfolio at each flow boundary and links the
    sub-period returns geometrically, so ``BacktestResult.returns`` is already
    flow-neutral; TWR is their compounded product. This is the figure to use
    when comparing allocations.

Money-weighted return (MWR)
    What annual rate did the investor's money actually earn, given when each
    contribution was made? It is the internal rate of return of the dated
    external cash flows and the final value. It depends on contribution timing
    as well as on the allocation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quantlab import TRADING_DAYS_PER_YEAR as TDY
from quantlab.analytics.metrics import cagr, total_return
from quantlab.backtesting.engine import BacktestResult

DAYS_PER_YEAR = 365.0  # actual/365 fixed day count on calendar dates
RATE_FLOOR = -0.999999  # a rate of -100% or less has no meaning for a long-only portfolio


@dataclass(frozen=True)
class IrrResult:
    rate: float  # effective annual rate; NaN unless status == "ok"
    status: str  # ok | too_few_flows | zero_span | no_sign_change | not_unique | no_root
    span_days: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def investor_cash_flows(result: BacktestResult) -> pd.Series:
    """Dated external cash flows from the investor's side.

    Sign convention: money the investor pays in is negative; the final
    liquidation value (equity at the last close, no selling costs) is positive.
    The initial amount is dated at the first session and each contribution at
    its own session. Flows on the same date are netted.
    """
    flows = -result.cash_flows[result.cash_flows != 0].astype(float)
    start = pd.Series({result.equity.index[0]: -float(result.config.initial_capital)})
    end = pd.Series({result.equity.index[-1]: float(result.equity.iloc[-1])})
    return pd.concat([start, flows, end]).groupby(level=0).sum().sort_index()


def net_present_value(rate: float, amounts: np.ndarray, years: np.ndarray) -> float:
    return float(np.sum(amounts / (1.0 + rate) ** years))


def money_weighted_return(flows: pd.Series, tolerance: float = 1e-12) -> IrrResult:
    """Effective annual internal rate of return of dated cash flows (XIRR).

    Solves sum_i CF_i / (1 + r)^(t_i) = 0 with t_i = days since the first flow
    / 365, by bisection on r between -99.9999% and 1e12, stopping when the
    bracket is narrower than ``tolerance`` relative to max(1, |r|).

    The rate is always annual. Over a span much shorter than a year it is an
    extrapolation and can be enormous; ``flow_summary`` therefore also reports
    the un-annualised return over the actual span.

    A rate is reported only when it exists and is unique: the dated flows must
    change sign exactly once (contributions followed by a final value always
    do). Otherwise ``rate`` is NaN and ``status`` says why:

    too_few_flows   fewer than two dated amounts
    zero_span       every flow falls on one date, so no rate is defined
    no_sign_change  all flows have the same sign (for example a final value of 0)
    not_unique      more than one sign change: several rates may solve the equation
    no_root         no solution inside the search bracket
    """
    flows = pd.Series(flows, dtype=float).dropna()
    flows = flows.groupby(level=0).sum().sort_index()
    flows = flows[flows != 0]
    if len(flows) < 2:
        return IrrResult(np.nan, "too_few_flows")
    days = np.array([(d - flows.index[0]).days for d in flows.index], dtype=float)
    span = int(days[-1])
    if span == 0:
        return IrrResult(np.nan, "zero_span")
    signs = np.sign(flows.to_numpy())
    changes = int(np.sum(signs[1:] != signs[:-1]))
    if changes == 0:
        return IrrResult(np.nan, "no_sign_change", span)
    if changes > 1:
        return IrrResult(np.nan, "not_unique", span)
    amounts, years = flows.to_numpy(), days / DAYS_PER_YEAR
    low, high = RATE_FLOOR, 1.0
    f_low = net_present_value(low, amounts, years)
    f_high = net_present_value(high, amounts, years)
    while np.sign(f_low) == np.sign(f_high) and high < 1e12:
        high *= 4.0
        f_high = net_present_value(high, amounts, years)
    if np.sign(f_low) == np.sign(f_high):
        return IrrResult(np.nan, "no_root", span)
    for _ in range(400):
        mid = 0.5 * (low + high)
        f_mid = net_present_value(mid, amounts, years)
        if f_mid == 0 or high - low <= tolerance * max(1.0, abs(mid)):
            break
        if np.sign(f_mid) == np.sign(f_low):
            low, f_low = mid, f_mid
        else:
            high = mid
    return IrrResult(float(0.5 * (low + high)), "ok", span)


def flow_summary(result: BacktestResult, periods: int = TDY) -> dict:
    """Headline figures for a funded portfolio. Amounts are in the portfolio's currency."""
    initial = float(result.config.initial_capital)
    contributed = float(result.cash_flows.sum())
    final = float(result.equity.iloc[-1])
    irr = money_weighted_return(investor_cash_flows(result))
    return {
        "initial_amount": initial,
        "contributions": contributed,
        "total_invested": initial + contributed,
        "final_value": final,
        "gain": final - initial - contributed,
        "time_weighted_total": total_return(result.returns),
        "time_weighted_annual": cagr(result.returns, periods),
        "money_weighted_annual": irr.rate,
        # Same rate expressed over the actual span, not extrapolated to a year.
        "money_weighted_period": (1.0 + irr.rate) ** (irr.span_days / DAYS_PER_YEAR) - 1.0,
        "money_weighted_status": irr.status,
        "span_days": irr.span_days,
    }
