# Quant Lab: master defect and limitation backlog

Produced by the QA milestone on 2026-11-17 (base commit `ef488d5`, QA branch `482360f`).
**Updated after the remediation campaign** on branch `claude/remediation-v1` (same day): the
status table below is current; the tables after it are the original QA findings, kept verbatim
as the record of what was found. Details of every change are in `docs/qa/REMEDIATION_REPORT.md`.

## Current status (after remediation)

Resolved means: code changed, the strict expected-failure test for the issue now passes as an
ordinary acceptance test (marker removed), and the full suite passes on Python 3.11 to 3.13.

| ID | Priority | Status | Commit | Acceptance test(s) now passing |
|---|---|---|---|---|
| QA-001 | P1 | Resolved | `9578544` | `test_f02_*`, `test_f02b_*`, `tests/unit/test_compare.py` |
| QA-002 | P1 | Resolved | `45b6e0b` | `test_j05_*`, `test_j05b_*`, `test_j07_*` |
| QA-004 | P1 | Resolved | `74a4c48` | `test_k07_*`, `test_k07b_*` (its QA-era input was invalid; corrected, see QA-042) |
| QA-006 | P1 | Resolved | `74a4c48` | `test_c07_*`, `test_c07b_*`, `test_c07c_*` |
| QA-007 | P1 | Resolved | `74a4c48` | `test_b13_*`, `test_b13b_*` |
| QA-010 | P1 | Resolved | `86ac2c7` | `test_b12a_*`, `test_b12b_*`, `test_n05_*` |
| QA-013 | P1 | Resolved | `86ac2c7` | `test_i08_*`, `test_i08b_*` |
| QA-014 | P1 | Resolved | `86ac2c7` | `test_i09_*` |
| QA-015 | P1 | Resolved | `74a4c48` | `test_k10_*`, `test_k10b_*` |
| QA-026 | P1 | Resolved (as specified: one definition, models labelled) | `9578544` | `tests/qa/test_n_consistency.py` (n01 to n07), browser L19, L20 |
| QA-032 | P1 | Resolved | `e1b0961` | `test_o05_*`, `test_o06_*`; `tools/verify_clean_env.sh` on 3.11, 3.12, 3.13; CI jobs `locked`, `study-exact` |
| QA-035 | P1 | **Open: licensing decision, not code** | none | Provider data is never bundled (`test_o02_*`); no rights claimed |
| QA-003 | P2 | Resolved | `45b6e0b` | `test_j05c_*` |
| QA-005 | P2 | Resolved | `74a4c48` | `test_k08_*`, `test_k08b_*` |
| QA-008 | P2 | Resolved | `74a4c48` | `test_k09_*`, `test_k09b_*` |
| QA-009 | P2 | Resolved | `86ac2c7` | `test_h04_*`, `test_h04b_*` |
| QA-011 | P2 | Resolved | `9578544`, `45b6e0b` | `test_a17_*`, `test_a17b_*` |
| QA-016 | P2 | Resolved | `86ac2c7` | `test_a20b_*` |
| QA-018 | P2 | Resolved | `86ac2c7` | `test_a11b_*`, `test_a09b_*` |
| QA-020 | P2 | Resolved (estimator specified; study unchanged) | `86ac2c7` | `test_d04_*`, `test_d04b_*`, `test_d12_*` |
| QA-022 | P2 | Resolved | `45b6e0b` | `test_j05d_*`, `test_j05e_*`, browser L22 |
| QA-023 | P2 | Resolved | `86ac2c7`, `45b6e0b` | `test_j06_*`, `test_j06b_*` |
| QA-024 | P2 | Resolved | `9578544` | `test_n04_*`, browser L19 |
| QA-027 | P2 | Open (new feature: contribution-aware Monte Carlo; deferred to wealth-planning milestone) | none | The page now states "a lump sum, no contributions" (`test_p05_*`) |
| QA-028 | P2 | Open (cash earns 0%; disclosed on every page and in reports) | none | `test_p08_*` checks the disclosure |
| QA-029 | P2 | Open (no historical crisis replay) | none | |
| QA-030 | P2 | Resolved | `86ac2c7`, `34e58a9` | `tests/qa/test_p_model_honesty.py` (p01 to p06), browser L21 |
| QA-031 | P2 | Partly resolved: synthetic and user data are bundled; provider data cannot be (QA-035) | `e1b0961` | `test_o01_*`, `test_o02_*`, `test_o03_*` |
| QA-033 | P2 | Open (process: evaluation period reused; disclosed) | none | `test_i10_*` |
| QA-012 | P3 | Resolved | `45b6e0b` | `test_j07b_*` |
| QA-017 | P3 | Open (partial provider response still fails the whole selection; cache served) | none | `test_b14_*` (characterisation) |
| QA-019 | P3 | Resolved | `86ac2c7` | `test_h05_*` |
| QA-021 | P3 | Resolved | `34e58a9` | `test_p07_*` |
| QA-025 | P3 | Resolved | `86ac2c7` | `test_j07c_*` |
| QA-036 | P3 | Resolved for the Investment Lab report and the generic report | `45b6e0b` | `test_j05_*`, `test_j05d_*` |
| QA-037 | P3 | Observation, unchanged (safe behaviour) | none | `test_b02_*`, `test_b08_*` |
| QA-038 | P3 | Resolved | `e1b0961` | `test_o04_*` |
| QA-039 | P3 | Open (forward tracking: future milestone) | none | |
| QA-040 | P3 | Open (no WCAG audit; Chromium-only checks) | none | browser L14, L15 |
| QA-041 | P3 | Resolved (audit in CI, weekly) | `e1b0961` | CI job `audit`; `test_o06_*` |

