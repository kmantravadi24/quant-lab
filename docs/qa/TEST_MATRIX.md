# Quant Lab QA: test matrix

> **After remediation (2026-11-17, branch `claude/remediation-v1`):** 669 pytest tests pass on
> Python 3.11, 3.12 and 3.13 with **no expected failures**. All 25 former XFAIL rows below are now
> ordinary passing acceptance tests. New suites: N (cross-page consistency, 9 tests),
> O (reproducibility, 6) and P (model honesty, 13). Browser checks: 23 (L19 to L22 added). The
> per-test register below is the QA-milestone record and is not regenerated; the current status of
> every issue is in `MASTER_BACKLOG.md`, and the changes are in `REMEDIATION_REPORT.md`.

Status vocabulary: **PASS** (executed, behaves as required) · **FAIL** (executed, a defect that is
not yet pinned by a test) · **XFAIL** (executed, confirmed defect pinned by a strict expected-failure
test that names its backlog ID; the test starts failing the build the day the defect is fixed
without the marker being removed) · **INCONCLUSIVE** (executed, evidence insufficient) ·
**NOT TESTED** (not executed in this milestone).

Run on 2026-11-17 against commit `ef488d5` plus this milestone's tests. No file under `src/` or
`app/` was changed.

| Suite | Scope | File | Checks | PASS | XFAIL | Backlog IDs pinned |
|---|---|---|---:|---:|---:|---|
| A | Inputs and adversarial UI | `tests/qa/test_a_inputs.py` | 61 | 54 | 7 | QA-011, QA-016, QA-018 |
| B | Data integrity and freshness | `tests/qa/test_b_c_data_cache.py` | 36 | 33 | 3 | QA-007, QA-010 |
| C | Cache, concurrency, recovery | (same file) | | | | QA-006 |
| D | Independent financial mathematics | `tests/qa/test_d_math.py` | 14 | 13 | 1 | QA-020 |
| E | Investment Lab accounting | `tests/qa/test_e_f_accounting_benchmarks.py` | 29 | 28 | 1 | — |
| F | Benchmarks | (same file) | | | | QA-001 |
| G | Monte Carlo and model risk | `tests/qa/test_g_h_simulation_stress.py` | 26 | 24 | 2 | — |
| H | Stress testing | (same file) | | | | QA-009 |
| I | Strategy and research integrity | `tests/qa/test_i_j_research_exports.py` | 24 | 17 | 7 | QA-013, QA-014 |
| J | Exports and reporting | (same file) | | | | QA-002, QA-003, QA-012, QA-022, QA-023 |
| K | Security and resilience | `tests/qa/test_k_m_security_operations.py` | 34 | 30 | 4 | QA-004, QA-005, QA-008, QA-015 |
| M | Performance and operations | (same file) | | | | — |
| L | Browser and UX (real Chromium) | `tests/browser/smoke.js` | 19 | 19 | 0 | — |
| — | Existing suite (baseline) | `tests/unit`, `tests/integration` | 402 | 402 | 0 | — |
| | **Total** | | **645** | **620** | **25** | |

pytest total: 626 collected = 601 passed + 25 xfailed, 0 failed, 0 skipped, on Python 3.11, 3.12
and 3.13. Browser total: 19 passed, 0 failed.

## What each suite establishes

| ID | Requirement | Method | Result |
|---|---|---|---|
| A01–A21 | Invalid tickers, short history, over-allocation, all-cash, total loss, bad weights/funding/costs, malformed ticker text, impossible parameters, reversed windows, single asset, zero volatility, new listings, empty data, oversized simulations | Library calls and Streamlit `AppTest` page runs | PASS, except QA-011, QA-016, QA-018 (XFAIL) |
| B01–B14 | Bad prices rejected not repaired; missing closes dropped and disclosed; no forward fill; malformed provider payloads; failure classification; incomplete session never served; per-instrument staleness; synthetic never substituted for live; frozen study inputs immune to refresh | Scripted provider + settable clock, temporary cache | PASS, except QA-007, QA-010 (XFAIL); QA-017 characterised |
| C01–C08 | Reruns use memory; restart recovery; 12 simultaneous users → 1 download; interrupted write and corruption keep the verified dataset; expiry; dashboard refresh states | Same harness, threads | PASS, except QA-006 (XFAIL) |
| D01–D15 | Compounding, volatility, CAGR, Sharpe, covariance (symmetric, PSD), risk contributions sum to volatility, VaR/ES, drawdown depth and duration, TWR, XIRR | Independent plain-Python references in `tests/qa/reference.py`; Hypothesis property tests (150 derandomised examples each) | PASS, except QA-020 (XFAIL) |
| E01–E09 | Cash reconciles fill by fill (fractional and whole shares, fixed fees); TWR is flow-neutral; MWR uses dated flows; scale invariance; contribution calendar; missing price keeps money in cash; rebalancing dates, drift and cost; 40-year horizon; display = engine = export | Replay of the trade log from first principles | PASS; QA-021 characterised |
| F01–F04 | Benchmarks built independently and labelled; chart series reconcile with the table; duplicates | Library | PASS, except QA-001 (XFAIL) |
| G01–G09 | Determinism by seed; every step is an observed return; block structure; exact event counts; cash dilution; invalid inputs; method sensitivity beyond noise; seed spread shrinks as 1/√paths | Library, synthetic history | PASS |
| H01–H06 | Reference scenario ($100k → −$14,665); scenario = sum of holdings; missing instrument and >100% loss refused; non-finite shocks; zero-value portfolio | Hand arithmetic | PASS, except QA-009 (XFAIL) |
| I01–I10 | Next-session fills; warm-up; chronological split; grid blind to the test period; complete trial count; Bonferroni/Holm by hand; bootstrap reproducible, paired, block-sensitive; costs monotone; record hash, protocol, checksums intact; sign conventions | Library, perturbation of post-split data, stored record | PASS, except QA-013, QA-014 (XFAIL) |
| J01–J08 | Analysis record completeness; portfolio-file round trip; corrupt files refused; NaN → strict JSON null; percent formatting; research report agrees with the record | Library + stored artefacts | PASS, except QA-002, QA-003, QA-012, QA-022, QA-023 (XFAIL) |
| K01–K15 | Malformed/binary/oversized uploads; HTML and JSON escaping; CSV formulas; path traversal; path disclosure; markup injection; no `eval`/`pickle`/shell; secrets scan; no tracebacks to users; no network needed | Local harmless inputs, AST scan, `git ls-files` scan | PASS, except QA-004, QA-005, QA-008, QA-015 (XFAIL) |
| M01–M07 | Loose time bounds; near-linear scaling; nine pages render cold; router; library import does not load UI/provider; CI contents; dependency declarations | Timers, subprocess | PASS |
| L01–L18 | Navigation, deep links on fresh sessions, synthetic label, refresh, edits, invalid-input recovery, rapid edits, tabs, save/reload, export = screen, corrupt file, laptop/phone layout, keyboard/naming, console errors | Playwright + Chromium against a local server | PASS |

