# Methodology

Every convention the platform uses, in one place. If a number in the dashboard
surprises you, the answer should be here.

## 1. Data

**Sources.** Four providers share one interface
(`fetch(tickers, start, end) -> MarketData`): Yahoo Finance via `yfinance`,
user-supplied CSV files (`CsvProvider`), a seeded synthetic generator, and an
on-disk cache that also serves frozen snapshots. Adding a source means writing
one class. Rights and provenance: [DATA.md](DATA.md).

**Completed sessions and freshness** (`data/sessions.py`, `data/freshness.py`).
A daily bar counts as an observation only once its session has officially
closed. The NYSE calendar (`exchange_calendars`, code `XNYS`) supplies regular
days, weekends, holidays, early closes and one-off closures. Given an explicit
timezone-aware instant, the last completed session is the latest session whose
official close is at or before that instant; the live provider drops any bar
dated later. Each instrument's last actual observation is then compared with
that session:

| State | Meaning |
|---|---|
| current | the last observation is the last completed session (also while the next session is in progress) |
| awaiting provider | exactly one completed session is missing and it closed less than the publication grace ago (default 2 hours) |
| stale | completed sessions are missing and the grace has passed, or more than one is missing |
| incomplete session | an observation is dated after the last completed session |
| no data | the instrument has no observation |

A dataset is as fresh as its worst instrument. Missing prices are never filled
to make data look current. Limits: one calendar (US equities) is applied to
every instrument; the calendar library covers about twenty years back and one
year ahead; an unscheduled closure is only known once the library is updated;
the 2-hour grace is a convention, not a measured provider delay.

**Refreshing the provider's daily data** (`data/refresh.py`, Yahoo source only).
The store keeps a verified, versioned copy of each dataset (tickers + history
start) and decides when the provider must be contacted.

| Situation | What happens |
|---|---|
| Verified cache has every completed session and is younger than 7 days | Served from memory; no request (weekends, holidays, overnight, session in progress) |
| A completed session is missing for any instrument | One request. If it brings the session: **Updated**. If not: **Checked; unchanged**, and the next automatic request waits 15 minutes, then 30, 60, ... capped at 6 hours |
| Cache older than 7 days | One request, to pick up price revisions |
| Manual refresh | Always one request, unless one was made in the last 60 seconds (**Refresh limited**) |
| Request fails, or the response is empty, malformed, or loses history the cache has | **Refresh failed**: the verified cache is untouched and still served, labelled with its true freshness |
| No verified cache and the request fails | **No usable data**; retried no sooner than 60 seconds later |

Five separate moments are tracked: the exchange close (calendar), the
provider publishing the bar (may lag, and a placeholder row with no close is
not a bar), a successful request, the atomic replacement of the verified cache,
and the data reaching calculations. Whatever a provider returns, nothing dated
after the last officially completed session is stored or served. Each dataset
is written as a complete new version and activated by an atomic rename; the
previous version is kept and used if the current one is unreadable. One request
per dataset at a time (in-process lock plus a lock file). Frozen snapshots,
uploaded files and synthetic data never pass through the store.

**Adjustment convention.** `auto_adjust=True`: open, high, low and close are
all multiplied by AdjClose/Close. Splits and cash dividends are folded into the
price series, as if each dividend were reinvested at the ex-date close. Signals,
fills and valuation all use this one series, so the accounting is internally
consistent.

Limits you must be able to state:

- Adjusted prices are a **total-return proxy**, not prices anyone traded at.
  An adjusted 1995 SPY price is far below the quoted price that day.
- They are **not point-in-time**: every new dividend rescales all earlier
  history. Ratios (returns) are stable; levels are not. This is why the
  experiment stores a data fingerprint.
- Because dividends are inside the price, the engine models **no dividend cash
  flows**. Share counts are in "adjusted share" units.

**Integrity rules** (`data/cleaning.py`):

