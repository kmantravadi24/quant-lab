"""Cash and holdings accounting. The only place where portfolio state changes."""

from __future__ import annotations

from dataclasses import dataclass, field

from quantlab.execution.costs import ExecutionConfig, fee, fill_price
from quantlab.execution.orders import Order


class ConstraintViolation(Exception):
    """An order would breach a portfolio constraint (cash or holdings)."""


@dataclass(frozen=True)
class Fill:
    ticker: str
    side: str
    shares: float
    reference_price: float
    fill_price: float
    notional: float
    fee: float
    slippage_cost: float
    realized_pnl: float  # sells only; average-cost basis including fees
    cash_after: float


@dataclass
class Portfolio:
    """Long-only cash account. Rejects anything that would borrow or short."""

    cash: float
    shares: dict[str, float] = field(default_factory=dict)
    avg_cost: dict[str, float] = field(default_factory=dict)  # per share, incl. buy fees

    def market_value(self, prices: dict[str, float]) -> float:
        return sum(q * prices[t] for t, q in self.shares.items() if q)

    def equity(self, prices: dict[str, float]) -> float:
        """The accounting identity: equity = cash + marked value of holdings."""
        return self.cash + self.market_value(prices)

    def execute(self, order: Order, cfg: ExecutionConfig) -> Fill:
        px = fill_price(order.side, order.reference_price, cfg)
        notional = order.shares * px
        cost = fee(notional, cfg)
        held = self.shares.get(order.ticker, 0.0)
        tol = 1e-9 * max(1.0, notional)
        realized = 0.0
        if order.side == "BUY":
            if notional + cost > self.cash + tol:
                raise ConstraintViolation(
                    f"BUY {order.ticker}: needs {notional + cost:.2f}, cash {self.cash:.2f}"
                )
            self.cash -= notional + cost
            basis = held * self.avg_cost.get(order.ticker, 0.0) + notional + cost
            self.shares[order.ticker] = held + order.shares
            self.avg_cost[order.ticker] = basis / self.shares[order.ticker]
        elif order.side == "SELL":
            if order.shares > held * (1 + 1e-12) + 1e-12:
                raise ConstraintViolation(
                    f"SELL {order.ticker}: {order.shares} shares, only {held} held"
                )
            if self.cash + notional - cost < -tol:
                raise ConstraintViolation(
                    f"SELL {order.ticker}: fee {cost:.2f} exceeds proceeds plus cash"
                )
            realized = notional - cost - order.shares * self.avg_cost.get(order.ticker, 0.0)
            self.cash += notional - cost
            remaining = held - order.shares
            self.shares[order.ticker] = 0.0 if abs(remaining) < 1e-12 else remaining
        else:
            raise ValueError(f"Unknown side {order.side}")
        return Fill(
            ticker=order.ticker,
            side=order.side,
            shares=order.shares,
            reference_price=order.reference_price,
            fill_price=px,
            notional=notional,
            fee=cost,
            slippage_cost=order.shares * abs(px - order.reference_price),
            realized_pnl=realized,
            cash_after=self.cash,
        )
