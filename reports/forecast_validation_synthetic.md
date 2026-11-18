# Forecast validation: walk-forward calibration of the Future Wealth models

Protocol hash `22657a8a1869`; data fingerprint `bfe00e3e2c4502a0` (SYNTHETIC); generated 2026-11-17T14:29:57+00:00. Record: `experiments/results/forecast_validation_22657a8a1869_synthetic.json`.

**Question.** Are the Future Wealth return models calibrated out of sample, and does any beat a normal (Gaussian i.i.d.) baseline?

**Decision rule (fixed in advance).** A model beats the baseline only if its mean CRPS is lower and a Diebold-Mariano test (Newey-West variance with h-1 lags, Harvey-Leybourne-Newbold small-sample correction, t p-values) rejects equality at 5% after Holm adjustment across the models tested at that portfolio, horizon and window. No test is attempted with fewer than 20 non-overlapping outcomes.

**Reading the table.** coverage_90 should be near 90% and coverage_50 near 50%; pit_ks is the distance of the PIT values from uniform (0 is perfect); crps is lower-is-better; skills are 1 - model/baseline (positive is better than the normal baseline). 'independent_outcomes' counts non-overlapping horizons: 12- and 36-month results rest on few independent observations and are weak evidence either way.

**Data caveat.** The snapshot was used before for the trend study (QA-033). Each forecast uses only months up to its origin; no setting was tuned on outcomes. This measures calibration, not a trading edge.

## Overall reading

- 36 model-versus-baseline tests were possible (18 more had too few independent outcomes and were not attempted).
- Significantly better than the normal baseline: none.
- Significantly worse: iid_bootstrap (SPY, 1m, rolling 60 months), block_bootstrap (SPY, 1m, rolling 60 months), ewma_filtered (SPY, 1m, rolling 60 months), iid_bootstrap (SPY, 1m, expanding), block_bootstrap (SPY, 1m, expanding), ewma_filtered (SPY, 1m, expanding).
- Holm adjustment is applied within each portfolio, horizon and window, not across the whole table of 36 tests: an isolated win should be read as weak evidence; a pattern that repeats across windows and portfolios is stronger.
- Mean 90% interval coverage by horizon (all windows and portfolios): 1 month: block_bootstrap 89%, ewma_filtered 89%, gaussian_iid 90%, iid_bootstrap 89%; 12 months: block_bootstrap 83%, ewma_filtered 89%, gaussian_iid 89%, iid_bootstrap 89%; 36 months: block_bootstrap 77%, ewma_filtered 88%, gaussian_iid 87%, iid_bootstrap 87%.

## Portfolio: SPY

Monthly returns 1993-02-28 to 2026-10-31 (405 months). 11,148 forecasts scored.

