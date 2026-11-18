"""Strategy and execution controls shared by the Strategy Lab and Backtesting pages."""

from __future__ import annotations

import streamlit as st

from quantlab.data import MarketData
from quantlab.execution import ExecutionConfig
from quantlab.strategies import CrossSectionalMomentum, MeanReversion, TrendFollowing

TREND, REVERSION, MOMENTUM = "Trend following", "Mean reversion", "Cross-sectional momentum"

INFO = {
    TREND: {
        "measures": "Whether an asset's recent average price is above its longer-run average.",
        "signal": "Hold the asset while the fast moving average is above the slow one; otherwise "
        "hold cash. Each selected asset gets an equal slice of capital.",
        "idea": "Returns tend to persist over several months, and large declines often unfold "
        "slowly enough to step aside.",
        "limits": "Reacts late by design, loses money in sideways markets (whipsaw), and cannot "
        "avoid a fast crash. No signal until the slow window is filled.",
    },
    REVERSION: {
        "measures": "How far today's price is from its recent average, in standard deviations "
        "(a z-score).",
        "signal": "Buy when the z-score falls below minus the entry level; sell when it rises "
        "back above minus the exit level.",
        "idea": "Short-term overreactions partially reverse.",
        "limits": "A low z-score can also be the start of a real decline: the 'average' it is "
        "measured against moves too. Trades often, so costs matter a great deal.",
    },
    MOMENTUM: {
        "measures": "Each asset's return over the lookback period, ranked against the others.",
        "signal": "On the first session of each period, hold the top-ranked assets; equal or "
        "inverse-volatility weights.",
        "idea": "Assets that recently outperformed their peers tend to keep doing so for a while.",
        "limits": "Results depend on the universe, which was chosen with hindsight. Needs at "
        "least as many assets with history as it is asked to hold.",
    },
}


def strategy_controls(data: MarketData):
    """Sidebar strategy configuration. Returns (strategy, kind) or stops with a clear message."""
    with st.sidebar:
        st.subheader("Strategy")
        kind = st.selectbox("Type", [TREND, REVERSION, MOMENTUM], key="p_kind")
        if kind == MOMENTUM:
            if len(data.tickers) < 2:
                st.error("Momentum ranks assets against each other: load at least two.")
                st.stop()
            lookback = st.number_input("Lookback (sessions)", 5, 504, 126, key="p_mom_look",
                                       help="126 sessions is about six months.")  # fmt: skip
            top_n = st.number_input("Assets held", 1, len(data.tickers),
                                    min(2, len(data.tickers)), key="p_mom_n")  # fmt: skip
            freq = st.selectbox("Rebalance", ["M", "W", "Q"], key="p_mom_freq",
                                format_func={"M": "Monthly", "W": "Weekly", "Q": "Quarterly"}.get)  # fmt: skip
            scheme = st.selectbox("Weighting", ["equal", "inverse_vol"], key="p_mom_w",
                                  format_func={"equal": "Equal", "inverse_vol": "Inverse volatility"}.get)  # fmt: skip
        else:
            valid = [t for t in st.session_state.get("p_assets", []) if t in data.tickers]
            st.session_state["p_assets"] = valid or data.tickers[:1]
            assets = st.multiselect("Assets", data.tickers, key="p_assets")
            if kind == TREND:
                fast = st.number_input("Fast average (sessions)", 2, 400, 50, key="p_fast",
                                       help="Shorter window: reacts quickly.")  # fmt: skip
                slow = st.number_input("Slow average (sessions)", 3, 600, 200, key="p_slow",
                                       help="Longer window: the trend baseline.")  # fmt: skip
            else:
                lookback = st.number_input("Lookback (sessions)", 2, 252, 20, key="p_mr_look")
                entry = st.number_input("Entry z-score", 0.1, 5.0, 2.0, 0.1, key="p_mr_in",
                                        help="Buy when price is this many standard deviations "
                                        "below its average.")  # fmt: skip
                exit_ = st.number_input("Exit z-score", -2.0, 4.9, 0.0, 0.1, key="p_mr_out",
                                        help="Sell when the z-score recovers above minus this "
                                        "value. 0 means back at the average.")  # fmt: skip
    if kind != MOMENTUM and not assets:
        st.error("Select at least one asset in the sidebar.")
        st.stop()
    try:
        if kind == TREND:
            return TrendFollowing(int(fast), int(slow), tuple(assets)), kind
        if kind == REVERSION:
            return MeanReversion(int(lookback), entry, exit_, tuple(assets)), kind
        return CrossSectionalMomentum(int(lookback), 0, int(top_n), freq, scheme), kind
    except ValueError as exc:
        hint = {TREND: "The fast window must be shorter than the slow window.",
                REVERSION: "The entry z-score must be larger than the exit z-score."}.get(kind, "")  # fmt: skip
        st.error(f"These parameters cannot work together. {hint} ({exc})")
        st.stop()


def execution_controls(data: MarketData):
    """Sidebar execution assumptions. Returns (config, benchmark ticker, annual risk-free rate)."""
    with st.sidebar:
        st.subheader("Execution")
        capital = st.number_input("Initial capital", 1_000.0, 1e9, 100_000.0, 1_000.0, key="p_cap")
        slippage = st.number_input("Slippage (bps per trade)", 0.0, 100.0, 2.0, 0.5, key="p_slip",
                                   help="How much worse than the opening price each fill is. "
                                   "1 bp = 0.01%.")  # fmt: skip
        fee = st.number_input("Fee (bps per trade)", 0.0, 100.0, 1.0, 0.5, key="p_fee",
                              help="Commission as a share of traded value.")  # fmt: skip
        fractional = st.checkbox("Allow fractional shares", True, key="p_frac")
        if st.session_state.get("p_bench") not in data.tickers:
            st.session_state["p_bench"] = data.tickers[0]
        benchmark = st.selectbox("Benchmark (buy and hold)", data.tickers, key="p_bench")
        rf = st.number_input("Risk-free rate (% per year)", 0.0, 20.0, 0.0, 0.25, key="p_rf",
                             help="Used in Sharpe, Sortino and alpha. Cash in the portfolio "
                             "itself earns nothing.")  # fmt: skip
    return ExecutionConfig(capital, slippage, fee, fractional_shares=fractional), benchmark, rf / 100
