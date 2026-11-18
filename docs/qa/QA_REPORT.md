# Quant Lab: independent QA and validation report

> **Historical record.** This report describes the application as it was at `482360f`, before
> remediation. For what has since been fixed, and what remains open, see
> [REMEDIATION_REPORT.md](REMEDIATION_REPORT.md) and the status table at the top of
> [MASTER_BACKLOG.md](MASTER_BACKLOG.md).

Date: 2026-11-17 · Branch: `claude/qa-validation-v1` · Role: validation, not development.
**No product code was changed.** Defects were recorded, not repaired.

Two words are used carefully throughout. **Verified** means an automated test in this repository
reproduced the result against an independent reference or hand arithmetic. **Observed** means it was
seen (manually, or once in a live run) and is not pinned by a deterministic test.

## 1. Executive summary

**Verdict: fit for limited private research use. Not ready for production (public or shared use).**

- The core is sound. Trade accounting, cash reconciliation, time-weighted and money-weighted
  returns, volatility, covariance, risk contributions, VaR/ES, drawdown and the stress arithmetic
  all agree with independent references. The frozen SPY study still reproduces exactly
  (429 values, largest difference 0). **No P0 finding.**
- The problems are at the edges: how results are labelled, exported, kept consistent between pages,
  and how the system behaves when storage or the data provider misbehaves.
- 40 backlog entries: 0 P0, 12 P1, 17 P2, 11 P3. Twenty-one are pinned by 25 strict
  expected-failure tests, so each fix is checked automatically.
- 626 automated tests (402 existing + 224 new) pass or expectedly fail identically on Python 3.11,
  3.12 and 3.13; 19 real-browser checks pass.

The three findings most likely to mislead a user today: the same portfolio is measured over
different windows on different pages (QA-010, QA-026); two research tables state the wrong sign
convention in their headings (QA-013, QA-014); and exported reports show returns as raw decimals
(QA-002).

## 2. Exact Git commit and environment

| Item | Value |
|---|---|
| Base commit under test | `ef488d54a919d3eab93b5792186d3716d688076b` ("Investment Lab page…"), CI run 44004058885 green |
| QA milestone | the commit on `claude/qa-validation-v1` that adds this file; it changes only `tests/`, `docs/qa/`, `pyproject.toml` (one dev dependency) and `.github/workflows/ci.yml` (one job) |
| Production code changed | none (`git status --short src app` is empty) |
| OS | Linux 6.18 (x86-64 container) |
| Python 3.13.18 | NumPy 2.5.3, pandas 3.0.5, Streamlit 1.67.0, Plotly 7.1.0, SciPy 1.18.1, pytest 9.2.0, Hypothesis 6.170.15, exchange_calendars 4.13.3 |
| Python 3.12.3 | NumPy 2.5.5, pandas 3.1.1 |
| Python 3.11.18 | NumPy 2.4.6, pandas 3.1.1 |
| Lint | Ruff 0.16.9, clean |
| Browser | Chromium via Playwright 1.63.0, Node 22 |
| Frozen dataset | fingerprint `76f294e718c47ee2`, every file matches its SHA-256 in `experiments/MANIFEST.json` |

Different NumPy/pandas versions across the three interpreters gave identical test outcomes.

## 3. Baseline test results

Before any QA work: clean tree at `ef488d5`, 402 tests collected, all passing; Ruff clean; frozen
study `--verify` PASS; CI green on 3.11/3.12/3.13.

## 4. Tests added and tests executed

| | Count |
|---|---:|
| Existing tests (unchanged) | 402 |
| New pytest tests (`tests/qa/`) | 224 (143 test functions, parametrised) |
| New browser checks (`tests/browser/smoke.js`) | 19 |
| **Executed** | **645** |

New supporting code: `tests/qa/reference.py` (plain-Python reference implementations, no pandas
statistics), `tests/fixtures/app.py` (offline page harness). Property-based tests use Hypothesis
with `derandomize=True`, so every run draws the same 150 examples. All tests are offline: a test
blocks sockets and renders six pages to prove it.

## 5. Pass/fail totals by category

| Suite | PASS | XFAIL | FAIL | SKIP |
|---|---:|---:|---:|---:|
| A Inputs / adversarial UI | 54 | 7 | 0 | 0 |
| B, C Data, freshness, cache, concurrency | 33 | 3 | 0 | 0 |
| D Financial mathematics | 13 | 1 | 0 | 0 |
| E, F Accounting, benchmarks | 28 | 1 | 0 | 0 |
| G, H Monte Carlo, stress | 24 | 2 | 0 | 0 |
| I, J Research integrity, exports | 17 | 7 | 0 | 0 |
| K, M Security, operations | 30 | 4 | 0 | 0 |
| L Browser | 19 | 0 | 0 | 0 |
| Existing suite | 402 | 0 | 0 | 0 |
| **Total** | **620** | **25** | **0** | **0** |

Every XFAIL is `strict=True` and names a backlog ID. "FAIL 0" does not mean "no defects"; it means
every confirmed defect is pinned. See `TEST_MATRIX.md` for the per-test register.

