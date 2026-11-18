# Trend following vs buy-and-hold: results (SYNTHETIC DATA)

> **Synthetic GBM data. Pipeline check only; these numbers mean nothing.**

- Record: `experiments/results/SYNTHETIC_trend_vs_buyhold_103ff696a37b.json`
- Data: synthetic-gbm, 1993-01-01 to 2026-10-30, retrieved 2026-11-18T21:15:45+00:00, close fingerprint `a3bece136ad62787`
- Adjustment: none (synthetic)
- Costs: 2.0 bps slippage + 1.0 bps fee per side; signals at close T, fills at open T+1
- Evaluations logged: 28 across 21 distinct strategy/asset/parameter/cost configurations; 11 of them looked at the out-of-sample period, all with parameters fixed in advance. No configuration was chosen using out-of-sample data.

## SPY (primary)

**Development** (1993-01-01 to 2012-12-31)

| name | cagr | volatility | sharpe | sortino | max_drawdown | max_drawdown_duration | es_95 | downside_deviation | turnover | trade_count |
|---|---|---|---|---|---|---|---|---|---|---|
| trend_50_200 | 2.46% | 12.65% | 0.256 | 0.375 | -32.14% | 1851 | 1.90% | 8.62% | 1.26 | 26 |
| buy_and_hold | 0.19% | 18.02% | 0.101 | 0.145 | -58.98% | 1955 | 2.29% | 12.53% | 0.05 | 1 |

**Out Of Sample** (2013-01-01 to 2026-10-30)

| name | cagr | volatility | sharpe | sortino | max_drawdown | max_drawdown_duration | es_95 | downside_deviation | turnover | trade_count |
|---|---|---|---|---|---|---|---|---|---|---|
| trend_50_200 | 6.02% | 13.09% | 0.512 | 0.751 | -29.07% | 1562 | 1.91% | 8.93% | 1.26 | 18 |
| buy_and_hold | 5.60% | 17.81% | 0.395 | 0.568 | -55.33% | 2087 | 2.30% | 12.38% | 0.00 | 0 |

Trend strategy was invested on 58% of out-of-sample sessions.

**Out-of-sample difference, trend minus buy-and-hold** (positive favours trend; only rows marked confirmatory are multiplicity-adjusted tests; paired stationary bootstrap, mean block 63 sessions, 2000 resamples)

| improvement | role | estimate | lower | upper | confidence | excludes_zero |
|---|---|---|---|---|---|---|
| max_drawdown | confirmatory | 26.26% | -12.91% | 38.38% | 98.3% | False |
| es_95 | confirmatory | 0.39% | 0.19% | 0.65% | 98.3% | True |
| downside_deviation | confirmatory | 3.45% | 1.94% | 5.28% | 98.3% | True |
| cagr | exploratory | 0.42% | -5.43% | 5.82% | 95.0% | False |
| sharpe | exploratory | 0.117 | -0.257 | 0.449 | 95.0% | False |

## QQQ (secondary, exploratory)

**Development** (1993-01-01 to 2012-12-31)

| name | cagr | volatility | sharpe | sortino | max_drawdown | max_drawdown_duration | es_95 | downside_deviation | turnover | trade_count |
|---|---|---|---|---|---|---|---|---|---|---|
| trend_50_200 | 0.50% | 13.28% | 0.104 | 0.148 | -49.32% | 2844 | 2.02% | 9.34% | 1.69 | 35 |
| buy_and_hold | 4.02% | 17.83% | 0.310 | 0.449 | -49.05% | 2837 | 2.28% | 12.33% | 0.05 | 1 |

**Out Of Sample** (2013-01-01 to 2026-10-30)

| name | cagr | volatility | sharpe | sortino | max_drawdown | max_drawdown_duration | es_95 | downside_deviation | turnover | trade_count |
|---|---|---|---|---|---|---|---|---|---|---|
| trend_50_200 | 0.22% | 13.42% | 0.083 | 0.119 | -35.18% | 1533 | 1.98% | 9.41% | 2.02 | 29 |
| buy_and_hold | 2.32% | 17.65% | 0.218 | 0.315 | -41.85% | 1179 | 2.24% | 12.22% | 0.00 | 0 |

Trend strategy was invested on 58% of out-of-sample sessions.

**Out-of-sample difference, trend minus buy-and-hold** (positive favours trend; only rows marked confirmatory are multiplicity-adjusted tests; paired stationary bootstrap, mean block 63 sessions, 2000 resamples)

| improvement | role | estimate | lower | upper | confidence | excludes_zero |
|---|---|---|---|---|---|---|
| max_drawdown | exploratory | 6.67% | -15.73% | 26.49% | 95.0% | False |
| es_95 | exploratory | 0.25% | 0.14% | 0.39% | 95.0% | True |
| downside_deviation | exploratory | 2.81% | 1.81% | 3.99% | 95.0% | True |
| cagr | exploratory | -2.10% | -7.87% | 3.60% | 95.0% | False |
| sharpe | exploratory | -0.135 | -0.454 | 0.190 | 95.0% | False |

## IWM (secondary, exploratory)

**Development** (1993-01-01 to 2012-12-31)

| name | cagr | volatility | sharpe | sortino | max_drawdown | max_drawdown_duration | es_95 | downside_deviation | turnover | trade_count |
|---|---|---|---|---|---|---|---|---|---|---|
| trend_50_200 | 1.90% | 14.22% | 0.204 | 0.293 | -37.07% | 2729 | 2.06% | 9.89% | 1.98 | 41 |
| buy_and_hold | 5.46% | 18.16% | 0.383 | 0.554 | -41.59% | 2330 | 2.31% | 12.56% | 0.05 | 1 |

