# Quant Lab 3.0 — Future Wealth: implementation report

Branch `claude/future-wealth-v1`, from the remediation branch at `d436baf`.
Methodology and assumptions: [forecasting.md](forecasting.md).

**Status: working and verified on synthetic data, in three Python versions, in clean
hash-locked environments and in a real browser; suitable for private use. Not approved for
public production** — for the same reasons as the rest of Quant Lab: market-data rights
(QA-035), no authentication or hosting evidence.

## 1. What was built

| Component | File | What it does |
|---|---|---|
| Plan | `forecast/plan.py` | `WealthPlan`: weights (rest cash), initial amount, contribution and frequency, yearly contribution growth, rebalancing, trading cost, annual fee, cash yield, inflation, horizon (1 month to 50 years). Every input validated; `from_spec` reuses an Investment Lab portfolio. |
| Return models | `forecast/returns.py` | Monthly returns from daily closes (held instruments only; incomplete final month dropped). Four joint models: i.i.d. bootstrap, stationary block bootstrap, EWMA filtered historical simulation, Gaussian baseline. |
| Account engine | `forecast/engine.py` | Vectorised monthly ledger with a fixed event order (deposit, trade with exact proportional costs, optional shock, market and interest, fee, valuation); time-weighted drawdowns; ledger identity; memory and work limits. |
| Goals and decisions | `forecast/goals.py` | Reach-by-horizon vs hold-at-end probabilities with Wilson intervals; first passage; percentile intervals from order statistics; deposits vs growth; deterministic and probabilistic required contributions; plan comparisons on common random numbers; model and history-window sensitivity. |
| Validation | `forecast/validation.py`, `experiments/forecast_validation.py` | Walk-forward evaluation without look-ahead; coverage, PIT, CRPS, Brier, pinball; Diebold–Mariano (Newey–West, Harvey–Leybourne–Newbold, t) with Holm adjustment and a minimum-sample rule; record summary for display. |
| Forecast record | `forecast/ledger.py` | Append-only, SHA-256 hash-chained forecasts and evaluations; tamper detection; due-forecast scoring against realised months. |
| Scenarios | `forecast/scenario.py` | Re-runnable scenario files; exact re-run. |
| Runtime maths | `forecast/_stats.py` | Normal, Student t and binomial functions, so the package needs only NumPy and pandas at run time. |
| Interface | `app/components/future_wealth.py` | "Future wealth" mode inside the Investment Lab (the historical comparison stays the default). |

## 2. The interface

