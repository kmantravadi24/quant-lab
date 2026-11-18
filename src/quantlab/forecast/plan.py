"""A forward-looking investment plan: what to hold, how it is funded, maintained and charged."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from quantlab.portfolio.spec import PortfolioSpec
from quantlab.strategies.fixed_weights import validate_long_only_weights

STEP = {"M": 1, "Q": 3, "A": 12}  # months between contributions / rebalances
MAX_YEARS = 50


@dataclass(frozen=True)
class WealthPlan:
    """Inputs of one future-wealth projection. All rates are annual decimals (0.03 = 3%).

    weights               long-only target weights; the remainder (1 - sum) is cash
    initial_amount        money invested at the start (time 0)
    contribution          amount added each contribution period
    frequency             "M" monthly, "Q" quarterly, "A" annually (first one in month 1)
    contribution_growth   the contribution rises by this much every 12 months
    rebalance             None (never; new money buys the target mix), "M", "Q" or "A"
    cost_bps              trading cost (spread + commission) per unit traded, in basis points
    annual_fee            fund or advisory fee on invested holdings, charged monthly
    cash_yield            interest earned by the cash part
    inflation             used only to express results in today's money
    horizon_years         length of the projection (months = round(12 x years))
    """

    weights: dict[str, float]
    initial_amount: float = 0.0
    contribution: float = 500.0
    frequency: str = "M"
    contribution_growth: float = 0.0
    rebalance: str | None = "A"
    cost_bps: float = 5.0
    annual_fee: float = 0.0
    cash_yield: float = 0.0
    inflation: float = 0.025
    horizon_years: float = 10.0
    name: str = "plan"

    def __post_init__(self) -> None:
        validate_long_only_weights(self.weights)
        numbers = {
            "initial_amount": self.initial_amount,
            "contribution": self.contribution,
            "contribution_growth": self.contribution_growth,
            "cost_bps": self.cost_bps,
            "annual_fee": self.annual_fee,
            "cash_yield": self.cash_yield,
            "inflation": self.inflation,
            "horizon_years": self.horizon_years,
        }
        for key, value in numbers.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"{key} must be a finite number, got {value!r}")
        if self.initial_amount < 0 or self.contribution < 0:
            raise ValueError("Amounts cannot be negative (withdrawals are not modelled)")
        if self.initial_amount == 0 and self.contribution == 0:
            raise ValueError("The plan invests nothing: set an initial amount or a contribution")
        if self.frequency not in STEP:
            raise ValueError("frequency must be 'M', 'Q' or 'A'")
        if self.rebalance not in (None, "M", "Q", "A"):
            raise ValueError("rebalance must be None, 'M', 'Q' or 'A'")
        if not -0.5 <= self.contribution_growth <= 1.0:
            raise ValueError("contribution_growth must be between -50% and +100% a year")
        if not 0 <= self.cost_bps <= 500:
            raise ValueError("cost_bps must be between 0 and 500")
        if not 0 <= self.annual_fee < 0.2:
            raise ValueError("annual_fee must be between 0% and 20%")
        if not -0.05 <= self.cash_yield <= 0.25:
            raise ValueError("cash_yield must be between -5% and 25%")
        if not -0.1 <= self.inflation <= 0.5:
            raise ValueError("inflation must be between -10% and 50%")
        if not 1 / 12 <= self.horizon_years <= MAX_YEARS:
            raise ValueError(f"horizon_years must be between 1 month and {MAX_YEARS} years")

    @property
    def months(self) -> int:
        return max(1, round(12 * self.horizon_years))

    @property
    def tickers(self) -> list[str]:
        return [t for t, w in self.weights.items() if w > 0]

    @property
    def cash_weight(self) -> float:
        return max(0.0, 1.0 - sum(self.weights.values()))

    def contribution_schedule(self) -> list[float]:
        """Deposit at the start of each month 1..months (initial amount NOT included)."""
        step = STEP[self.frequency]
        out = []
        for m in range(1, self.months + 1):
            if (m - 1) % step == 0:
                out.append(self.contribution * (1 + self.contribution_growth) ** ((m - 1) // 12))
            else:
                out.append(0.0)
        return out

    def total_contributed(self) -> float:
        return self.initial_amount + sum(self.contribution_schedule())

    def rebalance_month(self, m: int) -> bool:
        return self.rebalance is not None and (m - 1) % STEP[self.rebalance] == 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> WealthPlan:
        known = {k: payload[k] for k in cls.__dataclass_fields__ if k in payload}
        return cls(**known)

    @classmethod
    def from_spec(cls, spec: PortfolioSpec, **overrides) -> WealthPlan:
        """Start from an Investment Lab portfolio (same weights, funding and rebalancing)."""
        if spec.contribution_frequency == "W" and spec.contribution > 0:
            raise ValueError("Weekly contributions are not projected; use the monthly equivalent")
        base = {
            "weights": dict(spec.weights),
            "initial_amount": spec.initial_amount,
            "contribution": spec.contribution,
            "frequency": spec.contribution_frequency
            if spec.contribution_frequency in STEP
            else "M",
            "rebalance": spec.rebalance,
            "name": spec.name,
        }
        return cls(**{**base, **overrides})