## 6. Independently validated mathematical calculations

| Calculation | Independent method | Tolerance | Result |
|---|---|---|---|
| Simple returns, compounding, total return | Hand arithmetic; pure-Python loop | 1e-12 | Verified |
| Annualised volatility (sample, ×√252), CAGR, Sharpe | Hand arithmetic; `reference.py`; Hypothesis over random series | rel 1e-9 | Verified |
| Covariance matrix | Pure-Python double loop; symmetry; non-negative `wᵀΣw` for random weights | 1e-12 | Verified |
| Portfolio volatility and Euler risk contributions | Two-asset closed form; contributions sum to volatility | 1e-10 | Verified |
| Historical VaR and expected shortfall | Hand-ranked examples; reference quantile with linear interpolation | 1e-12 | Verified, except tie edge case QA-020 |
| Maximum drawdown depth and duration | Hand-built paths; O(n²) reference | 1e-12 | Verified |
| Cash ledger | Replayed every fill from the trade log: `cash −= shares×price×(1+slip) + fees`, fractional and whole shares, fixed fees | 1e-6 currency units | Verified |
| No leverage, cash never negative | Asserted on every session of every simulation, including a 40-year horizon | exact | Verified |
| Time-weighted return with contributions | Unitised-fund reference (units issued at the pre-flow valuation) | 1e-12 | Verified |
| Money-weighted return (XIRR) | Closed forms (single period, doubling); independent bisection on dated flows, actual/365 | rel 1e-7 | Verified |
| Scale invariance | Doubling all amounts doubles values, leaves returns unchanged | 1e-9 | Verified |
| Stress loss | Reference: $100k; SPY 20% −30%, QQQ 20% −35%, BND 33.3% −5%, cash 26.7% → −$14,665 | $0.01 | Verified |
| Monte Carlo | Same seed → identical paths; each step is an observed return; event probabilities equal exact counts; seed spread shrinks ≈ 1/√paths | exact / statistical | Verified (invariants). Path generator not re-implemented: INCONCLUSIVE as a full independent check |
| Multiple-testing adjustments | Bonferroni and Holm by hand | 1e-12 | Verified |
| Bootstrap | Same seed → same interval; paired resampling gives exactly 0 for identical series | exact | Verified |
| Published study | Re-run from the frozen dataset: 429 numbers, largest absolute difference 0; config hash and protocol unchanged | exact | Verified |

### Monte Carlo sensitivity experiment (model risk)

Run on the private reference data; Results computed on the private reference dataset are not published in this copy: redistribution
rights for that data are not established. The code that produces them is included; run it on data
you are licensed to use.
Consequence: QA-030 (uncertainty and lookback sensitivity are not communicated).

## 7. Identified defects

Full detail, reproduction and acceptance tests are in `MASTER_BACKLOG.md`. Verified defects:

- **Consistency:** QA-010 unheld instrument shortens the risk window; QA-001 duplicate benchmarks.
- **Labelling:** QA-013, QA-014 wrong sign convention in headings; QA-002 raw decimals; QA-003
  empty section; QA-011 `nan`; QA-012 negative zero; QA-022 allocations missing from HTML.
- **Resilience:** QA-006 unwritable cache crashes; QA-007 revised history accepted silently;
  QA-016 empty dataset simulates; QA-009, QA-018 non-finite inputs accepted; QA-019 NaN percentage.
- **Security:** QA-004 CSV formula injection; QA-015 unescaped upload name in HTML; QA-005 path
  escape (library only); QA-008 server path in user-facing notes.
- **Numerical edge:** QA-020 expected-shortfall tie handling.
- **Documentation:** QA-021 contribution timing sentence.

Observed, not pinned by a test: QA-025 covariance rounding (read from the format string), QA-037
provider returning a closed session without a close (seen once, live).

## 8. Known modelling limitations

Not bugs; the model is narrower than a user is likely to assume.

| ID | Limitation |
|---|---|
| QA-026 | Two portfolio conventions: engine-simulated account (Investment Lab) vs constant-weight return series (Risk, Monte Carlo, Stress) |
| QA-027 | Monte Carlo is lump-sum, constant-weight; no contributions, costs or rebalancing |
| QA-028 | Cash earns 0% |
| QA-029 | Stress scenarios are instantaneous user-entered shocks; no historical episodes, no correlation change |
| QA-030 | No sampling error on probabilities or tail statistics; lookback sensitivity hidden |
| QA-033 | The study's out-of-sample period has now been examined several times; adjustments cover three metrics, not reuse |
| — | Prices are total-return adjusted: dividends are assumed reinvested at no cost and with no tax; `test_e09` records this as a stated assumption |
| — | Historical VaR/ES assume the future resembles the sample; no parametric or extreme-value alternative |
| — | Fills at the next open with a fixed slippage in basis points: no market impact, no partial fills, no halts |

## 9. Reproducibility findings

