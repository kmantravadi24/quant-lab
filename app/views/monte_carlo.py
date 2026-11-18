import hashlib
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import streamlit as st
from components import theme
from components.common import downloads, figure, header, load_data, show
from components.portfolio import model_badge, portfolio_input

from quantlab.portfolio.compare import data_fingerprint
from quantlab.reporting import csv_bytes, json_bytes
from quantlab.reporting.experiment import environment
from quantlab.reporting.format import format_value
from quantlab.risk import holding_returns, portfolio_returns
from quantlab.simulations import lookback_windows, sensitivity, simulate, wilson_interval

METHODS = {"iid": "Independent days", "stationary": "Random-length blocks", "block": "Fixed-length blocks"}


def pct_with_interval(p: float, n: int) -> tuple[str, str]:
    low, high = wilson_interval(p, n)
    return format_value("prob_loss", p, digits=1), f"{low:.1%}–{high:.1%} (95%)"


header("Monte Carlo", "The spread of outcomes a resampling model of history implies. Not a forecast.")
data = load_data()
chosen = portfolio_input(data.tickers)
weights = chosen.weights
if chosen.held.empty:
    st.info("The portfolio is 100% cash, so every simulated path is flat. Enter a weight above.")
    st.stop()
returns = holding_returns(data.close, weights)  # only held instruments limit the history (QA-010)
if len(returns) < 60:
    st.error(f"Only {len(returns)} sessions are common to the instruments this portfolio holds; "
             "at least 60 are needed to resample from.")  # fmt: skip
    st.stop()

c = st.columns(6)
initial = c[0].number_input("Initial value", 1_000.0, 1e9, 100_000.0, 1_000.0, key="p_value")
horizon = c[1].number_input("Horizon (sessions)", 5, 2520, 252, help="252 sessions is about one year.")
n_paths = c[2].number_input("Simulated paths", 100, 20_000, 1_000, 100,
                            help="More paths shrink the random noise in each percentage below. "
                            "They do nothing about whether the model is right.")  # fmt: skip
