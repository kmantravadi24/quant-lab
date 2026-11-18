"""Account-level simulation of future wealth on simulated monthly returns.

This is a monthly ledger, run for many paths at once. It is NOT a fixed-weight
approximation: holdings drift with their own returns between rebalances, money
arrives on a schedule, trades pay costs and fees are charged.

Event order inside month m (m = 1 .. months), identical on every path:

1. Deposit: the month's contribution arrives in cash (the initial amount is in
   cash at time 0, before month 1).
2. Trading, at the start of the month, at the prices of that moment:
   * a rebalance month (and month 1 when rebalancing is on) trades the whole
     account back to target weights. The cost is ``cost_bps`` of every unit bought
     or sold and is solved exactly: V_after = V_before - c * sum_i |w_i V_after - h_i|;
   * any other month only invests spare cash above the cash target in the target
     mix (buys only, nothing sold): the cost is c per unit bought.
3. Optional scenario shock (stress tests only): every risky holding falls by
   ``shock`` at once.
4. Market: each holding grows by its simulated monthly return; cash earns
   ``cash_yield`` (monthly rate (1 + y)^(1/12) - 1).
5. Fees: ``annual_fee`` is charged on risky holdings at the monthly rate
   1 - (1 - f)^(1/12).
6. Valuation: V_m = cash + sum of holdings, recorded at the month's end.

Ledger identity checked on every path and month (``ledger=True``):
    V_m = deposits_to_date - costs - fees + market_gain + interest.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from quantlab.forecast.plan import WealthPlan
from quantlab.forecast.returns import ReturnModel

MAX_STORED_VALUES = 15_000_000  # paths x (months + 1) kept in memory (~120 MB of float64)
MAX_WORK = 300_000_000  # paths x months x instruments; bounds run time (a few seconds)


def check_size(n_paths: int, months: int, assets: int) -> None:
    if not isinstance(n_paths, (int, np.integer)) or n_paths < 1:
        raise ValueError("n_paths must be a positive integer")
    if n_paths * (months + 1) > MAX_STORED_VALUES:
        raise ValueError(
            f"{n_paths:,} paths over {months:,} months is more than the limit of "
            f"{MAX_STORED_VALUES:,} stored values: use fewer paths or a shorter horizon"
        )
    if n_paths * months * max(assets, 1) > MAX_WORK:
        raise ValueError("The simulation is too large; use fewer paths, instruments or months")


@dataclass
class Ledger:
    """Cumulative amounts per path at each month end, shape (paths, months + 1)."""

    deposits: np.ndarray
    costs: np.ndarray
    fees: np.ndarray
    market: np.ndarray
    interest: np.ndarray
    cash: np.ndarray
    holdings: np.ndarray  # (paths, months + 1, assets)


@dataclass
class WealthResult:
    plan: WealthPlan
    model: dict
    seed: int
    values: np.ndarray  # nominal account value, (paths, months + 1); column 0 = time 0
    contributed: np.ndarray  # cumulative deposits, (months + 1,): identical for every path
    twr_max_drawdown: np.ndarray  # worst fall of the time-weighted index, per path (<= 0)
    twr_total: np.ndarray  # time-weighted return over the horizon, per path
    total_costs: np.ndarray
    total_fees: np.ndarray
    shock: dict | None = None
    ledger: Ledger | None = field(default=None, repr=False)

    @property
    def months(self) -> int:
        return self.values.shape[1] - 1

    @property
    def n_paths(self) -> int:
        return self.values.shape[0]

    def deflator(self) -> np.ndarray:
        """Price level relative to today at each month end: (1 + inflation)^(m / 12)."""
        return (1 + self.plan.inflation) ** (np.arange(self.months + 1) / 12)

    def real_values(self) -> np.ndarray:
        return self.values / self.deflator()

    @property
    def terminal(self) -> np.ndarray:
        return self.values[:, -1]

    @property
    def terminal_real(self) -> np.ndarray:
        return self.values[:, -1] / self.deflator()[-1]

    def percentile_bands(self, percentiles=(5, 25, 50, 75, 95), real: bool = False) -> np.ndarray:
        data = self.real_values() if real else self.values
        return np.percentile(data, percentiles, axis=0)


def _rebalance(hold: np.ndarray, cash: np.ndarray, w: np.ndarray, c: float):
    """Trade every path to target weights; returns new holdings, cash and the cost paid."""
    total = cash + hold.sum(axis=1)
    after = total.copy()
    if c > 0:
        for _ in range(60):  # contraction with factor <= c * sum(w) < 1
            new = total - c * np.abs(after[:, None] * w - hold).sum(axis=1)
            if np.max(np.abs(new - after)) <= 1e-12 * max(1.0, float(np.max(total))):
                after = new
                break
            after = new
    new_hold = after[:, None] * w
    new_cash = after - new_hold.sum(axis=1)
    return new_hold, new_cash, total - after


def _deploy(hold: np.ndarray, cash: np.ndarray, w: np.ndarray, c: float):
    """Invest spare cash above the cash target in the target mix (buys only)."""
    invested_share = w.sum()
    if invested_share <= 0:
        return hold, cash, np.zeros_like(cash)
    total = cash + hold.sum(axis=1)
    reserve = (1.0 - invested_share) * total
    spare = np.maximum(cash - reserve, 0.0)
    bought = spare / (1.0 + c)
    return hold + bought[:, None] * (w / invested_share), cash - spare, spare - bought


def simulate_wealth(
    plan: WealthPlan,
    model: ReturnModel,
    n_paths: int = 2000,
    seed: int = 42,
    shock: float | None = None,
    shock_month: int = 1,
    ledger: bool = False,
) -> WealthResult:
    """Simulate ``n_paths`` futures of the account. Same inputs and seed, same output."""
    missing = [t for t in plan.tickers if t not in model.tickers]
    if missing:
        raise ValueError(f"The return model has no history for {missing}")
    if shock is not None and not (np.isfinite(shock) and -1.0 <= shock <= 0.0):
        raise ValueError("shock must be between -100% and 0%")
    months = plan.months
    if not 1 <= shock_month <= months:
        raise ValueError("shock_month must fall inside the horizon")
    n_assets = len(model.tickers)
    check_size(n_paths, months, n_assets)
    w = np.array([float(plan.weights.get(t, 0.0)) for t in model.tickers])
    c = plan.cost_bps / 10_000
    cash_rate = (1 + plan.cash_yield) ** (1 / 12) - 1
    fee_rate = 1 - (1 - plan.annual_fee) ** (1 / 12)
    deposits = plan.contribution_schedule()

    rng = np.random.default_rng(seed)
    model.start(n_paths, rng)
    hold = np.zeros((n_paths, n_assets))
    cash = np.full(n_paths, float(plan.initial_amount))
    values = np.empty((n_paths, months + 1))
    values[:, 0] = plan.initial_amount
    contributed = np.empty(months + 1)
    contributed[0] = plan.initial_amount
    cum = {k: np.zeros(n_paths) for k in ("costs", "fees", "market", "interest")}
    if ledger:
        book = {
            k: np.zeros((n_paths, months + 1))
            for k in ("deposits", "costs", "fees", "market", "interest", "cash")
        }
        book["deposits"][:, 0] = plan.initial_amount
        book["cash"][:, 0] = cash
        book_hold = np.zeros((n_paths, months + 1, n_assets))
    index = np.ones(n_paths)
    peak = np.ones(n_paths)
    worst = np.zeros(n_paths)
    for m in range(1, months + 1):
        start_value = values[:, m - 1]
        cash = cash + deposits[m - 1]  # 1. deposit
        contributed[m] = contributed[m - 1] + deposits[m - 1]
        if plan.rebalance_month(m):  # 2. trading
            hold, cash, cost = _rebalance(hold, cash, w, c)
        else:
            hold, cash, cost = _deploy(hold, cash, w, c)
        cum["costs"] += cost
        returns = model.draw(rng)  # always drawn, so every plan sees the same market
        if shock is not None and m == shock_month:  # 3. scenario shock
            loss = hold * shock
            hold = hold + loss
            cum["market"] += loss.sum(axis=1)
        gain = hold * returns  # 4. market
        hold = hold + gain
        cum["market"] += gain.sum(axis=1)
        interest = cash * cash_rate
        cash = cash + interest
        cum["interest"] += interest
        fee = hold * fee_rate  # 5. fees
        hold = hold - fee
        cum["fees"] += fee.sum(axis=1)
        values[:, m] = cash + hold.sum(axis=1)  # 6. valuation
        base = start_value + deposits[m - 1]
        step = np.divide(values[:, m], base, out=np.ones(n_paths), where=base > 0)
        index = index * step
        peak = np.maximum(peak, index)
        worst = np.minimum(worst, index / peak - 1.0)
        if ledger:
            book["deposits"][:, m] = contributed[m]
            for k in ("costs", "fees", "market", "interest"):
                book[k][:, m] = cum[k]
            book["cash"][:, m] = cash
            book_hold[:, m] = hold
    return WealthResult(
        plan=plan,
        model=model.describe(),
        seed=seed,
        values=values,
        contributed=contributed,
        twr_max_drawdown=worst,
        twr_total=index - 1.0,
        total_costs=cum["costs"],
        total_fees=cum["fees"],
        shock=None if shock is None else {"size": shock, "month": shock_month},
        ledger=Ledger(holdings=book_hold, **book) if ledger else None,
    )
