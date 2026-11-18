# Quant Lab: remediation report

Date: 2026-11-17 · Branch: `claude/remediation-v1`, created from the final QA commit `482360f`.
The Investment Lab (`claude/investment-lab-v1`), QA (`claude/qa-validation-v1`) and frozen-study
branches are untouched. Nothing was merged or deployed.

**Verdict: suitable for private research use and for sharing with trusted reviewers. Not approved
for public production use**, because market-data redistribution rights (QA-035), authentication,
hosting and independent operational evidence are still missing (section 10).

## 1. Summary

| | Before (QA, `482360f`) | After (`HEAD`) |
|---|---|---|
| pytest tests | 626: 601 passed, 25 strict expected failures | **669 passed**, 0 expected failures, 0 skipped, 0 failed |
| Python versions | 3.11, 3.12, 3.13 | 3.11, 3.12, 3.13 (and three clean hash-locked environments) |
| Browser checks (Chromium) | 19 passed | **23 passed** |
| Backlog P1 open | 12 | **1** (QA-035, a licensing decision) |
| Backlog P2 open | 17 | **4** limitations or deferred features + 1 partly resolved |
| Frozen study `--verify` | difference 0 | **difference 0** (record and dataset byte-identical) |

All 25 strict expected-failure tests from the QA milestone now pass as ordinary acceptance tests;
each marker was removed in the commit that fixed its issue. One of them had been passing for the
wrong reason (QA-042, section 3).

## 2. Every backlog issue addressed

Commits: `86ac2c7` (Phase A), `9578544` + `377db73` (B), `74a4c48` (C), `45b6e0b` (D),
`e1b0961` (E), `34e58a9` (F), `a2cb1ce` (verification fixes). The status table at the top of
`MASTER_BACKLOG.md` maps each ID to its commit and acceptance tests.

