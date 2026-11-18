"""Portfolio risk from historical returns.

Estimation method: sample covariance (ddof=1) of daily simple returns over the
supplied window, on sessions where every asset has a return, annualized by
multiplying by ``periods``. Assumes the window is representative and returns are
serially uncorrelated (the sqrt-time rule); both are approximations.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantlab import TRADING_DAYS_PER_YEAR as TDY

WEIGHT_TOL = 1e-6


def validate_weights(weights: pd.Series, allow_cash: bool = True) -> pd.Series:
    """Long-only weights summing to 1 (or <= 1 when the remainder is cash)."""
    w = pd.Series(weights, dtype=float)
    if not np.isfinite(w.to_numpy()).all():  # QA-018: inf is not reported as 'leverage'
        raise ValueError("Weights must be finite numbers (NaN or infinity found)")
    if (w < -WEIGHT_TOL).any():
        raise ValueError("Negative weights are not supported (long-only)")
    total = w.sum()
    if total > 1 + WEIGHT_TOL:
        raise ValueError(f"Weights sum to {total:.4f} > 1: leverage is not supported")
    if not allow_cash and abs(total - 1) > WEIGHT_TOL:
        raise ValueError(f"Weights sum to {total:.4f}, expected 1")
    return w


def covariance_matrix(returns: pd.DataFrame, periods: int = TDY) -> pd.DataFrame:
    clean = returns.dropna(how="any")
    if len(clean) < 2:
        raise ValueError("Need at least two complete return observations")
    return clean.cov(ddof=1) * periods


def portfolio_variance(weights: pd.Series, cov: pd.DataFrame) -> float:
    w = weights.reindex(cov.index).fillna(0.0).to_numpy()
    return float(w @ cov.to_numpy() @ w)


def portfolio_volatility(weights: pd.Series, cov: pd.DataFrame) -> float:
    return float(np.sqrt(portfolio_variance(weights, cov)))


def risk_contributions(weights: pd.Series, cov: pd.DataFrame) -> pd.DataFrame:
    """Euler decomposition of volatility: RC_i = w_i * (Sigma w)_i / sigma_p; sum RC_i = sigma_p."""
    w = weights.reindex(cov.index).fillna(0.0)
    sigma = portfolio_volatility(w, cov)
    if not sigma > 0:
        rc = pd.Series(np.nan, index=cov.index)
    else:
        rc = w * (cov.to_numpy() @ w.to_numpy()) / sigma
    return pd.DataFrame({
        "weight": w,
        "standalone_vol": np.sqrt(np.diag(cov.to_numpy())),
        "vol_contribution": rc,
        "pct_of_risk": rc / sigma if sigma > 0 else np.nan,
    })  # fmt: skip


def held_weights(weights: pd.Series) -> pd.Series:
    """The positions with a positive weight (cash and zero weights removed)."""
    w = validate_weights(weights)
    return w[w > 0]


def holding_returns(close: pd.DataFrame, weights: pd.Series) -> pd.DataFrame:
    """Daily simple returns of the HELD instruments, on sessions where every held one has one.

    Instruments that are loaded but carry no weight never restrict the window (QA-010):
    a short-history instrument the portfolio does not own cannot shorten its analysis.
    """
    held = held_weights(weights)
    missing = [t for t in held.index if t not in close.columns]
    if missing:
        raise KeyError(f"Held instruments not in the data: {missing}")
    prices = close[list(held.index)]
    return (prices / prices.shift(1) - 1.0).iloc[1:].dropna(how="any")


def portfolio_returns(returns: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Returns of a portfolio rebalanced to ``weights`` every session (cash earns zero)."""
    clean = returns[list(weights.index)].dropna(how="any")
    return (clean * weights).sum(axis=1).rename("portfolio")


def exposure_breakdown(weights: pd.Series, value: float = 1.0) -> pd.DataFrame:
    w = validate_weights(weights)
    out = pd.DataFrame({"weight": w, "value": w * value})
    out.loc["CASH"] = [1 - w.sum(), (1 - w.sum()) * value]
    return out


def effective_holdings(weights: pd.Series) -> float:
    """Inverse Herfindahl index of the invested weights: 1 / sum(w_i^2), w normalised to 1.

    Equals N for N equal positions and approaches 1 as one position dominates.
    It measures concentration of capital, not of risk.
    """
    w = pd.Series(weights, dtype=float)
    w = w[w > 0]
    if w.empty:
        return float("nan")
    w = w / w.sum()
    return float(1.0 / (w**2).sum())


def diversification_ratio(weights: pd.Series, cov: pd.DataFrame) -> float:
    """Weighted average of the assets' own volatilities divided by portfolio volatility.

    1.0 means no diversification benefit (one asset, or perfectly correlated
    assets); higher means the mix is less volatile than its parts.
    """
    w = pd.Series(weights, dtype=float).reindex(cov.index).fillna(0.0)
    sigma = portfolio_volatility(w, cov)
    if not sigma > 0:
        return float("nan")
    return float((w * np.sqrt(np.diag(cov.to_numpy()))).sum() / sigma)