| horizon | window | model | forecasts | independent_outcomes | coverage_90 | coverage_50 | pit_ks | crps | crps_skill_vs_baseline | dm_p_holm | brier_skill_vs_baseline |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | rolling 60 months | iid_bootstrap | 345 | 345 | 89.0% | 47.5% | 0.0279 | 0.0323 | -1.0% | 0.0113 | -0.8% |
| 1 | rolling 60 months | block_bootstrap | 345 | 345 | 89.0% | 47.5% | 0.0279 | 0.0323 | -1.0% | 0.0113 | -0.8% |
| 1 | rolling 60 months | ewma_filtered | 345 | 345 | 89.9% | 48.1% | 0.0279 | 0.0323 | -1.1% | 0.0113 | -0.6% |
| 1 | rolling 60 months | gaussian_iid | 345 | 345 | 90.4% | 48.7% | 0.0231 | 0.0320 | 0.0% | n/a | 0.0% |
| 1 | expanding | iid_bootstrap | 345 | 345 | 88.1% | 50.4% | 0.0431 | 0.0321 | -1.0% | 0.0096 | -1.1% |
| 1 | expanding | block_bootstrap | 345 | 345 | 88.1% | 50.4% | 0.0431 | 0.0321 | -1.0% | 0.0096 | -1.1% |
| 1 | expanding | ewma_filtered | 345 | 345 | 89.3% | 51.0% | 0.0432 | 0.0321 | -1.1% | 0.0096 | -1.2% |
| 1 | expanding | gaussian_iid | 345 | 345 | 89.0% | 48.7% | 0.0262 | 0.0317 | 0.0% | n/a | 0.0% |
| 1 | rolling 120 months | iid_bootstrap | 285 | 285 | 88.4% | 48.4% | 0.0372 | 0.0331 | -0.6% | 0.3369 | -0.6% |
| 1 | rolling 120 months | block_bootstrap | 285 | 285 | 88.4% | 48.4% | 0.0372 | 0.0331 | -0.6% | 0.3369 | -0.6% |
| 1 | rolling 120 months | ewma_filtered | 285 | 285 | 88.4% | 48.4% | 0.0397 | 0.0331 | -0.7% | 0.3369 | -0.6% |
| 1 | rolling 120 months | gaussian_iid | 285 | 285 | 88.1% | 48.1% | 0.0347 | 0.0329 | 0.0% | n/a | 0.0% |
| 12 | rolling 60 months | iid_bootstrap | 334 | 28 | 88.0% | 48.8% | 0.0502 | 0.1284 | 0.1% | 1.0000 | -0.7% |
| 12 | rolling 60 months | block_bootstrap | 334 | 28 | 76.9% | 42.8% | 0.0807 | 0.1317 | -2.5% | 0.4647 | -4.3% |
| 12 | rolling 60 months | ewma_filtered | 334 | 28 | 89.8% | 47.6% | 0.0542 | 0.1282 | 0.3% | 1.0000 | 0.8% |
| 12 | rolling 60 months | gaussian_iid | 334 | 28 | 87.7% | 47.6% | 0.0436 | 0.1285 | 0.0% | n/a | 0.0% |
| 12 | expanding | iid_bootstrap | 334 | 28 | 90.4% | 52.7% | 0.0344 | 0.1170 | 0.2% | 1.0000 | 0.1% |
| 12 | expanding | block_bootstrap | 334 | 28 | 79.3% | 44.3% | 0.0738 | 0.1184 | -1.0% | 1.0000 | -0.6% |
| 12 | expanding | ewma_filtered | 334 | 28 | 88.9% | 54.5% | 0.0426 | 0.1175 | -0.2% | 1.0000 | 0.9% |
| 12 | expanding | gaussian_iid | 334 | 28 | 90.7% | 53.0% | 0.0381 | 0.1172 | 0.0% | n/a | 0.0% |
| 12 | rolling 120 months | iid_bootstrap | 274 | 23 | 87.6% | 55.5% | 0.0977 | 0.1208 | 0.0% | 1.0000 | -0.5% |
| 12 | rolling 120 months | block_bootstrap | 274 | 23 | 83.9% | 50.7% | 0.0653 | 0.1217 | -0.8% | 1.0000 | -2.6% |
| 12 | rolling 120 months | ewma_filtered | 274 | 23 | 86.1% | 53.6% | 0.0984 | 0.1217 | -0.8% | 0.4523 | 0.6% |
| 12 | rolling 120 months | gaussian_iid | 274 | 23 | 88.3% | 54.7% | 0.0901 | 0.1208 | 0.0% | n/a | 0.0% |
| 36 | rolling 60 months | iid_bootstrap | 310 | 9 | 81.3% | 37.1% | 0.0909 | 0.3517 | -0.2% | 1.0000 | -0.8% |
| 36 | rolling 60 months | block_bootstrap | 310 | 9 | 65.5% | 32.6% | 0.1604 | 0.3738 | -6.5% | 0.3363 | 4.6% |
| 36 | rolling 60 months | ewma_filtered | 310 | 9 | 81.9% | 37.1% | 0.0998 | 0.3521 | -0.3% | 1.0000 | 3.2% |
| 36 | rolling 60 months | gaussian_iid | 310 | 9 | 82.9% | 37.4% | 0.0919 | 0.3510 | 0.0% | n/a | 0.0% |
| 36 | expanding | iid_bootstrap | 310 | 9 | 90.3% | 56.1% | 0.1002 | 0.2687 | -0.1% | 1.0000 | -0.7% |
| 36 | expanding | block_bootstrap | 310 | 9 | 78.7% | 49.0% | 0.1276 | 0.2731 | -1.8% | 1.0000 | 12.2% |
| 36 | expanding | ewma_filtered | 310 | 9 | 91.0% | 58.7% | 0.1064 | 0.2686 | -0.1% | 1.0000 | 0.3% |
| 36 | expanding | gaussian_iid | 310 | 9 | 90.0% | 56.5% | 0.0978 | 0.2683 | 0.0% | n/a | 0.0% |
| 36 | rolling 120 months | iid_bootstrap | 250 | 7 | 87.6% | 50.8% | 0.2190 | 0.3017 | 0.5% | 0.5743 | -0.4% |
| 36 | rolling 120 months | block_bootstrap | 250 | 7 | 80.4% | 47.2% | 0.1940 | 0.3062 | -1.0% | 1.0000 | 2.0% |
| 36 | rolling 120 months | ewma_filtered | 250 | 7 | 85.2% | 50.8% | 0.2230 | 0.3043 | -0.3% | 1.0000 | 3.1% |
| 36 | rolling 120 months | gaussian_iid | 250 | 7 | 87.6% | 52.4% | 0.2230 | 0.3032 | 0.0% | n/a | 0.0% |

