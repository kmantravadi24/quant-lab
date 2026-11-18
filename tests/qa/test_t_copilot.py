"""Suite T: the Quant Research Copilot tools and their MCP server.

Success criteria for the copilot are measurable: every number equals the library's,
every result is reproducible from its recorded call, every refusal is explicit, nothing
can be written or fetched, and the protocol path works end to end.
"""

import asyncio
import inspect
import json
import os
import sys
from pathlib import Path

import pytest

from quantlab.copilot import tools
from quantlab.forecast import (
    WealthPlan,
    build_model,
    goal_probabilities,
    monthly_returns,
    simulate_wealth,
)
from quantlab.forecast.validation import summarise_record

ROOT = Path(__file__).resolve().parents[2]
PLAN = {"dataset": "synthetic", "weights": {"SYN1": 0.6, "SYN2": 0.4}, "initial_amount": 5000.0,
        "contribution": 500.0, "horizon_years": 10.0, "goal": 100_000.0}  # fmt: skip


def test_t01_numbers_equal_the_library():
    out = tools.project_plan(**PLAN)
    assert out["ok"] and out["tool"] == "project_plan"
    data = tools._dataset("synthetic")
    plan = WealthPlan({"SYN1": 0.6, "SYN2": 0.4}, 5000.0, 500.0, name="copilot plan")
    model = build_model("block_bootstrap", monthly_returns(data.close, ["SYN1", "SYN2"]), block=12.0)
    direct = goal_probabilities(simulate_wealth(plan, model, 2000, 42), 100_000.0)
    got = out["result"]["summary"]["goal"]
    assert got["p_hold"] == direct["p_hold"] and got["p_reach"] == direct["p_reach"]
    assert got["p_hold_interval"] == list(direct["p_hold_interval"])


def test_t02_results_are_reproducible_from_their_recorded_call():
    first = tools.project_plan(**PLAN)
    again = tools.project_plan(**first["call"])
    assert again["result_hash"] == first["result_hash"]
    other = tools.project_plan(**{**PLAN, "seed": 43})
    assert other["result_hash"] != first["result_hash"]
    prov = first["provenance"]
    assert prov["dataset_synthetic"] is True and len(prov["dataset_fingerprint"]) == 16
    assert prov["model"]["window_months"] == 239 and prov["paths"] == 2000 and prov["seed"] == 42
    assert "Not a forecast" in first["nature"]


@pytest.mark.parametrize("bad, reason", [
    ({"dataset": "../../etc/passwd"}, "Unknown dataset"), ({"dataset": "yahoo"}, "Unknown dataset"),
    ({"weights": {"SYN1": 0.9, "SYN2": 0.4}}, "leverage"), ({"weights": {"ZZZ": 1.0}}, "not in the dataset"),
    ({"weights": {}}, "weights must be"), ({"paths": 50_000}, "paths must be"), ({"paths": 2.5}, "paths must be"),
    ({"model": "neural_net"}, "model must be"), ({"lookback_months": 6}, "lookback_months"),
    ({"horizon_years": 80}, "horizon_years"), ({"contribution": float("nan")}, "finite"),
    ({"goal": -5}, "goal must be"),
])  # fmt: skip
def test_t03_bad_requests_are_refused_with_a_reason_not_an_exception(bad, reason):
    out = tools.project_plan(**{**PLAN, **bad})
    assert out["ok"] is False and reason in out["error"], out


def test_t04_comparisons_use_common_random_numbers_and_are_bounded():
    out = tools.compare_plan_variants(dataset="synthetic", weights={"SYN1": 0.6, "SYN2": 0.4},
                                      variants={"$200": {"contribution": 200.0}, "$1000": {"contribution": 1000.0}},
                                      goal=100_000.0, paths=1000)  # fmt: skip
    assert out["ok"] and list(out["result"]) == ["base", "$200", "$1000"]
    losses = {k: v["summary"]["p_below_contributions"] for k, v in out["result"].items()}
    assert len(set(losses.values())) == 1  # same markets and mix: identical loss frequency
    too_many = tools.compare_plan_variants(dataset="synthetic", weights={"SYN1": 1.0},
                                           variants={str(i): {} for i in range(7)})  # fmt: skip
    assert not too_many["ok"] and "1 to 6" in too_many["error"]
    sneaky = tools.compare_plan_variants(dataset="synthetic", weights={"SYN1": 1.0},
                                         variants={"x": {"__class__": "y"}})  # fmt: skip
    assert not sneaky["ok"] and "unknown fields" in sneaky["error"]


