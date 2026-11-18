"""Shared dashboard helpers. Presentation only: every number comes from quantlab."""

from __future__ import annotations

import html
import os
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:  # lets the app run without `pip install -e .`
    sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from components import theme  # noqa: E402
from quantlab.analytics import DEFINITIONS  # noqa: E402
from quantlab.data import (  # noqa: E402
    DEFAULT_UNIVERSE,
    CachedProvider,
    CalendarError,
    CsvProvider,
    DataError,
    LiveDataStore,
    LoadResult,
    MarketData,
    Outcome,
    SyntheticProvider,
    YFinanceProvider,
    read_ohlcv_csv,
)
from quantlab.data.refresh import fmt_time  # noqa: E402
from quantlab.reporting.format import format_value  # noqa: E402

SNAPSHOT_DIR = ROOT / "experiments" / "data"
LIVE, FROZEN, USER, SYNTH = (
    "Yahoo Finance daily data",
    "Frozen research snapshot",
    "My own CSV files",
    "Synthetic demo data",
)
SOURCE_ALIASES = {"live": LIVE, "snapshot": FROZEN, "upload": USER, "synthetic": SYNTH}
SYNTHETIC_NAMES = ["SYN1", "SYN2", "SYN3", "SYN4", "SYN5"]
TICKER_RE = re.compile(r"^[A-Z0-9.\-=^]{1,12}$")
MAX_TICKERS = 10

LABELS = {
    "n_obs": "Sessions", "total_return": "Total return", "cagr": "CAGR",
    "volatility": "Volatility (ann.)", "sharpe": "Sharpe ratio", "sortino": "Sortino ratio",
    "downside_deviation": "Downside deviation (ann.)", "max_drawdown": "Max drawdown",
    "max_drawdown_duration": "Longest drawdown (sessions)", "calmar": "Calmar ratio",
    "var_95": "1-day VaR 95%", "es_95": "1-day ES 95%", "beta": "Beta vs benchmark",
    "alpha": "Alpha (CAPM, ann.)", "tracking_error": "Tracking error (ann.)",
    "information_ratio": "Information ratio", "turnover": "Turnover (two-sided, per year)",
    "trade_count": "Fills", "win_rate": "Win rate (sell fills)",
}  # fmt: skip
HELP = {
    "CAGR": "Compound annual growth rate: the constant yearly return that produces the same total growth.",
    "Volatility": "Standard deviation of daily returns, scaled to a year (x sqrt 252).",
    "Sharpe": "Average excess return per unit of volatility, annualized. Uses the risk-free rate set in the sidebar.",
    "Max drawdown": "Largest peak-to-trough fall in portfolio value over the period.",
    "ES": "Expected shortfall: the average loss on the worst 5% of days. A positive number is a loss.",
    "VaR": "Value at Risk: the daily loss exceeded on only (1 - confidence) of days in the window.",
}


def header(title: str, subtitle: str) -> None:
    """Page title, shared styling and cross-page widget memory."""
    theme.register_plotly_template()
    st.markdown(theme.CSS, unsafe_allow_html=True)
    # Streamlit drops widget values when a widget is not drawn on the current page.
    # Re-assigning them keeps dataset, strategy and allocation choices across pages.
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith("p_"):
            st.session_state[key] = st.session_state[key]
    st.title(title)
    st.markdown(f'<p class="ql-sub">{subtitle}</p>', unsafe_allow_html=True)


# ----------------------------------------------------------------------------- data


def cache_dir() -> Path:
    """Where verified market data is cached (QA-038).

    ``QUANTLAB_CACHE_DIR`` selects the folder, for example a persistent volume on a host
    whose application directory is read-only or wiped on every deploy. Default:
    ``.data_cache`` inside the repository. The folder must be writable; if it is not, the
    store serves verified data it already has and never contacts the provider.
    """
    configured = os.environ.get("QUANTLAB_CACHE_DIR", "").strip()
    return Path(configured).expanduser() if configured else ROOT / ".data_cache"


@st.cache_resource(show_spinner=False)
def live_store() -> LiveDataStore:
    """One store per server process, so every session shares the verified cache and cooldowns.

    The store decides, from the exchange calendar, when the provider needs to be
    contacted; ordinary reruns are served from memory without any download.
    """
    return LiveDataStore(YFinanceProvider(), cache_dir())


@st.cache_data(show_spinner=False)
def _synthetic(tickers: tuple[str, ...], start: str) -> MarketData:
    return SyntheticProvider(seed=7).fetch(list(tickers), start)


@st.cache_data(show_spinner=False)
def _snapshot(folder: str) -> MarketData:
    path = Path(folder)
    return CachedProvider(YFinanceProvider(), path.parent, float("inf"))._load(path)