### Found during remediation

| ID | Priority | Class | Finding | Status |
|---|---|---|---|---|
| QA-042 | P2 | reliability (test suite) | The strict xfail pinned for QA-004 built `PortfolioSpec(..., "never", "never", ...)`, an invalid frequency, so it raised `ValueError` before reaching the CSV code and "xfailed" for the wrong reason. QA-004 itself was real (the characterisation test proved it on the baseline). | Fixed: corrected input; every former xfail now passes on its asserted line |
| QA-043 | P3 | reliability | The frozen study reproduces bit for bit (difference 0) only with NumPy 2.5.3 / pandas 3.0.5, the versions that produced it. With the current locked versions (NumPy 2.4.6 / 2.5.5, pandas 3.1.1) the largest difference is 4.17e-14, identical on the untouched QA baseline, so it is library-version rounding, not a remediation change. Within the study's 1e-9 tolerance. | Mitigated: `requirements/study-py313.txt` + CI job `study-exact` asserts difference 0 |
| QA-044 | P3 | reliability | Pandas' default CSV float parser is not exact in the last bit, so a price bundle did not reproduce an analysis bit for bit. | Fixed for user CSV uploads (exact parsing); the cache/snapshot loader is deliberately unchanged because the published record was produced through it |
| QA-045 | P3 | security (environment) | A Python 3.11 virtual environment created by `venv` ships `setuptools` 79.0.1 with two advisories (PYSEC-2026-3447, GHSA-xmj3-9gf7-h52w). It is not a project dependency; both lock files audit clean. | Open (operational): upgrade `pip`/`setuptools` in deployment images |

**Count after remediation:** 0 P0; P1: 11 resolved, 1 open (QA-035, licensing); P2: 13 resolved,
1 partly resolved (QA-031), 4 open limitations or deferred features (QA-027, 028, 029, 033),
plus QA-042 fixed; P3: 8 resolved, 1 observation, 4 open (QA-017, 039, 040, 045), plus QA-043
mitigated and QA-044 fixed.

---

# Original QA findings (as found, before remediation)

Priority: **P0** wrong money or wrong numbers with no warning in the core engine · **P1** a user can
be misled, lose work, or be exposed; fix before any public or shared use · **P2** real but
bounded; fix before calling the product finished · **P3** polish or hardening.

