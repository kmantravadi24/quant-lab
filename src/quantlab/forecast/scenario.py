"""Reproducible scenario files: everything needed to re-run a projection exactly."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from quantlab.forecast.engine import WealthResult, simulate_wealth
from quantlab.forecast.goals import summary
from quantlab.forecast.plan import WealthPlan
from quantlab.forecast.returns import build_model, monthly_returns
from quantlab.reporting.experiment import environment

SCHEMA = "quantlab.future_wealth/1"


def scenario_payload(
    result: WealthResult,
    model_name: str,
    model_params: dict,
    lookback_months: int | None,
    data_meta: dict,
    fingerprint: str,
    goal: float | None = None,
    real_goal: bool = False,
) -> dict:
    bands = result.percentile_bands()
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "plan": result.plan.to_dict(),
        "model": {
            "name": model_name,
            "params": model_params,
            "lookback_months": lookback_months,
            "fitted": result.model,
        },
        "simulation": {"paths": result.n_paths, "seed": result.seed, "shock": result.shock},
        "goal": {"amount": goal, "in_todays_money": real_goal},
        "data": {**data_meta, "fingerprint": fingerprint},
        "summary": summary(result, goal, real_goal),
        "percentiles_by_month": {
            f"p{p}": bands[i].round(2).tolist() for i, p in enumerate((5, 25, 50, 75, 95))
        },
        "contributed_by_month": result.contributed.round(2).tolist(),
        "environment": environment(),
        "notes": [
            "Simulated outcomes under a stated model of returns. Not a forecast of what will "
            "happen and not investment advice.",
            "Probability intervals reflect Monte Carlo sampling only, not model uncertainty.",
        ],
    }


def rerun(payload: dict, close: pd.DataFrame) -> WealthResult:
    """Re-run a saved scenario on daily closes. Identical data and seed give identical numbers."""
    if payload.get("schema") != SCHEMA:
        raise ValueError("Not a Quant Lab future-wealth scenario file")
    plan = WealthPlan.from_dict(payload["plan"])
    spec = payload["model"]
    tickers = list(spec["fitted"]["tickers"])
    returns = monthly_returns(close, tickers)
    if spec.get("lookback_months"):
        returns = returns.iloc[-int(spec["lookback_months"]) :]
    model = build_model(spec["name"], returns, **spec.get("params", {}))
    sim = payload["simulation"]
    shock = sim.get("shock") or {}
    return simulate_wealth(
        plan,
        model,
        int(sim["paths"]),
        int(sim["seed"]),
        shock=shock.get("size"),
        shock_month=shock.get("month", 1),
    )


def same_result(payload: dict, result: WealthResult) -> bool:
    again = summary(result, payload["goal"]["amount"], payload["goal"]["in_todays_money"])
    return bool(
        np.isclose(
            again["median_terminal"], payload["summary"]["median_terminal"], rtol=0, atol=1e-6
        )
        and np.isclose(again["p5_terminal"], payload["summary"]["p5_terminal"], rtol=0, atol=1e-6)
    )