**Conclusions (pre-stated decision rule):**

- 1-month horizon, rolling 60 months (345 non-overlapping outcomes): iid_bootstrap, block_bootstrap, ewma_filtered are significantly WORSE than the normal baseline. 90% interval coverage: iid_bootstrap 89%, block_bootstrap 89%, ewma_filtered 90%, gaussian_iid 90%.
- 1-month horizon, expanding (345 non-overlapping outcomes): iid_bootstrap, block_bootstrap, ewma_filtered are significantly WORSE than the normal baseline. 90% interval coverage: iid_bootstrap 88%, block_bootstrap 88%, ewma_filtered 89%, gaussian_iid 89%.
- 1-month horizon, rolling 120 months (285 non-overlapping outcomes): iid_bootstrap, block_bootstrap, ewma_filtered did not differ significantly from the normal baseline; the extra complexity is not supported by this evidence. 90% interval coverage: iid_bootstrap 88%, block_bootstrap 88%, ewma_filtered 88%, gaussian_iid 88%.
- 12-month horizon, rolling 60 months (28 non-overlapping outcomes): iid_bootstrap, block_bootstrap, ewma_filtered did not differ significantly from the normal baseline; the extra complexity is not supported by this evidence. 90% interval coverage: iid_bootstrap 88%, block_bootstrap 77%, ewma_filtered 90%, gaussian_iid 88%.
- 12-month horizon, expanding (28 non-overlapping outcomes): iid_bootstrap, block_bootstrap, ewma_filtered did not differ significantly from the normal baseline; the extra complexity is not supported by this evidence. 90% interval coverage: iid_bootstrap 90%, block_bootstrap 79%, ewma_filtered 89%, gaussian_iid 91%.
- 12-month horizon, rolling 120 months (23 non-overlapping outcomes): iid_bootstrap, block_bootstrap, ewma_filtered did not differ significantly from the normal baseline; the extra complexity is not supported by this evidence. 90% interval coverage: iid_bootstrap 88%, block_bootstrap 84%, ewma_filtered 86%, gaussian_iid 88%.
- 36-month horizon, rolling 60 months (9 non-overlapping outcomes): too few independent outcomes (fewer than 20) to test any model against the baseline; no claim is made. 90% interval coverage, for information: iid_bootstrap 81%, block_bootstrap 65%, ewma_filtered 82%, gaussian_iid 83%.
- 36-month horizon, expanding (9 non-overlapping outcomes): too few independent outcomes (fewer than 20) to test any model against the baseline; no claim is made. 90% interval coverage, for information: iid_bootstrap 90%, block_bootstrap 79%, ewma_filtered 91%, gaussian_iid 90%.
- 36-month horizon, rolling 120 months (7 non-overlapping outcomes): too few independent outcomes (fewer than 20) to test any model against the baseline; no claim is made. 90% interval coverage, for information: iid_bootstrap 88%, block_bootstrap 80%, ewma_filtered 85%, gaussian_iid 88%.

