"""Fixed-weight risk estimate: one implementation shared by every page that shows one.

MODEL. The target weights are applied to each day's simple returns, i.e. the
portfolio is assumed to be rebalanced to target every session, with no
contributions, no trading costs and cash earning 0%. This is a statistical
description of the target allocation over a historical window. It is NOT the
account-level simulation of the transaction engine (``quantlab.portfolio``),
which buys at the next open, pays costs, drifts between rebalances and invests
contributions; the two give different numbers by construction.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quantlab import TRADING_DAYS_PER_YEAR as TDY
from quantlab.analytics import metrics as m
from quantlab.risk.portfolio import (
    covariance_matrix,
    diversification_ratio,
    effective_holdings,
    held_weights,
    portfolio_returns,
    portfolio_volatility,
    risk_contributions,
)

MODEL = "fixed-weight"
MODEL_DESCRIPTION = (
    "Fixed-weight estimate: target weights applied to every day's returns (rebalanced daily), "
    "no contributions, no trading costs, cash earning 0%. Not the account simulation."
)


@dataclass(frozen=True)
class RiskEstimate:
    weights: pd.Series  # held positions only; the remainder is cash
    returns: pd.DataFrame  # daily returns of the held instruments in the window
    portfolio: pd.Series  # fixed-weight portfolio daily returns
    covariance: pd.DataFrame  # annualised
    contributions: pd.DataFrame
    confidence: float

    @property
    def start(self) -> pd.Timestamp:
        return self.returns.index[0]

    @property
    def end(self) -> pd.Timestamp:
        return self.returns.index[-1]

    @property
    def sessions(self) -> int:
        return len(self.returns)

    @property
    def cash_weight(self) -> float:
        return max(0.0, 1.0 - float(self.weights.sum()))

    def correlation(self) -> pd.DataFrame:
        return self.returns.corr()

    def average_correlation(self) -> float:
        """Mean pairwise correlation; NaN (undefined) with fewer than two holdings."""
        corr = self.correlation()
        n = len(corr)
        if n < 2:
            return float("nan")
        values = [corr.iat[i, j] for i in range(n) for j in range(i + 1, n)]
        values = [v for v in values if pd.notna(v)]
        return float(sum(values) / len(values)) if values else float("nan")

    def summary(self) -> dict:
        return {
            "model": MODEL,
            "volatility_annual": portfolio_volatility(self.weights, self.covariance),
            "var_1d": m.historical_var(self.portfolio, self.confidence),
            "es_1d": m.historical_es(self.portfolio, self.confidence),
            "max_drawdown": m.max_drawdown(self.portfolio),
            "longest_drawdown_sessions": m.max_drawdown_duration(self.portfolio),
            "worst_day": float(self.portfolio.min()),
            "effective_holdings": effective_holdings(self.weights),
            "diversification_ratio": diversification_ratio(self.weights, self.covariance),
            "average_correlation": self.average_correlation(),
            "cash_weight": self.cash_weight,
            "confidence": self.confidence,
            "window": {"start": str(self.start.date()), "end": str(self.end.date()),
                       "sessions": self.sessions},  # fmt: skip
        }


def estimate_risk(
    returns: pd.DataFrame,
    weights: pd.Series,
    confidence: float = 0.95,
    periods: int = TDY,
) -> RiskEstimate:
    """Estimate fixed-weight risk on ``returns`` (held instruments, complete rows)."""
    held = held_weights(weights)
    if held.empty:
        raise ValueError("The portfolio is entirely cash: there is no market risk to estimate")
    window = returns[list(held.index)].dropna(how="any")
    if len(window) < 2:
        raise ValueError("Need at least two complete return observations")
    cov = covariance_matrix(window, periods)
    return RiskEstimate(
        weights=held,
        returns=window,
        portfolio=portfolio_returns(window, held),
        covariance=cov,
        contributions=risk_contributions(held, cov),
        confidence=confidence,
    )