| Problem | Policy |
|---|---|
| Invalid ticker or empty response | `InvalidTickerError` |
| Provider failure | `DataProviderError`; never silently replaced |
| Duplicate timestamps | keep last, record in dataset notes |
| Non-positive price, high < low | error; not repaired |
| Different calendars across assets | union calendar; NaN where no observation |
| Missing observation | stays NaN; nothing is forward-filled or interpolated |
| Today's possibly partial bar | excluded |
| Stale cache | refetched; if that fails, error unless `allow_stale=True`, which is then noted |
| Too little history | indicators stay NaN and produce no signal; `require_history` raises on demand |

Every `MarketData` carries `DatasetMetadata`: source, retrieval time, tickers,
date coverage, adjustment text, synthetic flag, notes.

## 2. Returns

- Simple return: `r_t = P_t / P_{t-1} - 1`. Adds **across assets** (portfolio
  return is the weighted sum).
- Log return: `l_t = ln(P_t / P_{t-1})`. Adds **across time**.
- All analytics take simple returns. Annualization: 252 sessions per year.
- A return across a missing price is NaN, not imputed.

## 3. Strategies

A strategy maps `MarketData` to target weights dated at decision time. A row
dated T uses only data dated T or earlier. Strategies never see cash, fills or
P&L. Only decision dates are emitted; between them the portfolio drifts.

| Strategy | Signal | Decision dates |
|---|---|---|
| Trend following | SMA(fast) > SMA(slow) per asset; 1/N capital slice each | when any signal changes |
| Mean reversion | enter at z <= -entry, exit at z >= -exit, z from trailing mean and sample std | when any state changes |
| Cross-sectional momentum | top N by trailing return; equal or inverse-volatility weights | first session of each new week, month or quarter |
| Buy and hold | fixed weights once | first session where all chosen assets have a price |

During warm-up every signal is zero (cash).

Indicators are computed on each asset's **own** observed sessions and then
aligned to the shared calendar. On a session where an asset has no price, its
last indicator value is carried forward (past information only) for at most
five sessions; after that the asset has no signal. Without this, a single
missing close would blank a 200-day average for 200 sessions.

## 4. Backtesting engine

For each session t:

1. **Open.** Pending orders (decided at the close of t-1 or earlier) fill at
   `open_t`. Buys pay `open * (1 + slippage)`, sells receive
   `open * (1 - slippage)`. Fee = `fee_bps * notional + fixed_fee`.
2. **Close.** Mark holdings at `close_t`. Record equity, cash, holdings.
3. **After the close.** A decision dated t becomes pending.

**Sizing.** Target shares = `weight * equity_at_open / open`. Sells execute
first. If buys would cost more than available cash once slippage and fees are
included, all buys are scaled down by the same factor. The portfolio therefore
never borrows; with a 100% target it ends a few basis points short of fully
invested. With `fractional_shares=False`, quantities round toward zero.

**Constraints.** Negative weights, weights summing above 1, NaN weights,
unknown tickers and off-calendar decision dates are rejected before the run.
Independently, the `Portfolio` ledger raises `ConstraintViolation` on any fill
that would overdraw cash or sell more than is held.

**Invariant.** At every close: `equity = cash + sum(shares * mark)`. Tested
against an independent valuation from the raw closes.

**Edge policies.**

| Situation | Policy |
|---|---|
| No open price for an ordered asset | not filled, logged in `unfilled`, order stays pending for the next priced session |
| No close for a held asset | marked at last observed price; flagged in `stale_marks` |
| New decision while orders are pending | the new decision replaces them |
| Decision on the final session | never executes |
| Sale whose proceeds are below its fixed fee | dropped and logged; the position stays |
| Buy that cash cannot fund after costs | dropped and logged |
| Dividends, splits | inside adjusted prices; no separate events |
| Cash | earns zero |

**Turnover.** Per session: traded notional / equity at the open (two-sided).
Reported as the annual sum.

**Win rate.** Share of sell fills with positive realized P&L on an average-cost
basis, net of fees. For strategies that scale in and out it is a rough guide.

## 4a. Funded portfolios: contributions, rebalancing and their returns

Library: `portfolio/spec.py`, `strategies/fixed_weights.py`, `analytics/flows.py`.
No dashboard page uses these yet.

