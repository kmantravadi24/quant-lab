"""Hypothetical instantaneous shocks to individual holdings.

Every scenario here is HYPOTHETICAL. Shocks are applied independently per
holding; nothing in this module models how assets actually move together, so a
scenario is only as realistic as the joint shock vector the user supplies.
"""

from __future__ import annotations

import math

import pandas as pd


def _validate(holdings_value: pd.Series, shocks: dict[str, float]) -> None:
    values = pd.Series(holdings_value, dtype=float)
    if not values.map(math.isfinite).all():
        raise ValueError("Holding values must be finite numbers")
    if (values < 0).any():
        raise ValueError("Holding values cannot be negative (long-only)")
    if not values.sum() > 0:
        # QA-019: a percentage effect on a portfolio worth nothing is undefined (0/0).
        raise ValueError("The portfolio has no value to stress")
    unknown = [t for t in shocks if t not in values.index]
    if unknown:
        raise KeyError(f"Shocks reference holdings not in the portfolio: {unknown}")
    for name, shock in shocks.items():
        # QA-009: a blank (NaN) shock is not silently 'no change', and inf is not a price move.
        if not isinstance(shock, (int, float)) or not math.isfinite(shock):
            raise ValueError(f"Shock for {name} is not a finite number ({shock!r})")
    if any(s < -1 for s in shocks.values()):
        raise ValueError("A long holding cannot lose more than 100%")


def apply_scenario(holdings_value: pd.Series, shocks: dict[str, float]) -> pd.DataFrame:
    """Per-holding effect of percentage shocks (e.g. {"SPY": -0.20}). Unlisted holdings: 0.

    Raises ValueError for non-finite shocks or values, negative values, a portfolio
    worth nothing, or a loss beyond 100%; KeyError for a shock on an unknown holding.
    """
    _validate(holdings_value, shocks)
    shock = pd.Series(shocks, dtype=float).reindex(holdings_value.index).fillna(0.0)
    pnl = holdings_value * shock
    total = holdings_value.sum()
    return pd.DataFrame({
        "value_before": holdings_value,
        "shock": shock,
        "pnl": pnl,
        "value_after": holdings_value + pnl,
        "contribution_pct": pnl / total,
    })  # fmt: skip


def scenario_summary(holdings_value: pd.Series, scenarios: dict[str, dict[str, float]]):
    """Compare several hypothetical scenarios: portfolio value before/after and loss."""
    rows = {}
    before = float(holdings_value.sum())
    for name, shocks in scenarios.items():
        pnl = float(apply_scenario(holdings_value, shocks)["pnl"].sum())
        rows[name] = {
            "value_before": before,
            "value_after": before + pnl,
            "pnl": pnl,
            "pnl_pct": pnl / before,
        }
    return pd.DataFrame(rows).T