def snapshot_folders() -> list[Path]:
    if not SNAPSHOT_DIR.exists():
        return []
    return sorted(p for p in SNAPSHOT_DIR.iterdir() if (p / "metadata.json").exists())


def parse_tickers(raw: str) -> tuple[str, ...]:
    tickers = tuple(dict.fromkeys(t.strip().upper() for t in raw.split(",") if t.strip()))
    if not tickers:
        st.error("Enter at least one ticker, for example `SPY, TLT`.")
        st.stop()
    bad = [t for t in tickers if not TICKER_RE.match(t)]
    if bad:
        st.error(f"Not valid ticker symbols: {', '.join(bad)}. Use letters, digits, `.` or `-`.")
        st.stop()
    if len(tickers) > MAX_TICKERS:
        st.error(f"Please choose at most {MAX_TICKERS} tickers (got {len(tickers)}).")
        st.stop()
    return tickers


def _use_synthetic() -> None:
    st.session_state["p_source"] = SYNTH


def _user_data() -> MarketData:
    with st.sidebar:
        files = st.file_uploader("CSV files, one per instrument", type="csv",
                                 accept_multiple_files=True, key="upload")  # fmt: skip
    if files:
        frames = {}
        for f in files:
            ticker = Path(f.name).stem.upper()
            if not TICKER_RE.match(ticker):  # QA-015: the file name becomes an instrument name
                st.error(f"Could not use `{html.escape(f.name)}`: the file name must be a ticker "
                         "(letters, digits, '.', '-', '=' or '^', up to 12 characters), for example "
                         "SPY.csv. The other files are unaffected.")  # fmt: skip
                continue
            try:
                frames[ticker] = read_ohlcv_csv(f, ticker)
            except DataError as exc:
                # Report the rejected file and carry on with the valid ones; nothing is repaired.
                st.error(f"Could not use `{f.name}`: {exc}. Remove it from the upload list or "
                         "fix the file; the other files are unaffected.")  # fmt: skip
        st.session_state["user_frames"] = frames
    frames = st.session_state.get("user_frames")
    if not frames:
        st.info(
            "**Upload your own daily price data** in the sidebar: one CSV per instrument, named "
            "after its ticker (`SPY.csv`). Required columns: `date, open, high, low, close`; "
            "`volume` is optional; if `adj close` is present, prices are scaled by "
            "adj close / close. Files stay in this browser session and are not stored."
        )
        st.stop()
    return CsvProvider(frames).fetch(list(frames))


def public_demo() -> bool:
    """QUANTLAB_PUBLIC_DEMO=1 on a shared public deployment: visitors cannot write to the server
    or pull third-party market data through it."""
    return os.environ.get("QUANTLAB_PUBLIC_DEMO", "").strip().lower() in ("1", "true", "yes")


def load_data() -> MarketData:
    """Sidebar dataset controls shared by every page. Returns the active dataset or stops."""
    if public_demo():  # Yahoo's terms grant no redistribution: a shared server must not relay it
        sources = [SYNTH, USER]
    else:
        sources = [LIVE] + ([FROZEN] if snapshot_folders() else []) + [USER, SYNTH]
    default = SOURCE_ALIASES.get(os.environ.get("QUANTLAB_DEFAULT_SOURCE", "live"), LIVE)
    if st.session_state.get("p_source") not in sources:
        st.session_state["p_source"] = default if default in sources else sources[0]
    refresh = False
    with st.sidebar:
        st.subheader("Dataset")
        source = st.selectbox("Source", sources, key="p_source",
                              help="Where prices come from. The badge at the top of every page "
                              "always shows which source is active.")  # fmt: skip
        if source == LIVE:
            raw = st.text_input("Tickers (comma separated)", ", ".join(DEFAULT_UNIVERSE),
                                key="p_tick")  # fmt: skip
        elif source == SYNTH:
            # Simulated instruments get invented names so they cannot be mistaken for real ones.
            raw = st.text_input("Simulated instruments (comma separated)", ", ".join(SYNTHETIC_NAMES),
                                key="p_syn_tick", help="Names are labels only: every series is a "
                                "seeded random walk.")  # fmt: skip
        if source in (LIVE, SYNTH):
            start = st.date_input("History start", date(2005, 1, 1), key="p_start",
                                  min_value=date(1990, 1, 1), max_value=date.today())  # fmt: skip
        if source == LIVE:
            refresh = st.button(
                "Refresh market data", key="refresh_live", icon=":material/refresh:",
                width="stretch",
                help="Ask Yahoo Finance now for the latest completed daily data for the selected "
                "tickers and history start. Other cached datasets are not touched.",
            )  # fmt: skip
    result = None
    try:
        if source == LIVE:
            with st.spinner("Checking for the latest completed daily data..."):
                result = live_store().get(list(parse_tickers(raw)), str(start), force=refresh)
            data = result.data
        elif source == SYNTH:
            data = _synthetic(parse_tickers(raw), str(start))
        elif source == FROZEN:
            folders = snapshot_folders()
            with st.sidebar:
                folder = st.selectbox("Snapshot", folders, format_func=lambda p: p.name,
                                      key="p_snap")  # fmt: skip
            data = _snapshot(str(folder))
        else:
            data = _user_data()
    except (DataError, CalendarError) as exc:
        st.error(f"**No usable data.** Data could not be loaded. {exc}")
        st.caption("Nothing is estimated or substituted when data is unavailable. Check the "
                   "ticker symbols, try again in a minute (the provider rate-limits), or explore "
                   "the app with clearly labelled synthetic data.")  # fmt: skip
        st.button("Switch to synthetic demo data", on_click=_use_synthetic)
        st.stop()
    if len(data.dates) < 2:
        st.error("The dataset has fewer than two sessions. Choose an earlier start date.")
        st.stop()
    source_badge(data, source)
    st.session_state["_data_status"] = None if result is None else result.to_dict()
    if result is not None:
        show_data_status(result)
    return data