**Portfolio specification.** Long-only target weights summing to at most 1
(the remainder is a cash reserve), an initial amount, an optional recurring
contribution (weekly, monthly or quarterly) and a rebalancing policy (never,
monthly, quarterly or annual). It contains no account or personal data.

**Timeline.** Everything follows the existing rule: decide after a close,
trade at the next open.

| Event | When |
|---|---|
| Contribution | Added to cash at the **open** of the first session of each new period, before any fill that day |
| Initial purchase | Decided at the close of the first session on which every held instrument has a price; filled at the next open |
| Deploying a contribution | Decided at the close of the contribution day; at the next open, spare cash above the reserve is invested at the target mix. Nothing is sold and drift is not corrected. The contribution therefore normally waits one session in cash. Exception: an order decided at the previous close (for example a scheduled rebalance) that fills on the contribution's own open is sized on equity including the deposit, so the deposit is invested that open. No information from the deposit day is used (corrected wording, QA-021) |
| Rebalance | Decided at the close of the first session of the month / quarter / year; at the next open the whole portfolio is traded to target, sells first. If a contribution falls on the same day the rebalance invests it |

Target weights are constants and decision dates depend only on the calendar
(a period start is recognised by comparing a session with the one before it),
so no price from the future can influence a decision. Costs come out of the
amount being invested: buys are scaled so the reserve is not drawn down and
cash never goes negative; with whole shares the remainder stays in cash. A
deployment for an instrument with no price that day is not carried forward:
that cash waits for the next decision and the event is logged.

**Time-weighted return.** External flows must not look like performance. The
portfolio is valued at the flow boundary, the open before the deposit
(holdings at open prices plus cash), and the two sub-periods are linked:

```
r_t = (E_pre / E_{t-1}) x (E_t / (E_pre + C_t)) - 1
```

`E_pre` is equity at the open before the deposit `C_t`; `E_t` and `E_{t-1}`
are closing equity. On days without a flow this is `E_t / E_{t-1} - 1`,
computed exactly as before, so existing results are unchanged bit for bit. The
compounded product of `r_t` is the time-weighted return: use it to compare
allocations. It is checked against an independent unitised-fund calculation.
The shortcut `(E_t - C_t) / E_{t-1} - 1` is wrong for a deposit at the open:
it treats the cash as if it had arrived at the close.

**Money-weighted return.** The effective annual internal rate of return of the
investor's dated cash flows: payments in are negative (initial amount on the
first session, each contribution on its date); the final value at the last
close is positive, with no selling costs. Day count is actual/365 on calendar
dates. Solved by bisection between -99.9999% and 1e12 to a relative bracket of
1e-12. A rate is reported only if the flows change sign exactly once;
otherwise the result is NaN with a reason (too few flows, zero span, no sign
change, not unique, no root). Because an annual rate over a few days or weeks
is an extrapolation, the un-annualised return over the actual span is reported
alongside it. It depends on when money was added as well as on the allocation,
so it is never shown without the time-weighted figure.

**What adjusted prices do and do not support here.** Simulated fills use
Yahoo's adjusted opens. They are a consistent total-return proxy, not prices
anyone could have traded at: a contribution "buys" adjusted shares, share
counts are not real share counts, and dividends are assumed reinvested at the
ex-date close with no delay, cash drag or tax. Returns are meaningful; quoted
quantities and execution prices are approximations. Anything that needs real
execution prices (forward paper trading) must use raw prices and explicit
corporate actions, which this milestone does not attempt.

**Not implemented:** withdrawals, interest on cash, tolerance-band
rebalancing, taxes.

**Comparing portfolios** (`portfolio/compare.py`, the Investment Lab page).
Every portfolio in a comparison is simulated through the engine on:

- one window: from the first session on which every instrument held by *any*
  of the compared portfolios has a price, to the last session;
- one calendar: every session in that window, for all portfolios;
- one funding plan and one cost setting.

Three simple benchmarks are offered, funded identically: everything in the
first held instrument; equal weights across the held instruments; and the same
weights with the opposite maintenance choice (never rebalanced, or rebalanced
annually). Nothing is ranked or recommended.