| ID | What was wrong | What changed | Acceptance evidence |
|---|---|---|---|
| QA-001 | Single-asset portfolio offered benchmarks identical to itself | `benchmark_specs` drops any candidate that would simulate identically (`equivalence_key`: same weights, and rebalancing ignored when one asset and no cash). The single-asset benchmark is now 100% of the **largest** holding (was the first listed). Simple portfolios get distinct alternatives from other loaded instruments (at most three) | `test_f02*`, unit `test_benchmarks_*` |
| QA-002 | Investment Lab HTML showed returns as raw decimals | One formatter (`quantlab.reporting.format`) with a unit per statistic, used on screen and in every report | `test_j05*`, `test_j07` |
| QA-003 | Empty "Strategy" section | Report sections render only when they have content | `test_j05c` |
| QA-004 | CSV formula injection | `csv_bytes` neutralises text cells, headers and index labels starting with `= + - @ TAB CR`; numbers untouched. Every CSV export goes through it (trade log and parameter grid included) | `test_k07`, `test_k07b` |
| QA-005 | `start` could escape the cache folder | `validate_request`: plain tickers and ISO dates only, plus a resolved-path containment check | `test_k08` (5 cases), `test_k08b` (6 cases) |
| QA-006 | Unwritable cache crashed the page | Lock or state write failure: the provider is **not** contacted (an unrecorded attempt could repeat on every page view); the verified cache is served with a warning, or a clear error names `QUANTLAB_CACHE_DIR` | `test_c07`, `test_c07b`, `test_c07c` |
| QA-007 | Provider revisions accepted silently | Per-instrument comparison of overlapping closes (relative tolerance 1e-8); new outcome `REVISED`; warning headline, notes and `to_dict()["revisions"]` | `test_b13`, `test_b13b` (also: identical refetch is not a revision) |
| QA-008 | Server paths in user-facing notes | `safe_message` reduces paths to file names in notes and errors | `test_k09`, `test_k09b` |
| QA-009 | NaN shock treated as 0; infinite shock accepted | Stress library refuses non-finite shocks and values | `test_h04`, `test_h04b` (3 cases) |
| QA-010 | Unheld short-history instrument shortened Risk/MC/Stress windows | `risk.holding_returns`: only held instruments set the window; the Risk caption names unheld instruments | `test_b12a` (252, not 149), `test_b12b` (all three pages) |
| QA-011 | Undefined correlation shown as `nan` | Shared formatter shows "n/a"; average correlation is undefined for one holding or zero variance | `test_a17`, `test_a17b` |
| QA-012 | Negative zero ("-0.00") | Formatter strips the sign from values that round to zero | `test_j07b` |
| QA-013 | Validation Lab header claimed one subtraction for all rows | "Computed as" column per row; "Improvement (+ favours trend)" header | `test_i08`, `test_i08b` |
| QA-014 | Study caption said "trend minus buy-and-hold" for loss rows | Caption states the improvement convention; each row says its subtraction. Values unchanged | `test_i09` |
| QA-015 | Uploaded file name injected as HTML | Badge text escaped; uploaded file names must be valid tickers | `test_k10`, `test_k10b` |
| QA-016 | Empty dataset simulated to an empty result | `simulate_portfolio` raises `InsufficientHistoryError` | `test_a20b` |
| QA-018 | Non-finite costs/capital/weights accepted; infinite weight called "leverage" | Finite checks in `ExecutionConfig`, `PortfolioSpec` and `validate_weights` | `test_a11b` (6 cases), `test_a09b` |
| QA-019 | Zero-value stress gave NaN | Refused with a reason; all-cash portfolios still show zero loss | `test_h05` |
| QA-020 | ES tail lost an observation equal to the quantile | Estimator specified (section 4) | `test_d04`, `test_d04b`, property test `test_d12` |
| QA-021 | Docs said every deposit waits one session | Exception documented in the app, analysis record and methodology | `test_p07` |
| QA-022 | Report omitted allocations | New standalone Investment Lab report (section 6) | `test_j05d`, `test_j05e`, browser L22 |
| QA-023 | Risk exports lacked fingerprint and environment | Risk, Monte Carlo and Stress JSON exports carry timestamp, analysed portfolio, model, dataset fingerprint and environment | `test_j06`, `test_j06b` |
| QA-024 | Risk insights for Portfolio A only | Selector over every compared portfolio plus a side-by-side table | `test_n04`, browser L19 |
| QA-025 | Covariance rounded to four decimals | Three significant figures | `test_j07c` |
| QA-026 | Separate portfolio definitions per page | See section 5 | `tests/qa/test_n_consistency.py`, browser L20 |
| QA-030 | No uncertainty or sensitivity in Monte Carlo | See section 7 | `tests/qa/test_p_model_honesty.py`, browser L21 |
| QA-031 | Exports did not package data | Price bundle for synthetic and user data; provider data refused | `test_o01` (bit-exact round trip), `test_o02`, `test_o03` |
| QA-032 | No lock file or clean-machine check | Hash-locked `requirements/lock.txt` and `requirements/study-py313.txt`; `tools/verify_clean_env.sh`; CI jobs `locked` and `study-exact` | `test_o05`, `test_o06`; section 8 |
| QA-036 | Internal field names in reports | Plain-language labels everywhere a person reads; statistics CSV gains name and unit columns | `test_j05`, `test_j05d` |
| QA-038 | Fixed cache location | `QUANTLAB_CACHE_DIR` | `test_o04` |
| QA-041 | No dependency audit in CI | `pip-audit` of both lock files in CI, plus a weekly scheduled run | CI job `audit` |

Other improvements made while verifying: risk explanations on the Risk page (diversification
metrics and a plain guide to volatility, VaR, ES, correlation and cash); loss deltas no longer show
a rising arrow; Monte Carlo ranges no longer truncated; the report chart names every series.

## 3. Defects found during remediation