def show_data_status(result: LoadResult) -> None:
    """What happened on this load and how current the provider's daily data is.

    Shown for the Yahoo source only. Frozen, uploaded and synthetic datasets are
    historical by nature and make no freshness claim. The wording reports what
    actually happened; a click on Refresh is never reported as a success by itself.
    """
    level, text = result.headline()
    if result.outcome is Outcome.UPDATED and level == "ok":
        st.success(text)
    elif level == "warning":
        st.warning(text)
    elif level == "info" or result.outcome in (Outcome.UNCHANGED, Outcome.UPDATED):
        st.info(text)
    else:
        st.caption(f":material/check_circle: {text}")
    report = result.freshness
    with st.expander("Market data status", expanded=not report.is_current):
        attempt = fmt_time(result.last_attempt_at)
        if result.last_attempt_outcome:
            attempt += f" ({result.last_attempt_outcome})"
        rows = {
            "Provider": f"{result.data.metadata.source} (daily history; not a live quote feed)",
            "Latest completed exchange session": f"{report.expected_session.date()} ({report.exchange})",
            "Overall status": report.state.value.replace("_", " "),
            "This view was served from": ("a provider request just now" if result.served_from == "provider"
                                          else "the verified cache"),
            "Last successful retrieval": fmt_time(result.retrieved_at),
            "Last provider request": attempt,
            "Next automatic check": (fmt_time(result.next_check_at) if result.next_check_at is not None
                                     else "when the next session completes"),
        }  # fmt: skip
        if result.last_error:
            rows["Last error"] = result.last_error
        st.table(pd.DataFrame({"": rows}))
        per = pd.DataFrame([i.to_dict() for i in report.instruments]).set_index("ticker")
        per["state"] = per["state"].str.replace("_", " ")
        st.dataframe(per.rename(columns={"last_observation": "Latest available observation",
                                         "state": "Status", "sessions_behind": "Completed sessions missing"}),
                     width="stretch")  # fmt: skip
        for note in result.notes:
            st.caption(f"Note: {note}")
        st.caption("A session counts only after its official close (NYSE calendar, including early "
                   "closes and holidays). Instruments on another calendar can appear behind when "
                   "they are not. Missing sessions are never filled in.")  # fmt: skip


def source_badge(data: MarketData, source: str) -> None:
    meta = data.metadata
    kind, label = {
        LIVE: ("live", "YAHOO DAILY DATA"), FROZEN: ("frozen", "FROZEN RESEARCH SNAPSHOT"),
        USER: ("user", "USER-SUPPLIED DATA"), SYNTH: ("synthetic", "SYNTHETIC DEMO DATA"),
    }[source]  # fmt: skip
    esc = html.escape  # instrument names can come from uploaded file names (QA-015)
    st.markdown(
        f'<span class="ql-badge ql-{kind}">{label}</span><span class="ql-meta">'
        f"{esc(str(meta.source))} &nbsp;|&nbsp; {esc(', '.join(data.tickers))} &nbsp;|&nbsp; "
        f"{esc(str(meta.start))} to {esc(str(meta.end))} &nbsp;|&nbsp; {len(data.dates):,} sessions</span>",
        unsafe_allow_html=True,
    )
    if meta.synthetic:
        st.warning("These prices are **simulated random walks, not market history**. Use them "
                   "to explore the tools. No number on this page describes a real asset.")  # fmt: skip
    with st.sidebar.expander("Data provenance"):
        st.write(f"**Source:** {meta.source}")
        st.write(f"**Retrieved:** {meta.retrieved_at}")
        st.write(f"**Adjustment:** {meta.adjustment}")
        for note in meta.notes:
            st.write(f"- {note}")


