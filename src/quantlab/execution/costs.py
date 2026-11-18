"""Execution cost model: proportional slippage plus proportional and fixed fees."""

from __future__ import annotations

import math
from dataclasses import dataclass

BPS = 1e-4


@dataclass(frozen=True)
class ExecutionConfig:
    """All execution assumptions in one explicit place.

    slippage_bps  adverse price move applied to the reference (open) price:
                  buys fill at open*(1+s), sells at open*(1-s)
    fee_bps       commission as a fraction of filled notional
    fixed_fee     flat charge per fill, in currency
    fractional_shares  True: any real quantity; False: whole shares, rounded toward zero trade
    min_trade_notional trades smaller than this are not sent (avoids numerical dust)
    """

    initial_capital: float = 100_000.0
    slippage_bps: float = 2.0
    fee_bps: float = 1.0
    fixed_fee: float = 0.0
    fractional_shares: bool = True
    min_trade_notional: float = 1e-6

    def __post_init__(self) -> None:
        # QA-018: NaN slips through every '<' comparison and inf is not a cost or a capital.
        numbers = {"initial_capital": self.initial_capital, "slippage_bps": self.slippage_bps,
                   "fee_bps": self.fee_bps, "fixed_fee": self.fixed_fee,
                   "min_trade_notional": self.min_trade_notional}  # fmt: skip
        for name, value in numbers.items():
            numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
            if not numeric or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number, got {value!r}")
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if min(self.slippage_bps, self.fee_bps, self.fixed_fee) < 0:
            raise ValueError("costs cannot be negative")

    @property
    def slip(self) -> float:
        return self.slippage_bps * BPS

    @property
    def fee_rate(self) -> float:
        return self.fee_bps * BPS


def fill_price(side: str, reference_price: float, cfg: ExecutionConfig) -> float:
    return reference_price * (1 + cfg.slip) if side == "BUY" else reference_price * (1 - cfg.slip)


def fee(notional: float, cfg: ExecutionConfig) -> float:
    return notional * cfg.fee_rate + cfg.fixed_fee