| ID | Finding | Resolution |
|---|---|---|
| QA-042 | The strict xfail pinned for QA-004 passed for the wrong reason: it built `PortfolioSpec(..., "never", "never", ...)`, an invalid frequency, which raised before the CSV code ran. QA-004 itself was real (the characterisation test showed the formula written verbatim on the baseline). | Input corrected. Every former xfail now passes on the line it asserts. |
| QA-043 | The study reproduces bit for bit only with NumPy 2.5.3 / pandas 3.0.5, the versions that produced it. With the current locked versions the largest difference is 4.17e-14, and the untouched QA baseline gives exactly the same 4.17e-14 in that environment. | `requirements/study-py313.txt` and CI job `study-exact` (asserts difference 0). |
| QA-044 | Pandas' default CSV parser can differ in the last bit, so a price bundle did not reproduce an analysis exactly (2e-15). | User CSVs are now parsed as text and converted with Python's correctly rounded `float`. The cache and frozen-snapshot loader is deliberately unchanged. |
| QA-045 | A Python 3.11 venv ships `setuptools` 79.0.1 with two advisories; it is not a project dependency. | Open (operational). Both lock files audit clean. |

## 4. Changes to financial methodology

1. **Expected shortfall (QA-020).** Specification, written into `historical_es`:
   `ES = -mean{ r_i : r_i <= Q + 1e-12 }`, where `Q` is the type-7 linear-interpolation empirical
   quantile at `1 - confidence`, exactly as before. Observations equal to the quantile belong to
   the tail even when floating-point evaluation of `1 - confidence` puts `Q` a rounding error
   below them. VaR is unchanged. A first attempt, which instead rounded `1 - confidence` to 12
   decimals, moved nine exploratory `var_95` values in the published study by ≤1.7e-17. It was
   rejected so that the study stays bit-exact. The tolerance version gives difference 0.
2. **Analysis window of fixed-weight pages (QA-010).** Only instruments with a positive weight
   limit the window on Risk, Monte Carlo and Stress. Before, every loaded instrument did.
3. **Benchmarks (QA-001).** "100% X" now uses the largest holding, not the first listed.
   Alternatives that would simulate identically are not offered.
4. **Inputs refused rather than coerced:** non-finite shocks, weights, costs and capital; zero-value
   stress portfolios; empty datasets.

Unchanged: the transaction engine, fills, costs, contributions, time- and money-weighted returns,
volatility, covariance, drawdowns, VaR, the Monte Carlo generator and the bootstrap.

## 5. Portfolio consistency (QA-026)

- One definition, `PortfolioSpec`. The Investment Lab publishes its portfolios to the session.
  Risk Analytics, Monte Carlo and Stress Test offer them in a "Portfolio to analyse" selector,
  defaulting to the first Investment Lab portfolio when one exists. Custom weights remain
  available as a separate option.
- The two models are **not** presented as the same. The Investment Lab is an account simulation
  (next-open fills, costs, drift, contributions). The other pages are fixed-weight statistical
  models and carry a "MODEL: FIXED WEIGHTS" badge saying so. Investment Lab risk insights show
  both, labelled HISTORICAL and ESTIMATE, and explain why they differ.
- One implementation of the fixed-weight estimate (`quantlab.risk.estimate_risk`) serves Risk
  Analytics and the Investment Lab. `test_n03` recomputes the Risk page's volatility and drawdown
  independently from the published weights and the page's own window. `test_n05` shows that both
  pages give identical estimates on the same window.

## 6. Exports and reporting

The Investment Lab HTML report is a standalone document, with no scripts and no external
requests, and every user string escaped. It contains:

- key findings, each traceable to a number in the tables
- what was simulated: evaluation period, funding, costs and order timing
- allocations and maintenance for every portfolio
- the value chart with money paid in
- results grouped as outcome, returns, risk and maintenance, each in its own unit
- a signed comparison with every alternative, with the subtraction stated
- fixed-weight risk estimates marked ESTIMATE, separate from HISTORICAL results
- limitations, a glossary, and reproducibility metadata (fingerprint, source, versions, commit)

