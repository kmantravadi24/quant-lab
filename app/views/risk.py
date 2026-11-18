from datetime import UTC, datetime

import streamlit as st
from components.common import (
    HELP,
    downloads,
    figure,
    header,
    heatmap,
    line_chart,
    load_data,
    show,
)
from components.portfolio import model_badge, portfolio_input

from quantlab.analytics import metrics as m
from quantlab.data.transforms import rolling_volatility
from quantlab.portfolio.compare import data_fingerprint
from quantlab.reporting import csv_bytes, json_bytes
from quantlab.reporting.experiment import environment
from quantlab.reporting.format import format_significant, format_value
from quantlab.risk import estimate_risk, exposure_breakdown, holding_returns, portfolio_returns

header("Risk Analytics", "How much a fixed-weight portfolio has moved, and where that risk comes from.")
data = load_data()
chosen = portfolio_input(data.tickers)
weights = chosen.weights
if chosen.held.empty:
    st.info("The portfolio is 100% cash, so there is no market risk to measure. Enter a weight above.")
    st.stop()

# Only the instruments the portfolio holds limit the window (QA-010).
returns = holding_returns(data.close, weights)
if len(returns) < 60:
    st.error(f"Only {len(returns)} sessions are common to the instruments this portfolio holds. "
             "At least 60 are needed to estimate risk: load more history or change the holdings.")  # fmt: skip
    st.stop()
c1, c2, c3 = st.columns(3)
max_years = len(returns) // 252
if max_years >= 2:
    years = c1.slider("Estimation window (most recent years)", 1, max_years, min(5, max_years),
                      help="Risk is estimated from this much recent history. Short windows react "
                      "faster but are noisier.")  # fmt: skip
else:  # a slider needs a range; with under two years of data use everything available
    years = 1
    c1.caption("Estimation window: all available history (under two years loaded).")
conf = c2.select_slider("Confidence level", [0.90, 0.95, 0.975, 0.99], 0.95)
value = c3.number_input("Portfolio value", 1_000.0, 1e9, 100_000.0, 1_000.0, key="p_value")
est = estimate_risk(returns.iloc[-years * 252 :], weights, conf)
s = est.summary()
span = f"{est.start.date()} to {est.end.date()} ({est.sessions:,} sessions)"
unheld = [t for t in data.tickers if t not in est.weights.index]

model_badge(f"Window: {span}.")
k = st.columns(5)
k[0].metric("Volatility (annual)", format_value("volatility", s["volatility_annual"]), help=HELP["Volatility"])
k[1].metric(f"1-day VaR {conf:.1%}", format_value("var_1d", s["var_1d"]),
            f"{format_value('pnl', s['var_1d'] * value)} loss", delta_color="off", delta_arrow="off", help=HELP["VaR"])  # fmt: skip
k[2].metric(f"1-day ES {conf:.1%}", format_value("es_1d", s["es_1d"]),
            f"{format_value('pnl', s['es_1d'] * value)} loss", delta_color="off", delta_arrow="off",
            help="Expected shortfall: the average loss on the days at or beyond the VaR level.")  # fmt: skip
k[3].metric("Max drawdown", format_value("max_drawdown", s["max_drawdown"]), help=HELP["Max drawdown"])
k[4].metric("Longest drawdown", f"{s['longest_drawdown_sessions']:,} sessions",
            help="Longest stretch spent below a previous high.")  # fmt: skip
st.caption(f"**Historical estimate on {span}** for **{chosen.name}**. Daily returns, sample "
           "covariance scaled to a year (x252), the portfolio held at its target weights every day, "
           "cash earning nothing. VaR and ES are read directly from this window's worst days: they "
           "describe the past, they are not a ceiling on future losses. Absolute risk measures, not "
           "relative to a benchmark."
           + (f" Only held instruments set the window; {', '.join(unheld)} "
              f"{'is' if len(unheld) == 1 else 'are'} loaded but not held and "
              f"{'does' if len(unheld) == 1 else 'do'} not shorten it." if unheld else ""))  # fmt: skip

d = st.columns(4)
d[0].metric("Effective holdings", f"{format_value('effective_holdings', s['effective_holdings'], digits=1)} of {len(est.weights)}",
            help="1 / sum of squared invested weights: how many equal positions the concentration "
            "is equivalent to.")  # fmt: skip
d[1].metric("Diversification ratio", format_value("diversification_ratio", s["diversification_ratio"]),
            help="Weighted average of the holdings' own volatilities / portfolio volatility. 1.00 means "
            "mixing them reduced volatility not at all.")  # fmt: skip
d[2].metric("Average correlation", format_value("average_correlation", s["average_correlation"]),
            help="Mean correlation between pairs of holdings. n/a with one holding.")  # fmt: skip
