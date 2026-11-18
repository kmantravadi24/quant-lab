"""Convert target weights into sized orders that respect the cash constraint."""

from __future__ import annotations

import math
from dataclasses import dataclass

from quantlab.execution.costs import ExecutionConfig


@dataclass(frozen=True)
class Order:
    ticker: str
    side: str  # BUY or SELL
    shares: float  # always positive
    reference_price: float


def size_orders(
    targets: dict[str, float],
    shares: dict[str, float],
    prices: dict[str, float],
    equity: float,
    cash: float,
    cfg: ExecutionConfig,
) -> tuple[list[Order], list[tuple[str, str]]]:
    """Size orders moving each ticker in ``targets`` toward weight * equity.

    Returns ``(orders, skipped)`` where ``skipped`` lists ``(ticker, reason)``
    for intended trades that were deliberately not sent.

    ``prices`` holds the execution reference price (next open) for tradable
    tickers only. Sells come first; buys are then scaled down pro rata, if
    needed, so that total cost including slippage and fees never exceeds the
    cash available. A sale whose proceeds would not cover its own fixed fee is
    skipped, because executing it would take cash below what the sale raises.
    The portfolio therefore cannot borrow and cash cannot go negative.
    """
    sells: list[Order] = []
    buys: list[Order] = []
    skipped: list[tuple[str, str]] = []
    for ticker, weight in targets.items():
        px = prices[ticker]
        held = shares.get(ticker, 0.0)
        delta = max(0.0, weight * equity / px) - held
        if not cfg.fractional_shares:
            delta = math.floor(delta) if delta > 0 else -math.floor(-delta)
        if weight == 0.0 and delta < 0:
            delta = -held  # full exit: leave no residual dust
        delta = max(delta, -held)  # never sell more than is held
        if abs(delta) * px < cfg.min_trade_notional:
            continue
        if delta < 0:
            net = -delta * px * (1 - cfg.slip) * (1 - cfg.fee_rate) - cfg.fixed_fee
            if net <= 0:
                skipped.append((ticker, "sale proceeds below fixed fee; order dropped"))
                continue
        (buys if delta > 0 else sells).append(
            Order(ticker, "BUY" if delta > 0 else "SELL", abs(delta), px)
        )

    proceeds = sum(
        o.shares * o.reference_price * (1 - cfg.slip) * (1 - cfg.fee_rate) - cfg.fixed_fee
        for o in sells
    )
    return sells + _fit_buys_to_cash(buys, cash + proceeds, cfg, skipped), skipped


def _fit_buys_to_cash(
    buys: list[Order], available: float, cfg: ExecutionConfig, skipped: list[tuple[str, str]]
) -> list[Order]:
    """Scale buys down pro rata so total cost (slippage and fees included) fits ``available``."""
    unit = (1 + cfg.slip) * (1 + cfg.fee_rate)
    variable = sum(o.shares * o.reference_price * unit for o in buys)
    fixed = cfg.fixed_fee * len(buys)
    if not buys or variable + fixed <= available:
        return buys
    scale = max(0.0, available - fixed) / variable * (1 - 1e-12)
    scaled = []
    for o in buys:
        q = o.shares * scale
        if not cfg.fractional_shares:
            q = math.floor(q)
        if q * o.reference_price >= cfg.min_trade_notional:
            scaled.append(Order(o.ticker, "BUY", q, o.reference_price))
        else:
            skipped.append((o.ticker, "insufficient cash after costs; order dropped"))
    return scaled


def size_cash_deployment(
    targets: dict[str, float],
    total_target_weight: float,
    prices: dict[str, float],
    equity: float,
    cash: float,
    cfg: ExecutionConfig,
) -> tuple[list[Order], list[tuple[str, str]]]:
    """Buy-only orders that invest spare cash at the target mix, without selling anything.

    Used to put a new contribution to work when no rebalance is due. Spare cash
    is the cash above the portfolio's target cash share:
    ``investable = cash - (1 - total_target_weight) * equity``. Each tradable
    ticker in ``targets`` receives ``investable * weight / total_target_weight``.
    Costs are paid out of the investable amount, so the cash reserve is not
    drawn down and cash cannot go negative. Existing holdings are left as they
    are: drift is not corrected.
    """
    skipped: list[tuple[str, str]] = []
    reserve = max(0.0, 1.0 - total_target_weight) * equity
    investable = max(0.0, cash - reserve)
    buys: list[Order] = []
    if total_target_weight <= 0:
        return buys, skipped
    for ticker, weight in targets.items():
        px = prices[ticker]
        quantity = investable * weight / total_target_weight / px
        if not cfg.fractional_shares:
            quantity = math.floor(quantity)
        if quantity * px >= cfg.min_trade_notional:
            buys.append(Order(ticker, "BUY", quantity, px))
    budget = investable * sum(targets.values()) / total_target_weight
    return _fit_buys_to_cash(buys, budget, cfg, skipped), skipped