Screenshots are in `evidence/remediation/`.

## 7. Model honesty (QA-030)

Monte Carlo now shows:

- a 95% Wilson interval for path-count noise next to each probability (matches SciPy to 1e-12)
- a visible "Not a forecast" notice
- a model-dependence table that asks the same question over every available lookback (3, 5,
  10 years, all) and all three resampling methods, with a plain reading of the spread
- an assumptions tab: fixed weights, lump sum, cash at 0%

Exports include the intervals and the sensitivity table. A test with a regime change in the
history confirms that the effect of the lookback choice exceeds three times the widest sampling
interval, and that more paths do not remove it.

## 8. Reproducibility and clean environments

| Check | Result |
|---|---|
| `tools/verify_clean_env.sh` (fresh venv, `--require-hashes` lock, `pip check`, Ruff, full suite, study) on Python 3.11.18, 3.12.3, 3.13.18 | PASS on all three (study difference 4.17e-14, within tolerance) |
| Study environment (`study-py313.txt`, fresh venv) | **difference 0** |
| Untouched QA baseline `482360f` in the current locked environment | difference 4.17e-14: the same, so version-driven |
| `experiments/` and `reports/` versus `482360f` | byte-identical (`git diff` empty) |
| Price bundle round trip through the upload path | identical fingerprint and every statistic bit for bit |
| Wheel build and clean import | PASS; wheel holds no data or tests |

## 9. Security verification

| Area | Evidence |
|---|---|
| CSV injection | `test_k07*`: formulas neutralised in headers, cells and index; negative numbers unchanged |
| HTML injection | `test_k05`, `test_k10*`: reports and badge escape all user strings; upload names validated |
| Path traversal | `test_k08*`: 11 hostile `start`/ticker values refused; nothing written |
| Information leakage | `test_k09b`: no server paths in notes or errors |
| Unwritable storage | `test_c07*`: no crash, no provider contact, clear message |
| Revised data | `test_b13*`: reported, never silent |
| Dependencies | `pip-audit` of both lock files: no known vulnerabilities (2026-11-17); CI job `audit`, weekly |
| Code scan | `test_k11`: no `eval`/`exec`/`pickle`/`shell=`; `test_k12`: the nine raw-HTML calls (four files) are inventoried and reviewed; `test_k13`: no secrets in tracked files |

## 10. Remaining issues and production blockers

| ID | Status | Why it is not closed |
|---|---|---|
| QA-035 | **Blocks public production** | A licensing decision. No redistribution right is claimed and provider data is never bundled. |
| None | **Blocks public production** | No authentication, rate limiting, monitoring or error reporting. Nothing has been deployed, so hosted behaviour is unverified (see `docs/DEPLOYMENT.md`). |
| QA-031 | Partly resolved | Provider prices cannot be packaged until QA-035 is settled. |
| QA-027 | Open, deferred | Contribution-aware Monte Carlo is a new wealth-planning feature. The page now says "a lump sum, no contributions". |
| QA-028 | Open, disclosed | Cash earns 0% everywhere; stated on every page and in reports. |
| QA-029 | Open | No historical crisis replay. |
| QA-033 | Open, process | The study's evaluation period has been reused; any new claim needs fresh data. |
| QA-017 | Open (P3) | A partial provider response fails the whole selection (the cache is still served). |
| QA-039 | Open | Forward paper tracking is a future milestone. |
| QA-040 | Open | No WCAG audit; only Chromium naming, focus and reflow checks. |
| QA-045 | Open (operational) | Upgrade `setuptools` in deployment images. |

## 11. Browser, visual evidence and performance

**Browser** (`tests/browser/run.sh`, Chromium, synthetic data, local server): 23 passed, 0 failed
(`evidence/remediation/browser_results.json`). The 19 original checks show the same on-screen
values as at `482360f` (for example a final value of 257,336 for the default portfolio, and
223,990 after edits), so the Investment Lab's numbers did not change. New checks:

