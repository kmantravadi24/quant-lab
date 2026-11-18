"""Multiple-testing bookkeeping.

Every configuration that is evaluated is one more chance to find something that
looks good by luck (the physicist's look-elsewhere effect). The registry makes
the number of looks an explicit, reported quantity.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class TrialRegistry:
    trials: list[dict] = field(default_factory=list)

    def record(self, strategy: str, params: dict, period: str, **metrics: float) -> None:
        self.trials.append({"strategy": strategy, "params": params, "period": period, **metrics})

    @property
    def count(self) -> int:
        return len(self.trials)

    def distinct_configurations(self) -> int:
        return len({(t["strategy"], tuple(sorted(t["params"].items()))) for t in self.trials})


def bonferroni(p_values: list[float]) -> list[float]:
    """p_adj = min(1, m * p). Controls family-wise error under any dependence; conservative."""
    m = len(p_values)
    return [min(1.0, p * m) for p in p_values]


def holm(p_values: list[float]) -> list[float]:
    """Holm step-down adjusted p-values. Uniformly more powerful than Bonferroni, same guarantee."""
    m = len(p_values)
    order = np.argsort(p_values)
    adjusted = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p_values[i]))
        adjusted[i] = running
    return adjusted.tolist()
