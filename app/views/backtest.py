import json

import pandas as pd
import streamlit as st
from components import theme
from components.common import (
    HELP,
    LABELS,
    assumptions_expander,
    definitions_expander,
    downloads,
    figure,
    header,
    line_chart,
    load_data,
    show,
    stats_table,
)
from components.strategy import execution_controls, strategy_controls

from quantlab.analytics.metrics import drawdown_series
from quantlab.backtesting import backtest_strategy
from quantlab.reporting import backtest_bundle, cost_summary, html_report
from quantlab.research import evaluate
from quantlab.strategies import BuyAndHold

header("Backtesting", "Decide at the close of day T. Trade at the open of day T+1. Pay for it.")
data = load_data()
strategy, kind = strategy_controls(data)
cfg, benchmark, risk_free = execution_controls(data)

with st.spinner("Simulating the strategy and its benchmark..."):
    result = backtest_strategy(strategy, data, cfg)
    bench = backtest_strategy(BuyAndHold({benchmark: 1.0}), data, cfg)

first, last = data.dates[0].date(), data.dates[-1].date()
w1, w2, w3 = st.columns([1, 1, 2])
start = w1.date_input("Evaluate from", first, min_value=first, max_value=last)
end = w2.date_input("Evaluate to", last, min_value=first, max_value=last)
if start >= end:
    st.error("The evaluation window must start before it ends.")
    st.stop()
w3.caption("The simulation always runs on the full history, so indicators are warmed up with "
           "earlier data. This window only selects which sessions the statistics describe. "
           "Choosing a window after seeing results is a form of cherry-picking.")  # fmt: skip
start, end = pd.Timestamp(start), pd.Timestamp(end)
r, b = result.returns.loc[start:end], bench.returns.loc[start:end]
if len(r) < 2:
    st.error("The evaluation window contains fewer than two sessions.")
    st.stop()

name, bname = kind, f"Buy & hold {benchmark}"
stats = evaluate(result, start, end, benchmark=bench.returns, risk_free=risk_free)
bstats = evaluate(bench, start, end, benchmark=bench.returns, risk_free=risk_free)
if result.trades.empty:
    st.warning("**The strategy never traded**, so it stayed in cash. There is not enough history "
               "for these windows, or the entry condition never occurred.")  # fmt: skip
else:
    st.success(f"Backtest complete: {len(r):,} sessions evaluated, {int(stats['trade_count'])} fills "
               f"in the window ({len(result.trades)} over the full history), benchmark {benchmark}.")  # fmt: skip

cards = [("CAGR", "cagr", True, HELP["CAGR"]), ("Volatility", "volatility", True, HELP["Volatility"]),
         ("Sharpe ratio", "sharpe", False, HELP["Sharpe"]), ("Max drawdown", "max_drawdown", True, HELP["Max drawdown"]),
         ("1-day ES 95%", "es_95", True, HELP["ES"])]  # fmt: skip
for col, (label, key, pct, tip) in zip(st.columns(5), cards, strict=True):
    value, delta = stats[key], stats[key] - bstats[key]
    col.metric(label, "n/a" if pd.isna(value) else (f"{value:.2%}" if pct else f"{value:.2f}"),
               None if pd.isna(delta) else (f"{delta:+.2%} vs benchmark" if pct else f"{delta:+.2f} vs benchmark"),
               delta_color="off", delta_arrow="off", help=tip)  # fmt: skip

t_perf, t_stats, t_trades, t_expo, t_assume, t_export = st.tabs(
    ["Performance", "Statistics", "Trades & costs", "Exposure", "Assumptions", "Export"]
)
growth = pd.DataFrame({name: cfg.initial_capital * (1 + r).cumprod(),
                       bname: cfg.initial_capital * (1 + b).cumprod()})  # fmt: skip
with t_perf:
    fig = line_chart(growth, f"Growth of {cfg.initial_capital:,.0f} over the evaluation window",
                     "Portfolio value")  # fmt: skip
    show(fig)
    dd = pd.DataFrame({name: drawdown_series(r), bname: drawdown_series(b)})
    dfig = figure("Drawdown: fall from the highest value reached so far", "Drawdown", 280, ".0%")
    for col, color in zip(dd.columns, (theme.ACCENT, theme.BENCH), strict=True):
        dfig.add_scatter(x=dd.index, y=dd[col], name=col, line=dict(width=1.3, color=color),
                         fill="tozeroy" if col == name else None, fillcolor="rgba(91,141,239,0.12)")  # fmt: skip
    show(dfig)
    st.caption("Both portfolios run through the same engine, costs and calendar. When the two "
               "drawdown lines coincide, the strategy was fully invested in the benchmark asset.")  # fmt: skip

with t_stats:
    st.dataframe(stats_table({name: stats, bname: bstats}), width="stretch", height=670)
    st.caption(f"Window {start.date()} to {end.date()}, risk-free rate {risk_free:.2%}. Beta, "
               "alpha, tracking error and information ratio are measured against the benchmark "
               "(so they are trivial in the benchmark column).")  # fmt: skip
    definitions_expander()