Classification: **defect** (contrary to its own specification or to correctness) · **financial-model
risk** (works as built; the model is narrower than a user would assume) · **usability** · **security** ·
**reliability** (operations, reproducibility, data supply) · **new feature**.

"Blocks production" means: must be closed before the dashboard is offered to anyone other than its
author as something to rely on.

**Count: 0 × P0, 12 × P1, 17 × P2, 11 × P3.** No defect was found in trade accounting, return
measurement or risk arithmetic beyond the edge case QA-020.

## P1

| ID | Class | Module | Evidence / reproduction | Expected behaviour | Remediation | Acceptance test | Blocks production |
|---|---|---|---|---|---|---|---|
| QA-001 | defect | `portfolio/compare.py::benchmark_specs`, Investment Lab | Portfolio A = 100% of one instrument: the portfolio and all offered benchmarks have identical final values and appear as duplicate columns. `test_f02_*` | A benchmark identical to the portfolio (or to another benchmark) is not offered, or is merged and labelled as identical | De-duplicate by resolved weights + funding; say so on the page | `test_f02b_benchmarks_should_be_distinct_from_the_portfolio_and_each_other` | Yes |
| QA-002 | defect | `reporting/exports.py` (`PERCENT_KEYS`) | Investment Lab HTML shows `time_weighted_annual`, `money_weighted_annual`, etc. as raw decimals (0.07 for 7%). `test_j05_*` | Every rate in the report is formatted as a percentage | Add the Investment Lab keys to the percent set, or carry units with each statistic | `test_j05b_investment_lab_html_should_show_returns_as_percentages` | Yes |
| QA-004 | security | `reporting/exports.py::csv_bytes` | A portfolio named `=cmd|'/C calc'!A0` is written verbatim as a CSV header cell; Excel would evaluate it. `test_k07_*` | Cells starting with `= + - @` are neutralised (prefixed with `'`) | Sanitise text cells on CSV export | `test_k07b_csv_exports_should_neutralise_leading_formula_characters` | Yes |
| QA-006 | reliability | `data/refresh.py` (lock/state writes) | Cache folder becomes read-only: `PermissionError` escapes and the page crashes although a verified dataset is in memory/disk. `test_c07_*` | Serve the verified cache with a warning; outcome FAILED/CACHED | Catch `OSError` around lock and state persistence | `test_c07b_unwritable_cache_should_serve_the_verified_dataset_with_a_warning` | Yes (hosted file systems are often read-only) |
| QA-007 | reliability | `data/refresh.py` | Provider revises an old price (split/dividend restatement): accepted silently, outcome "unchanged", only the fingerprint changes. `test_b13_*` | The user is told history was revised, with the affected range | Compare overlapping history on refresh; add an outcome note | `test_b13b_a_revision_of_history_should_be_reported` | Yes |
| QA-010 | defect | `app/views/risk.py`, `monte_carlo.py`, `stress.py` | These pages call `dropna(how="any")` across every loaded instrument, so an instrument with a short history that is **not held** (the "BND" case) shortens the estimation window: 149 instead of 252 sessions in the test. Investment Lab uses held instruments only, so the same portfolio gets different windows on different pages. `test_b12a_*` | Only held instruments limit the window; the window is stated | Restrict to instruments with non-zero weight before dropping rows | `test_b12b_unheld_instrument_should_not_shorten_the_risk_window` | Yes |
| QA-013 | defect | `app/views/research.py` (Validation Lab) | Column header reads "Trend minus buy & hold" for every row, but the expected-shortfall row is computed as buy & hold minus trend. `test_i08_*` | Header describes what each row is ("Improvement; positive favours trend") | Rename the column; keep the per-row hints | `test_i08b_*` | Yes |
| QA-014 | defect | `app/views/research.py` (published study) | Caption: "Difference = trend minus buy-and-hold". Record stores ES and downside deviation as benchmark minus strategy. Numbers are right; the sentence is wrong. `test_i07_*` | Caption states the improvement convention | Correct the caption | `test_i09_published_study_caption_should_describe_the_improvement_convention` | Yes |
| QA-015 | security | `app/components/common.py::source_badge` | Instrument names (taken from uploaded file names) are interpolated into HTML rendered with `unsafe_allow_html`. A file named `<img src=x onerror=…>.csv` puts live markup on the page. Self-inflicted in a single-user session; not acceptable in a shared deployment. `test_k10_*` | All interpolated text is HTML-escaped; tickers validated on upload as they are for typed input | `html.escape` + apply `TICKER_RE` to upload names | `test_k10b_badge_should_escape_instrument_names` | Yes |
| QA-026 | financial-model risk | Risk / Monte Carlo / Stress vs Investment Lab | Two portfolio definitions exist. Investment Lab simulates a funded account through the engine (contributions, costs, drift, rebalancing). Risk, Monte Carlo and Stress each take their own weight inputs and apply constant weights to return series. The same "portfolio" therefore has different numbers on different pages, and nothing links them | One portfolio definition shared by all pages, or an explicit statement on each page of which convention it uses | Introduce a shared portfolio object in session state; label conventions | New test: one portfolio produces reconciling figures across pages | Yes |
| QA-032 | reliability | Packaging / CI | Dependencies have lower bounds only and there is no lock file; results were verified in three local environments and in CI, never in an independently built, pinned environment. A future pandas/NumPy release could change results unnoticed between CI runs | A pinned, hash-locked environment that reproduces the study from a clean machine | Add a lock file (e.g. `pip-compile --generate-hashes`), a scheduled CI run, and a container recipe | Scheduled CI job reproducing `--verify` from the lock file | Yes |
| QA-035 | reliability (data rights) | `experiments/data/`, live data | Redistribution rights for Yahoo-derived data are not established (`MANIFEST.json`: `NOT ESTABLISHED`). The public-candidate builder excludes the snapshot, but a public dashboard serving live Yahoo data is a separate question | Written basis for whatever data the public product serves | Licensed or openly licensed source for public use; keep the private snapshot private | Manifest status changes with a cited licence | Yes |