| Check | What it proves |
|---|---|
| L19 | Investment Lab risk insights switch to any portfolio and compare all side by side |
| L20 | Risk Analytics opens on the Investment Lab portfolio, with its weights and the fixed-weight model badge |
| L21 | Monte Carlo shows the 95% sampling range on each probability and the model-dependence table |
| L22 | The downloaded report contains findings, allocations, period, comparison, limitations and reproducibility metadata, with no `nan` |

Screenshots (`evidence/remediation/`): `risk_shared_portfolio.png`,
`monte_carlo_model_dependence.png`, `invest_risk_insights.png`, `invest_phone.png` (390 px:
no horizontal overflow, no clipped labels), `report_top.png`, `report_results.png`, and the
synthetic-data report itself (`investment_lab_report_synthetic.html`).

**Performance.** Same machine, same synthetic inputs, best of 5 (library) or 3 (pages, Streamlit
`AppTest`) runs, measured one after the other with nothing else running. Indicative only.

| Operation | Before (`482360f`) | After |
|---|---:|---:|
| trend backtest, 15y | 0.03 s | 0.03 s |
| Investment Lab comparison, 4 portfolios, 15y | 0.24 s | 0.24 s |
| Monte Carlo 5,000 x 252 | 0.05 s | 0.06 s |
| Monte Carlo 20,000 x 252 | 0.21 s | 0.22 s |
| page overview (AppTest, cold) | 0.23 s | 0.27 s |
| page invest (AppTest, cold) | 0.42 s | 0.77 s |
| page risk (AppTest, cold) | 0.27 s | 0.28 s |
| page monte_carlo (AppTest, cold) | 0.29 s | 0.90 s |
| page stress (AppTest, cold) | 0.22 s | 0.29 s |
| page backtest (AppTest, cold) | 0.47 s | 0.50 s |
| page research (AppTest, cold) | 3.14 s | 3.74 s |

Library operations are unchanged within noise. Two pages are slower because they do more:

- the Investment Lab computes a risk estimate for every compared portfolio and builds the report
- Monte Carlo runs the model-dependence table: 9 to 12 extra simulations of up to 2,000 paths

Both stay under one second. The full pytest suite takes about 2.5 to 3 minutes per Python version
(about 2 minutes before, with 43 fewer tests).

## 12. Git and CI

Branch `claude/remediation-v1`, from `482360f`, committed in reviewable groups:

| Commit | Content |
|---|---|
| `86ac2c7` | Phase A: financial correctness and research labels |
| `9578544`, `377db73` | Phase B: one portfolio definition, distinct benchmarks (plus a lint fix) |
| `74a4c48` | Phase C: security and resilience |
| `45b6e0b` | Phase D: reports and formatting |
| `e1b0961` | Phase E: reproducibility and operations |
| `34e58a9` | Phase F: model honesty |
| `a2cb1ce` | Verification fixes, browser checks, documentation |
| (this commit) | This report and evidence |

Local verification of the final code before pushing:

| Check | Result |
|---|---|
| pytest, Python 3.13.18 (NumPy 2.5.3, pandas 3.0.5) | 669 passed, 0 failed, 0 xfail, 0 skipped |
| pytest, Python 3.12.3 (NumPy 2.5.5, pandas 3.1.1) | 669 passed (4 pre-existing pandas warnings, as at baseline) |
| pytest, Python 3.11.18 (NumPy 2.4.6, pandas 3.1.1) | 669 passed (same 4 warnings) |
| Clean hash-locked environments (`tools/verify_clean_env.sh`), 3.11.18 / 3.12.3 / 3.13.18 | PASS on the final code: 669 passed each, `pip check`, Ruff, study difference 4.17e-14 |
| Ruff | clean |
| Wheel build and clean import | PASS |
| Frozen study `--verify` | PASS, difference 0 |
| Browser | 23 passed |

The CI results for the pushed commit are recorded in the final message of this milestone.
