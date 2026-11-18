"""Performance statistics.

Conventions
- Inputs are *simple* periodic returns unless stated otherwise.
- Annualization uses ``periods`` observations per year (default 252 sessions).
- ``risk_free`` is an annual simple rate, converted to a per-period rate by
  division (rf / periods).
- Sample standard deviations use ddof=1.
- Anything undefined (zero variance, too few observations, non-positive equity)
  returns NaN rather than a misleading number.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantlab import TRADING_DAYS_PER_YEAR as TDY

DEFINITIONS: dict[str, str] = {
    "total_return": "prod(1 + r_t) - 1",
    "cagr": "(prod(1 + r_t))^(periods / n) - 1, n = number of return observations",
    "volatility": "std(r_t, ddof=1) * sqrt(periods)",
    "sharpe": "mean(r_t - rf/periods) / std(r_t - rf/periods, ddof=1) * sqrt(periods)",
    "sortino": "mean(r_t - rf/periods) * periods / (sqrt(mean(min(r_t - rf/periods, 0)^2)) "
    "* sqrt(periods))",
    "max_drawdown": "min_t (V_t / max_{s<=t} V_s - 1), V = compounded wealth; reported <= 0",
    "max_drawdown_duration": "longest run of sessions spent below a previous wealth peak",
    "calmar": "cagr / |max_drawdown|",
    "beta": "cov(r, b) / var(b) on overlapping sessions",
    "alpha": "CAPM (Jensen) alpha: [mean(r - rf) - beta * mean(b - rf)] * periods",
    "tracking_error": "std(r - b, ddof=1) * sqrt(periods)",
    "information_ratio": "mean(r - b) * periods / tracking_error",
    "turnover": "sum(traded notional / equity at open) / years  (two-sided, annualized)",
    "trade_count": "number of fills in the trade ledger",
    "win_rate": "share of sell fills with positive realized P&L (average-cost basis, net of fees)",
    "var": "historical VaR_a = -Q(1 - a), Q = type-7 empirical quantile; positive = loss",
    "expected_shortfall": "ES_a = -mean(r | r <= Q(1 - a)); ties with Q (to 1e-12) are in the tail",
}


def _clean(returns: pd.Series) -> pd.Series:
    return pd.Series(returns).dropna().astype(float)


def align(returns: pd.Series, benchmark: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Inner-join two return series on common sessions (handles different start dates)."""
    both = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
    return both.iloc[:, 0], both.iloc[:, 1]


def wealth_index(returns: pd.Series) -> pd.Series:
    return (1.0 + _clean(returns)).cumprod()


def total_return(returns: pd.Series) -> float:
    r = _clean(returns)
    return float((1.0 + r).prod() - 1.0) if len(r) else np.nan


def cagr(returns: pd.Series, periods: int = TDY) -> float:
    r = _clean(returns)
    if len(r) == 0:
        return np.nan
    growth = float((1.0 + r).prod())
    if growth <= 0:
        return np.nan  # wiped out: a geometric growth rate is undefined
    return growth ** (periods / len(r)) - 1.0


def volatility(returns: pd.Series, periods: int = TDY) -> float:
    r = _clean(returns)
    return float(r.std(ddof=1) * np.sqrt(periods)) if len(r) >= 2 else np.nan


def sharpe(returns: pd.Series, risk_free: float = 0.0, periods: int = TDY) -> float:
    excess = _clean(returns) - risk_free / periods
    if len(excess) < 2:
        return np.nan
    sd = excess.std(ddof=1)
    if not sd > 1e-15:
        return np.nan
    return float(excess.mean() / sd * np.sqrt(periods))


def downside_deviation(returns: pd.Series, risk_free: float = 0.0, periods: int = TDY) -> float:
    """Annualized root-mean-square of returns below the per-period risk-free target."""
    excess = _clean(returns) - risk_free / periods
    if len(excess) == 0:
        return np.nan
    return float(np.sqrt((np.minimum(excess, 0.0) ** 2).mean()) * np.sqrt(periods))


def sortino(returns: pd.Series, risk_free: float = 0.0, periods: int = TDY) -> float:
    excess = _clean(returns) - risk_free / periods
    dd = downside_deviation(returns, risk_free, periods)
    if len(excess) < 2 or not dd > 1e-15:
        return np.nan
    return float(excess.mean() * periods / dd)


def drawdown_series(returns: pd.Series) -> pd.Series:
    """Drawdown from the running peak; the peak starts at the initial wealth of 1."""
    wealth = wealth_index(returns)
    peak = np.maximum(wealth.cummax(), 1.0)
    return wealth / peak - 1.0


def max_drawdown(returns: pd.Series) -> float:
    dd = drawdown_series(returns)
    return float(dd.min()) if len(dd) else np.nan


def max_drawdown_duration(returns: pd.Series) -> int:
    """Longest consecutive number of sessions under water (unrecovered runs count to the end)."""
    under = (drawdown_series(returns) < 0).to_numpy()
    longest = run = 0
    for u in under:
        run = run + 1 if u else 0
        longest = max(longest, run)
    return int(longest)