## P2

| ID | Class | Module | Evidence / reproduction | Expected behaviour | Remediation | Acceptance test | Blocks production |
|---|---|---|---|---|---|---|---|
| QA-003 | usability | `reporting/exports.py::html_report` | Investment Lab HTML prints a "Strategy" heading with an empty row. `test_j05_*` | Sections without content are omitted | Skip empty sections | `test_j05c_*` | No |
| QA-005 | security | `data/refresh.py`, `dataset_key` | `LiveDataStore.get(["SPY"], "../../../escaped")` writes outside the cache folder. The dashboard passes a date, so it is not reachable from the UI. `test_k08_*` | `start` validated as a date before any path is built | Parse `start`; reject otherwise | `test_k08b_store_should_refuse_a_start_that_is_not_a_date` | No (until an API is exposed) |
| QA-008 | security | `data/refresh.py::_load_cache` | Recovery notes shown to users include the server's absolute path (`[Errno 2] … '/…/close.csv'`). `test_k09_*` | Notes name the version, not the path | Strip exception text to its class and file name | `test_k09b_*` | No |
| QA-009 | defect | `risk/stress.py` | A NaN shock is treated as 0; an infinite shock is accepted. `test_h04_*` | Non-finite shocks are refused | Validate with `np.isfinite` | `test_h04b_non_finite_shocks_should_be_rejected` | No |
| QA-011 | usability | Investment Lab risk insights; `risk` correlation | Undefined correlation (single asset, or a zero-variance asset) is displayed as `nan`. `test_a17_*` | "n/a" with a one-line reason | Format undefined values centrally | `test_a17b_undefined_correlation_should_read_not_available` | No |
| QA-016 | defect | `portfolio/spec.py::simulate_portfolio` | An empty dataset simulates to an empty result instead of raising. The comparison layer does refuse it. `test_a20_*` | A clear error | Validate at the simulator boundary | `test_a20b_*` | No |
| QA-018 | defect | `execution/config`, weight validation | NaN/inf slippage or fees are accepted; an infinite weight is reported as "leverage". `test_a11_*`, `test_a09_*` | Non-finite settings are refused and named as such | `math.isfinite` checks | `test_a11b_*`, `test_a09b_*` | No |
| QA-020 | defect | `analytics/metrics.py::historical_es` | Tail membership uses `<=` against a floating-point quantile; with `1 − 0.90` the boundary observation drops out (ES 5% instead of 4% for an 11-point example). Affects only ties at the quantile. `test_d04_*` | Stable tail definition independent of float rounding | Select the tail by rank (`k = ceil(n·α)` smallest) | `test_d04b_*` | No |
| QA-022 | usability | `app/views/invest.py` export | The HTML report does not state the portfolio allocations it analysed (the JSON record does) | Allocations, funding and rebalancing shown in the report | Pass the specs to `html_report` | `test_j05d_html_should_state_the_portfolio_allocations` | No |
| QA-023 | reliability | `app/views/risk.py` (also Monte Carlo, Stress exports) | Risk export has window, method and weights but no dataset fingerprint, software version or timestamp. `test_j06_*` | Same reproducibility block as the Investment Lab record | Reuse the record builder | `test_j06b_*` | No |
| QA-024 | usability | `app/views/invest.py` (Risk insights tab) | Risk insights are computed for Portfolio A only (`primary`); B and C get headline statistics but no risk breakdown | Selector for which portfolio to inspect, or all three | Parameterise the tab | New AppTest | No |
| QA-027 | financial-model risk | `simulations/monte_carlo.py`, Monte Carlo page | Simulation compounds one lump sum at constant weights. Recurring contributions, rebalancing and costs are not modelled, so it cannot answer "what might my funded plan be worth" | Contribution-aware paths, or an explicit statement that it is lump-sum only | Simulate through the engine or add a flow vector | New tests on a contribution schedule | No |
| QA-028 | financial-model risk | Engine | Uninvested cash earns 0%. For a portfolio with a large cash reserve over many years this understates value and shifts Sharpe | Optional cash rate, default disclosed | Add a rate series to the ledger | New accounting test | No |
| QA-029 | financial-model risk | `risk/stress.py`, Stress page | Only user-entered instantaneous shocks. No library of historical episodes (2008, 2020, 2022), no multi-day paths, no correlation shift | Dated historical scenarios replayed from data, clearly labelled | Add episode replay from the loaded history | New tests against the frozen data | No |
| QA-030 | financial-model risk | Monte Carlo, Risk, Investment Lab | Probabilities and tail statistics are shown as point values without sampling error, and the dominant sensitivity (lookback window) is not surfaced. Measured on the reference data: the history window changed P(drawdown worse than 20% in a year) several-fold, far more than seed-to-seed noise (about ±1 point at 1,000 paths). See QA report §6 | Standard error next to each probability; lookback sensitivity shown or warned | Add binomial SE and a sensitivity panel | New test asserting SE is displayed | No |
| QA-031 | reliability | Exports | Exports identify the data by fingerprint, source and window but do not package the prices; if the provider later revises history (QA-007) the analysis cannot be re-run exactly | Option to include the data snapshot (subject to QA-035) | Bundle prices for user-supplied and synthetic data; fingerprint + refusal otherwise | Round-trip test | No |
| QA-033 | financial-model risk | Research study | The out-of-sample period has been examined more than once (original run, audit, now QA). Bonferroni covers the three pre-registered metrics, not the reuse of the evaluation period or the exploratory rows. The page already says "no longer untouched data" | Any new claim needs fresh data or a new pre-registration | Forward tracking (QA-034); keep the disclosure | n/a (process) | No (for the tool); yes for any new research claim |