Figures are labelled by kind. *Historical*: what the simulated portfolio did
(returns, realised volatility, drawdown, worst day, expected shortfall, costs,
drift). *Estimated*: computed from the window's covariance at the target
weights (estimated volatility, risk contributions, diversification ratio =
weighted average of own volatilities / portfolio volatility, effective
holdings = 1 / sum of squared normalised weights). Allocation drift is the
largest absolute gap between an actual and a target weight at each close,
cash included.

A saved portfolio file holds definitions and assumptions only, plus the
fingerprint of the dataset it was saved against (a hash of the window's open
and close prices). On reload the page states whether the current dataset is
the same, in which case results reproduce exactly, or different.

## 5. Performance statistics

`r` = strategy simple returns, `b` = benchmark, `rf` = annual risk-free rate,
`N` = 252, `n` = number of observations.

| Statistic | Definition |
|---|---|
| Total return | `prod(1 + r) - 1` |
| CAGR | `prod(1 + r)^(N/n) - 1` |
| Volatility | `std(r, ddof=1) * sqrt(N)` |
| Sharpe | `mean(r - rf/N) / std(r - rf/N) * sqrt(N)` |
| Downside deviation | `sqrt(mean(min(r - rf/N, 0)^2)) * sqrt(N)` |
| Sortino | `mean(r - rf/N) * N / downside deviation` |
| Max drawdown | `min_t (V_t / max_{s<=t} V_s - 1)`, peak floored at initial wealth |
| Drawdown duration | longest run of sessions below a prior peak |
| Calmar | `CAGR / abs(max drawdown)` |
| Beta | `cov(r, b) / var(b)` |
| Alpha | CAPM: `[mean(r - rf/N) - beta * mean(b - rf/N)] * N` |
| Tracking error | `std(r - b) * sqrt(N)` |
| Information ratio | `mean(r - b) * N / tracking error` |
| VaR (historical) | `-quantile(r, 1 - a)`; positive = loss |
| Expected shortfall | `-mean(r given r <= quantile(r, 1 - a))` |

Undefined cases return NaN: zero variance, fewer than two observations, wealth
at or below zero, no overlap with the benchmark. Benchmark-relative statistics
use only sessions present in both series.

Absolute measures: volatility, VaR, ES, drawdown. Relative measures: beta,
alpha, tracking error, information ratio.

## 6. Risk

Sample covariance of daily simple returns over a stated window, complete rows
only, annualized by 252. Portfolio volatility `sqrt(w' S w)`. Risk
contribution `RC_i = w_i (S w)_i / sigma_p`, which sums to `sigma_p`. Weights
must be long-only and sum to at most 1; the remainder is cash.

Stress tests multiply holdings by user-set shocks. They are hypothetical and
assume nothing about co-movement.

## 7. Monte Carlo

Resample historical portfolio returns and compound.

- **iid**: each day independent. Keeps observed fat tails; destroys volatility
  clustering, so drawdowns are understated.
- **block / stationary**: resample runs of consecutive days. Keeps short-range
  dependence; cannot create regimes the window never contained.

Fixed seed gives identical paths. Output describes the model, not the future.

## 8. Research validation

- **Chronological split**: development, optional validation, final test. No
  shuffling. Backtests run on full history so indicators warm up on earlier
  data; evaluation windows are sliced afterwards.
- **Parameter grid**: development period only. Every evaluation is logged in a
  `TrialRegistry`.
- **Cost sweep, subperiods**: do conclusions survive?
- **Bootstrap intervals**: percentile intervals from a stationary bootstrap;
  strategy and benchmark rows are resampled together so differences keep their
  pairing. Assumes approximate stationarity.
- **Multiple testing**: Bonferroni or Holm across the primary family; anything
  else is labelled exploratory.

## 9. Reproducibility

`save_experiment` writes the configuration, its hash, data provenance, package
versions, the git commit, whether the working tree was dirty, and all result
tables to JSON. The study reads a frozen dataset from `experiments/data/`
(same file layout as the cache) so a re-run reproduces the record exactly. Seeds are explicit
parameters everywhere randomness is used.