Plan inputs up front (starting amount, regular contribution, yearly increase, horizon, goal,
holdings); costs and advanced model settings in expanders. Headline cards: median ending value
(and in today's money), 5th–95th percentile, chance of reaching the goal by the horizon, of
holding it at the end, of ending below the money paid in, and total paid in — each probability
with its 95% sampling range. A plain-language paragraph says what drives the projection
(deposits vs growth, history window, costs, inflation), followed by warnings when a model is
used outside its suitable horizon or when validation found long-horizon ranges too narrow.

Tabs: Projection (fan chart, paid-in line, goal), Milestones ($100k, $250k, $500k, $1M and the
goal: reach, hold, median time, by-year curves), Deposits vs growth, Downside (1-in-100 and
1-in-20 outcomes, drawdown distribution, the same 35% crash early versus late), Compare plans
(contribution level, allocation, fees, contribution growth, cash share; common random numbers),
Required contribution (constant-return arithmetic and 50/75/90% simulated), Model sensitivity
(4 models × history windows; sampling vs model uncertainty stated numerically), Validation
(stored study, generated summary, optional quick check on the loaded data), Assumptions & export
(event order, model description, scenario JSON, percentile CSV, forecast record).

## 3. Validity audit

| Risk | How it is handled | Evidence |
|---|---|---|
| Look-ahead in validation | Each forecast is fitted on months up to its origin only; outcomes are the next h months. | `test_r03` rewrites every later month and the forecasts do not change; `test_r04` checks outcomes. |
| Leakage into recorded forecasts | The record stores the last data month; evaluation uses only months after it, once each month of the horizon exists. | `test_r10`. |
| Overstated significance | Holm across models; HLN small-sample correction; no test with fewer than 20 independent outcomes. | The synthetic check found false 36-month "wins" before the fix; `test_r05`, `r07`, `r12`, `r13`. |
| Test power | On data with persistent volatility regimes EWMA must win — and does. | `test_r06`. |
| Stale or invented claims | Statements about validation on the page are computed from the stored record. | `test_r16`, `test_s09`. |
| Projection vs outcome | "Not a forecast" and model labels on every view; sampling ranges labelled as path noise only; model sensitivity shown numerically; long horizons warned as too narrow. | `test_s02`, browser L23. |
| Reproducibility | Same seed and inputs give identical arrays; scenario files re-run bit for bit. | `test_q12`, `test_r11`. |
| Survivorship and hindsight | Disclosed; not correctable with the available data. | `docs/forecasting.md` §8. |
| Data reuse | The validation data were used before for the trend study (QA-033); disclosed in the report. | `reports/forecast_validation.md`. |

## 4. Validation results

> Results computed on the private reference dataset are not published in this copy: redistribution
> rights for that data are not established. The code that produces them is included; run it on data
> you are licensed to use.

## 5. Tests

All results below were executed on the final code of this branch (2026-11-18).

| Check | Result |
|---|---|
| Full pytest, Python 3.13.18 / 3.12.3 / 3.11.18 | 763 passed on each before the last two tests were added; **764 passed** in the clean environments below. 0 failed, 0 skipped, 0 expected failures. 4 warnings on 3.11/3.12 are the pre-existing pandas ones. |
| Clean hash-locked environments (`tools/verify_clean_env.sh`), 3.11.18 and 3.13.18 | PASS: fresh venv, `--require-hashes` install, `pip check`, Ruff, 764 passed, study verification |
| Frozen trend study, exact environment (NumPy 2.5.3, pandas 3.0.5) | PASS, largest difference **0** |
| Frozen trend study, current locked versions | PASS, 4.17e-14 (library-version rounding, documented as QA-043) |
| Browser (Chromium, `tests/browser/run.sh`) | **24 passed**, 0 failed, including L23 (Future Wealth projects, explains model uncertainty, records a forecast) |
| Ruff | clean |
| Wheel build and clean import | PASS; `quantlab.forecast` imports without SciPy |

New tests in this milestone (95 in all):

| Suite | Tests | Covers |
|---|---:|---|
| Q `test_q_future_wealth.py` | 62 | Engine against an independent plain-Python ledger (12 configurations plus 60 property-based examples); ledger identity at every month and path; zero-return, all-cash, zero-contribution, increasing-contribution, rebalancing, transaction-cost, crash and persistently negative markets; invalid plans and inputs; seed reproducibility and common random numbers; monthly history construction; horizons from 1 month to 50 years; resource guard; goal probabilities and first passage by brute force; percentile intervals; inflation; closed-form annuity and required contributions; model definitions (including an independent EWMA re-implementation and correlation preservation); runtime and memory bound. |
| R `test_r_forecast_validation.py` | 18 | CRPS against its closed form; DM and KS references; no look-ahead; realised outcomes; calibration and no reward for complexity on correctly specified data; power on regime data; Holm; HLN; minimum-sample rule; ledger append-only, tamper detection (edit, delete, reorder), single evaluation; scenario re-run; runtime maths against SciPy; import without SciPy; record summary. |
| S `test_s_future_wealth_ui.py` | 15 | Default mode unchanged; every section rendered with its labels; headline numbers equal library numbers; inputs change outputs; leverage, all-cash, zero-contribution and 30-year plans; model and crash settings; common random numbers in comparisons; forecast recording; validation text generated from the record; standard horizons; Overview regression. |

## 6. Performance (bounded benchmark, one shared container, indicative)

| Operation | Time | Peak memory |
|---|---:|---:|
| 2,000 paths × 10 years × 2 assets (any model) | 0.05–0.06 s | 2.6 MB |
| 10,000 paths × 20 years × 3 assets | 0.36–0.52 s | 22 MB |
| 20,000 paths × 20 years × 3 assets (dashboard maximum at 20 years) | 0.74–0.99 s | 44 MB |
| Required contribution, 500 paths, bisection to $5 | 0.38 s | <1 MB |
| Model sensitivity, 4 models × 3 windows, 1,000 paths | 0.72 s | 1.3 MB |
| Quick walk-forward check (4 models, 1 and 12 months) | 1.57 s | 1.1 MB |
| Future Wealth page, cold render with default settings | 1.94 s | 32 MB |

EWMA is the slowest (sequential volatility update). Limits: 15 million stored values and 300
million path-month-instrument operations per run; larger requests are refused with a reason
(`test_q14b`).

## 7. Defects found and fixed during this milestone

| Found by | Defect | Fix |
|---|---|---|
| Suite Q | `required_contribution` crashed when the plan had no initial amount (built an invalid zero plan). | Guard before building the trial plan. |
| Synthetic validation run | False "significant" wins at 36 months on i.i.d. normal data. | HLN correction, t p-values, Holm, minimum 20 independent outcomes; regression test. |
| Suite S | An all-cash plan crashed the Compare tab (model built on zero instruments). | Fall back to the loaded history. |
| Browser suite | New result files in `experiments/results` crashed the Overview page. | Overview reads only trend-study records; regression test. |
| Review | Runtime imports of SciPy, a development-only dependency: a hosted app would not start. | `forecast/_stats.py`, tested against SciPy; import test. |
| Review | Validation findings typed into the interface could go stale. | Generated from the record. |

## 8. Limitations and remaining risks

- Projections assume the future resembles the sampled history; long-horizon (10–20 year)
  calibration cannot be validated with ~33 years of data, and 12-month ranges were too narrow.
- US-equity-heavy demo instruments; no bonds or international data in the frozen snapshot.
- Month-end granularity; no taxes, withdrawals or behavioural changes; constant contribution
  growth; buy-only months leave the cash share approximately (not exactly) on target.
- The forecast record lives in a local folder (`QUANTLAB_FORECAST_DIR`); it is append-only and
  tamper-evident, not tamper-proof (anyone with file access can delete the whole file).
- Interface performance: about 2 s per change at default settings; 20,000-path runs with many
  comparison and sensitivity tabs take several seconds.
- Not deployed publicly; data rights (QA-035) unchanged.