with t_trades:
    costs = cost_summary(result)
    c = st.columns(4)
    c[0].metric("Fills", f"{costs['fills']:,.0f}")
    c[1].metric("Fees paid", f"{costs['fees_paid']:,.0f}")
    c[2].metric("Slippage paid", f"{costs['slippage_paid']:,.0f}")
    c[3].metric("Total cost", f"{costs['total_cost_pct_of_initial_capital']:.2%}",
                help="Fees plus slippage over the full history, as a share of initial capital.")  # fmt: skip
    ledger = result.trades.copy()
    if len(ledger):
        ledger["date"], ledger["decision_date"] = ledger["date"].dt.date, ledger["decision_date"].dt.date
    st.dataframe(
        ledger, width="stretch", height=360, hide_index=True,
        column_config={
            "decision_date": st.column_config.Column("Decided (close)"),
            "date": st.column_config.Column("Filled (open)"),
            "shares": st.column_config.NumberColumn(format="%.2f"),
            "reference_price": st.column_config.NumberColumn("Open price", format="%.2f"),
            "fill_price": st.column_config.NumberColumn("Fill price", format="%.2f"),
            "notional": st.column_config.NumberColumn(format="%.0f"),
            "fee": st.column_config.NumberColumn(format="%.2f"),
            "slippage_cost": st.column_config.NumberColumn("Slippage", format="%.2f"),
            "realized_pnl": st.column_config.NumberColumn("Realized P&L", format="%.0f"),
            "cash_after": st.column_config.NumberColumn("Cash after", format="%.0f"),
        },
    )  # fmt: skip
    st.caption("Every fill is dated after its decision. Realized P&L is shown on sells, on an "
               "average-cost basis net of fees.")  # fmt: skip
    if len(result.unfilled):
        st.markdown(f"**Orders that could not be filled ({len(result.unfilled)})**")
        st.dataframe(result.unfilled, width="stretch", hide_index=True)

with t_expo:
    weights = result.weights.loc[start:end]
    active = [col for col in weights if weights[col].any()]
    efig = figure("Share of the portfolio in each asset at the close", "Weight", 320, ".0%")
    for col in active:
        efig.add_scatter(x=weights.index, y=weights[col], name=col, stackgroup="w", line=dict(width=0.6))
    show(efig)
    invested = weights.sum(axis=1)
    e = st.columns(3)
    e[0].metric("Sessions invested", f"{(invested > 0.01).mean():.0%}")
    e[1].metric("Average exposure", f"{invested.mean():.0%}")
    e[2].metric("Highest exposure", f"{invested.max():.0%}", help="Never above 100%: no leverage.")

with t_assume:
    assumptions_expander(expanded=True)
    st.markdown(
        f"**This run:** {cfg.slippage_bps:g} bps slippage and {cfg.fee_bps:g} bps fee per trade, "
        f"{'fractional' if cfg.fractional_shares else 'whole'} shares, initial capital "
        f"{cfg.initial_capital:,.0f}, benchmark buy-and-hold {benchmark}. Data: {data.metadata.source}, "
        f"{data.metadata.start} to {data.metadata.end}."
    )

with t_export:
    notes = [
        "Signals use data to the close of day T and fill at the open of day T+1.",
        "Long-only, no leverage, cash earns no interest, flat basis-point cost model.",
        "Adjusted prices: returns include reinvested dividends; levels are not traded quotes.",
        "Instruments were chosen with hindsight; results are historical simulations.",
        f"Statistics cover {start.date()} to {end.date()}.",
    ]
    all_stats = {name: stats, bname: bstats}
    files = backtest_bundle(strategy, result, bench, all_stats, data.metadata.to_dict(),
                            evaluation_window=[str(start.date()), str(end.date())],
                            risk_free=risk_free, benchmark_asset=benchmark,
                            data_status=st.session_state.get("_data_status"))  # fmt: skip
    report = html_report(f"{name} vs {bname}", all_stats, growth, json.loads(files["config.json"]),
                         notes, LABELS)  # fmt: skip
    st.markdown("Everything below describes the run currently on screen.")
    downloads({
        "Equity & returns (CSV)": (files["equity_curve.csv"], "equity_curve.csv"),
        "Statistics (CSV)": (files["statistics.csv"], "statistics.csv"),
        "Trade log (CSV)": (files["trades.csv"], "trades.csv"),
    }, "bt1")  # fmt: skip
    downloads({
        "Statistics (JSON)": (files["statistics.json"], "statistics.json"),
        "Configuration (JSON)": (files["config.json"], "config.json"),
        "Research summary (HTML)": (report.encode(), "quantlab_summary.html"),
    }, "bt2")  # fmt: skip
    st.caption("The equity CSV covers the full simulated history; statistics cover the evaluation "
               "window. The HTML summary is a single self-contained file.")  # fmt: skip