max_years = max(1, len(returns) // 252)
years = c[3].number_input("History sampled (years)", 1, max_years, min(10, max_years),
                          help="Days are drawn from this many most recent years. This choice usually "
                          "moves the answer more than anything else on the page.")  # fmt: skip
method = c[4].selectbox("Resampling", list(METHODS), format_func=METHODS.get)
seed = c[5].number_input("Random seed", 0, 2**31 - 1, 42,
                         help="The same seed and inputs always reproduce exactly the same paths.")  # fmt: skip
block = st.slider("Average block length (sessions)", 2, 126, 21) if method != "iid" else 1
MAX_CELLS = 5_000_000  # paths x sessions; about 120 MB of working memory
if n_paths * horizon > MAX_CELLS:
    st.error(f"{int(n_paths):,} paths over {int(horizon):,} sessions is {int(n_paths * horizon):,} "
             f"simulated values, above this app's limit of {MAX_CELLS:,}. Reduce the number of "
             "paths or the horizon. (The Python API has no such limit.)")  # fmt: skip
    st.stop()

full = portfolio_returns(returns, chosen.held)
sample = full.iloc[-int(years) * 252 :]
with st.spinner(f"Simulating {int(n_paths):,} paths..."):
    res = simulate(sample, int(horizon), int(n_paths), initial, method, block, int(seed))
s = res.summary()
p_dd = res.prob_drawdown_worse_than(-0.20)
digest = hashlib.sha256(res.paths.tobytes()).hexdigest()[:12]

model_badge(f"Resampling {res.n_sample:,} daily returns from {res.sample_start} to {res.sample_end}; "
            "a lump sum, no contributions.")  # fmt: skip
loss, loss_range = pct_with_interval(s["prob_loss"], int(n_paths))
fall, fall_range = pct_with_interval(p_dd, int(n_paths))
k = st.columns(5)
k[0].metric("Median outcome", format_value("median_terminal", s["median_terminal"]))
k[1].metric("5th to 95th percentile", f"{s['p5_terminal'] / 1000:,.0f}k to {s['p95_terminal'] / 1000:,.0f}k",
            help=f"{s['p5_terminal']:,.0f} to {s['p95_terminal']:,.0f}. Nine in ten simulated paths end in this range.")  # fmt: skip
k[2].metric("Paths ending below start", loss, loss_range, delta_color="off", delta_arrow="off",
            help="The range below (95% Wilson interval) is sampling noise from using a finite "
            "number of paths only. "
            "It says nothing about whether the model resembles the future.")  # fmt: skip
k[3].metric("Median max drawdown", format_value("median_max_drawdown", s["median_max_drawdown"], digits=1))
k[4].metric("Paths falling 20% or more", fall, fall_range, delta_color="off", delta_arrow="off",
            help="Share of paths whose worst peak-to-trough fall exceeded 20%. The range below is its "
            "95% sampling interval (path-count noise only).")  # fmt: skip
st.caption(f"Run fingerprint `{digest}` (seed {seed}). Re-running with the same inputs gives the "
           "same fingerprint. The small grey ranges are path-count noise; the next section shows the "
           "much larger effect of the modelling choices.")  # fmt: skip

st.info("**Not a forecast.** These percentages are properties of a model that reshuffles "
        f"{res.n_sample:,} past days ({res.sample_start} to {res.sample_end}); they are not "
        "probabilities about the real future. See the model-dependence tab before relying on any "
        "of them.")  # fmt: skip

t_paths, t_sens, t_about, t_export = st.tabs(["Paths", "How much the answer depends on the model", "Assumptions", "Export"])
with t_paths:
    bands = res.percentile_bands()
    x = np.arange(len(bands))
    fan = figure("Simulated portfolio value: percentile bands and a sample of individual paths",
                 "Portfolio value", 440, x_title="Sessions ahead")  # fmt: skip
    for path in res.paths[: min(30, len(res.paths))]:
        fan.add_scatter(x=x, y=path, mode="lines", line=dict(width=0.5, color="rgba(139,149,167,0.28)"),
                        showlegend=False, hoverinfo="skip")  # fmt: skip
    fan.add_scatter(x=x, y=bands["p95"], line=dict(width=0), showlegend=False, hoverinfo="skip")
    fan.add_scatter(x=x, y=bands["p5"], fill="tonexty", fillcolor="rgba(91,141,239,0.14)",
                    line=dict(width=0), name="5th to 95th percentile")  # fmt: skip
    fan.add_scatter(x=x, y=bands["p75"], line=dict(width=0), showlegend=False, hoverinfo="skip")
    fan.add_scatter(x=x, y=bands["p25"], fill="tonexty", fillcolor="rgba(91,141,239,0.28)",
                    line=dict(width=0), name="25th to 75th percentile")  # fmt: skip
    fan.add_scatter(x=x, y=bands["p50"], line=dict(color=theme.ACCENT, width=2.2), name="Median")
    show(fan)
    left, right = st.columns(2)
    hist = figure("Where the paths end", "Number of paths", 320, x_title="Final portfolio value")
    hist.add_histogram(x=res.terminal, nbinsx=60, name="Paths", marker_color=theme.ACCENT)
    hist.add_vline(x=initial, line_dash="dash", line_color=theme.BENCH, annotation_text="start")
    hist.update_layout(hovermode="x")
    left.plotly_chart(hist, width="stretch", config={"displaylogo": False})
    dd = figure("Worst fall along each path", "Number of paths", 320, x_title="Maximum drawdown")
    dd.add_histogram(x=res.max_drawdowns(), nbinsx=60, name="Paths", marker_color=theme.NEGATIVE)
    dd.update_xaxes(tickformat=".0%")
    dd.update_layout(hovermode="x")
    right.plotly_chart(dd, width="stretch", config={"displaylogo": False})

with t_sens:
    st.markdown("The same question, asked with different history and different resampling, at the "
                "same horizon, path count and seed. **Path-count noise is the small range inside each "
                "cell; the differences between rows are model risk, and more paths do not reduce "
                "them.**")  # fmt: skip
    looks = lookback_windows(len(full))
    table = sensitivity(full, int(horizon), int(min(n_paths, 2000)), initial, int(seed), -0.20, looks,
                        (("iid", 1), ("block", block if method == "block" else 21),
                         ("stationary", block if method == "stationary" else 21)))  # fmt: skip
    shown = pd.DataFrame({
        "History sampled": table["lookback"] + " (" + table["sample_start"] + " to " + table["sample_end"] + ")",
        "Resampling": table["method"].map(METHODS),
        "Paths ending below start": [f"{p:.1%} ({lo:.1%} to {hi:.1%})" for p, lo, hi in
                                     zip(table["prob_loss"], table["prob_loss_low"], table["prob_loss_high"], strict=True)],
        "Paths falling 20% or more": [f"{p:.1%} ({lo:.1%} to {hi:.1%})" for p, lo, hi in
                                      zip(table["prob_drawdown"], table["prob_drawdown_low"], table["prob_drawdown_high"], strict=True)],
        "Median outcome": table["median_terminal"].map(lambda v: format_value("median_terminal", v)),
    })  # fmt: skip
    st.dataframe(shown, width="stretch", hide_index=True)
    spread = table["prob_drawdown"].max() - table["prob_drawdown"].min()
    st.markdown(f"**Reading this:** across these choices the chance of a 20% fall ranges from "
                f"{table['prob_drawdown'].min():.1%} to {table['prob_drawdown'].max():.1%} "
                f"(a spread of {spread:.1%} points), against a sampling range of about "
                f"±{1.96 * (p_dd * (1 - p_dd) / n_paths) ** 0.5:.1%} for the run above. "
                "Which history you treat as representative matters more than how many paths you "
                "draw. None of these rows is the 'right' one.")  # fmt: skip
    st.caption(f"Each row uses {int(min(n_paths, 2000)):,} paths (capped to keep the page quick); "
               "ranges in brackets are 95% Wilson intervals for path-count noise.")  # fmt: skip

with t_about:
    st.markdown(
        f"**What this is, and is not.** Each path strings together {horizon} daily returns drawn from "
        f"the {res.n_sample:,} this portfolio's target weights would have produced between "
        f"{res.sample_start} and {res.sample_end}. The percentages are properties of that model, not "
        "probabilities about the real future.\n\n"
        "- **Independent days** keeps the real size of bad days but shuffles away the fact that bad "
        "days cluster. Whether that makes simulated drawdowns milder or harsher depends on the "
        "history sampled.\n"
        "- **Block methods** keep runs of consecutive days together, restoring some clustering, but "
        "cannot invent a regime the sampled years never contained.\n"
        "- **Every method assumes the future resembles the sampled window.** A calm window produces "
        "calm simulations; a window containing a crash puts that crash in many paths.\n"
        "- **Fixed weights, lump sum.** The portfolio is held at its target weights each day; no "
        "contributions, withdrawals, trading costs or taxes; cash earns 0%. For a funded plan with "
        "contributions, the Investment Lab's historical simulation is the relevant tool.\n"
        "- **Sampling range** next to a percentage covers only the randomness of a finite number of "
        "paths."
    )

with t_export:
    lo_l, hi_l = wilson_interval(s["prob_loss"], int(n_paths))
    lo_d, hi_d = wilson_interval(p_dd, int(n_paths))
    summary = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "portfolio": chosen.describe(),
        **s, "prob_drawdown_worse_than_20pct": p_dd,
        "sampling_intervals_95": {"prob_loss": [lo_l, hi_l], "prob_drawdown_worse_than_20pct": [lo_d, hi_d],
                                  "method": "Wilson score, path-count noise only"},
        "settings": {"initial_value": initial, "horizon": int(horizon), "paths": int(n_paths),
                     "method": method, "block": block, "seed": int(seed),
                     "sample": [res.sample_start, res.sample_end, res.n_sample]},
        "model": "fixed-weight resampling of historical daily returns; lump sum; not a forecast",
        "run_fingerprint": digest,
        "data": {**data.metadata.to_dict(), "fingerprint": data_fingerprint(data)},
        "environment": environment(),
    }  # fmt: skip
    downloads({"Simulation summary (JSON)": (json_bytes(summary), "monte_carlo_summary.json"),
               "Percentile bands (CSV)": (csv_bytes(res.percentile_bands(), "session"), "percentile_bands.csv"),
               "Model sensitivity (CSV)": (csv_bytes(table, None), "monte_carlo_sensitivity.csv")}, "mc")  # fmt: skip