# ----------------------------------------------------------------------------- charts


def figure(title: str = "", y_title: str = "", height: int = 380, yfmt: str | None = None,
           x_title: str = "") -> go.Figure:  # fmt: skip
    fig = go.Figure()
    fig.update_layout(title=title, height=height)
    fig.update_xaxes(title_text=x_title)
    fig.update_yaxes(title_text=y_title, tickformat=yfmt)
    return fig


def line_chart(df: pd.DataFrame | pd.Series, title: str = "", y_title: str = "",
               yfmt: str | None = None, height: int = 380) -> go.Figure:  # fmt: skip
    df = df.to_frame() if isinstance(df, pd.Series) else df
    fig = figure(title, y_title, height, yfmt)
    for col in df.columns:
        fig.add_scatter(x=df.index, y=df[col], name=str(col), mode="lines", line=dict(width=1.7))
    return fig


def heatmap(corr: pd.DataFrame, height: int = 380) -> go.Figure:
    fig = figure(height=height)
    fig.add_trace(go.Heatmap(
        z=corr.values, x=list(corr.columns), y=list(corr.index), zmin=-1, zmax=1,
        colorscale=[[0, theme.NEGATIVE], [0.5, theme.SURFACE], [1, theme.ACCENT]],
        text=corr.round(2).values, texttemplate="%{text}", colorbar=dict(title="corr", thickness=12),
    ))  # fmt: skip
    fig.update_layout(hovermode="closest", margin=dict(t=20))
    return fig


def show(fig: go.Figure) -> None:
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})


# ----------------------------------------------------------------------------- numbers


def fmt_stat(key: str, value) -> str:
    return format_value(key, value)


def stats_table(stats: dict[str, dict[str, float]]) -> pd.DataFrame:
    """Format {column name: summary dict} as a display table."""
    keys = list(next(iter(stats.values())))
    return pd.DataFrame(
        {name: [fmt_stat(k, s.get(k)) for k in keys] for name, s in stats.items()},
        index=[LABELS.get(k, k) for k in keys],
    )


def definitions_expander() -> None:
    with st.expander("How each statistic is calculated"):
        st.caption("Simple daily returns, 252 sessions per year, sample standard deviation "
                   "(ddof = 1). Anything undefined (for example a ratio with zero variance) is "
                   "shown as n/a rather than a number.")  # fmt: skip
        for key, text in DEFINITIONS.items():
            st.markdown(f"**{LABELS.get(key, key.replace('_', ' ').title())}**  \n`{text}`")


def assumptions_expander(expanded: bool = False) -> None:
    with st.expander("Assumptions behind every backtest", expanded=expanded):
        st.markdown(
            """
| Topic | What the engine does |
|---|---|
| **Signal timing** | A decision uses data up to the close of day T and trades at the **open of day T+1**. It can never trade at a price it has already seen. |
| **Slippage** | Buys fill above the open and sells below it by the stated basis points (1 bp = 0.01%). |
| **Fees** | A percentage of traded value, in basis points, charged on every fill. |
| **Prices** | Split- and dividend-adjusted. Returns include reinvested dividends; price levels are not the quotes that traded on the day. |
| **Returns** | Simple daily returns of portfolio value, compounded. Annualized with 252 sessions. |
| **Constraints** | Long-only. No leverage, no shorting. Cash earns no interest. |
| **Missing prices** | No trade happens on a day without a price; the order waits. |
| **What it is not** | A forecast, or evidence that a strategy will work. The instruments were chosen with hindsight (survivorship and selection bias). |
"""
        )


def downloads(files: dict[str, tuple[bytes, str]], key: str) -> None:
    """A row of download buttons: {button label: (content, file name)}."""
    cols = st.columns(len(files))
    for i, (col, (label, (content, name))) in enumerate(zip(cols, files.items(), strict=True)):
        mime = {"csv": "text/csv", "json": "application/json", "html": "text/html",
                "md": "text/markdown", "zip": "application/zip"}[name.rsplit(".", 1)[-1]]  # fmt: skip
        col.download_button(label, content, name, mime, key=f"dl_{key}_{i}", width="stretch",
                            on_click="ignore")  # no rerun: keeps the current tab open
