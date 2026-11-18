"""The copilot's tools: validated library calls with provenance, limits and an audit log.

Design rules (see docs/copilot.md):

* Read-only. No tool writes forecasts, fetches provider data, accepts a file path or runs
  code. Consequential actions stay behind buttons a person presses in the dashboard.
* Every number comes from ``quantlab.forecast``; nothing is estimated by the AI.
* Every result carries ``provenance`` (dataset fingerprint, model window, seed, paths,
  Quant Lab version, git commit) and ``call`` (the normalised arguments), so an answer can
  be re-run exactly. ``result_hash`` identifies the numbers.
* Every result says what kind of statement it is: a simulation under stated assumptions,
  never a forecast of what will happen.
* Inputs are validated by the library; sizes are capped (paths, variants, horizon).
* Errors are returned as ``{"ok": false, "error": ...}`` rather than raised, so the
  assistant sees the reason and can correct its call.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from quantlab.data import SyntheticProvider
from quantlab.data.models import MarketData
from quantlab.data.providers import load_dataset
from quantlab.forecast import (
    LABELS,
    SUITABILITY,
    WealthPlan,
    build_model,
    compare_plans,
    decomposition,
    goal_probabilities,
    monthly_returns,
    required_contribution,
    required_contribution_deterministic,
    sensitivity,
    simulate_wealth,
    summary,
)
from quantlab.forecast.validation import summarise_record
from quantlab.portfolio.compare import data_fingerprint
from quantlab.reporting.experiment import environment

ROOT = Path(__file__).resolve().parents[3]
MAX_PATHS = 5_000
MAX_VARIANTS = 6
NATURE = (
    "Simulation of a stated plan under a stated model of historical returns. Not a forecast "
    "of what will happen, not investment advice; probabilities are model properties."
)
SYNTHETIC = ["SYN1", "SYN2", "SYN3", "SYN4", "SYN5"]


class ToolError(ValueError):
    """A request the tools refuse, with a reason the assistant can act on."""


# ----------------------------------------------------------------------------- datasets


@functools.lru_cache(maxsize=4)
def _dataset(name: str) -> MarketData:
    if name == "synthetic":
        return SyntheticProvider(seed=7).fetch(SYNTHETIC, "2005-01-01", "2024-12-31")
    if name == "frozen":
        folders = sorted((ROOT / "experiments" / "data").glob("*"))
        if not folders:
            raise ToolError("The frozen research snapshot is not present in this checkout")
        return load_dataset(folders[0])
    raise ToolError(f"Unknown dataset {name!r}; call list_datasets for the approved names")


def list_datasets() -> dict:
    """The datasets the tools may use. No tool contacts a market-data provider."""
    out = []
    for name, note in (
        (
            "synthetic",
            "Simulated random walks (seed 7). Demonstrates the method; "
            "says nothing about real markets.",
        ),
        (
            "frozen",
            "Frozen Yahoo-derived snapshot used by the research study. "
            "Private: redistribution rights not established.",
        ),
    ):
        try:
            data = _dataset(name)
        except ToolError as exc:
            out.append({"name": name, "available": False, "reason": str(exc)})
            continue
        out.append(
            {
                "name": name,
                "available": True,
                "note": note,
                "instruments": list(data.tickers),
                "first_session": str(data.dates[0].date()),
                "last_session": str(data.dates[-1].date()),
                "synthetic": bool(data.metadata.synthetic),
                "fingerprint": data_fingerprint(data),
            }
        )
    return {"datasets": out}


# ----------------------------------------------------------------------------- helpers


def _git_commit() -> str | None:
    head = ROOT / ".git" / "HEAD"
    try:
        ref = head.read_text().strip()
        if ref.startswith("ref: "):
            return (ROOT / ".git" / ref[5:]).read_text().strip()
        return ref
    except OSError:
        return None


def _plan(args: dict) -> WealthPlan:
    weights = args.get("weights")
    if not isinstance(weights, dict) or not weights:
        raise ToolError('weights must be an object such as {"SYN1": 0.6, "SYN2": 0.4}')
    fields = {
        k: args[k]
        for k in (
            "initial_amount",
            "contribution",
            "frequency",
            "contribution_growth",
            "rebalance",
            "cost_bps",
            "annual_fee",
            "cash_yield",
            "inflation",
            "horizon_years",
        )
        if k in args
    }
    return WealthPlan(
        weights={str(k): float(v) for k, v in weights.items()}, name="copilot plan", **fields
    )


def _model(
    data: MarketData, tickers: list[str], name: str, lookback_months: int | None, block: float
):
    if name not in LABELS:
        raise ToolError(f"model must be one of {sorted(LABELS)}")
    unknown = [t for t in tickers if t not in data.tickers]
    if unknown:
        raise ToolError(f"{unknown} not in the dataset; available: {list(data.tickers)}")
    returns = monthly_returns(data.close, tickers)
    if lookback_months is not None:
        if not isinstance(lookback_months, int) or lookback_months < 24:
            raise ToolError(
                "lookback_months must be an integer of at least 24, or null for all history"
            )
        returns = returns.iloc[-lookback_months:]
    params = {"block": float(block)} if name == "block_bootstrap" else {}
    return build_model(name, returns, **params), returns, params


def _paths(n) -> int:
    if not isinstance(n, int) or not 100 <= n <= MAX_PATHS:
        raise ToolError(f"paths must be an integer from 100 to {MAX_PATHS}")
    return n


def _clean(obj):
    """JSON-safe: tuples to lists, NaN/inf to None, numpy scalars to Python numbers."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        return float(obj) if np.isfinite(obj) else None
    if isinstance(obj, np.integer):
        return int(obj)
    return obj


