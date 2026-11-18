import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from components import theme
from components.common import downloads, figure, header, heatmap, line_chart, load_data, show

from quantlab.data import transforms as tf
from quantlab.reporting import csv_bytes

header("Market Explorer", "Adjusted daily prices. Gaps are shown as gaps, never filled in.")
data = load_data()
returns = tf.simple_returns(data.close)
t_price, t_perf, t_vol, t_corr, t_quality = st.tabs(
    ["Price", "Performance", "Volatility & rolling statistics", "Correlation", "Data quality"]
)

with t_price:
    c1, c2, c3 = st.columns([2, 1, 1])
    ticker = c1.selectbox("Instrument", data.tickers)
    fast = c2.number_input("Fast moving average (sessions)", 2, 400, 50)
    slow = c3.number_input("Slow moving average (sessions)", 3, 600, 200)
    bars = data.select([ticker])
    fig = figure(f"{ticker}: daily open-high-low-close with moving averages", "Adjusted price", 480)
    fig.add_trace(go.Candlestick(
        x=bars.dates, open=bars.open[ticker], high=bars.high[ticker], low=bars.low[ticker],
        close=bars.close[ticker], name=ticker, increasing_line_color=theme.POSITIVE,
        decreasing_line_color=theme.NEGATIVE,
    ))  # fmt: skip
    for window, color in ((fast, theme.BENCH), (slow, theme.VIOLET)):
        ma = tf.moving_average(bars.close[ticker], int(window))
        fig.add_scatter(x=ma.index, y=ma, name=f"{window}-session average",
                        line=dict(width=1.4, color=color))  # fmt: skip
    fig.update_layout(xaxis_rangeslider_visible=False)
    show(fig)
    st.caption("Prices are adjusted for splits and dividends, so older levels are lower than the "
               "quotes that actually traded. Returns are unaffected.")  # fmt: skip

with t_perf:
    show(line_chart(tf.normalize(data.close), "Growth of 100 from each instrument's first date",
                    "Value (start = 100)", height=420))  # fmt: skip
    yearly = (1 + returns).groupby(returns.index.year).prod() - 1
    yearly = yearly.where(returns.groupby(returns.index.year).count() > 0)
    st.markdown("**Calendar-year returns**")
    st.dataframe(yearly.sort_index(ascending=False).style.format("{:.1%}", na_rep="n/a"),
                 width="stretch", height=320)  # fmt: skip
    st.caption("First and last years may be partial.")

with t_vol:
    window = st.slider("Rolling window (sessions)", 10, 252, 63,
                       help="63 sessions is about three months.")  # fmt: skip
    show(line_chart(tf.rolling_volatility(returns, window),
                    f"Annualized volatility over the trailing {window} sessions",
                    "Volatility (per year)", ".0%"))  # fmt: skip
    roll_ret = (1 + returns).rolling(window, min_periods=window).apply(lambda x: x.prod(), raw=True) - 1
    show(line_chart(roll_ret, f"Return over the trailing {window} sessions", "Return", ".0%", 320))
    st.caption("Volatility clusters: calm and turbulent periods persist. This is why a single "
               "long-run volatility number understates risk in a crisis.")  # fmt: skip

with t_corr:
    complete = returns.dropna(how="any")
    if len(complete) < 30 or len(data.tickers) < 2:
        st.info("Correlations need at least two instruments with 30 sessions in common.")
    else:
        show(heatmap(tf.correlation_matrix(returns), 420))
        st.caption(f"Pearson correlation of daily returns, {complete.index[0].date()} to "
                   f"{complete.index[-1].date()} ({len(complete):,} sessions common to all "
                   "instruments). +1 moves together, 0 unrelated, -1 opposite.")  # fmt: skip
        if len(data.tickers) >= 2:
            a, b = st.columns(2)
            first = a.selectbox("Rolling correlation between", data.tickers, 0)
            second = b.selectbox("and", data.tickers, 1)
            roll = returns[first].rolling(126, min_periods=126).corr(returns[second])
            show(line_chart(roll.rename(f"{first} vs {second}"),
                            "Correlation over the trailing 126 sessions", "Correlation", ".1f", 300))
            st.caption("Correlations are not constants: diversification measured in one period "
                       "can weaken in another.")  # fmt: skip

with t_quality:
    quality = pd.DataFrame({
        "First session": data.close.apply(lambda s: s.first_valid_index().date()),
        "Last session": data.close.apply(lambda s: s.last_valid_index().date()),
        "Sessions with a price": data.close.notna().sum(),
        "Calendar sessions missing": data.close.isna().sum(),
        "Largest daily move": returns.abs().max().map("{:.1%}".format),
    })  # fmt: skip
    st.dataframe(quality, width="stretch")
    st.caption("'Calendar sessions missing' counts dates on which another loaded instrument "
               "traded and this one has no price (for example before its launch).")  # fmt: skip
    for note in data.metadata.notes:
        st.write(f"- {note}")
    if data.metadata.source == "yfinance":
        st.caption("Exports of provider data are for your own analysis. Yahoo's terms do not "
                   "grant redistribution rights.")  # fmt: skip
    downloads({"Download closes (CSV)": (csv_bytes(data.close), "adjusted_close.csv"),
               "Download daily returns (CSV)": (csv_bytes(returns), "daily_returns.csv")}, "market")  # fmt: skip
