import json

import streamlit as st
from components.common import ROOT, header, line_chart, load_data, show

from quantlab.analytics import performance_summary
from quantlab.data.transforms import normalize, simple_returns

header("Quant Lab", "Systematic Research. Measurable Risk. Reproducible Results.")
data = load_data()

st.markdown(
    "A research environment for testing systematic investment ideas **honestly**: signals are "
    "computed from past data only, trades fill the next day and pay costs, and every result "
    "comes with its uncertainty and its limitations."
)

k = st.columns(4)
k[0].metric("Instruments", len(data.tickers))
k[1].metric("Sessions", f"{len(data.dates):,}")
k[2].metric("First session", data.metadata.start)
k[3].metric("Last session", data.metadata.end)

st.subheader("Selected instruments")
show(line_chart(normalize(data.close), "Growth of 100 invested at each instrument's first date",
                "Value (start = 100)"))  # fmt: skip
returns = simple_returns(data.close)
common = returns.dropna(how="any")
use_common = len(common) >= 30
sample = common if use_common else returns
rows = {t: performance_summary(sample[t]) for t in data.tickers}
st.dataframe(
    {
        "CAGR": {t: f"{r['cagr']:.2%}" for t, r in rows.items()},
        "Volatility (ann.)": {t: f"{r['volatility']:.2%}" for t, r in rows.items()},
        "Sharpe (rf = 0)": {t: f"{r['sharpe']:.2f}" for t, r in rows.items()},
        "Max drawdown": {t: f"{r['max_drawdown']:.2%}" for t, r in rows.items()},
        "Sessions": {t: f"{r['n_obs']:,.0f}" for t, r in rows.items()},
    },
    width="stretch",
)
if use_common:
    st.caption(f"All instruments measured over the same {len(common):,} sessions "
               f"({common.index[0].date()} to {common.index[-1].date()}), so rows are comparable. "
               "Buy-and-hold figures from adjusted prices, before any trading costs.")  # fmt: skip
else:
    st.caption("The instruments share too little history: each row uses that instrument's own "
               "dates, so rows are not directly comparable.")  # fmt: skip

st.subheader("Research workflow")
steps = [
    ("views/invest.py", "Investment Lab", "Build, fund and compare hypothetical portfolios."),
    ("views/market.py", "Market Explorer", "Inspect prices, volatility and correlations."),
    ("views/strategy.py", "Strategy Lab", "See exactly when a rule is in or out of the market."),
    ("views/backtest.py", "Backtesting", "Simulate the rule with next-day fills and costs."),
    ("views/risk.py", "Risk Analytics", "Volatility, VaR, expected shortfall, risk contributions."),
    ("views/monte_carlo.py", "Monte Carlo", "The range of outcomes a resampling model implies."),
    ("views/stress.py", "Stress Test", "Hypothetical shocks to individual holdings."),
    ("views/research.py", "Research & Reporting", "The published study and how to reproduce it."),
]
for row in (steps[:4], steps[4:8]):
    cols = st.columns(4)
    for col, (path, title, text) in zip(cols, row, strict=False):
        with col:
            st.markdown(f'<div class="ql-card"><b>{title}</b><br><span>{text}</span></div>',
                        unsafe_allow_html=True)  # fmt: skip
            if st.session_state.get("_router"):
                st.page_link(path, label=f"Open {title}", icon=":material/arrow_forward:")

st.subheader("Latest recorded experiment")
records = sorted(
    # Only the trend study's records: other result files (e.g. forecast validation) differ in form.
    (p for p in (ROOT / "experiments" / "results").glob("trend_vs_buyhold_*.json") if "SYNTHETIC" not in p.name),
    key=lambda p: json.loads(p.read_text())["run_at"],
)
if not records:
    st.info("No experiment is recorded in this copy. Run `python experiments/trend_vs_buyhold.py` "
            "on data you are licensed to use.")
else:
    rec = json.loads(records[-1].read_text())
    spy = rec["results"]["assets"][rec["config"]["primary_asset"]]
    oos = {(r.get("name") or r.get("index")): r for r in spy["out_of_sample"]}
    trend, bench = oos["trend_50_200"], oos["buy_and_hold"]
    st.markdown(f"**{rec['config']['question']}**")
    c = st.columns(4)
    c[0].metric("Trend CAGR", f"{trend['cagr']:.2%}", f"{trend['cagr'] - bench['cagr']:+.2%} vs buy and hold", delta_color="off", delta_arrow="off")
    c[1].metric("Buy-and-hold CAGR", f"{bench['cagr']:.2%}")
    c[2].metric("Max drawdown, trend", f"{trend['max_drawdown']:.2%}")
    c[3].metric("Max drawdown, buy and hold", f"{bench['max_drawdown']:.2%}")
    test = spy["split"]["test"]
    st.caption(
        f"{rec['config']['primary_asset']}, evaluation period {test[0]} to {test[1]}, run "
        f"{rec['run_at'][:10]} on a frozen dataset (fingerprint `{rec['results']['data_fingerprint_close']}`, "
        f"code `{(rec['environment']['git_commit'] or '')[:7]}`). A historical result on a period "
        "that has since been re-examined: it is not a fresh out-of-sample confirmation, and not a "
        "forecast. Details on the Research & Reporting page."
    )