def _finish(
    tool: str,
    call: dict,
    result: dict,
    data: MarketData | None,
    model=None,
    paths: int | None = None,
    seed: int | None = None,
) -> dict:
    body = _clean(result)
    payload = {
        "ok": True,
        "tool": tool,
        "nature": NATURE,
        "call": _clean(call),
        "result": body,
        "provenance": {
            "dataset_fingerprint": data_fingerprint(data) if data is not None else None,
            "dataset_synthetic": bool(data.metadata.synthetic) if data is not None else None,
            "model": model.describe() if model is not None else None,
            "paths": paths,
            "seed": seed,
            "quantlab": environment().get("quantlab"),
            "git_commit": _git_commit(),
        },
    }
    payload["result_hash"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[
        :16
    ]
    return payload


def _audit(tool: str, call: dict, outcome: dict, seconds: float) -> None:
    folder = os.environ.get("QUANTLAB_COPILOT_LOG", "").strip()
    if not folder:
        return
    entry = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tool": tool,
        "call": _clean(call),
        "ok": outcome.get("ok"),
        "error": outcome.get("error"),
        "result_hash": outcome.get("result_hash"),
        "seconds": round(seconds, 3),
    }
    path = Path(folder).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    with open(path / "copilot_audit.jsonl", "a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


def tool(fn):
    """Uniform error handling and audit logging for every copilot tool."""

    @functools.wraps(fn)
    def wrapper(**kwargs):
        began = time.perf_counter()
        try:
            outcome = fn(**kwargs)
        except (ToolError, ValueError, KeyError, TypeError) as exc:
            outcome = {
                "ok": False,
                "tool": fn.__name__,
                "error": f"{type(exc).__name__}: {exc}",
                "call": _clean(kwargs),
            }
        _audit(fn.__name__, kwargs, outcome, time.perf_counter() - began)
        return outcome

    return wrapper


# ----------------------------------------------------------------------------- tools


@tool
def project_plan(
    dataset: str,
    weights: dict,
    initial_amount: float = 0.0,
    contribution: float = 500.0,
    horizon_years: float = 10.0,
    goal: float | None = None,
    goal_in_todays_money: bool = False,
    model: str = "block_bootstrap",
    lookback_months: int | None = None,
    block_months: float = 12.0,
    paths: int = 2000,
    seed: int = 42,
    **plan_fields,
) -> dict:
    """Simulate a funded plan: percentiles, goal probabilities and the deposits/growth split."""
    call = dict(locals())
    call.pop("plan_fields")
    call.update(plan_fields)
    data = _dataset(dataset)
    plan = _plan(
        {
            **plan_fields,
            "weights": weights,
            "initial_amount": initial_amount,
            "contribution": contribution,
            "horizon_years": horizon_years,
        }
    )
    fitted, _, _ = _model(
        data, plan.tickers or list(weights)[:1], model, lookback_months, block_months
    )
    result = simulate_wealth(plan, fitted, _paths(paths), seed)
    out = {
        "summary": summary(result, goal, goal_in_todays_money),
        "plan": plan.to_dict(),
        "deposits_vs_growth": {q: decomposition(result, q) for q in (5, 50, 95)},
        "model_suitability": SUITABILITY[model],
    }
    return _finish("project_plan", call, out, data, fitted, paths, seed)


@tool
def compare_plan_variants(
    dataset: str,
    weights: dict,
    variants: dict,
    initial_amount: float = 0.0,
    contribution: float = 500.0,
    horizon_years: float = 10.0,
    goal: float | None = None,
    model: str = "block_bootstrap",
    lookback_months: int | None = None,
    paths: int = 2000,
    seed: int = 42,
) -> dict:
    """Compare variants of one plan against the SAME simulated markets (common random numbers).

    ``variants`` maps a label to plan-field overrides, e.g. {"high": {"contribution": 1000}}.
    """
    call = dict(locals())
    if not isinstance(variants, dict) or not 1 <= len(variants) <= MAX_VARIANTS:
        raise ToolError(f"variants must be an object with 1 to {MAX_VARIANTS} entries")
    data = _dataset(dataset)
    base = _plan(
        {
            "weights": weights,
            "initial_amount": initial_amount,
            "contribution": contribution,
            "horizon_years": horizon_years,
        }
    )
    plans = {"base": base}
    for label, overrides in variants.items():
        if not isinstance(overrides, dict):
            raise ToolError(f"variant {label!r} must be an object of plan fields")
        bad = set(overrides) - set(WealthPlan.__dataclass_fields__) - {"name"}
        if bad:
            raise ToolError(f"variant {label!r} has unknown fields {sorted(bad)}")
        plans[str(label)] = replace(base, **overrides)
    held = sorted({t for p in plans.values() for t in p.tickers}) or list(weights)[:1]
    fitted, _, _ = _model(data, held, model, lookback_months, 12.0)
    compared = compare_plans(plans, fitted, _paths(paths), seed, goal)
    out = {
        name: {"plan": c["plan"].to_dict(), "summary": c["summary"]} for name, c in compared.items()
    }
    return _finish("compare_plan_variants", call, out, data, fitted, paths, seed)


@tool
def contribution_needed(
    dataset: str,
    weights: dict,
    goal: float,
    horizon_years: float = 10.0,
    initial_amount: float = 0.0,
    probability: float = 0.5,
    assumed_annual_returns: list | None = None,
    model: str = "block_bootstrap",
    lookback_months: int | None = None,
    seed: int = 11,
    **plan_fields,
) -> dict:
    """Contribution per period needed for a goal: at constant assumed returns, and so that a
    stated share of simulated paths ends at or above it (500 paths, bisection to $5)."""
    call = dict(locals())
    call.pop("plan_fields")
    call.update(plan_fields)
    data = _dataset(dataset)
    plan = _plan(
        {
            **plan_fields,
            "weights": weights,
            "initial_amount": initial_amount,
            "contribution": plan_fields.get("contribution", 500.0),
            "horizon_years": horizon_years,
        }
    )
    rates = assumed_annual_returns or [0.04, 0.06, 0.08]
    deterministic = {
        f"{r:.4f}": required_contribution_deterministic(plan, goal, float(r)) for r in rates
    }
    fitted, _, _ = _model(data, plan.tickers or list(weights)[:1], model, lookback_months, 12.0)
    simulated = required_contribution(
        plan, fitted, goal, probability, n_paths=500, seed=seed, tolerance=5.0
    )
    out = {
        "goal": goal,
        "probability": probability,
        "constant_return": deterministic,
        "simulated": simulated,
        "notes": "Constant-return figures are arithmetic without costs; simulated ones keep costs, "
        "fees and contribution growth and inherit every limitation of the model.",
    }
    return _finish("contribution_needed", call, out, data, fitted, 500, seed)


@tool
def model_sensitivity(
    dataset: str,
    weights: dict,
    goal: float,
    initial_amount: float = 0.0,
    contribution: float = 500.0,
    horizon_years: float = 10.0,
    seed: int = 5,
) -> dict:
    """The same plan under every model and several history windows: shows model uncertainty."""
    call = dict(locals())
    data = _dataset(dataset)
    plan = _plan(
        {
            "weights": weights,
            "initial_amount": initial_amount,
            "contribution": contribution,
            "horizon_years": horizon_years,
        }
    )
    tickers = plan.tickers or list(weights)[:1]
    _, returns, _ = _model(data, tickers, "iid_bootstrap", None, 12.0)
    looks = {
        "all": len(returns),
        **{f"last {y} years": 12 * y for y in (10, 5) if 12 * y < len(returns)},
    }
    models = {
        "iid_bootstrap": {},
        "block_bootstrap": {"block": 12.0},
        "ewma_filtered": {},
        "gaussian_iid": {},
    }
    rows = sensitivity(plan, returns, models, looks, n_paths=1000, seed=seed, goal=goal)
    holds = [r["p_hold_goal"] for r in rows]
    out = {
        "rows": rows,
        "p_hold_goal_range": [min(holds), max(holds)],
        "sampling_half_width_at_1000_paths": float(1.96 * np.sqrt(0.25 / 1000)),
        "reading": "The spread between rows is model uncertainty; more paths do not shrink it.",
    }
    return _finish("model_sensitivity", call, out, data, None, 1000, seed)


@tool
def validation_results() -> dict:
    """What the stored walk-forward validation found, per horizon, with its conclusions."""
    folder = ROOT / "experiments" / "results"
    records = [
        p for p in sorted(folder.glob("forecast_validation_*.json")) if "synthetic" not in p.stem
    ]
    if not records:
        raise ToolError("No real-data validation record is stored")
    record = json.loads(records[-1].read_text())
    out = {
        "protocol_hash": record["protocol_hash"],
        "decision_rule": record["protocol"]["decision_rule"],
        "summary": summarise_record(record),
        "conclusions": {k: v["conclusions"] for k, v in record["results"].items()},
    }
    return _finish("validation_results", {}, out, None)


TOPICS = {
    "event_order": "## 2.",
    "return_models": "## 3.",
    "outputs_and_uncertainty": "## 4.",
    "validation": "## 5.",
    "forecast_record": "## 6.",
    "limitations": "## 8.",
}


@tool
def methodology(topic: str) -> dict:
    """An approved section of docs/forecasting.md, verbatim: quote it, do not invent."""
    if topic not in TOPICS:
        raise ToolError(f"topic must be one of {sorted(TOPICS)}")
    text = (ROOT / "docs" / "forecasting.md").read_text()
    start = text.index(TOPICS[topic])
    nxt = text.find("\n## ", start + 4)
    section = text[start : nxt if nxt != -1 else len(text)].strip()
    return _finish("methodology", {"topic": topic}, {"topic": topic, "text": section}, None)


@tool
def list_approved_datasets() -> dict:
    """Datasets available to the tools, with fingerprints and rights notes."""
    return _finish("list_approved_datasets", {}, list_datasets(), None)


def goal_check(result_payload: dict, goal: float) -> dict:
    """Helper for evaluations: recompute hold/reach from a project_plan call's own inputs."""
    call = result_payload["call"]
    data = _dataset(call["dataset"])
    plan = WealthPlan.from_dict(result_payload["result"]["plan"])
    fitted, _, _ = _model(
        data,
        plan.tickers or list(call["weights"])[:1],
        call["model"],
        call["lookback_months"],
        call["block_months"],
    )
    return goal_probabilities(simulate_wealth(plan, fitted, call["paths"], call["seed"]), goal)


TOOLS = [
    list_approved_datasets,
    project_plan,
    compare_plan_variants,
    contribution_needed,
    model_sensitivity,
    validation_results,
    methodology,
]
