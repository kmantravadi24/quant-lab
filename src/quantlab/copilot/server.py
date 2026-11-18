"""MCP server exposing the Quant Research Copilot tools (read-only).

Run:   python -m quantlab.copilot.server        (stdio; used by Claude Code via .mcp.json)

Requires the optional ``agent`` extra: ``pip install -e ".[agent]"``.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from quantlab.copilot import tools

INSTRUCTIONS = """You are connected to Quant Lab's research tools. Rules:
1. Every number you state must come from a tool result in this conversation; quote it, and
   give the tool's result_hash and the dataset fingerprint so the answer can be re-run.
2. Tool results are simulations under stated assumptions, never forecasts. Say so, and give the
   model, history window and paths. Never claim a strategy or plan will achieve a result.
3. When a probability matters, also call model_sensitivity: report the spread across models
   and history windows, and say that sampling ranges cover path noise only.
4. For methodology questions call methodology and quote it; for model reliability call
   validation_results. If the tools cannot answer, say so instead of estimating.
5. These tools cannot record forecasts, fetch market data or change anything. Those actions
   belong to the person, in the dashboard.
"""

READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
server = MCPServer("quantlab-copilot", instructions=INSTRUCTIONS)


@server.tool(annotations=READ_ONLY)
def list_approved_datasets() -> dict:
    """Datasets the tools may use (instruments, dates, fingerprints, rights notes)."""
    return tools.list_approved_datasets()


@server.tool(annotations=READ_ONLY)
def project_plan(
    dataset: str,
    weights: dict[str, float],
    initial_amount: float = 0.0,
    contribution: float = 500.0,
    horizon_years: float = 10.0,
    goal: float | None = None,
    goal_in_todays_money: bool = False,
    frequency: str = "M",
    contribution_growth: float = 0.0,
    rebalance: str | None = "A",
    cost_bps: float = 5.0,
    annual_fee: float = 0.0,
    cash_yield: float = 0.0,
    inflation: float = 0.025,
    model: str = "block_bootstrap",
    lookback_months: int | None = None,
    block_months: float = 12.0,
    paths: int = 2000,
    seed: int = 42,
) -> dict:
    """Simulate a funded investment plan month by month. Weights are fractions (the rest is cash);
    frequency M/Q/A; rebalance null/M/Q/A; rates are annual decimals. Returns ending-value
    percentiles, goal reach and hold probabilities with sampling ranges, deposits vs growth
    and provenance."""
    return tools.project_plan(
        dataset=dataset,
        weights=weights,
        initial_amount=initial_amount,
        contribution=contribution,
        horizon_years=horizon_years,
        goal=goal,
        goal_in_todays_money=goal_in_todays_money,
        model=model,
        lookback_months=lookback_months,
        block_months=block_months,
        paths=paths,
        seed=seed,
        frequency=frequency,
        contribution_growth=contribution_growth,
        rebalance=rebalance,
        cost_bps=cost_bps,
        annual_fee=annual_fee,
        cash_yield=cash_yield,
        inflation=inflation,
    )


@server.tool(annotations=READ_ONLY)
def compare_plan_variants(
    dataset: str,
    weights: dict[str, float],
    variants: dict[str, dict],
    initial_amount: float = 0.0,
    contribution: float = 500.0,
    horizon_years: float = 10.0,
    goal: float | None = None,
    model: str = "block_bootstrap",
    lookback_months: int | None = None,
    paths: int = 2000,
    seed: int = 42,
) -> dict:
    """Compare up to 6 variants of a plan on the SAME simulated markets. Each variant overrides plan
    fields, e.g. {"$1000/month": {"contribution": 1000}, "1% fee": {"annual_fee": 0.01}}."""
    return tools.compare_plan_variants(
        dataset=dataset,
        weights=weights,
        variants=variants,
        initial_amount=initial_amount,
        contribution=contribution,
        horizon_years=horizon_years,
        goal=goal,
        model=model,
        lookback_months=lookback_months,
        paths=paths,
        seed=seed,
    )


@server.tool(annotations=READ_ONLY)
def contribution_needed(
    dataset: str,
    weights: dict[str, float],
    goal: float,
    horizon_years: float = 10.0,
    initial_amount: float = 0.0,
    probability: float = 0.5,
    contribution_growth: float = 0.0,
    assumed_annual_returns: list[float] | None = None,
    model: str = "block_bootstrap",
    lookback_months: int | None = None,
) -> dict:
    """Contribution per period needed to end at or above the goal: at constant assumed returns,
    and so that the given share of simulated paths ends at or above it."""
    return tools.contribution_needed(
        dataset=dataset,
        weights=weights,
        goal=goal,
        horizon_years=horizon_years,
        initial_amount=initial_amount,
        probability=probability,
        assumed_annual_returns=assumed_annual_returns,
        model=model,
        lookback_months=lookback_months,
        contribution_growth=contribution_growth,
    )


@server.tool(annotations=READ_ONLY)
def model_sensitivity(
    dataset: str,
    weights: dict[str, float],
    goal: float,
    initial_amount: float = 0.0,
    contribution: float = 500.0,
    horizon_years: float = 10.0,
) -> dict:
    """Re-run one plan under all four models and several history windows: model uncertainty."""
    return tools.model_sensitivity(
        dataset=dataset,
        weights=weights,
        goal=goal,
        initial_amount=initial_amount,
        contribution=contribution,
        horizon_years=horizon_years,
    )


@server.tool(annotations=READ_ONLY)
def validation_results() -> dict:
    """Walk-forward validation of the return models on real data: coverage, tests, conclusions."""
    return tools.validation_results()


@server.tool(annotations=READ_ONLY)
def methodology(topic: str) -> dict:
    """Approved methodology text. Topics: event_order, return_models, outputs_and_uncertainty,
    validation, forecast_record, limitations."""
    return tools.methodology(topic=topic)


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
