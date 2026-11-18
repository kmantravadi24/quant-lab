# Future Wealth: methodology and assumptions

Quant Lab's Future Wealth engine projects a **funded investment plan** forward and shows the
spread of outcomes the plan would have **if the future resembled a chosen slice of history in a
chosen way**. It is decision support for questions you control: how much to save, what to hold,
what fees cost, and what risks come with each choice. It is not a forecast, not advice, and it
places no orders.

Code: `src/quantlab/forecast/`. Tests: `tests/qa/test_q_future_wealth.py` (engine, goals),
`test_r_forecast_validation.py` (validation, ledger, scenarios), `test_s_future_wealth_ui.py`
(interface). Validation study: `experiments/forecast_validation.py`, results in
`reports/forecast_validation.md`.

## 1. The plan (`WealthPlan`)

| Input | Meaning |
|---|---|
| `weights` | Long-only target weights per instrument; the remainder is cash. No leverage. |
| `initial_amount` | Money in the account at time 0. |
| `contribution`, `frequency` | Deposit every month (`M`), quarter (`Q`) or year (`A`); the first deposit is in month 1. |
| `contribution_growth` | The deposit rises by this rate every 12 months: deposit in month m = c·(1+g)^⌊(m−1)/12⌋. |
| `rebalance` | `None` (never; new money buys the target mix), `M`, `Q` or `A` (first rebalance in month 1). |
| `cost_bps` | Trading cost on every dollar bought or sold (spread plus commission). |
| `annual_fee` | Fund or advisory fee on invested holdings, charged monthly at 1 − (1 − f)^(1/12). |
| `cash_yield` | Interest on the cash part, monthly rate (1 + y)^(1/12) − 1. Default 0%. |
| `inflation` | Used only to express values in today's money: real = nominal / (1 + π)^(m/12). |
| `horizon_years` | 1 month to 50 years; months = round(12 × years). |

All inputs must be finite and inside stated ranges; otherwise the plan is refused with a reason.
`WealthPlan.from_spec` starts from an Investment Lab portfolio (weekly contributions are refused
rather than silently converted).

## 2. Account simulation and event order

`simulate_wealth` is a **monthly account ledger run on many paths at once**. Holdings drift with
their own returns between rebalances, deposits arrive on schedule, trades pay costs and fees are
charged. It never substitutes a fixed-weight return for the account.

Inside month m, identically on every path:

1. **Deposit.** The month's contribution is added to cash.
2. **Trading**, at the start of the month:
   - **Rebalance month:** the whole account is traded to target weights. With proportional cost
     c, the post-trade value V′ solves V′ = V − c·Σᵢ|wᵢV′ − hᵢ|. This is a contraction because
     c·Σw < 1, so the solution is unique; it is solved to 1e-12.
   - **Other months:** only spare cash above the cash target, (1 − Σw)·V, is invested in the
     target mix. Nothing is sold, and the cost is c per dollar bought. The cash share after buying
     is therefore approximately, not exactly, on target.
3. **Scenario shock** (stress scenarios only): every risky holding falls by the shock at once.
4. **Market:** each holding is multiplied by (1 + its simulated monthly return), and cash earns
   interest.
5. **Fee** on risky holdings.
6. **Valuation:** V_m = cash + Σ holdings, recorded at the month end.

**Ledger identity**, verified on every path and month by the tests:
V_m = deposits − costs − fees + market gains + interest.

**Time-weighted return.** Each month's portfolio return is V_m / (V_{m−1} + deposit_m) − 1. Its
compounded index gives the reported drawdowns, which therefore exclude the effect of deposits.

**Why this is a separate engine from the backtester.** The transaction engine
(`quantlab.backtesting`) processes one daily price history with next-open fills. Forward
simulation needs thousands of monthly paths at once, so it uses vectorised monthly arithmetic.
Its conventions are deliberately simple and are pinned against an independent plain-Python
ledger (`tests/qa/reference.py::reference_wealth`) to about 1e-10.

