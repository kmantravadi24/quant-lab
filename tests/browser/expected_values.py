"""Engine values the browser checks must see on screen (synthetic data, Investment Lab defaults).

Printed as JSON for tests/browser/smoke.js: the default Portfolio A, and Portfolio A after L06's
edit (SYN1 30%, SYN2 40%, 30% cash). Same data, costs and funding as the dashboard defaults."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from quantlab.data import SyntheticProvider  # noqa: E402
from quantlab.execution import ExecutionConfig  # noqa: E402
from quantlab.portfolio.compare import compare_portfolios  # noqa: E402
from quantlab.portfolio.spec import PortfolioSpec  # noqa: E402

data = SyntheticProvider(7).fetch(["SYN1", "SYN2", "SYN3", "SYN4", "SYN5"], "2005-01-01")
cfg = ExecutionConfig(initial_capital=10_000.0, slippage_bps=2.0, fee_bps=1.0)


def final(weights: dict[str, float]) -> str:
    spec = PortfolioSpec(weights, 10_000.0, 500.0, "M", "A", "Portfolio A")
    return f"{compare_portfolios(data, {'Portfolio A': spec}, cfg, 0.0).stats['Portfolio A']['final_value']:,.0f}"


print(json.dumps({"default": final({"SYN1": 0.6, "SYN2": 0.4}), "l06": final({"SYN1": 0.3, "SYN2": 0.4})}))