## Not tested in this milestone

| Area | Status | Why |
|---|---|---|
| Live Yahoo Finance responses in automated tests | NOT TESTED (by rule) | Tests must be offline and deterministic. One manual live observation is recorded in the report. |
| Screen-reader behaviour, colour contrast, full WCAG audit | NOT TESTED | Only naming, focus movement, heading count and reflow were automated. |
| Firefox, Safari, real mobile devices | NOT TESTED | Chromium only (desktop and emulated 390 px viewport). |
| Multi-process cache locking on a network filesystem or Windows | NOT TESTED | Threads within one process on Linux only. |
| Load: many concurrent browser sessions, memory growth over days | NOT TESTED | No hosted environment exists. |
| Deployment on Streamlit Community Cloud or similar | NOT TESTED | Deployment was not authorised. |
| Whether the provider's adjusted prices are themselves correct | NOT TESTED | No second data source is available. |
| Monte Carlo path generation against an independent implementation | INCONCLUSIVE | Invariants and statistical properties verified; no second implementation written. |
| Yahoo returning a just-closed session with an empty close | INCONCLUSIVE | Observed once live; handled safely; frequency unknown. |

## Per-test register

One row per test function (parametrised cases are counted in *Cases*). The scenario and the expected
behaviour are the test's own name, which is written as the requirement it checks. *Evidence* is the
assertion outcome in the run of 2026-11-17 (`pytest tests/qa`), or the backlog entry for an XFAIL.
*Severity when failing* is the priority a new failure of that test would be given (for XFAIL rows: the
priority of the pinned defect).

