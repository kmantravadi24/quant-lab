# Quant Research Copilot

An AI assistant (Claude Code, Claude Desktop, or any MCP client) connected to Quant Lab's
validated analytical tools. Ask it a question about a savings plan, and it answers by calling
tools whose numbers come from the tested Future Wealth library. Every answer can be traced and
re-run.

## Why this design

- **Smallest useful form.** It is one read-only MCP server: no agent framework, no model calls
  inside our code, no API key. The client provides the reasoning; Quant Lab provides the
  computations and the evidence.
- **The model never computes a number.** Every figure comes from `quantlab.forecast`, which has
  95 independent tests. The assistant's job is to choose tools, combine results and explain
  them.
- **Read-only by construction.** No tool records forecasts, fetches market data, accepts a file
  path, URL or code, or changes anything. Consequential actions (recording a forecast,
  downloading data) stay behind buttons a person presses in the dashboard. A tool that could
  write would need a real human approval step; a `confirm=true` argument the model can set
  itself is not one.
- **Why not multi-agent?** Every question here is answered by at most a few tool calls
  over deterministic functions. A planner, worker and critic around them would add latency,
  cost and failure modes without adding correctness. The checks a "critic" would do are encoded
  in the tools: refusals, provenance, sensitivity.

## Tools

| Tool | Answers | Notes |
|---|---|---|
| `list_approved_datasets` | Which data can I use? | `synthetic` (always), `frozen` (private snapshot, if present). No provider access. |
| `project_plan` | What could this plan be worth; what is the chance of reaching or holding a goal? | Percentiles, reach and hold probabilities with sampling ranges, deposits vs growth, model suitability. |
| `compare_plan_variants` | What difference does a decision make ($ per month, fee, allocation…)? | Up to 6 variants on the same simulated markets (common random numbers). |
| `contribution_needed` | How much must I save? | At constant assumed returns (arithmetic), and for a stated share of simulated paths (bisection, 500 paths). |
| `model_sensitivity` | How much does the answer depend on the model and history window? | 4 models × history windows; reports the range and the sampling half-width. |
| `validation_results` | How reliable are these models? | Generated from the stored walk-forward validation record. |
| `methodology` | What exactly does the simulation assume? | Verbatim sections of `docs/forecasting.md`. |

Every successful result contains:

- `nature`: the statement is a simulation under stated assumptions, not a forecast;
- `call`: the normalised arguments; passing them back reproduces the result;
- `result_hash`: identifies the numbers;
- `provenance`: dataset fingerprint, synthetic flag, fitted model and history window, paths,
  seed, Quant Lab version and git commit.

A refused request returns `{"ok": false, "error": "...reason..."}`, so the assistant can correct
its call instead of guessing.

## Safety controls

| Risk | Control |
|---|---|
| Fabricated numbers | Server instructions require quoting tool results with their hash and fingerprint; every number is computed by tested code. |
| Overconfident claims | Every result carries `nature`; instructions require reporting model sensitivity for probabilities and never claiming outcomes. |
| Prompt injection | Tools return only numbers computed here and our own documentation, never third-party text; there is no tool through which injected instructions could cause a write. |
| Path traversal and data exfiltration | The dataset is an enum (`synthetic`, `frozen`); no path, URL or code arguments (enforced by `test_t05`). |
| Runaway cost | At most 5,000 paths per call and 6 variants; horizon of at most 50 years; the engine's own work limits apply. |
| Consequential actions | None are exposed. |
| Auditability | With `QUANTLAB_COPILOT_LOG` set, every call is appended to `copilot_audit.jsonl` with its arguments, outcome, result hash and duration. |

## Using it

```bash
pip install -e ".[agent]"          # mcp>=2.3,<3 (also in requirements/lock.txt)
```

Claude Code picks up `.mcp.json` in the repository root, which starts
`python -m quantlab.copilot.server` and logs to `.data_cache/copilot/`. Example questions:

- "With $5,000 now and $500 a month in 60/40 SYN1/SYN2, what is the chance of holding $100k
  after 10 years? How sensitive is that to the model?"
- "Compare $300, $500 and $800 a month, and a 1% fee, for that plan."
- "How much a month do I need for a 75% chance of $250k in 15 years?"
- "How well calibrated were 12-month forecasts in validation?"

## How it is evaluated (Suite T, `tests/qa/test_t_copilot.py`)

1. **Numbers equal the library** (`t01`).
2. **Reproducible from the recorded call**: the same hash, and a different seed gives a
   different hash (`t02`).
3. **12 kinds of bad request** are refused with a reason, not an exception (`t03`).
4. **Comparisons use common random numbers**, and limits are enforced (`t04`).
5. **No write, fetch or execute capability**, checked structurally (`t05`).
6. **Audit log** records successes and refusals (`t06`).
7. **Methodology is verbatim**, and validation matches the stored record (`t07`).
8. **Required contribution and sensitivity** are internally consistent (`t08`).
9. **Only read-only tools are registered** over MCP (`t09`).
10. **End to end over stdio** with a real MCP client and server process (`t10`).

What is **not** tested automatically is the quality of the assistant's *prose*: whether it
quotes faithfully and adds the caveats. That needs a model in the loop. The measurable check is
simple: every number in an answer must appear in a tool result with the same `result_hash`.
Anything else is a fabrication.