def calmar(returns: pd.Series, periods: int = TDY) -> float:
    mdd = max_drawdown(returns)
    if np.isnan(mdd) or mdd == 0:
        return np.nan
    return cagr(returns, periods) / abs(mdd)


def beta(returns: pd.Series, benchmark: pd.Series) -> float:
    r, b = align(returns, benchmark)
    if len(r) < 2 or not b.var(ddof=1) > 1e-18:
        return np.nan
    return float(r.cov(b) / b.var(ddof=1))


def alpha(
    returns: pd.Series, benchmark: pd.Series, risk_free: float = 0.0, periods: int = TDY
) -> float:
    """Annualized CAPM (Jensen) alpha: intercept of excess returns on benchmark excess returns."""
    r, b = align(returns, benchmark)
    bt = beta(r, b)
    if np.isnan(bt):
        return np.nan
    rf = risk_free / periods
    return float(((r - rf).mean() - bt * (b - rf).mean()) * periods)


def tracking_error(returns: pd.Series, benchmark: pd.Series, periods: int = TDY) -> float:
    r, b = align(returns, benchmark)
    return float((r - b).std(ddof=1) * np.sqrt(periods)) if len(r) >= 2 else np.nan


def information_ratio(returns: pd.Series, benchmark: pd.Series, periods: int = TDY) -> float:
    r, b = align(returns, benchmark)
    te = tracking_error(r, b, periods)
    if np.isnan(te) or not te > 1e-15:
        return np.nan
    return float((r - b).mean() * periods / te)


# Observations within this distance of the empirical quantile are treated as equal to it.
# Daily returns carry at most ~16 significant digits; the quantile itself is computed from
# ``1 - confidence`` (e.g. 1 - 0.90 = 0.09999999999999998), which can shift it by ~1e-17.
TAIL_TOLERANCE = 1e-12


def _check_confidence(confidence: float) -> None:
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be strictly between 0 and 1")


def historical_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """One-period historical VaR as a positive loss.

    Estimator: ``VaR = -Q(1 - confidence)``, where ``Q`` is the linearly interpolated
    empirical quantile (Hyndman-Fan type 7, NumPy's default). Unchanged since the
    published study.
    """
    _check_confidence(confidence)
    r = _clean(returns)
    return float(-np.quantile(r, 1 - confidence)) if len(r) else np.nan


def historical_es(returns: pd.Series, confidence: float = 0.95) -> float:
    """One-period historical expected shortfall as a positive loss.

    Estimator: ``ES = -mean{ r_i : r_i <= Q + TAIL_TOLERANCE }`` with ``Q`` as in
    :func:`historical_var`. An observation equal to the quantile belongs to the tail,
    including when floating-point evaluation of ``1 - confidence`` puts ``Q`` a rounding
    error below it (QA-020). Hence ``ES >= VaR`` always. Tail membership differs from the
    earlier ``r_i <= Q`` rule only for such ties; the published study has none.
    """
    _check_confidence(confidence)
    r = _clean(returns)
    if len(r) == 0:
        return np.nan
    q = np.quantile(r, 1 - confidence)
    return float(-r[r <= q + TAIL_TOLERANCE].mean())


def annual_turnover(turnover: pd.Series, periods: int = TDY) -> float:
    return float(turnover.sum() / (len(turnover) / periods)) if len(turnover) else np.nan


def win_rate(trades: pd.DataFrame) -> float:
    sells = trades[trades["side"] == "SELL"] if len(trades) else trades
    return float((sells["realized_pnl"] > 0).mean()) if len(sells) else np.nan


def performance_summary(
    returns: pd.Series,
    benchmark: pd.Series | None = None,
    risk_free: float = 0.0,
    periods: int = TDY,
    turnover: pd.Series | None = None,
    trades: pd.DataFrame | None = None,
) -> dict[str, float]:
    """All headline statistics for one return series."""
    out = {
        "n_obs": float(len(_clean(returns))),
        "total_return": total_return(returns),
        "cagr": cagr(returns, periods),
        "volatility": volatility(returns, periods),
        "sharpe": sharpe(returns, risk_free, periods),
        "sortino": sortino(returns, risk_free, periods),
        "downside_deviation": downside_deviation(returns, risk_free, periods),
        "max_drawdown": max_drawdown(returns),
        "max_drawdown_duration": float(max_drawdown_duration(returns)),
        "calmar": calmar(returns, periods),
        "var_95": historical_var(returns, 0.95),
        "es_95": historical_es(returns, 0.95),
    }
    if benchmark is not None:
        out |= {
            "beta": beta(returns, benchmark),
            "alpha": alpha(returns, benchmark, risk_free, periods),
            "tracking_error": tracking_error(returns, benchmark, periods),
            "information_ratio": information_ratio(returns, benchmark, periods),
        }
    if turnover is not None:
        out["turnover"] = annual_turnover(turnover.reindex(returns.index).fillna(0.0), periods)
    if trades is not None:
        out["trade_count"] = float(len(trades))
        out["win_rate"] = win_rate(trades)
    return out
