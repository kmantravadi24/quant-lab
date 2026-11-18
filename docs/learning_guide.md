# Learning guide

Written for someone with a physics background. The aim is that you can explain
and defend every part of this project without the code in front of you.

## The mental model

| Finance | Physics you already know |
|---|---|
| Price path | Trajectory of a noisy system; geometric Brownian motion is a random walk in log-price, the same mathematics as diffusion |
| Log return | Displacement per time step; additive, so variances add over time |
| Volatility scaling with sqrt(T) | Diffusion: rms displacement grows as sqrt(t). Holds only if steps are uncorrelated |
| Covariance matrix | The same object as in error propagation: `var(f) = J S J^T`. Portfolio variance `w' S w` is error propagation with `J = w` |
| Diversification | Averaging partially independent measurements reduces the error on the mean |
| Backtest | A simulated experiment. Look-ahead bias is a causality violation: the detector responding before the particle arrives |
| Out-of-sample test | Blind analysis: freeze the cuts before unblinding the signal region |
| Multiple testing | The look-elsewhere effect: scan enough mass bins and one will show a 3-sigma bump |
| Bootstrap | Estimating a sampling distribution from the data itself when no closed form exists |
| Block bootstrap | Resampling in chunks longer than the correlation time, as with autocorrelated Monte Carlo chains |
| Volatility clustering | Heteroskedastic noise: the noise amplitude is itself a slowly varying random process |
| Fat tails | Non-Gaussian errors: 5-sigma events happen far more often than a normal model predicts |
| Sharpe ratio | Signal-to-noise ratio per sqrt(year). Its t-statistic is roughly `Sharpe * sqrt(years)` |
| Monte Carlo here | Resampling an empirical distribution, not sampling a known Hamiltonian. The "model" is "the past repeats" |

## Reading order through the code

1. `data/models.py`, `data/cleaning.py`: what a dataset is and what is refused.
2. `strategies/base.py`, then `trend.py`: the timing contract.
3. `execution/orders.py`, `portfolio/ledger.py`: sizing and the cash constraint.
4. `backtesting/engine.py`: the 60-line loop that everything depends on.
5. `tests/unit/test_engine.py`: read the hand calculations in the comments and
   redo two of them on paper.
6. `analytics/metrics.py`, `research/bootstrap.py`.
7. `experiments/trend_vs_buyhold.py`: how a study is assembled.

## Exercises that build real understanding

1. In `engine.py`, move step 3 (decision becomes pending) above step 1. Which
   tests fail, and why does the equity curve improve? That improvement is
   look-ahead bias, measured.
2. Change the fill from the next open to the same close for a fast strategy
   (mean reversion). Compare Sharpe ratios. How much "alpha" was timing error?
3. Derive `sum_i RC_i = sigma_p` from Euler's theorem for homogeneous functions.
4. Show that for i.i.d. returns the standard error of the Sharpe ratio is about
   `sqrt((1 + S^2/2) / n)`. How many years are needed to tell 0.7 from 0.9?
5. Run the Monte Carlo page with iid, then stationary resampling with a 63-day
   block. Explain the change in the drawdown histogram.
6. Add a strategy of your own. The perturbation test in `test_engine.py`
   accepts any strategy in its list: add yours and see whether it is causal.

## Questions you should be able to answer

**Engine**

- Why trade at the next open and not the signal's close? *The close is the
  information. You cannot know it and trade at it. Using it adds a return you
  could not have earned.*
- How do you know there is no look-ahead? *Two tests: rewrite all data after a
  cutoff and confirm decisions, trades and equity up to the cutoff are bit-for-bit
  identical; and confirm decisions on truncated history equal decisions on full
  history.*
- What stops leverage? *Weights are validated; buys are scaled to available
  cash after costs; the ledger independently refuses overdrafts.*
- What happens on a day with no price? *No trade. The order waits. The holding
  is marked at its last price and flagged.*

**Data**

- What is an adjusted price and what is wrong with it? *A back-scaled series
  whose returns include dividends. Not a tradable price, and revised with every
  dividend, so not point-in-time.*
- What is survivorship bias here? *The ETFs were picked today. Funds that
  closed or stayed tiny are missing.*

**Statistics**

- Simple or log returns? *Simple across assets, log across time. Analytics use
  simple returns and compound them.*
- Why ddof=1? *Unbiased sample variance when the mean is estimated from the
  same data.*
- VaR versus expected shortfall? *VaR is a quantile: the loss exceeded 5% of
  days. ES is the mean loss on those days. ES sees the tail's shape and is
  sub-additive; VaR is neither.*
- Why a block bootstrap? *Squared returns are autocorrelated. Resampling single
  days destroys clustering and makes drawdown intervals too narrow.*
- Why Bonferroni on three metrics? *Three chances to find an effect by luck.
  Each interval is run at 1 - 0.05/3 so the family error stays near 5%.*
- Is the Sharpe difference significant? *No: the interval spans zero. And the
  Sharpe ratio was not a primary metric.*

**The study**

- Why did it fail out of sample? *The big loss was a 23-session crash. A
  200-day average cannot react that fast, and it re-entered late after V-shaped
  recoveries.*
- Did costs kill it? *No. About one round trip a year; 50 bps costs barely move
  the result.*
- What is the weakest part of the study? *Sample size for drawdowns (only a
  handful of episodes), and that 50/200 is famous because of the history used for
  development.*
- Why report a negative result? *A correctly measured null is a finding. A
  platform that only ever produces winners is not measuring anything.*
