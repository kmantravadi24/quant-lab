import streamlit as st
from components import theme
from components.common import downloads, figure, header, load_data, show
from components.strategy import (
    INFO,
    MOMENTUM,
    REVERSION,
    TREND,
    strategy_controls,
    synthetic_trend_note,
)

from quantlab.reporting import csv_bytes, json_bytes
from quantlab.reporting.exports import describe_strategy

header("Strategy Lab", "What the rule measures, and exactly when it is in or out of the market.")
data = load_data()
strategy, kind = strategy_controls(data)
out = strategy.generate(data)

info = INFO[kind]
c1, c2 = st.columns(2)
c1.markdown(f"**What it measures**  \n{info['measures']}\n\n**How a signal is generated**  \n{info['signal']}")
c2.markdown(f"**The idea being tested**  \n{info['idea']}\n\n**Known weaknesses**  \n{info['limits']}")
st.caption("Change the parameters in the sidebar. A signal dated T uses prices up to the close "
           "of T only, and would trade at the open of T+1.")  # fmt: skip

held = out.signals.loc[:, out.signals.any()]
k = st.columns(4)
k[0].metric("Decisions", len(out.weights), help="Dates on which the target portfolio changes.")
k[1].metric("Sessions with a position", f"{(out.signals.sum(axis=1) > 0).mean():.0%}")
first = out.weights.index[0].date() if len(out.weights) else "none"
k[2].metric("First decision", str(first), help="Earlier sessions lack enough history for a signal.")
k[3].metric("Assets ever held", f"{held.shape[1]} of {len(data.tickers)}")
synthetic_trend_note(data, kind)
if out.weights.empty:
    st.warning("**No signal was ever generated.** There is not enough history for these windows, "
               "or the entry condition never occurred. Shorten the windows or load more history.")  # fmt: skip
    st.stop()

candidates = list(strategy.tickers) if getattr(strategy, "tickers", None) else data.tickers
asset = st.selectbox("Inspect asset", candidates)
close = data.close[asset].dropna()
signal = out.signals[asset].reindex(close.index).fillna(0)

fig = figure(f"{asset}: price, indicator and position", "Adjusted price", 420)
fig.add_scatter(x=close.index, y=close, name="Close", line=dict(color=theme.TEXT, width=1.3))
if kind == TREND:
    for name, color in (("fast_ma", theme.ACCENT), ("slow_ma", theme.BENCH)):
        s = out.diagnostics[name][asset]
        fig.add_scatter(x=s.index, y=s, name=name.replace("_ma", " average").title(),
                        line=dict(color=color, width=1.4))  # fmt: skip
# Shade the sessions on which the rule holds the asset.
change = signal.diff().fillna(signal.iloc[0])
starts, ends = list(signal.index[change > 0]), list(signal.index[change < 0])
if len(ends) < len(starts):
    ends.append(signal.index[-1])
for a, b in zip(starts, ends, strict=True):
    fig.add_vrect(x0=a, x1=b, fillcolor=theme.POSITIVE, opacity=0.10, line_width=0)
show(fig)
st.caption("Green bands: sessions on which the rule's signal says to hold the asset.")

if kind == REVERSION:
    z = out.diagnostics["zscore"][asset]
    zfig = figure(f"{asset}: z-score of price against its trailing average",
                  "Standard deviations", 280)  # fmt: skip
    zfig.add_scatter(x=z.index, y=z, name="z-score", line=dict(color=theme.ACCENT, width=1.2))
    zfig.add_hline(y=-strategy.entry_z, line_dash="dash", line_color=theme.POSITIVE,
                   annotation_text="buy below")  # fmt: skip
    zfig.add_hline(y=-strategy.exit_z, line_dash="dot", line_color=theme.NEGATIVE,
                   annotation_text="sell above")  # fmt: skip
    show(zfig)
if kind == MOMENTUM:
    score = out.diagnostics["score"]
    sfig = figure(f"Trailing {strategy.lookback}-session return of each asset (the ranking score)",
                  "Return", 300, ".0%")  # fmt: skip
    for col in score.columns:
        sfig.add_scatter(x=score.index, y=score[col], name=col, line=dict(width=1.2))
    show(sfig)

st.subheader("Decision log")
log = out.weights.copy()
log.index = log.index.date
log.index.name = "decided at close of"
st.dataframe(log.sort_index(ascending=False).style.format("{:.0%}"), width="stretch", height=260)
st.caption("Target portfolio weights on each decision date; the remainder is cash. Each row "
           "would be executed at the next session's open. Use the Backtesting page to simulate it.")  # fmt: skip
downloads({
    "Download decisions (CSV)": (csv_bytes(out.weights, "decision_date"), "decisions.csv"),
    "Download daily signals (CSV)": (csv_bytes(out.signals, "date"), "signals.csv"),
    "Download strategy config (JSON)": (json_bytes({"strategy": describe_strategy(strategy),
                                                    "data": data.metadata.to_dict()}), "strategy.json"),
}, "strategy")  # fmt: skip
