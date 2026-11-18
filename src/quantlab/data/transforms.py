"""Pure transformations of price panels. All rolling windows are trailing (causal)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantlab import TRADING_DAYS_PER_YEAR


def simple_returns(prices: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    """r_t = P_t / P_{t-1} - 1. A gap (NaN price) yields NaN, never an imputed return."""
    return prices / prices.shift(1) - 1.0


def log_returns(prices: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    """l_t = ln(P_t / P_{t-1}). Additive across time; simple returns are additive across assets."""
    return np.log(prices / prices.shift(1))


def cumulative_returns(returns: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    """Compounded growth of 1 minus 1 from simple returns (NaN treated as no observation)."""
    return (1.0 + returns.fillna(0.0)).cumprod() - 1.0


def normalize(prices: pd.DataFrame, base: float = 100.0) -> pd.DataFrame:
    """Rebase each series to ``base`` at its own first valid observation."""
    first = prices.apply(lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan)
    return prices / first * base


def moving_average(prices: pd.DataFrame | pd.Series, window: int) -> pd.DataFrame | pd.Series:
    """Trailing simple moving average; NaN until ``window`` observations exist."""
    return prices.rolling(window, min_periods=window).mean()


def rolling_volatility(
    returns: pd.DataFrame | pd.Series, window: int, periods: int = TRADING_DAYS_PER_YEAR
) -> pd.DataFrame | pd.Series:
    """Annualized trailing sample standard deviation (ddof=1) of simple returns."""
    return returns.rolling(window, min_periods=window).std(ddof=1) * np.sqrt(periods)


def correlation_matrix(returns: pd.DataFrame) -> pd.DataFrame:
    """Pearson correlation on sessions where every instrument has a return."""
    return returns.dropna(how="any").corr()
