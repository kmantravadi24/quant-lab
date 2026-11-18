"""Monte Carlo sensitivity experiment for docs/qa/QA_REPORT.md (not a regression target).

Run from the repository root:  python docs/qa/evidence/mc_sensitivity.py out.csv
Needs the private frozen dataset in experiments/data/.
"""

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "src")

from quantlab.data.providers import load_dataset  # noqa: E402
from quantlab.simulations import simulate  # noqa: E402

data = load_dataset(next(Path("experiments/data").iterdir()))
returns = data.close["SPY"].pct_change().dropna()
lookbacks = {"3y": returns.iloc[-756:], "10y": returns.iloc[-2520:], "full": returns}
methods = [("iid", 21), ("block", 21), ("block", 63), ("stationary", 21), ("stationary", 63)]
rows = []
for (label, history), (method, block), paths in itertools.product(
    lookbacks.items(), methods, (1000, 5000, 20000)
):
    drawdown, loss, p5 = [], [], []
    for seed in range(10):
        res = simulate(history, horizon=252, n_paths=paths, method=method, block=block, seed=seed)
        drawdown.append(res.prob_drawdown_worse_than(-0.20))
        loss.append(res.prob_terminal_below(res.initial_value))
        p5.append(float(np.percentile(res.terminal, 5) / res.initial_value - 1))
    p = float(np.mean(drawdown))
    rows.append(
        {
            "lookback": label,
            "obs": len(history),
            "method": method,
            "block": block if method != "iid" else None,
            "paths": paths,
            "p_dd20": p,
            "sd_across_seeds": float(np.std(drawdown, ddof=1)),
            "binomial_se": float(np.sqrt(p * (1 - p) / paths)),
            "min_seed": float(min(drawdown)),
            "max_seed": float(max(drawdown)),
            "p_loss": float(np.mean(loss)),
            "p5_return": float(np.mean(p5)),
        }
    )
table = pd.DataFrame(rows)
table.to_csv(sys.argv[1], index=False)
pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 100)
print(table.round(4).to_string(index=False))