**Resource limits.** At most 15 million stored values (paths × (months + 1), about 120 MB) and
300 million path-month-instrument operations. The dashboard caps paths at 20,000. A 20-year,
10,000-path, three-instrument run takes about 1 s and about 40 MB (Suite Q).

## 3. Return models (`quantlab.forecast.returns`)

**Monthly history.** Each month's value is the last available close of that calendar month.
Only months where every **held** instrument has a value are used: an instrument the plan does not
hold never shortens the history. A final month whose last close is more than four days before
month end counts as incomplete and is dropped.

All four models draw **every instrument in the same month together**. That keeps the historical
cross-correlation, which Suite Q checks for each model.

| Model | What it assumes | Suited to | Weakness |
|---|---|---|---|
| Historical months, independent (`iid_bootstrap`) | Each future month is a random historical month (the whole cross-section). | A baseline at any horizon. | Ignores runs of bad months; the future cannot contain a month worse than the window's worst. |
| Historical runs of months (`block_bootstrap`) | Stationary bootstrap: runs of consecutive months with geometric lengths, mean `block` (default 12). | 3 to 20 years: keeps multi-month runs such as bear markets and volatility clustering. | With short windows, ranges are slightly too narrow (a finite-sample effect, seen in validation); runs wrap from the end of the window to the start. |
| Volatility-adjusted history (`ewma_filtered`) | Filtered historical simulation. Historical shocks are standardised by an EWMA volatility (monthly λ = 0.97, initialised at the window variance), then rescaled by today's volatility, which evolves with the simulated returns. Returns are floored at −99%. | 1 month to about 2 years: it conditions on current volatility. | EWMA has no mean reversion, so over long horizons volatility drifts and the extra information fades. Treat it as a sensitivity there. |
| Normal distribution (`gaussian_iid`) | Monthly log returns jointly normal with the window's mean and covariance. | Reference baseline for validation. | Thin tails: understates crashes. |

None of these models knows the future. The choice of **history window** usually matters more
than the choice of model; the dashboard's Model sensitivity tab shows both.

## 4. Outputs and their uncertainty

- **Ending-value percentiles** (5th, 25th, 50th, 75th, 95th; 1st for the downside), in nominal
  dollars and in today's money. Each percentile has a distribution-free 95% interval from order
  statistics: the count of draws below the true q-quantile is Binomial(n, q).
- **Goal probabilities**, two separate questions:
  - **reach**: the account is at or above the goal at any month end within the horizon (first
    passage, month ends only);
  - **hold**: it is at or above the goal at the end.

  Reach is always at least hold. A goal can be stated in today's money. The probability of having
  reached the goal by each year, and the median time to reach it, are also reported.
- **Probability of ending below total contributions.**
- **Drawdowns:** the worst fall of the time-weighted index on each path (median, 5th percentile,
  share of paths worse than 30%).
- **Deposits versus growth** at any percentile: deposits + growth = ending value, exactly.
- **Required contribution:**
  - *Deterministic:* at a stated constant annual return, without costs. The ending value is linear
    in the contribution, so C = (goal − initial·(1+r)^n) / B.
  - *Probabilistic:* the smallest contribution for which a stated share of paths ends at or above
    the goal. Found by bisection with common random numbers: every trial amount faces the same
    simulated markets, so the probability rises monotonically with the amount (a test checks this).
- **Plan comparisons** use **common random numbers**: every compared plan faces the same simulated
  months, so differences come from the decision, not from luck.

### Two kinds of uncertainty

1. **Monte Carlo sampling uncertainty** comes from using a finite number of paths. It shrinks as
   1/√paths and is shown as 95% Wilson intervals (verified against SciPy to 1e-12).
2. **Model uncertainty** is whether the chosen history and resampling scheme describe the future.
   **More paths do not reduce it.** It is shown by re-running the same plan under every model and
   several history windows. In typical cases the spread across models and windows is several
   times the sampling interval.

