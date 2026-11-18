"""Chronologically correct daily backtesting engine.

Timeline for every session t on the calendar
--------------------------------------------
1. OPEN of t   : orders pending from decisions made at the close of t-1 or
                 earlier are filled at open_t (+/- slippage, plus fees).
2. CLOSE of t  : the portfolio is marked to market at close_t and recorded.
3. after CLOSE : if the strategy made a decision dated t, it becomes pending.

A decision dated t therefore can never trade at any price dated <= t.

External cash flows
-------------------
A contribution dated t is added to cash at the OPEN of t, before that session's
fills. It is not invested by arriving: it is invested by the next decision that
executes. The portfolio is valued at that boundary (holdings at the open),
which makes the return series flow-neutral:

    r_t = (E_pre / E_{t-1}) * (E_t / (E_pre + C_t)) - 1

where E_pre is equity at the open before the deposit. On days without a flow
this is exactly E_t / E_{t-1} - 1, computed as before.

Policies (see docs/methodology.md)
- Missing open for a ticker: its order is not filled, is logged as unfilled,
  and stays pending for the next session that has a price. No trade is ever
  fabricated on a date without a price.
- Missing close for a held ticker: it is marked at its last observed price and
  the date is flagged in ``stale_marks``.
- A new decision replaces any still-pending orders.
- A sale too small to cover its own fixed fee, or a buy that cash cannot fund
  after costs, is dropped and logged as unfilled.
- Prices are dividend/split adjusted, so no separate dividend cash flows exist.
- Cash earns no interest. No borrowing, no shorting.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from quantlab.data.models import MarketData
from quantlab.execution.costs import ExecutionConfig
from quantlab.execution.orders import size_cash_deployment, size_orders
from quantlab.portfolio.ledger import Portfolio
from quantlab.strategies.base import Strategy

WEIGHT_TOL = 1e-9
TRADE_COLUMNS = [
    "date", "decision_date", "ticker", "side", "shares", "reference_price", "fill_price",
    "notional", "fee", "slippage_cost", "realized_pnl", "cash_after",
]  # fmt: skip


@dataclass(frozen=True)
class BacktestResult:
    equity: pd.Series  # close-of-session portfolio equity
    returns: pd.Series  # simple daily returns of equity (first vs initial capital)
    cash: pd.Series
    holdings: pd.DataFrame  # shares held at each close
    positions: pd.DataFrame  # marked value of each holding at each close
    trades: pd.DataFrame  # audit ledger, one row per fill
    unfilled: pd.DataFrame  # orders that could not be filled, with reasons
    turnover: pd.Series  # traded notional / equity at the open, per session
    stale_marks: pd.DataFrame  # True where a holding was marked at a stale price
    target_weights: pd.DataFrame
    config: ExecutionConfig
    name: str = "backtest"
    cash_flows: pd.Series | None = None  # external contributions by session (0 where none)
    equity_before_flow: pd.Series | None = None  # equity at the open, before a contribution

    @property
    def weights(self) -> pd.DataFrame:
        """Realized close-of-session portfolio weights (cash is 1 - row sum)."""
        return self.positions.div(self.equity, axis=0)

    def config_dict(self) -> dict:
        return asdict(self.config)


def validate_target_weights(weights: pd.DataFrame, data: MarketData) -> None:
    """Reject anything the long-only, unlevered engine cannot hold."""
    unknown = [c for c in weights.columns if c not in data.tickers]
    if unknown:
        raise ValueError(f"Weights reference unknown tickers: {unknown}")
    if not weights.index.isin(data.dates).all():
        raise ValueError("Every decision date must be a session in the dataset")
    if not weights.index.is_monotonic_increasing or weights.index.has_duplicates:
        raise ValueError("Decision dates must be unique and increasing")
    values = weights.to_numpy(dtype=float)
    if np.isnan(values).any():
        raise ValueError("Target weights contain NaN")
    if (values < -WEIGHT_TOL).any():
        raise ValueError("Negative target weight: short selling is not supported")
    if (values.sum(axis=1) > 1 + WEIGHT_TOL).any():
        raise ValueError("Target weights sum to more than 1: leverage is not supported")


def validate_cash_flows(cash_flows: pd.Series | None, data: MarketData) -> dict:
    """External contributions: non-negative amounts on session dates. Returns {date: amount}."""
    if cash_flows is None or len(cash_flows) == 0:
        return {}
    flows = pd.Series(cash_flows, dtype=float)
    if flows.isna().any() or not np.isfinite(flows.to_numpy()).all():
        raise ValueError("Cash flows contain NaN or infinite values")
    if (flows < 0).any():
        raise ValueError("Withdrawals are not supported: cash flows must be >= 0")
    if flows.index.has_duplicates:
        raise ValueError("Cash-flow dates must be unique")
    if not flows.index.isin(data.dates).all():
        raise ValueError("Every cash-flow date must be a session in the dataset")
    return {d: float(v) for d, v in flows.items() if v}


def run_backtest(
    data: MarketData,
    target_weights: pd.DataFrame,
    config: ExecutionConfig | None = None,
    name: str = "backtest",
    cash_flows: pd.Series | None = None,
    cash_only: pd.DatetimeIndex | None = None,
) -> BacktestResult:
    """Simulate target weights through the open/close timeline described above.

    ``cash_flows``: external contributions (>= 0) indexed by session date.
    ``cash_only``: decision dates whose row of ``target_weights`` only invests
    spare cash at that mix, leaving existing holdings alone.
    """
    cfg = config or ExecutionConfig()
    validate_target_weights(target_weights, data)
    deposits = validate_cash_flows(cash_flows, data)
    invest_only = set(pd.DatetimeIndex(cash_only)) if cash_only is not None else set()
    if not invest_only <= set(target_weights.index):
        raise ValueError("Every cash-only date must be a decision date in target_weights")
    tickers = data.tickers
    dates = data.dates
    opens = data.open.to_numpy(dtype=float)
    closes = data.close.to_numpy(dtype=float)
    col = {t: i for i, t in enumerate(tickers)}
    decisions = {d: row for d, row in target_weights.iterrows()}

    pf = Portfolio(cash=cfg.initial_capital)
    last_price: dict[str, float] = {}
    pending: dict[str, float] = {}
    pending_date: pd.Timestamp | None = None
    pending_invest_only = False

    n = len(dates)
    flows = np.zeros(n)
    before_flow = np.full(n, np.nan)
    equity = np.empty(n)
    cash = np.empty(n)
    holdings = np.zeros((n, len(tickers)))
    positions = np.zeros((n, len(tickers)))
    stale = np.zeros((n, len(tickers)), dtype=bool)
    turnover = np.zeros(n)
    trades: list[dict] = []
    unfilled: list[dict] = []

    for i, date in enumerate(dates):
        # 0. OPEN: an external contribution arrives before anything trades.
        deposit = deposits.get(date, 0.0)
        if deposit:
            at_open = dict(last_price)
            for t, q in pf.shares.items():
                if q and not np.isnan(opens[i, col[t]]):
                    at_open[t] = opens[i, col[t]]
            before_flow[i] = pf.equity(at_open)  # valuation at the flow boundary
            pf.cash += deposit
            flows[i] = deposit

        # 1. OPEN: fill pending orders at this session's open.
        if pending:
            tradable = {t: opens[i, col[t]] for t in pending if not np.isnan(opens[i, col[t]])}
            for t in pending:
                if t not in tradable:
                    unfilled.append({
                        "date": date, "decision_date": pending_date, "ticker": t,
                        "reason": "no open price; order carried forward",
                    })  # fmt: skip
            # Mark every holding at today's open where one exists, else its last price.
            marks = dict(last_price)
            for t, q in pf.shares.items():
                if q and not np.isnan(opens[i, col[t]]):
                    marks[t] = opens[i, col[t]]
            marks.update(tradable)
            held_unpriced = [t for t, q in pf.shares.items() if q and t not in marks]
            if held_unpriced:  # cannot happen: a holding implies a past fill price
                raise RuntimeError(f"Holding without any price: {held_unpriced}")
            equity_open = pf.equity(marks)
            if pending_invest_only:
                orders, skipped = size_cash_deployment(
                    {t: pending[t] for t in tradable if pending[t] > 0},
                    sum(pending.values()), tradable, equity_open, pf.cash, cfg,
                )  # fmt: skip
            else:
                orders, skipped = size_orders(
                    {t: pending[t] for t in tradable}, pf.shares, tradable, equity_open,
                    pf.cash, cfg,
                )  # fmt: skip
            for t, reason in skipped:
                unfilled.append({
                    "date": date, "decision_date": pending_date, "ticker": t, "reason": reason,
                })  # fmt: skip
            for order in orders:
                fill = pf.execute(order, cfg)
                trades.append({"date": date, "decision_date": pending_date, **fill.__dict__})
                turnover[i] += fill.notional / equity_open
            # A rebalance order without a price waits for one. A cash deployment does not:
            # the unspent share simply stays in cash until the next decision.
            carried = {} if pending_invest_only else pending
            pending = {t: w for t, w in carried.items() if t not in tradable}
            last_price.update(tradable)

        # 2. CLOSE: mark to market.
        for t, j in col.items():
            if not np.isnan(closes[i, j]):
                last_price[t] = closes[i, j]
            elif pf.shares.get(t, 0.0):
                stale[i, j] = True
        for t, q in pf.shares.items():
            holdings[i, col[t]] = q
            positions[i, col[t]] = q * last_price[t] if q else 0.0
        cash[i] = pf.cash
        equity[i] = pf.cash + positions[i].sum()

        # 3. After the close: today's decision becomes pending for a later open.
        if date in decisions:
            pending = {t: float(w) for t, w in decisions[date].items()}
            pending_date = date
            pending_invest_only = date in invest_only

    equity_s = pd.Series(equity, index=dates, name="equity")
    previous = equity_s.shift(1).fillna(cfg.initial_capital)
    returns = equity_s / previous - 1.0
    for i in np.flatnonzero(flows):  # flow days: link the two sub-periods around the deposit
        overnight = before_flow[i] / previous.iloc[i]
        after = equity[i] / (before_flow[i] + flows[i])
        returns.iloc[i] = overnight * after - 1.0
    frame = lambda arr: pd.DataFrame(arr, index=dates, columns=tickers)  # noqa: E731
    return BacktestResult(
        equity=equity_s,
        returns=returns.rename("returns"),
        cash=pd.Series(cash, index=dates, name="cash"),
        holdings=frame(holdings),
        positions=frame(positions),
        trades=pd.DataFrame(trades, columns=TRADE_COLUMNS),
        unfilled=pd.DataFrame(unfilled, columns=["date", "decision_date", "ticker", "reason"]),
        turnover=pd.Series(turnover, index=dates, name="turnover"),
        stale_marks=frame(stale),
        target_weights=target_weights,
        config=cfg,
        name=name,
        cash_flows=pd.Series(flows, index=dates, name="cash_flow"),
        equity_before_flow=pd.Series(before_flow, index=dates, name="equity_before_flow"),
    )


def backtest_strategy(
    strategy: Strategy,
    data: MarketData,
    config: ExecutionConfig | None = None,
    as_of: str | pd.Timestamp | None = None,
) -> BacktestResult:
    """Generate a strategy's decisions and simulate them."""
    if as_of is not None:
        data = data.truncate(as_of)
    output = strategy.generate(data)
    return run_backtest(
        data, output.weights, config, name=strategy.name, cash_only=output.cash_only
    )