def test_t05_no_tool_can_write_fetch_or_execute():
    banned = {"path", "file", "filename", "url", "code", "command", "directory", "folder", "confirm"}
    for fn in tools.TOOLS:
        names = set(inspect.signature(inspect.unwrap(fn)).parameters)
        assert not names & banned, (fn.__name__, names & banned)
    source = (ROOT / "src" / "quantlab" / "copilot" / "tools.py").read_text()
    for forbidden in ("ForecastLedger", "YFinanceProvider", "LiveDataStore", "subprocess", "eval(", "exec("):
        assert forbidden not in source, forbidden


def test_t06_every_call_is_audited_when_logging_is_on(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTLAB_COPILOT_LOG", str(tmp_path))
    good = tools.methodology(topic="limitations")
    bad = tools.methodology(topic="secrets")
    lines = [json.loads(x) for x in (tmp_path / "copilot_audit.jsonl").read_text().splitlines()]
    assert [x["ok"] for x in lines] == [True, False]
    assert lines[0]["result_hash"] == good["result_hash"] and "topic must be" in lines[1]["error"]
    assert not bad["ok"]


def test_t07_methodology_is_quoted_verbatim_and_validation_matches_the_record():
    text = tools.methodology(topic="event_order")["result"]["text"]
    assert text.startswith("## 2.") and text in (ROOT / "docs" / "forecasting.md").read_text()
    out = tools.validation_results()
    real = [p for p in sorted((ROOT / "experiments" / "results").glob("forecast_validation_*.json"))
            if "synthetic" not in p.stem]  # fmt: skip
    if not real:  # public copy: the restricted-data record is withheld, and the tool says so
        assert not out["ok"] and "No real-data validation record" in out["error"]
        return
    path = real[-1]
    expected = json.loads(json.dumps(summarise_record(json.loads(path.read_text()))))
    assert out["result"]["summary"] == expected


def test_t08_required_contribution_and_sensitivity():
    need = tools.contribution_needed(dataset="synthetic", weights={"SYN1": 0.6, "SYN2": 0.4}, goal=100_000.0,
                                     initial_amount=5000.0, probability=0.75)  # fmt: skip
    assert need["ok"] and need["result"]["simulated"]["probability"] >= 0.75
    assert set(need["result"]["constant_return"]) == {"0.0400", "0.0600", "0.0800"}
    sens = tools.model_sensitivity(dataset="synthetic", weights={"SYN1": 0.6, "SYN2": 0.4}, goal=100_000.0,
                                   initial_amount=5000.0)  # fmt: skip
    rows = sens["result"]["rows"]
    assert sens["ok"] and {r["model"] for r in rows} == {"iid_bootstrap", "block_bootstrap", "ewma_filtered", "gaussian_iid"}
    lo, hi = sens["result"]["p_hold_goal_range"]
    assert lo == min(r["p_hold_goal"] for r in rows) and hi == max(r["p_hold_goal"] for r in rows)


def test_t09_mcp_server_registers_only_read_only_tools():
    from quantlab.copilot.server import server

    async def go():
        listed = await server.list_tools()
        result = await server.call_tool("project_plan", PLAN)
        return listed, result

    listed, result = asyncio.run(go())
    assert {t.name for t in listed} == {fn.__name__ for fn in tools.TOOLS}
    assert all(t.annotations.read_only_hint and not t.annotations.destructive_hint for t in listed)
    body = json.loads(result.content[0].text)
    assert body["ok"] and body["result_hash"] == tools.project_plan(**PLAN)["result_hash"]


def test_t10_end_to_end_over_stdio():
    """The real protocol path: a separate server process, an MCP client, a tool call."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    params = StdioServerParameters(command=sys.executable, args=["-m", "quantlab.copilot.server"], env=env, cwd=ROOT)

    async def go():
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            called = await session.call_tool("methodology", {"topic": "limitations"})
            return listed, called

    listed, called = asyncio.run(go())
    assert len(listed.tools) == 7
    body = json.loads(called.content[0].text)
    assert body["ok"] and "Hindsight and survivorship" in body["result"]["text"]