d[3].metric("Cash", format_value("cash_weight", s["cash_weight"], digits=1),
            help="Held at its value; earns 0% here, so it lowers volatility and return in proportion.")  # fmt: skip
with st.expander("How to read these numbers"):
    st.markdown(
        "- **Volatility** measures how much the value moved day to day, scaled to a year. It treats "
        "rises and falls alike.\n"
        "- **VaR** is a threshold: on the stated share of days in this window the loss was larger. "
        "**ES** is the average of those larger losses, so it is always at least the VaR.\n"
        "- **Diversification** comes from holdings that do not move together. With average "
        "correlation near 1 the diversification ratio stays near 1.00, whatever the number of "
        "holdings; effective holdings counts concentration of money, not of risk.\n"
        "- **Cash** is held at its value and earns nothing in this model. 20% cash scales "
        "volatility, VaR and ES down by 20% exactly; it does not make the invested part safer.\n"
        "- Every figure is **historical** for the stated window and assumes the weights are held "
        "exactly every day. A different window, or the future, can be calmer or much worse."
    )

t_contrib, t_corr, t_time, t_export = st.tabs(["Risk contributions", "Correlation & covariance", "Through time", "Export"])
rc = est.contributions
with t_contrib:
    left, right = st.columns([3, 2])
    with left:
        bar = figure("Capital share vs risk share", "Share", 340, ".0%")
        bar.add_bar(x=rc.index, y=rc["weight"], name="Capital weight")
        bar.add_bar(x=rc.index, y=rc["pct_of_risk"], name="Share of volatility")
        bar.update_layout(barmode="group", hovermode="x")
        show(bar)
        st.caption("An asset can hold 20% of the money and carry 30% of the risk. Contribution = "
                   "weight x (covariance x weights) / portfolio volatility; contributions add up "
                   "to total volatility. Cash has no volatility and contributes nothing.")  # fmt: skip
    with right:
        shown = rc.rename(columns={"weight": "Weight", "standalone_vol": "Own volatility",
                                   "vol_contribution": "Contribution", "pct_of_risk": "Share of risk"})  # fmt: skip
        st.dataframe(shown.map(lambda v: format_value("volatility", v)), width="stretch")
        exposure = exposure_breakdown(weights, value)
        st.dataframe(exposure.assign(weight=exposure["weight"].map(lambda v: format_value("cash_weight", v)),
                                     value=exposure["value"].map(lambda v: format_value("final_value", v)))
                     .rename(columns={"weight": "Weight", "value": "Value"}), width="stretch")  # fmt: skip
with t_corr:
    if len(est.weights) < 2:
        st.info("The portfolio holds one instrument, so there is no correlation between holdings "
                "to show (a correlation needs two series).")  # fmt: skip
    else:
        show(heatmap(est.correlation(), 380))
        st.caption(f"Correlation of daily returns over {span}. 1 means the two always moved together, "
                   "0 no linear relation, -1 opposite. Lower correlation between holdings is what "
                   "makes a mix less volatile than its parts.")  # fmt: skip
    with st.expander("Annualized covariance matrix"):
        st.dataframe(est.covariance.map(format_significant), width="stretch")
        st.caption("Three significant figures (small numbers are shown in scientific notation, "
                   "e.g. 4.1e-05). The diagonal is each instrument's variance; its square root is "
                   "the annual volatility.")  # fmt: skip
with t_time:
    roll = st.slider("Rolling window (sessions)", 21, 252, 63)
    full = portfolio_returns(returns, est.weights)
    show(line_chart(rolling_volatility(full, roll).rename("Portfolio"),
                    f"Annualized volatility over the trailing {roll} sessions, "
                    f"{returns.index[0].date()} to {returns.index[-1].date()}",
                    "Volatility (per year)", ".0%", 300))  # fmt: skip
    show(line_chart(m.drawdown_series(full).rename("Portfolio"),
                    "Drawdown from the highest value so far, full history of the held instruments",
                    "Drawdown", ".0%", 260))  # fmt: skip
with t_export:
    summary = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "portfolio": chosen.describe(), "portfolio_value": value, **s,
        "estimation_window": s["window"], "method": "historical; sample covariance x252",
        "model": "fixed-weight: target weights applied to each day's returns; no contributions, "
        "no costs, cash earns 0%",
        "data": {**data.metadata.to_dict(), "fingerprint": data_fingerprint(data)},
        "environment": environment(),
    }  # fmt: skip
    downloads({"Risk metrics (JSON)": (json_bytes(summary), "risk_metrics.json"),
               "Risk contributions (CSV)": (csv_bytes(rc, "asset"), "risk_contributions.csv"),
               "Covariance matrix (CSV)": (csv_bytes(est.covariance, "asset"), "covariance.csv")}, "risk")  # fmt: skip