## 5. Validation (`quantlab.forecast.validation`)

Walk-forward evaluation works as follows.

- At each monthly origin, a model is fitted **only** on months up to the origin: a rolling 60 or
  120 months, or an expanding window. It then forecasts the cumulative return of the target
  portfolio over the next h months (rebalanced monthly, before costs).
- Contributions are known in advance and add no forecasting content, so they are left out.
- A test rewrites every month after an origin and confirms that the forecasts at and before that
  origin are unchanged.

Scores:

- central 50% and 90% interval coverage
- PIT uniformity (Kolmogorov–Smirnov distance)
- CRPS (a proper scoring rule)
- Brier score for the probability of a loss
- pinball losses at the 5th, 50th and 95th percentiles
- median log error

Each score is reported by market period and by estimation window.

**Decision rule, fixed before the real data were evaluated.** A model "beats" the normal
baseline only if all of the following hold:

- its mean CRPS is lower;
- a Diebold–Mariano test rejects equality at 5%, using a Newey–West variance with h − 1 lags,
  the Harvey–Leybourne–Newbold small-sample correction and t p-values;
- the rejection survives a Holm adjustment across the models tested at that portfolio, horizon
  and window;
- there are at least 20 non-overlapping outcomes.

The last two conditions were added after the synthetic pipeline check produced false "wins" at
36 months on i.i.d. normal data. Suite R pins the fix.

Results on the private reference data are not published in this copy (redistribution rights
not established). `reports/forecast_validation_synthetic.md` shows the pipeline on synthetic data;
run `python experiments/forecast_validation.py` on data you are licensed to use.

**Nothing here is evidence of a predictive edge.**

## 6. Forecast record (`quantlab.forecast.ledger`)

"Record this forecast" appends one line to `forecasts.jsonl`. The folder is
`QUANTLAB_FORECAST_DIR`, or `<cache>/forecasts` if that is not set. Each line contains:

- the plan, model, data source, fingerprint and last month used;
- percentiles 1 to 99 of the portfolio's cumulative return at 1, 12 and 36 months, with target
  months;
- the projected wealth percentiles.

Each line also holds the SHA-256 hash of its own content and of the previous line. Editing,
deleting or reordering any line breaks the chain; `verify()` reports it, and further appends are
refused. The file is only ever opened for appending.

"Check due forecasts" scores every forecast whose target month has passed against realised
monthly returns (PIT, 50% and 90% coverage). It appends the results to a separate chained
`evaluations.jsonl`, at most once per forecast and horizon.

## 7. Scenario files

"Scenario (JSON, re-runnable)" stores the plan, model and parameters, history window, paths, seed,
any shock, the data fingerprint, the summary, the month-by-month percentiles and the software
environment. `quantlab.forecast.scenario.rerun(payload, close)` re-runs it. With the same data
it reproduces every value bit for bit (`test_r11`).

## 8. Limitations

- **History is not the future.** Every model resamples or fits one window. Structural change,
  regimes the window never contained, and valuation-dependent returns are outside them.
- **Adjusted prices** are a total-return proxy: dividends are reinvested, and there are no taxes.
- **Month-end granularity:** goals touched and lost within a month are not counted, and
  intra-month drawdowns are understated.
- **The plan is fixed:** no withdrawals, no behaviour changes, no taxes, no rebalancing bands. The
  contribution grows at a constant rate.
- **Hindsight and survivorship:** the instruments were chosen today, from funds that still exist and did
  well enough to be familiar. Their history flatters them; delisted or closed funds are absent.
- **Small instrument sets:** results describe the loaded instruments only. A short-history
  instrument limits the window for every plan that holds it.
- **Validation is limited:** about 33 years of US equity data, few independent long-horizon
  outcomes, and a dataset seen before. Calibration at 10 to 20 years cannot be checked with
  existing data at all.