| Test ID | Feature | Scenario and expected behaviour | Implementation | Cases | Result | Evidence | Severity when failing |
|---|---|---|---|---:|---|---|---|
| A01 | Inputs / adversarial UI | invalid ticker among valid ones is named and nothing is shown | `tests/qa/test_a_inputs.py::test_a01_invalid_ticker_among_valid_ones_is_named_and_nothing_is_shown` | 1 | PASS | assertions held | P1 |
| A02 | Inputs / adversarial UI | insufficient history is explained | `tests/qa/test_a_inputs.py::test_a02_insufficient_history_is_explained` | 4 | PASS | assertions held | P1 |
| A03 | Inputs / adversarial UI | allocation above 100 percent is refused | `tests/qa/test_a_inputs.py::test_a03_allocation_above_100_percent_is_refused` | 3 | PASS | assertions held | P1 |
| A04 | Inputs / adversarial UI | A05 all cash risk and monte carlo | `tests/qa/test_a_inputs.py::test_a04_a05_all_cash_risk_and_monte_carlo` | 2 | PASS | assertions held | P1 |
| A06 | Inputs / adversarial UI | all cash stress test loses nothing | `tests/qa/test_a_inputs.py::test_a06_all_cash_stress_test_loses_nothing` | 1 | PASS | assertions held | P1 |
| A07 | Inputs / adversarial UI | total loss is valid and a08 more than total loss is not | `tests/qa/test_a_inputs.py::test_a07_total_loss_is_valid_and_a08_more_than_total_loss_is_not` | 1 | PASS | assertions held | P1 |
| A09 | Inputs / adversarial UI | invalid weights are rejected everywhere | `tests/qa/test_a_inputs.py::test_a09_invalid_weights_are_rejected_everywhere` | 6 | PASS | assertions held | P1 |
| A10 | Inputs / adversarial UI | invalid funding is rejected | `tests/qa/test_a_inputs.py::test_a10_invalid_funding_is_rejected` | 4 | PASS | assertions held | P1 |
| A11 | Inputs / adversarial UI | invalid execution settings are rejected | `tests/qa/test_a_inputs.py::test_a11_invalid_execution_settings_are_rejected` | 5 | PASS | assertions held | P1 |
| A11B | Inputs / adversarial UI | nonfinite execution settings should be rejected | `tests/qa/test_a_inputs.py::test_a11b_nonfinite_execution_settings_should_be_rejected` | 4 | XFAIL | QA-018: non-finite execution settings are accepted | P2 |
| A09B | Inputs / adversarial UI | nonfinite weight should be reported as nonfinite | `tests/qa/test_a_inputs.py::test_a09b_nonfinite_weight_should_be_reported_as_nonfinite` | 1 | XFAIL | QA-018: an infinite weight is reported as 'leverage' | P2 |
| A12 | Inputs / adversarial UI | ui weight and amount inputs cannot go below zero | `tests/qa/test_a_inputs.py::test_a12_ui_weight_and_amount_inputs_cannot_go_below_zero` | 1 | PASS | assertions held | P1 |
| A13 | Inputs / adversarial UI | malformed ticker input is rejected with a reason | `tests/qa/test_a_inputs.py::test_a13_malformed_ticker_input_is_rejected_with_a_reason` | 9 | PASS | assertions held | P1 |
| A14 | Inputs / adversarial UI | duplicate and mixed case tickers are normalised visibly | `tests/qa/test_a_inputs.py::test_a14_duplicate_and_mixed_case_tickers_are_normalised_visibly` | 1 | PASS | assertions held | P1 |
| A15 | Inputs / adversarial UI | impossible strategy parameters are rejected | `tests/qa/test_a_inputs.py::test_a15_impossible_strategy_parameters_are_rejected` | 10 | PASS | assertions held | P1 |
| A16 | Inputs / adversarial UI | reversed or empty evaluation window is refused | `tests/qa/test_a_inputs.py::test_a16_reversed_or_empty_evaluation_window_is_refused` | 1 | PASS | assertions held | P1 |
| A17 | Inputs / adversarial UI | single asset portfolio is handled end to end | `tests/qa/test_a_inputs.py::test_a17_single_asset_portfolio_is_handled_end_to_end` | 1 | PASS | assertions held | P1 |
| A17B | Inputs / adversarial UI | undefined correlation should read not available | `tests/qa/test_a_inputs.py::test_a17b_undefined_correlation_should_read_not_available` | 1 | XFAIL | QA-011: undefined correlation is displayed as 'nan' | P2 |
| A18 | Inputs / adversarial UI | zero volatility and singular covariance do not produce fake numbers | `tests/qa/test_a_inputs.py::test_a18_zero_volatility_and_singular_covariance_do_not_produce_fake_numbers` | 1 | PASS | assertions held | P1 |
| A19 | Inputs / adversarial UI | newly listed instrument limits the window and too new is refused | `tests/qa/test_a_inputs.py::test_a19_newly_listed_instrument_limits_the_window_and_too_new_is_refused` | 1 | PASS | assertions held | P1 |
| A20 | Inputs / adversarial UI | empty dataset is refused by comparison | `tests/qa/test_a_inputs.py::test_a20_empty_dataset_is_refused_by_comparison` | 1 | PASS | assertions held | P1 |
| A20B | Inputs / adversarial UI | empty dataset should be refused by the simulator | `tests/qa/test_a_inputs.py::test_a20b_empty_dataset_should_be_refused_by_the_simulator` | 1 | XFAIL | QA-016: an empty dataset simulates to an empty result | P2 |
| A21 | Inputs / adversarial UI | oversized simulation is refused in the ui and bounded inputs in the library | `tests/qa/test_a_inputs.py::test_a21_oversized_simulation_is_refused_in_the_ui_and_bounded_inputs_in_the_library` | 1 | PASS | assertions held | P1 |
| B01 | Data integrity / freshness | nonpositive or infinite prices are rejected not repaired | `tests/qa/test_b_c_data_cache.py::test_b01_nonpositive_or_infinite_prices_are_rejected_not_repaired` | 4 | PASS | assertions held | P1 |
| B02 | Data integrity / freshness | a row without a close is dropped and reported never filled | `tests/qa/test_b_c_data_cache.py::test_b02_a_row_without_a_close_is_dropped_and_reported_never_filled` | 1 | PASS | assertions held | P1 |
| B03 | Data integrity / freshness | missing open is kept as missing and high below low is rejected | `tests/qa/test_b_c_data_cache.py::test_b03_missing_open_is_kept_as_missing_and_high_below_low_is_rejected` | 1 | PASS | assertions held | P1 |
| B04 | Data integrity / freshness | duplicate and out of order rows are normalised and disclosed | `tests/qa/test_b_c_data_cache.py::test_b04_duplicate_and_out_of_order_rows_are_normalised_and_disclosed` | 1 | PASS | assertions held | P1 |
| B05 | Data integrity / freshness | a missing session is never forward filled into a return | `tests/qa/test_b_c_data_cache.py::test_b05_a_missing_session_is_never_forward_filled_into_a_return` | 1 | PASS | assertions held | P1 |
| B06 | Data integrity / freshness | empty or malformed provider responses never become data | `tests/qa/test_b_c_data_cache.py::test_b06_empty_or_malformed_provider_responses_never_become_data` | 4 | PASS | assertions held | P1 |
| B07 | Data integrity / freshness | failures are classified as far as the evidence allows | `tests/qa/test_b_c_data_cache.py::test_b07_failures_are_classified_as_far_as_the_evidence_allows` | 5 | PASS | assertions held | P1 |
| B08 | Data integrity / freshness | an incomplete session never enters the verified dataset | `tests/qa/test_b_c_data_cache.py::test_b08_an_incomplete_session_never_enters_the_verified_dataset` | 1 | PASS | assertions held | P1 |
| B09 | Data integrity / freshness | stale and missing data is identified per instrument | `tests/qa/test_b_c_data_cache.py::test_b09_stale_and_missing_data_is_identified_per_instrument` | 1 | PASS | assertions held | P1 |
| B10 | Data integrity / freshness | synthetic data never replaces real data silently | `tests/qa/test_b_c_data_cache.py::test_b10_synthetic_data_never_replaces_real_data_silently` | 1 | PASS | assertions held | P1 |
| B11 | Data integrity / freshness | a live refresh cannot change the frozen study inputs | `tests/qa/test_b_c_data_cache.py::test_b11_a_live_refresh_cannot_change_the_frozen_study_inputs` | 1 | PASS | assertions held | P1 |
| B12 | Data integrity / freshness | late listed instrument window characterisation | `tests/qa/test_b_c_data_cache.py::test_b12_late_listed_instrument_window_characterisation` | 1 | PASS | current behaviour recorded (see paired XFAIL / backlog) | P1 |
| B12A | Data integrity / freshness | risk page window with an unheld short history instrument | `tests/qa/test_b_c_data_cache.py::test_b12a_risk_page_window_with_an_unheld_short_history_instrument` | 1 | PASS | assertions held | P1 |
| B12B | Data integrity / freshness | unheld instrument should not shorten the risk window | `tests/qa/test_b_c_data_cache.py::test_b12b_unheld_instrument_should_not_shorten_the_risk_window` | 1 | XFAIL | QA-010: an unheld instrument shortens the Risk page's window | P1 |
| B13 | Data integrity / freshness | revised history is accepted and changes the fingerprint | `tests/qa/test_b_c_data_cache.py::test_b13_revised_history_is_accepted_and_changes_the_fingerprint` | 1 | PASS | assertions held | P1 |
| B13B | Data integrity / freshness | a revision of history should be reported | `tests/qa/test_b_c_data_cache.py::test_b13b_a_revision_of_history_should_be_reported` | 1 | XFAIL | QA-007: revised historical prices are not surfaced | P1 |
| B14 | Data integrity / freshness | partial instrument response characterisation | `tests/qa/test_b_c_data_cache.py::test_b14_partial_instrument_response_characterisation` | 1 | PASS | current behaviour recorded (see paired XFAIL / backlog) | P1 |
| C01 | Cache / concurrency / recovery | repeated reruns use memory and never redownload | `tests/qa/test_b_c_data_cache.py::test_c01_repeated_reruns_use_memory_and_never_redownload` | 1 | PASS | assertions held | P1 |
| C02 | Cache / concurrency / recovery | restart recovers data cooldown and attempt history | `tests/qa/test_b_c_data_cache.py::test_c02_restart_recovers_data_cooldown_and_attempt_history` | 1 | PASS | assertions held | P1 |
| C03 | Cache / concurrency / recovery | recovering from an invalid selection back to a valid one | `tests/qa/test_b_c_data_cache.py::test_c03_recovering_from_an_invalid_selection_back_to_a_valid_one` | 1 | PASS | assertions held | P1 |
| C04 | Cache / concurrency / recovery | many simultaneous users cause one download and see one dataset | `tests/qa/test_b_c_data_cache.py::test_c04_many_simultaneous_users_cause_one_download_and_see_one_dataset` | 1 | PASS | assertions held | P1 |
| C05 | Cache / concurrency / recovery | interrupted write and corruption never lose the verified dataset | `tests/qa/test_b_c_data_cache.py::test_c05_interrupted_write_and_corruption_never_lose_the_verified_dataset` | 1 | PASS | assertions held | P1 |
| C06 | Cache / concurrency / recovery | expired cache is rechecked once and no cache startup downloads once | `tests/qa/test_b_c_data_cache.py::test_c06_expired_cache_is_rechecked_once_and_no_cache_startup_downloads_once` | 1 | PASS | assertions held | P1 |
| C07 | Cache / concurrency / recovery | unwritable cache characterisation | `tests/qa/test_b_c_data_cache.py::test_c07_unwritable_cache_characterisation` | 1 | PASS | current behaviour recorded (see paired XFAIL / backlog) | P1 |
| C07B | Cache / concurrency / recovery | unwritable cache should serve the verified dataset with a warning | `tests/qa/test_b_c_data_cache.py::test_c07b_unwritable_cache_should_serve_the_verified_dataset_with_a_warning` | 1 | XFAIL | QA-006: an unwritable cache crashes instead of serving the verified data | P1 |
| C08 | Cache / concurrency / recovery | dashboard refresh states end to end | `tests/qa/test_b_c_data_cache.py::test_c08_dashboard_refresh_states_end_to_end` | 1 | PASS | assertions held | P1 |
| D01 | Financial mathematics | returns and compounding by hand | `tests/qa/test_d_math.py::test_d01_returns_and_compounding_by_hand` | 1 | PASS | assertions held | P0 |
| D02 | Financial mathematics | volatility cagr sharpe by hand | `tests/qa/test_d_math.py::test_d02_volatility_cagr_sharpe_by_hand` | 1 | PASS | assertions held | P0 |
| D03 | Financial mathematics | two asset covariance volatility and contributions by hand | `tests/qa/test_d_math.py::test_d03_two_asset_covariance_volatility_and_contributions_by_hand` | 1 | PASS | assertions held | P0 |
| D04 | Financial mathematics | var and expected shortfall by hand | `tests/qa/test_d_math.py::test_d04_var_and_expected_shortfall_by_hand` | 1 | PASS | assertions held | P0 |
| D04B | Financial mathematics | expected shortfall should include an observation exactly at the quantile | `tests/qa/test_d_math.py::test_d04b_expected_shortfall_should_include_an_observation_exactly_at_the_quantile` | 1 | XFAIL | QA-020: ES tail membership flips on floating-point quantile ties | P2 |
| D05 | Financial mathematics | drawdown depth and duration by hand | `tests/qa/test_d_math.py::test_d05_drawdown_depth_and_duration_by_hand` | 1 | PASS | assertions held | P0 |
| D06 | Financial mathematics | xirr closed forms | `tests/qa/test_d_math.py::test_d06_xirr_closed_forms` | 1 | PASS | assertions held | P0 |
| D07 | Financial mathematics | undefined metrics are nan and never a number | `tests/qa/test_d_math.py::test_d07_undefined_metrics_are_nan_and_never_a_number` | 1 | PASS | assertions held | P0 |
| D10 | Financial mathematics | return statistics match the reference | `tests/qa/test_d_math.py::test_d10_return_statistics_match_the_reference` | 1 | PASS | assertions held | P0 |
| D11 | Financial mathematics | sharpe matches the reference | `tests/qa/test_d_math.py::test_d11_sharpe_matches_the_reference` | 1 | PASS | assertions held | P0 |
| D12 | Financial mathematics | var and expected shortfall match the reference | `tests/qa/test_d_math.py::test_d12_var_and_expected_shortfall_match_the_reference` | 1 | PASS | assertions held | P0 |
| D13 | Financial mathematics | covariance and risk contribution invariants | `tests/qa/test_d_math.py::test_d13_covariance_and_risk_contribution_invariants` | 1 | PASS | assertions held | P0 |
| D14 | Financial mathematics | xirr matches the reference for contribution schedules | `tests/qa/test_d_math.py::test_d14_xirr_matches_the_reference_for_contribution_schedules` | 1 | PASS | assertions held | P0 |
| D15 | Financial mathematics | cash is a zero return asset and scaling weights scales risk | `tests/qa/test_d_math.py::test_d15_cash_is_a_zero_return_asset_and_scaling_weights_scales_risk` | 1 | PASS | assertions held | P0 |
| E01 | Investment Lab accounting | every fill reconciles cash from first principles | `tests/qa/test_e_f_accounting_benchmarks.py::test_e01_every_fill_reconciles_cash_from_first_principles` | 10 | PASS | assertions held | P0 |
| E02 | Investment Lab accounting | time weighted return is flow neutral and money weighted uses dated flows | `tests/qa/test_e_f_accounting_benchmarks.py::test_e02_time_weighted_return_is_flow_neutral_and_money_weighted_uses_dated_flows` | 5 | PASS | assertions held | P0 |
| E03 | Investment Lab accounting | doubling every amount doubles values and leaves returns unchanged | `tests/qa/test_e_f_accounting_benchmarks.py::test_e03_doubling_every_amount_doubles_values_and_leaves_returns_unchanged` | 1 | PASS | assertions held | P0 |
| E04 | Investment Lab accounting | contribution calendar and next session investment | `tests/qa/test_e_f_accounting_benchmarks.py::test_e04_contribution_calendar_and_next_session_investment` | 3 | PASS | assertions held | P0 |
| E05 | Investment Lab accounting | missing price on deployment day keeps the money in cash | `tests/qa/test_e_f_accounting_benchmarks.py::test_e05_missing_price_on_deployment_day_keeps_the_money_in_cash` | 1 | PASS | assertions held | P0 |
| E06 | Investment Lab accounting | annual versus no rebalancing dates drift and cost | `tests/qa/test_e_f_accounting_benchmarks.py::test_e06_annual_versus_no_rebalancing_dates_drift_and_cost` | 1 | PASS | assertions held | P0 |
| E07 | Investment Lab accounting | forty year horizon stays consistent | `tests/qa/test_e_f_accounting_benchmarks.py::test_e07_forty_year_horizon_stays_consistent` | 1 | PASS | assertions held | P0 |
| E08 | Investment Lab accounting | displayed values equal engine values and exports | `tests/qa/test_e_f_accounting_benchmarks.py::test_e08_displayed_values_equal_engine_values_and_exports` | 1 | PASS | assertions held | P0 |
| E09 | Investment Lab accounting | adjusted price model is a stated limitation not an accounting error | `tests/qa/test_e_f_accounting_benchmarks.py::test_e09_adjusted_price_model_is_a_stated_limitation_not_an_accounting_error` | 1 | PASS | assertions held | P0 |
| F01 | Benchmarks | benchmarks are built independently and labelled accurately | `tests/qa/test_e_f_accounting_benchmarks.py::test_f01_benchmarks_are_built_independently_and_labelled_accurately` | 1 | PASS | assertions held | P1 |
| F02 | Benchmarks | single asset portfolio benchmarks are all identical characterisation | `tests/qa/test_e_f_accounting_benchmarks.py::test_f02_single_asset_portfolio_benchmarks_are_all_identical_characterisation` | 1 | PASS | current behaviour recorded (see paired XFAIL / backlog) | P1 |
| F02B | Benchmarks | benchmarks should be distinct from the portfolio and each other | `tests/qa/test_e_f_accounting_benchmarks.py::test_f02b_benchmarks_should_be_distinct_from_the_portfolio_and_each_other` | 1 | XFAIL | QA-001: duplicate benchmarks are offered for a single-asset portfolio | P1 |
| F03 | Benchmarks | chart series reconcile with the statistics table | `tests/qa/test_e_f_accounting_benchmarks.py::test_f03_chart_series_reconcile_with_the_statistics_table` | 1 | PASS | assertions held | P1 |
| F04 | Benchmarks | ui orders user portfolios first and hides duplicate names | `tests/qa/test_e_f_accounting_benchmarks.py::test_f04_ui_orders_user_portfolios_first_and_hides_duplicate_names` | 1 | PASS | assertions held | P1 |
| G01 | Monte Carlo / model risk | shape determinism and validity | `tests/qa/test_g_h_simulation_stress.py::test_g01_shape_determinism_and_validity` | 3 | PASS | assertions held | P1 |
| G02 | Monte Carlo / model risk | every simulated step is an observed return compounded correctly | `tests/qa/test_g_h_simulation_stress.py::test_g02_every_simulated_step_is_an_observed_return_compounded_correctly` | 3 | PASS | assertions held | P1 |
| G03 | Monte Carlo / model risk | block methods preserve runs of consecutive days | `tests/qa/test_g_h_simulation_stress.py::test_g03_block_methods_preserve_runs_of_consecutive_days` | 1 | PASS | assertions held | P1 |
| G04 | Monte Carlo / model risk | event counts and probabilities are exact arithmetic | `tests/qa/test_g_h_simulation_stress.py::test_g04_event_counts_and_probabilities_are_exact_arithmetic` | 1 | PASS | assertions held | P1 |
| G05 | Monte Carlo / model risk | cash dilutes risk proportionally and all cash is flat | `tests/qa/test_g_h_simulation_stress.py::test_g05_cash_dilutes_risk_proportionally_and_all_cash_is_flat` | 1 | PASS | assertions held | P1 |
| G06 | Monte Carlo / model risk | invalid inputs are refused | `tests/qa/test_g_h_simulation_stress.py::test_g06_invalid_inputs_are_refused` | 1 | PASS | assertions held | P1 |
| G07 | Monte Carlo / model risk | ui export summary is reproducible from the same inputs | `tests/qa/test_g_h_simulation_stress.py::test_g07_ui_export_summary_is_reproducible_from_the_same_inputs` | 1 | PASS | assertions held | P1 |
| G08 | Monte Carlo / model risk | model risk drawdown frequency depends on the resampling method | `tests/qa/test_g_h_simulation_stress.py::test_g08_model_risk_drawdown_frequency_depends_on_the_resampling_method` | 1 | PASS | assertions held | P1 |
| G09 | Monte Carlo / model risk | more paths narrow the spread across seeds at the expected rate | `tests/qa/test_g_h_simulation_stress.py::test_g09_more_paths_narrow_the_spread_across_seeds_at_the_expected_rate` | 1 | PASS | assertions held | P1 |
| H01 | Stress testing | reference scenario loss is 14665 | `tests/qa/test_g_h_simulation_stress.py::test_h01_reference_scenario_loss_is_14665` | 1 | PASS | assertions held | P1 |
| H02 | Stress testing | scenario pnl equals the sum of holding pnl | `tests/qa/test_g_h_simulation_stress.py::test_h02_scenario_pnl_equals_the_sum_of_holding_pnl` | 6 | PASS | assertions held | P1 |
| H03 | Stress testing | missing instrument and excess loss are refused | `tests/qa/test_g_h_simulation_stress.py::test_h03_missing_instrument_and_excess_loss_are_refused` | 1 | PASS | assertions held | P1 |
| H04 | Stress testing | non finite shocks characterisation | `tests/qa/test_g_h_simulation_stress.py::test_h04_non_finite_shocks_characterisation` | 1 | PASS | current behaviour recorded (see paired XFAIL / backlog) | P1 |
| H04B | Stress testing | non finite shocks should be rejected | `tests/qa/test_g_h_simulation_stress.py::test_h04b_non_finite_shocks_should_be_rejected` | 2 | XFAIL | QA-009: non-finite stress shocks are not rejected | P2 |
| H05 | Stress testing | zero value portfolio characterisation | `tests/qa/test_g_h_simulation_stress.py::test_h05_zero_value_portfolio_characterisation` | 1 | PASS | current behaviour recorded (see paired XFAIL / backlog) | P1 |
| H06 | Stress testing | stress page labels scenarios as hypothetical and reconciles | `tests/qa/test_g_h_simulation_stress.py::test_h06_stress_page_labels_scenarios_as_hypothetical_and_reconciles` | 1 | PASS | assertions held | P1 |
| I01 | Research integrity | decisions fill at the next session and warm up is respected | `tests/qa/test_i_j_research_exports.py::test_i01_decisions_fill_at_the_next_session_and_warm_up_is_respected` | 1 | PASS | assertions held | P1 |
| I02 | Research integrity | split is chronological and the grid cannot see the test period | `tests/qa/test_i_j_research_exports.py::test_i02_split_is_chronological_and_the_grid_cannot_see_the_test_period` | 1 | PASS | assertions held | P1 |
| I03 | Research integrity | multiple comparison adjustments by hand | `tests/qa/test_i_j_research_exports.py::test_i03_multiple_comparison_adjustments_by_hand` | 1 | PASS | assertions held | P1 |
| I04 | Research integrity | bootstrap is reproducible paired and sensitive to block length | `tests/qa/test_i_j_research_exports.py::test_i04_bootstrap_is_reproducible_paired_and_sensitive_to_block_length` | 1 | PASS | assertions held | P1 |
| I05 | Research integrity | transaction costs only ever reduce returns | `tests/qa/test_i_j_research_exports.py::test_i05_transaction_costs_only_ever_reduce_returns` | 1 | PASS | assertions held | P1 |
| I06 | Research integrity | the published record and frozen dataset are intact | `tests/qa/test_i_j_research_exports.py::test_i06_the_published_record_and_frozen_dataset_are_intact` | 1 | PASS | assertions held | P1 |
| I07 | Research integrity | sign convention of published improvements | `tests/qa/test_i_j_research_exports.py::test_i07_sign_convention_of_published_improvements` | 1 | PASS | assertions held | P1 |
| I08 | Research integrity | validation lab label characterisation | `tests/qa/test_i_j_research_exports.py::test_i08_validation_lab_label_characterisation` | 1 | PASS | current behaviour recorded (see paired XFAIL / backlog) | P1 |
| I08B | Research integrity | validation lab header should not claim one subtraction for all rows | `tests/qa/test_i_j_research_exports.py::test_i08b_validation_lab_header_should_not_claim_one_subtraction_for_all_rows` | 1 | XFAIL | QA-013: Validation Lab column header misstates the sign of the ES row | P1 |
| I09 | Research integrity | published study caption should describe the improvement convention | `tests/qa/test_i_j_research_exports.py::test_i09_published_study_caption_should_describe_the_improvement_convention` | 1 | XFAIL | QA-014: study caption says 'trend minus buy-and-hold' for improvement-oriented rows | P1 |
| I10 | Research integrity | published study page separates confirmatory from exploratory | `tests/qa/test_i_j_research_exports.py::test_i10_published_study_page_separates_confirmatory_from_exploratory` | 1 | PASS | assertions held | P1 |
| J01 | Exports / reporting | investment lab record contains what reproduction needs | `tests/qa/test_i_j_research_exports.py::test_j01_investment_lab_record_contains_what_reproduction_needs` | 1 | PASS | assertions held | P2 |
| J02 | Exports / reporting | portfolio file round trip and corrupt files | `tests/qa/test_i_j_research_exports.py::test_j02_portfolio_file_round_trip_and_corrupt_files` | 1 | PASS | assertions held | P2 |
| J03 | Exports / reporting | undefined values are exported safely | `tests/qa/test_i_j_research_exports.py::test_j03_undefined_values_are_exported_safely` | 1 | PASS | assertions held | P2 |
| J04 | Exports / reporting | backtest html formats percentages and flags synthetic data | `tests/qa/test_i_j_research_exports.py::test_j04_backtest_html_formats_percentages_and_flags_synthetic_data` | 1 | PASS | assertions held | P2 |
| J05 | Exports / reporting | investment lab html characterisation | `tests/qa/test_i_j_research_exports.py::test_j05_investment_lab_html_characterisation` | 1 | PASS | current behaviour recorded (see paired XFAIL / backlog) | P2 |
| J05B | Exports / reporting | investment lab html should show returns as percentages | `tests/qa/test_i_j_research_exports.py::test_j05b_investment_lab_html_should_show_returns_as_percentages` | 1 | XFAIL | QA-002: Investment Lab HTML shows returns as raw decimals | P1 |
| J05C | Exports / reporting | html should omit a section with no content | `tests/qa/test_i_j_research_exports.py::test_j05c_html_should_omit_a_section_with_no_content` | 1 | XFAIL | QA-003: HTML report prints an empty Strategy section | P2 |
| J05D | Exports / reporting | html should state the portfolio allocations | `tests/qa/test_i_j_research_exports.py::test_j05d_html_should_state_the_portfolio_allocations` | 1 | XFAIL | QA-022: Investment Lab HTML omits the portfolio allocations | P2 |
| J06 | Exports / reporting | risk export metadata characterisation | `tests/qa/test_i_j_research_exports.py::test_j06_risk_export_metadata_characterisation` | 1 | PASS | current behaviour recorded (see paired XFAIL / backlog) | P2 |
| J06B | Exports / reporting | risk export should carry reproducibility metadata | `tests/qa/test_i_j_research_exports.py::test_j06b_risk_export_should_carry_reproducibility_metadata` | 1 | XFAIL | QA-023: risk export lacks dataset fingerprint and environment | P2 |
| J07 | Exports / reporting | formatting of percentages and negative zero characterisation | `tests/qa/test_i_j_research_exports.py::test_j07_formatting_of_percentages_and_negative_zero_characterisation` | 1 | PASS | current behaviour recorded (see paired XFAIL / backlog) | P2 |
| J07B | Exports / reporting | rounded zero should not carry a minus sign | `tests/qa/test_i_j_research_exports.py::test_j07b_rounded_zero_should_not_carry_a_minus_sign` | 1 | XFAIL | QA-012: negative zero is displayed ("-0.00") | P3 |
| J08 | Exports / reporting | research markdown and manifest are consistent with the record | `tests/qa/test_i_j_research_exports.py::test_j08_research_markdown_and_manifest_are_consistent_with_the_record` | 1 | PASS | assertions held | P2 |
| K01 | Security / resilience | malformed uploads are rejected with a reason | `tests/qa/test_k_m_security_operations.py::test_k01_malformed_uploads_are_rejected_with_a_reason` | 7 | PASS | assertions held | P1 |
| K02 | Security / resilience | impossible prices in an upload are refused not repaired | `tests/qa/test_k_m_security_operations.py::test_k02_impossible_prices_in_an_upload_are_refused_not_repaired` | 3 | PASS | assertions held | P1 |
| K03 | Security / resilience | unicode bom timezones duplicates and ordering are handled openly | `tests/qa/test_k_m_security_operations.py::test_k03_unicode_bom_timezones_duplicates_and_ordering_are_handled_openly` | 1 | PASS | assertions held | P1 |
| K04 | Security / resilience | large upload is bounded by configuration and parses in bounded time | `tests/qa/test_k_m_security_operations.py::test_k04_large_upload_is_bounded_by_configuration_and_parses_in_bounded_time` | 1 | PASS | assertions held | P1 |
| K05 | Security / resilience | html report escapes every user controlled string | `tests/qa/test_k_m_security_operations.py::test_k05_html_report_escapes_every_user_controlled_string` | 1 | PASS | assertions held | P1 |
| K06 | Security / resilience | json exports are strict json and inert | `tests/qa/test_k_m_security_operations.py::test_k06_json_exports_are_strict_json_and_inert` | 1 | PASS | assertions held | P1 |
| K07 | Security / resilience | csv formula injection characterisation | `tests/qa/test_k_m_security_operations.py::test_k07_csv_formula_injection_characterisation` | 1 | PASS | current behaviour recorded (see paired XFAIL / backlog) | P1 |
| K07B | Security / resilience | csv exports should neutralise leading formula characters | `tests/qa/test_k_m_security_operations.py::test_k07b_csv_exports_should_neutralise_leading_formula_characters` | 1 | XFAIL | QA-004: CSV exports do not neutralise spreadsheet formulas | P1 |
| K08 | Security / resilience | start argument can escape the cache folder characterisation | `tests/qa/test_k_m_security_operations.py::test_k08_start_argument_can_escape_the_cache_folder_characterisation` | 1 | PASS | current behaviour recorded (see paired XFAIL / backlog) | P1 |
| K08B | Security / resilience | store should refuse a start that is not a date | `tests/qa/test_k_m_security_operations.py::test_k08b_store_should_refuse_a_start_that_is_not_a_date` | 1 | XFAIL | QA-005: LiveDataStore does not validate `start` before building a path | P2 |
| K09 | Security / resilience | cache recovery note characterisation | `tests/qa/test_k_m_security_operations.py::test_k09_cache_recovery_note_characterisation` | 1 | PASS | current behaviour recorded (see paired XFAIL / backlog) | P1 |
| K09B | Security / resilience | user facing notes should not contain server paths | `tests/qa/test_k_m_security_operations.py::test_k09b_user_facing_notes_should_not_contain_server_paths` | 1 | XFAIL | QA-008: recovery notes expose the server's filesystem path | P2 |
| K10 | Security / resilience | uploaded file name reaches the page as markup characterisation | `tests/qa/test_k_m_security_operations.py::test_k10_uploaded_file_name_reaches_the_page_as_markup_characterisation` | 1 | PASS | current behaviour recorded (see paired XFAIL / backlog) | P1 |
| K10B | Security / resilience | badge should escape instrument names | `tests/qa/test_k_m_security_operations.py::test_k10b_badge_should_escape_instrument_names` | 1 | XFAIL | QA-015: uploaded file name is not escaped in the data-source badge | P1 |
| K11 | Security / resilience | no dynamic code execution shell or unsafe deserialisation | `tests/qa/test_k_m_security_operations.py::test_k11_no_dynamic_code_execution_shell_or_unsafe_deserialisation` | 1 | PASS | assertions held | P1 |
| K12 | Security / resilience | raw html is only used in known places | `tests/qa/test_k_m_security_operations.py::test_k12_raw_html_is_only_used_in_known_places` | 1 | PASS | assertions held | P1 |
| K13 | Security / resilience | no credentials or private keys in tracked files | `tests/qa/test_k_m_security_operations.py::test_k13_no_credentials_or_private_keys_in_tracked_files` | 1 | PASS | assertions held | P1 |
| K14 | Security / resilience | pages never show a traceback for bad input | `tests/qa/test_k_m_security_operations.py::test_k14_pages_never_show_a_traceback_for_bad_input` | 1 | PASS | assertions held | P1 |
| K15 | Security / resilience | the library needs no network and opens no socket | `tests/qa/test_k_m_security_operations.py::test_k15_the_library_needs_no_network_and_opens_no_socket` | 1 | PASS | assertions held | P1 |
| M01 | Performance / operations | core computations finish within loose bounds | `tests/qa/test_k_m_security_operations.py::test_m01_core_computations_finish_within_loose_bounds` | 1 | PASS | assertions held | P2 |
| M02 | Performance / operations | backtest cost grows roughly linearly with history | `tests/qa/test_k_m_security_operations.py::test_m02_backtest_cost_grows_roughly_linearly_with_history` | 1 | PASS | assertions held | P2 |
| M03 | Performance / operations | every page renders from a cold start within a bound | `tests/qa/test_k_m_security_operations.py::test_m03_every_page_renders_from_a_cold_start_within_a_bound` | 1 | PASS | assertions held | P2 |
| M04 | Performance / operations | router registers nine pages and stable urls | `tests/qa/test_k_m_security_operations.py::test_m04_router_registers_nine_pages_and_stable_urls` | 1 | PASS | assertions held | P2 |
| M05 | Performance / operations | importing the library does not load the dashboard or the data provider | `tests/qa/test_k_m_security_operations.py::test_m05_importing_the_library_does_not_load_the_dashboard_or_the_data_provider` | 1 | PASS | assertions held | P2 |
| M06 | Performance / operations | ci runs the supported versions lint tests and study verification | `tests/qa/test_k_m_security_operations.py::test_m06_ci_runs_the_supported_versions_lint_tests_and_study_verification` | 1 | PASS | assertions held | P2 |
| M07 | Performance / operations | dependencies are declared and dev tools stay out of the runtime | `tests/qa/test_k_m_security_operations.py::test_m07_dependencies_are_declared_and_dev_tools_stay_out_of_the_runtime` | 1 | PASS | assertions held | P2 |
| L01 | Browser / UX | home page lists all nine pages | `tests/browser/smoke.js` | 1 | PASS | 9 links | P2 |
| L02 | Browser / UX | sidebar navigation renders every page without an error box | `tests/browser/smoke.js` | 1 | PASS | check held | P2 |
| L03 | Browser / UX | direct links work on a fresh session | `tests/browser/smoke.js` | 1 | PASS | check held | P2 |
| L04 | Browser / UX | synthetic data is labelled as synthetic | `tests/browser/smoke.js` | 1 | PASS | SYNTHETIC DEMO DATA | P2 |
| L05 | Browser / UX | browser refresh reproduces the same result | `tests/browser/smoke.js` | 1 | PASS | 257,336 -> 257,336 | P2 |
| L06 | Browser / UX | editing an allocation updates the result | `tests/browser/smoke.js` | 1 | PASS | 257,336 -> 228,908 | P2 |
| L07 | Browser / UX | over-allocation is refused, then recovers when corrected | `tests/browser/smoke.js` | 1 | PASS | refused true, recovered true | P2 |
| L08 | Browser / UX | rapid edits settle on the last input | `tests/browser/smoke.js` | 1 | PASS | 223,990 | P2 |
| L09 | Browser / UX | every Investment Lab tab renders | `tests/browser/smoke.js` | 1 | PASS | Growth / Compare / Drawdown & drift / Risk insights / Costs & timeline / Assumptions / Save & export | P2 |
| L11 | Browser / UX | exported final value equals the value on screen | `tests/browser/smoke.js` | 1 | PASS | 5 downloads; file 223,990, screen 223,990 | P2 |
| L12 | Browser / UX | HTML report is self-contained and carries the synthetic banner | `tests/browser/smoke.js` | 1 | PASS | 48605 bytes | P2 |
| L10 | Browser / UX | saving and reloading a portfolio reproduces the result | `tests/browser/smoke.js` | 1 | PASS | saved 223,990, reloaded 223,990 | P2 |
| L13 | Browser / UX | a corrupt portfolio file is refused with a message | `tests/browser/smoke.js` | 1 | PASS | check held | P2 |
| L14 | Browser / UX | laptop layout (1280x720); phone layout (390x844) | `tests/browser/smoke.js` | 2 | PASS | horizontal overflow 0px, clipped labels 0; horizontal overflow 0px, clipped labels 0 | P2 |
| L15 | Browser / UX | controls are named, keyboard focus moves, one page heading | `tests/browser/smoke.js` | 1 | PASS | unnamed controls 0 , focus on A, h1 1, lang "en" | P2 |
| L16 | Browser / UX | stress page shows scenario and per-holding results | `tests/browser/smoke.js` | 1 | PASS | 3 tables | P2 |
| L17 | Browser / UX | Monte Carlo page labels itself as not a forecast | `tests/browser/smoke.js` | 1 | PASS | check held | P2 |
| L18 | Browser / UX | no uncaught browser errors during the run | `tests/browser/smoke.js` | 1 | PASS | check held | P2 |