## P3

| ID | Class | Module | Evidence / reproduction | Expected behaviour | Remediation | Acceptance test | Blocks production |
|---|---|---|---|---|---|---|---|
| QA-012 | usability | Formatting helpers | Values that round to zero keep their sign: `-0.00`. `test_j07_*` | `0.00` | Normalise after rounding | `test_j07b_*` | No |
| QA-017 | reliability | `data/refresh.py` | If one of several requested instruments fails, the whole selection fails (cached data is still served if present). `test_b14_*` | Partial result with the failure named, or keep all-or-nothing and say so | Decide and document | Update `test_b14_*` | No |
| QA-019 | defect | `risk/stress.py` | A zero-value portfolio gives a NaN percentage loss. `test_h05_*` | "n/a" or a refusal | Guard the division | Extend `test_h05_*` | No |
| QA-021 | usability | Docs vs engine | Docs say every contribution waits one session. When an earlier-decided order fills on the deposit day, that deposit is spent at the same open. Accounting is correct. `test_e04_*` | Docs describe the actual rule | Edit the assumptions text | Text assertion | No |
| QA-025 | usability | `app/views/risk.py:95` | Covariance matrix shown with four fixed decimals, leaving one or two significant figures for low-volatility assets (and occasional `-0.0000`) | Significant-figure or scientific formatting | Change the format string | AppTest on formatted values | No |
| QA-036 | usability | HTML reports | Statistic names are internal keys (`time_weighted_annual`, `n_obs`), allocations and conclusions have no explanatory text, technical fields are unexplained | Plain-language labels and a short "how to read this" | Label map + glossary section | Text assertions | No |
| QA-037 | reliability | Yahoo provider | On 2026-11-16 at about 20:24 ET Yahoo returned that day's row with an empty close, hours after the close. The store dropped the row and reported "one session behind", which is the safe behaviour | Keep; consider a retry hint | None required; monitor | Existing `test_b02_*`, `test_b08_*` | No |
| QA-038 | reliability | `app/components/common.py::live_store` | Cache location is fixed at `<repo>/.data_cache`; not configurable, lost on every redeploy of an ephemeral host, and the lock is per-machine | Configurable path; documented behaviour on ephemeral hosts | Environment variable | Unit test | No |
| QA-039 | new feature | Forward testing | No forward (paper) portfolio tracking: every result is a backtest | Dated, append-only forward record | Planned milestone (deferred Phase 3) | n/a | No |
| QA-040 | usability | Accessibility / browsers | Only Chromium, naming, focus and reflow were checked. No screen-reader, contrast or cross-browser evidence | WCAG 2.1 AA review | Audit with axe + manual pass | Browser suite extension | No |
| QA-041 | security | Dependencies | `pip-audit` on the project's pinned-as-installed set (Python 3.12 environment): no known vulnerabilities on 2026-11-17. Not run in CI, so this decays | Audit on a schedule | Add a scheduled CI job | CI job | No |

