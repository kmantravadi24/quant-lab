"""Quant Lab dashboard entry point:  streamlit run app/main.py"""

import sys
from pathlib import Path

import streamlit as st

APP = Path(__file__).resolve().parent
for path in (APP, APP.parent / "src"):  # works with or without `pip install -e .`
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

st.set_page_config(page_title="Quant Lab", page_icon=":material/monitoring:", layout="wide")
st.logo(str(APP / "assets" / "logo.svg"), size="large")
st.session_state["_router"] = True

# Page files live in "views", not "pages": Streamlit treats a folder called "pages" as its
# own multipage app and would serve direct links to it without running this entry point.
page = st.navigation(
    {
        "Invest": [
            st.Page("views/overview.py", title="Overview", icon=":material/home:", default=True),
            st.Page("views/invest.py", title="Investment Lab", icon=":material/pie_chart:"),
        ],
        "Research": [
            st.Page("views/market.py", title="Market Explorer", icon=":material/candlestick_chart:"),
            st.Page("views/strategy.py", title="Strategy Lab", icon=":material/science:"),
            st.Page("views/backtest.py", title="Backtesting", icon=":material/timeline:"),
        ],
        "Risk": [
            st.Page("views/risk.py", title="Risk Analytics", icon=":material/shield:"),
            st.Page("views/monte_carlo.py", title="Monte Carlo", icon=":material/casino:"),
            st.Page("views/stress.py", title="Stress Test", icon=":material/warning:"),
        ],
        "Reporting": [
            st.Page("views/research.py", title="Research & Reporting", icon=":material/description:"),
        ],
    }
)
page.run()