90% interval coverage during the 2007-2009 crisis (rolling 120-month window):

| horizon | model | forecasts | coverage_90 |
|---|---|---|---|
| 1 | iid_bootstrap | 24 | 91.7% |
| 1 | block_bootstrap | 24 | 91.7% |
| 1 | ewma_filtered | 24 | 95.8% |
| 1 | gaussian_iid | 24 | 91.7% |
| 12 | iid_bootstrap | 24 | 100.0% |
| 12 | block_bootstrap | 24 | 100.0% |
| 12 | ewma_filtered | 24 | 100.0% |
| 12 | gaussian_iid | 24 | 100.0% |
| 36 | iid_bootstrap | 24 | 100.0% |
| 36 | block_bootstrap | 24 | 100.0% |
| 36 | ewma_filtered | 24 | 100.0% |
| 36 | gaussian_iid | 24 | 100.0% |

## Portfolio: equal_SPY_QQQ_IWM

Monthly returns 1993-02-28 to 2026-10-31 (405 months). 11,148 forecasts scored.

| horizon | window | model | forecasts | independent_outcomes | coverage_90 | coverage_50 | pit_ks | crps | crps_skill_vs_baseline | dm_p_holm | brier_skill_vs_baseline |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | rolling 60 months | iid_bootstrap | 345 | 345 | 88.7% | 49.9% | 0.0252 | 0.0174 | -0.4% | 1.0000 | -0.5% |
| 1 | rolling 60 months | block_bootstrap | 345 | 345 | 88.7% | 49.9% | 0.0252 | 0.0174 | -0.4% | 1.0000 | -0.5% |
| 1 | rolling 60 months | ewma_filtered | 345 | 345 | 88.7% | 51.0% | 0.0232 | 0.0173 | -0.3% | 1.0000 | -0.7% |
| 1 | rolling 60 months | gaussian_iid | 345 | 345 | 89.6% | 49.9% | 0.0400 | 0.0173 | 0.0% | n/a | 0.0% |
| 1 | expanding | iid_bootstrap | 345 | 345 | 90.7% | 51.3% | 0.0354 | 0.0173 | -0.5% | 0.2697 | -0.7% |
| 1 | expanding | block_bootstrap | 345 | 345 | 90.7% | 51.3% | 0.0354 | 0.0173 | -0.5% | 0.2697 | -0.7% |
| 1 | expanding | ewma_filtered | 345 | 345 | 90.4% | 51.9% | 0.0374 | 0.0173 | -0.5% | 0.2697 | -1.1% |
| 1 | expanding | gaussian_iid | 345 | 345 | 90.7% | 50.7% | 0.0341 | 0.0172 | 0.0% | n/a | 0.0% |
| 1 | rolling 120 months | iid_bootstrap | 285 | 285 | 89.8% | 49.5% | 0.0274 | 0.0175 | -0.5% | 0.6196 | -0.6% |
| 1 | rolling 120 months | block_bootstrap | 285 | 285 | 89.8% | 49.5% | 0.0274 | 0.0175 | -0.5% | 0.6196 | -0.6% |
| 1 | rolling 120 months | ewma_filtered | 285 | 285 | 90.2% | 51.2% | 0.0322 | 0.0176 | -0.6% | 0.6196 | -0.7% |
| 1 | rolling 120 months | gaussian_iid | 285 | 285 | 89.8% | 50.5% | 0.0474 | 0.0175 | 0.0% | n/a | 0.0% |
| 12 | rolling 60 months | iid_bootstrap | 334 | 28 | 88.0% | 57.8% | 0.0504 | 0.0617 | 0.1% | 1.0000 | 0.2% |
| 12 | rolling 60 months | block_bootstrap | 334 | 28 | 83.2% | 52.7% | 0.0519 | 0.0632 | -2.3% | 0.2430 | -2.9% |
| 12 | rolling 60 months | ewma_filtered | 334 | 28 | 88.3% | 57.2% | 0.0464 | 0.0616 | 0.2% | 1.0000 | 0.4% |
| 12 | rolling 60 months | gaussian_iid | 334 | 28 | 87.1% | 56.9% | 0.0474 | 0.0618 | 0.0% | n/a | 0.0% |
| 12 | expanding | iid_bootstrap | 334 | 28 | 89.5% | 51.5% | 0.1013 | 0.0627 | 0.4% | 0.4900 | -0.1% |
| 12 | expanding | block_bootstrap | 334 | 28 | 85.9% | 48.8% | 0.1042 | 0.0634 | -0.7% | 0.4900 | -2.2% |
| 12 | expanding | ewma_filtered | 334 | 28 | 89.5% | 53.3% | 0.1133 | 0.0626 | 0.5% | 0.4900 | 0.3% |
| 12 | expanding | gaussian_iid | 334 | 28 | 89.2% | 50.9% | 0.0992 | 0.0629 | 0.0% | n/a | 0.0% |
| 12 | rolling 120 months | iid_bootstrap | 274 | 23 | 88.7% | 55.1% | 0.0671 | 0.0629 | -0.2% | 0.6403 | -0.9% |
| 12 | rolling 120 months | block_bootstrap | 274 | 23 | 87.2% | 51.1% | 0.0381 | 0.0646 | -2.9% | 0.0584 | -3.6% |
| 12 | rolling 120 months | ewma_filtered | 274 | 23 | 89.1% | 56.6% | 0.0730 | 0.0624 | 0.5% | 0.3149 | 0.5% |
| 12 | rolling 120 months | gaussian_iid | 274 | 23 | 89.1% | 54.7% | 0.0633 | 0.0627 | 0.0% | n/a | 0.0% |
| 36 | rolling 60 months | iid_bootstrap | 310 | 9 | 91.6% | 44.8% | 0.0663 | 0.1283 | 0.5% | 0.3178 | -0.3% |
| 36 | rolling 60 months | block_bootstrap | 310 | 9 | 79.0% | 39.7% | 0.1134 | 0.1355 | -5.1% | 0.2875 | -2.6% |
| 36 | rolling 60 months | ewma_filtered | 310 | 9 | 91.6% | 45.2% | 0.0573 | 0.1280 | 0.7% | 0.3178 | -0.3% |
| 36 | rolling 60 months | gaussian_iid | 310 | 9 | 91.9% | 46.1% | 0.0604 | 0.1289 | 0.0% | n/a | 0.0% |
| 36 | expanding | iid_bootstrap | 310 | 9 | 87.1% | 48.1% | 0.1665 | 0.1266 | 0.9% | 0.0023 | 0.9% |
| 36 | expanding | block_bootstrap | 310 | 9 | 80.3% | 42.9% | 0.1862 | 0.1288 | -0.9% | 0.5110 | -2.5% |
| 36 | expanding | ewma_filtered | 310 | 9 | 89.4% | 49.7% | 0.1639 | 0.1260 | 1.3% | 0.2158 | 2.2% |
| 36 | expanding | gaussian_iid | 310 | 9 | 86.1% | 47.4% | 0.1702 | 0.1277 | 0.0% | n/a | 0.0% |
| 36 | rolling 120 months | iid_bootstrap | 250 | 7 | 82.4% | 41.6% | 0.1480 | 0.1370 | 0.0% | 0.9720 | -0.6% |
| 36 | rolling 120 months | block_bootstrap | 250 | 7 | 77.2% | 38.4% | 0.1570 | 0.1418 | -3.5% | 0.1173 | -1.3% |
| 36 | rolling 120 months | ewma_filtered | 250 | 7 | 86.4% | 45.2% | 0.1450 | 0.1342 | 2.1% | 0.0486 | 0.8% |
| 36 | rolling 120 months | gaussian_iid | 250 | 7 | 83.6% | 43.2% | 0.1480 | 0.1370 | 0.0% | n/a | 0.0% |