**Out Of Sample** (2013-01-01 to 2026-10-30)

| name | cagr | volatility | sharpe | sortino | max_drawdown | max_drawdown_duration | es_95 | downside_deviation | turnover | trade_count |
|---|---|---|---|---|---|---|---|---|---|---|
| trend_50_200 | 5.22% | 14.42% | 0.425 | 0.622 | -29.20% | 1435 | 2.05% | 9.86% | 1.26 | 18 |
| buy_and_hold | 8.52% | 18.03% | 0.543 | 0.798 | -31.75% | 463 | 2.23% | 12.28% | 0.00 | 0 |

Trend strategy was invested on 64% of out-of-sample sessions.

**Out-of-sample difference, trend minus buy-and-hold** (positive favours trend; only rows marked confirmatory are multiplicity-adjusted tests; paired stationary bootstrap, mean block 63 sessions, 2000 resamples)

| improvement | role | estimate | lower | upper | confidence | excludes_zero |
|---|---|---|---|---|---|---|
| max_drawdown | exploratory | 2.54% | -12.92% | 21.13% | 95.0% | False |
| es_95 | exploratory | 0.18% | 0.09% | 0.30% | 95.0% | True |
| downside_deviation | exploratory | 2.42% | 1.41% | 3.57% | 95.0% | True |
| cagr | exploratory | -3.29% | -8.55% | 2.06% | 95.0% | False |
| sharpe | exploratory | -0.118 | -0.401 | 0.176 | 95.0% | False |

## Robustness (SPY)

**Parameter sensitivity, development period only**

| fast | slow | cagr | sharpe | max_drawdown | es_95 | mdd_better_than_bh |
|---|---|---|---|---|---|---|
| 20 | 100 | 3.77% | 0.365 | -28.04% | 1.84% | True |
| 20 | 150 | 1.53% | 0.183 | -45.07% | 1.91% | True |
| 20 | 200 | 2.35% | 0.246 | -39.63% | 1.91% | True |
| 20 | 250 | 1.07% | 0.148 | -42.09% | 1.92% | True |
| 50 | 100 | 2.78% | 0.287 | -38.89% | 1.85% | True |
| 50 | 150 | 2.25% | 0.243 | -32.79% | 1.86% | True |
| 50 | 200 | 2.46% | 0.256 | -32.14% | 1.90% | True |
| 50 | 250 | 2.00% | 0.219 | -34.65% | 1.94% | True |
| 100 | 150 | 1.47% | 0.179 | -31.03% | 1.90% | True |
| 100 | 200 | 2.04% | 0.222 | -32.61% | 1.94% | True |
| 100 | 250 | 1.27% | 0.163 | -29.58% | 1.96% | True |

Buy-and-hold development max drawdown: -58.98%. 11 of 11 parameter pairs had a shallower drawdown.

**Transaction-cost sensitivity, out-of-sample** (total one-way cost)

| cost_bps | cagr | sharpe | max_drawdown | es_95 | turnover |
|---|---|---|---|---|---|
| 0 | 6.06% | 0.515 | -28.99% | 1.91% | 1.26 |
| 3 | 6.02% | 0.512 | -29.07% | 1.91% | 1.26 |
| 10 | 5.93% | 0.505 | -29.27% | 1.91% | 1.26 |
| 25 | 5.73% | 0.491 | -29.76% | 1.91% | 1.26 |
| 50 | 5.40% | 0.466 | -30.81% | 1.92% | 1.25 |

**Five-year subperiods, full sample**

| period | strategy | cagr | volatility | max_drawdown | es_95 |
|---|---|---|---|---|---|
| 1993-01-01 to 1997-12-31 | trend_50_200 | 0.94% | 11.33% | -30.12% | 1.82% |
| 1993-01-01 to 1997-12-31 | buy_and_hold | -6.87% | 17.92% | -46.68% | 2.34% |
| 1998-01-01 to 2002-12-31 | trend_50_200 | 6.18% | 14.55% | -26.01% | 1.99% |
| 1998-01-01 to 2002-12-31 | buy_and_hold | 13.50% | 18.13% | -25.12% | 2.25% |
| 2003-01-01 to 2007-12-31 | trend_50_200 | 4.83% | 13.30% | -19.71% | 1.94% |
| 2003-01-01 to 2007-12-31 | buy_and_hold | 1.40% | 17.99% | -44.19% | 2.29% |
| 2008-01-01 to 2012-12-31 | trend_50_200 | -1.89% | 11.10% | -19.98% | 1.78% |
| 2008-01-01 to 2012-12-31 | buy_and_hold | -5.97% | 18.03% | -53.57% | 2.26% |
| 2013-01-01 to 2017-12-29 | trend_50_200 | 8.29% | 15.55% | -26.65% | 2.11% |
| 2013-01-01 to 2017-12-29 | buy_and_hold | 14.70% | 17.72% | -17.34% | 2.25% |
| 2018-01-01 to 2022-12-30 | trend_50_200 | 1.02% | 10.32% | -25.10% | 1.67% |
| 2018-01-01 to 2022-12-30 | buy_and_hold | -7.28% | 18.06% | -51.31% | 2.39% |
| 2023-01-02 to 2026-10-30 | trend_50_200 | 9.85% | 12.81% | -16.00% | 1.83% |
| 2023-01-02 to 2026-10-30 | buy_and_hold | 12.35% | 17.56% | -19.46% | 2.21% |
