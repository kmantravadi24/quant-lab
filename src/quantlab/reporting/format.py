"""One formatter for every number a user reads, on screen or in an export.

* Undefined values (None, NaN, +/-inf) are shown as "n/a", never as "nan" (QA-011).
* A value that rounds to zero is shown without a minus sign: "0.00", not "-0.00" (QA-012).
* Each statistic has one unit: percent, money, count, ratio or plain number (QA-002).
* Users see plain-language names, never internal field names (QA-036).
"""

from __future__ import annotations

import math
import numbers

PERCENT = "percent"
MONEY = "money"
COUNT = "count"
RATIO = "ratio"
NUMBER = "number"

KINDS: dict[str, str] = {
    # returns and risk, as fractions (0.07 = 7%)
    **dict.fromkeys(
        [
            "total_return", "cagr", "volatility", "max_drawdown", "var_95", "es_95", "alpha",
            "tracking_error", "downside_deviation", "win_rate", "time_weighted_annual",
            "time_weighted_total", "money_weighted_annual", "money_weighted_period", "worst_day",
            "drift_average", "drift_max", "trading_cost_pct_of_invested", "cash_weight_target",
            "volatility_annual", "var_1d", "es_1d", "cash_weight",
            "prob_loss", "prob_drawdown_worse_than_20pct", "median_max_drawdown",
            "p5_max_drawdown",
        ],
        PERCENT,
    ),
    **dict.fromkeys(
        [
            "final_value", "total_invested", "gain", "trading_cost", "contributions",
            "initial_amount", "median_terminal", "p5_terminal", "p95_terminal", "mean_terminal",
            "value_before", "value_after", "pnl",
        ],
        MONEY,
    ),
    **dict.fromkeys(
        ["n_obs", "trade_count", "max_drawdown_duration", "longest_drawdown_sessions",
         "span_days", "sessions", "contribution_count"],
        COUNT,
    ),
    **dict.fromkeys(
        ["sharpe", "sortino", "calmar", "information_ratio", "beta", "diversification_ratio",
         "average_correlation", "effective_holdings", "turnover"],
        RATIO,
    ),
}  # fmt: skip

LABELS: dict[str, str] = {
    "n_obs": "Sessions", "total_return": "Total return", "cagr": "CAGR",
    "volatility": "Volatility (annual)", "sharpe": "Sharpe ratio", "sortino": "Sortino ratio",
    "downside_deviation": "Downside deviation (annual)", "max_drawdown": "Maximum drawdown",
    "max_drawdown_duration": "Longest drawdown (sessions)", "calmar": "Calmar ratio",
    "var_95": "1-day value at risk, 95%", "es_95": "1-day expected shortfall, 95%",
    "beta": "Beta vs benchmark", "alpha": "Alpha (CAPM, annual)",
    "tracking_error": "Tracking error (annual)", "information_ratio": "Information ratio",
    "turnover": "Turnover (two-sided, per year)", "trade_count": "Fills",
    "win_rate": "Win rate (sell fills)",
    "final_value": "Final value", "total_invested": "Total paid in", "gain": "Gain after costs",
    "time_weighted_annual": "Time-weighted return (annual)",
    "time_weighted_total": "Time-weighted return (whole period)",
    "money_weighted_annual": "Money-weighted return (annual)",
    "money_weighted_period": "Money-weighted return (whole period)",
    "money_weighted_status": "Money-weighted return status",
    "worst_day": "Worst day", "trading_cost": "Trading costs paid",
    "trading_cost_pct_of_invested": "Trading costs as share of money paid in",
    "drift_average": "Average drift from target", "drift_max": "Largest drift from target",
    "cash_weight_target": "Target cash", "contributions": "Contributions paid in",
    "contribution_count": "Number of contributions", "span_days": "Calendar days",
    "volatility_annual": "Volatility (annual, estimated)", "var_1d": "1-day value at risk",
    "es_1d": "1-day expected shortfall", "longest_drawdown_sessions": "Longest drawdown (sessions)",
    "effective_holdings": "Effective number of holdings",
    "diversification_ratio": "Diversification ratio", "average_correlation": "Average correlation",
    "cash_weight": "Cash", "initial_amount": "Initial amount",
    # execution and data fields that appear in report appendices
    "initial_capital": "Initial capital", "slippage_bps": "Slippage (basis points)",
    "fee_bps": "Commission (basis points)", "fixed_fee": "Fixed fee per fill",
    "fractional_shares": "Fractional shares allowed", "min_trade_notional": "Smallest trade sent",
    "source": "Source", "tickers": "Instruments", "start": "First session", "end": "Last session",
    "adjustment": "Price adjustment", "retrieved_at": "Retrieved at", "synthetic": "Synthetic data",
    "notes": "Notes", "fingerprint": "Dataset fingerprint", "frequency": "Frequency",
    "timezone": "Time zone", "provider": "Provider", "seed": "Random seed",
    "generated_at": "Generated at", "timing": "Order timing", "total_cost": "Total cost",
    "total_fees": "Fees", "total_slippage": "Slippage cost", "python": "Python",
    "platform": "Platform", "quantlab": "Quant Lab version", "git_commit": "Git commit",
    "git_dirty": "Uncommitted changes", "numpy": "NumPy", "pandas": "pandas",
}  # fmt: skip


def is_defined(value) -> bool:
    if value is None or isinstance(value, bool):
        return value is not None
    if isinstance(value, numbers.Real):
        return math.isfinite(float(value))
    return True


def _no_negative_zero(text: str) -> str:
    """'-0.00' -> '0.00', '-0.00%' -> '0.00%', but '-0.01' unchanged."""
    if text.startswith("-") and not any(c in "123456789" for c in text):
        return text[1:]
    return text


def format_value(key: str | None, value, kind: str | None = None, digits: int = 2) -> str:
    """Format ``value`` for a reader. ``kind`` overrides the unit looked up from ``key``."""
    if not is_defined(value):
        return "n/a"
    if not isinstance(value, numbers.Real) or isinstance(value, bool):
        return str(value)
    kind = kind or KINDS.get(key or "", NUMBER)
    v = float(value)
    if kind == PERCENT:
        text = f"{v:.{digits}%}"
    elif kind in (MONEY, COUNT):
        text = f"{v:,.0f}"
    else:
        text = f"{v:,.{digits}f}"
    return _no_negative_zero(text)


def format_signed(key: str | None, value, kind: str | None = None, digits: int = 2) -> str:
    """Like :func:`format_value` with an explicit sign ('+1.20%'); zero has no sign."""
    text = format_value(key, value, kind, digits)
    if text == "n/a" or text.startswith("-") or not any(c in "123456789" for c in text):
        return text
    return "+" + text


def format_significant(value, figures: int = 3) -> str:
    """Significant-figure formatting for small quantities such as covariances (QA-025)."""
    if not is_defined(value):
        return "n/a"
    v = float(value)
    if v == 0:
        return "0"
    text = f"{v:.{figures}g}"
    return _no_negative_zero(text)


def label(key: str) -> str:
    """Plain-language name of a statistic; unknown keys are tidied, not shown raw."""
    return LABELS.get(key, key.replace("_", " ").capitalize())