**Conclusions (pre-stated decision rule):**

- 1-month horizon, rolling 60 months (345 non-overlapping outcomes): iid_bootstrap, block_bootstrap, ewma_filtered did not differ significantly from the normal baseline; the extra complexity is not supported by this evidence. 90% interval coverage: iid_bootstrap 89%, block_bootstrap 89%, ewma_filtered 89%, gaussian_iid 90%.
- 1-month horizon, expanding (345 non-overlapping outcomes): iid_bootstrap, block_bootstrap, ewma_filtered did not differ significantly from the normal baseline; the extra complexity is not supported by this evidence. 90% interval coverage: iid_bootstrap 91%, block_bootstrap 91%, ewma_filtered 90%, gaussian_iid 91%.
- 1-month horizon, rolling 120 months (285 non-overlapping outcomes): iid_bootstrap, block_bootstrap, ewma_filtered did not differ significantly from the normal baseline; the extra complexity is not supported by this evidence. 90% interval coverage: iid_bootstrap 90%, block_bootstrap 90%, ewma_filtered 90%, gaussian_iid 90%.
- 12-month horizon, rolling 60 months (28 non-overlapping outcomes): iid_bootstrap, block_bootstrap, ewma_filtered did not differ significantly from the normal baseline; the extra complexity is not supported by this evidence. 90% interval coverage: iid_bootstrap 88%, block_bootstrap 83%, ewma_filtered 88%, gaussian_iid 87%.
- 12-month horizon, expanding (28 non-overlapping outcomes): iid_bootstrap, block_bootstrap, ewma_filtered did not differ significantly from the normal baseline; the extra complexity is not supported by this evidence. 90% interval coverage: iid_bootstrap 90%, block_bootstrap 86%, ewma_filtered 90%, gaussian_iid 89%.
- 12-month horizon, rolling 120 months (23 non-overlapping outcomes): iid_bootstrap, block_bootstrap, ewma_filtered did not differ significantly from the normal baseline; the extra complexity is not supported by this evidence. 90% interval coverage: iid_bootstrap 89%, block_bootstrap 87%, ewma_filtered 89%, gaussian_iid 89%.
- 36-month horizon, rolling 60 months (9 non-overlapping outcomes): too few independent outcomes (fewer than 20) to test any model against the baseline; no claim is made. 90% interval coverage, for information: iid_bootstrap 92%, block_bootstrap 79%, ewma_filtered 92%, gaussian_iid 92%.
- 36-month horizon, expanding (9 non-overlapping outcomes): too few independent outcomes (fewer than 20) to test any model against the baseline; no claim is made. 90% interval coverage, for information: iid_bootstrap 87%, block_bootstrap 80%, ewma_filtered 89%, gaussian_iid 86%.
- 36-month horizon, rolling 120 months (7 non-overlapping outcomes): too few independent outcomes (fewer than 20) to test any model against the baseline; no claim is made. 90% interval coverage, for information: iid_bootstrap 82%, block_bootstrap 77%, ewma_filtered 86%, gaussian_iid 84%.

90% interval coverage during the 2007-2009 crisis (rolling 120-month window):

| horizon | model | forecasts | coverage_90 |
|---|---|---|---|
| 1 | iid_bootstrap | 24 | 95.8% |
| 1 | block_bootstrap | 24 | 95.8% |
| 1 | ewma_filtered | 24 | 95.8% |
| 1 | gaussian_iid | 24 | 95.8% |
| 12 | iid_bootstrap | 24 | 100.0% |
| 12 | block_bootstrap | 24 | 100.0% |
| 12 | ewma_filtered | 24 | 100.0% |
| 12 | gaussian_iid | 24 | 100.0% |
| 36 | iid_bootstrap | 24 | 100.0% |
| 36 | block_bootstrap | 24 | 100.0% |
| 36 | ewma_filtered | 24 | 100.0% |
| 36 | gaussian_iid | 24 | 100.0% |