## Carried-forward manual findings: where each one landed

| Manual finding | Backlog ID |
|---|---|
| Duplicate benchmarks in some portfolio configurations | QA-001 |
| HTML percentage formatting / returns as raw decimals | QA-002 |
| Empty Strategy section | QA-003 |
| Undefined correlation shown as `nan` | QA-011 |
| Over-rounded covariance and negative zero | QA-025, QA-012 |
| Risk Insights restricted to Portfolio A | QA-024 |
| Separate portfolio definitions and accounting conventions | QA-026 |
| Limited contribution-aware Monte Carlo | QA-027 |
| Zero-interest cash | QA-028 |
| Limited historical crisis modelling | QA-029 |
| Insufficient sample-size uncertainty communication | QA-030 |
| Limited data-snapshot reproducibility in exports; full data not packaged | QA-031 |
| Risk exports omit reproducibility metadata | QA-023 |
| Missing independent fresh-environment verification | QA-032 |
| Research multiple-testing and evaluation-reuse limits | QA-033 |
| Missing forward portfolio tracking | QA-039 |
| Unestablished market-data redistribution rights | QA-035 |
| Allocations and conclusions lack context; technical fields unexplained | QA-022, QA-036 |
| Duplicate benchmark columns in reports | QA-001 |
| Validation Lab "Trend minus buy & hold" label | QA-013, QA-014 |
| BND missing-history effect on the common window | QA-010 |