- **Verified:** the study reproduces bit-for-bit from the frozen dataset; the record's file name
  equals the hash of its protocol; dataset files match their checksums; a live refresh cannot touch
  the frozen inputs; a saved portfolio file reloads to the same result in the browser.
- **Verified:** Investment Lab analysis records carry schema, UTC timestamp, allocations, costs,
  window, data fingerprint, source and software version.
- **Gap:** Risk, Monte Carlo and Stress exports lack fingerprint and version (QA-023).
- **Gap:** no export packages the prices themselves (QA-031); together with QA-007 an analysis on
  live data may not be exactly repeatable later.
- **Gap:** no lock file and no clean-machine reproduction (QA-032). Mitigating evidence: identical
  outcomes across three interpreter/NumPy/pandas combinations.
- **Constraint:** the frozen dataset is private (QA-035). Without it the study cannot be reproduced;
  CI skips that step when the folder is absent. See `REPRODUCIBILITY.md`.

## 10. Security and operational findings

Security (local, harmless inputs only; no production system was touched):

| Check | Result |
|---|---|
| Malformed, binary, wrong-delimiter, non-numeric, formula-bearing uploads | PASS: refused with a reason, no traceback |
| Upload size | PASS: server limit 20 MB; 200,000 rows parse in under a second |
| HTML report escaping; self-contained (no scripts, no external URLs) | PASS |
| JSON exports are strict JSON (NaN/inf → null) | PASS |
| No `eval`/`exec`/`pickle`/`shell=`; subprocess only for fixed git commands in one module | PASS |
| Secrets scan of tracked files | PASS: none found |
| No network needed for synthetic or uploaded data | PASS |
| CSV formula injection | XFAIL QA-004 |
| Markup injection through an uploaded file name | XFAIL QA-015 |
| Path traversal through `start` (library API) | XFAIL QA-005 |
| Server path disclosure in notes | XFAIL QA-008 |
| Dependency vulnerabilities (`pip-audit`, project environment, 2026-11-17) | PASS: none known. Not in CI (QA-041) |
| Authentication, rate limiting, multi-tenant isolation | NOT TESTED: none exists; the app is single-user by design |

Operations (measured on this machine, 15 years of daily data; indicative only):

| Operation | Time |
|---|---:|
| Trend backtest, one asset | 0.02 s |
| Investment Lab, four portfolios, monthly contributions | 0.20 s |
| Monte Carlo 5,000 × 252, block bootstrap | 0.04 s |
| Monte Carlo 20,000 × 252 | 0.19 s |
| Slowest page, cold render under test | about 5 s (Research) |
| Full pytest suite | about 2 minutes |

Five times the history costs well under fifteen times the time (no quadratic step). 12 simultaneous
requests for the same data cause one download. An interrupted or corrupted cache write never loses
the verified dataset. Not covered: read-only storage (QA-006), fixed cache path (QA-038).

## 11. Production-readiness gaps

1. Data rights for anything served publicly (QA-035).
2. One portfolio definition across pages (QA-026, QA-010).
3. Correct labels and units wherever a number leaves the screen (QA-002, QA-013, QA-014, QA-022).
4. Safe exports and escaped HTML (QA-004, QA-015).
5. Graceful behaviour on read-only or ephemeral storage (QA-006, QA-038).
6. Detection of revised history (QA-007).
7. Pinned environment and clean-machine reproduction (QA-032).
8. No monitoring, error reporting, authentication or usage limits: none exists and none was tested.

## 12. Residual risks and untested areas

- Live provider behaviour is covered only by scripted responses. One live anomaly was observed
  (QA-037). Correctness of the provider's adjusted prices is untested: there is no second source.
- Chromium only; no screen reader, contrast or cross-browser evidence (QA-040).
- Concurrency tested with threads in one process on Linux, not multiple processes or hosts.
- No load, soak or memory-growth testing; no hosted deployment was exercised.
- Monte Carlo path generation is checked by invariants, not by a second implementation.
- Hypothesis explores 150 fixed examples per property: strong evidence, not proof.
- Timing figures are from one shared container and are not benchmarks.
- The tests characterise current behaviour of defects; if a fix changes behaviour in a different
  way than expected, the paired characterisation test will need a deliberate update.

## 13. Recommended release-blocking criteria

A release beyond private use should require all of the following:

1. Every P1 closed, its strict-XFAIL marker removed, and the test passing.
2. Zero unexpected failures on Python 3.11, 3.12, 3.13; Ruff clean; wheel builds and imports.
3. Frozen study `--verify` PASS with fingerprint `76f294e718c47ee2` and difference 0.
4. Browser job green.
5. One portfolio produces reconciling figures on every page (new test for QA-026).
6. Every export carries units, allocations, data fingerprint and software version.
7. A lock file, and the suite passing from it on a clean machine.
8. A written data-rights position for the data the release serves.
9. `pip-audit` clean at release time.
10. No change to `src/quantlab/{backtesting,execution,portfolio,analytics,risk}` without the Suite D
    and E tests passing unchanged.
