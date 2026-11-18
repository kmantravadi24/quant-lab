"""Future wealth forecasting: contribution-aware account simulation on joint return models.

Read-only decision support. Nothing here places orders or claims a predictive edge.
"""

from quantlab.forecast.engine import WealthResult, simulate_wealth
from quantlab.forecast.goals import (
    MILESTONES,
    compare_plans,
    decomposition,
    deterministic_value,
    goal_probabilities,
    quantile_interval,
    required_contribution,
    required_contribution_deterministic,
    sensitivity,
    summary,
)
from quantlab.forecast.plan import WealthPlan
from quantlab.forecast.returns import (
    LABELS,
    MODELS,
    SUITABILITY,
    BlockBootstrap,
    EWMAFiltered,
    GaussianIID,
    IIDBootstrap,
    build_model,
    monthly_returns,
)

__all__ = [
    "LABELS",
    "MILESTONES",
    "MODELS",
    "SUITABILITY",
    "BlockBootstrap",
    "EWMAFiltered",
    "GaussianIID",
    "IIDBootstrap",
    "WealthPlan",
    "WealthResult",
    "build_model",
    "compare_plans",
    "decomposition",
    "deterministic_value",
    "goal_probabilities",
    "monthly_returns",
    "quantile_interval",
    "required_contribution",
    "required_contribution_deterministic",
    "sensitivity",
    "simulate_wealth",
    "summary",
]
