"""Release check: drive a deployed Quant Lab and compare what it shows with the library.

    python tests/browser/release_check.py <base-url> [--public-demo] [--shots DIR]

Needs Node with Playwright (as for tests/browser/run.sh). Read-only against the target.
Expects the deployment's default data source to be the synthetic demo data.
Exit code 0 only if every journey passes and the numbers match.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quantlab.data import SyntheticProvider  # noqa: E402
from quantlab.forecast import (  # noqa: E402
    WealthPlan,
    build_model,
    monthly_returns,
    simulate_wealth,
    summary,
)


def expected() -> dict:
    """The default Future Wealth plan on the default synthetic data, computed by the library."""
    data = SyntheticProvider(seed=7).fetch(["SYN1", "SYN2", "SYN3", "SYN4", "SYN5"], "2005-01-01")
    plan = WealthPlan({"SYN1": 0.6, "SYN2": 0.4}, 5_000.0, 500.0, "M", 0.03, "A", 5.0, 0.001, 0.0, 0.025, 10.0)
    model = build_model("block_bootstrap", monthly_returns(data.close, ["SYN1", "SYN2"]), block=12.0)
    s = summary(simulate_wealth(plan, model, 2000, 42), 100_000.0)

    def short(x: float) -> str:
        return f"${x / 1e6:,.2f}M" if abs(x) >= 1e6 else f"${x / 1e3:,.0f}k"

    return {
        "Median after 10 yr": short(s["median_terminal"]),
        "Reach $100k by year 10": f"{s['goal']['p_reach']:.0%}",
        "Hold it at the end": f"{s['goal']['p_hold']:.0%}",
        "End below what you paid in": f"{s['p_below_contributions']:.0%}",
        "Total you pay in": short(s["total_contributed"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--public-demo", action="store_true", help="expect forecast recording to be off")
    parser.add_argument("--shots", default="")
    args = parser.parse_args()
    out = Path(tempfile.mkdtemp()) / "release.json"
    env = {**os.environ}
    subprocess.run(["node", str(ROOT / "tests" / "browser" / "release_smoke.js"), args.url, str(out), args.shots],
                   env=env, check=False)  # fmt: skip
    result = json.loads(out.read_text())
    failures = [c for c in result["checks"] if not c["pass"]]
    want = expected()
    for label, value in want.items():
        shown = (result["shown"].get(label) or {}).get("value")
        ok = shown == value
        print(f"{'PASS' if ok else 'FAIL'} N  {label}: screen {shown!r}, library {value!r}")
        if not ok:
            failures.append({"id": f"number {label}"})
    if args.public_demo:
        ok = result["shown"].get("recording_disabled") and result["shown"].get("record_button") == 0
        print(f"{'PASS' if ok else 'FAIL'} P  public demo: forecast recording disabled")
        if not ok:
            failures.append({"id": "public demo"})
    print(f"model line: {result['shown'].get('model_line')}")
    print(f"coverage warning: {result['shown'].get('coverage_warning')}")
    print(f"\n{'RELEASE CHECK PASSED' if not failures else f'RELEASE CHECK FAILED ({len(failures)})'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
