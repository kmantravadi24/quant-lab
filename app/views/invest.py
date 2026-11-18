import json

import pandas as pd
import streamlit as st
from components import theme
from components.common import (
    assumptions_expander,
    downloads,
    figure,
    header,
    line_chart,
    load_data,
    show,
)
from components.portfolio import publish_lab_portfolios

from quantlab.data import DataError
from quantlab.execution import ExecutionConfig
from quantlab.portfolio.compare import (
    allocation_drift,
    analysis_record,
    benchmark_specs,
    compare_portfolios,
    data_fingerprint,
    load_portfolio_file,
    portfolio_file,
    reproduction_status,
)
from quantlab.portfolio.spec import PortfolioSpec
from quantlab.reporting import csv_bytes, json_bytes
from quantlab.reporting.bundle import can_bundle, price_bundle
from quantlab.reporting.format import KINDS, format_value, label
from quantlab.reporting.investment_report import investment_report
from quantlab.risk import estimate_risk, holding_returns

SLOTS = ("A", "B", "C")
# "never" rather than None: a None option makes Streamlit show an empty "Choose an option" box.
REBALANCE = {"never": "Never", "M": "Monthly", "Q": "Quarterly", "A": "Annually"}
FREQUENCY = {"M": "Monthly", "W": "Weekly", "Q": "Quarterly"}
ROWS = {
    "final_value": "Final value", "total_invested": "Total paid in", "gain": "Gain",
    "time_weighted_annual": "Time-weighted return (annual)",
    "money_weighted_annual": "Money-weighted return (annual)",
    "volatility": "Volatility (annual)", "sharpe": "Sharpe ratio",
    "max_drawdown": "Max drawdown", "max_drawdown_duration": "Longest drawdown (sessions)",
    "es_95": "1-day expected shortfall 95%", "worst_day": "Worst day",
    "trading_cost": "Trading cost paid", "turnover": "Turnover (per year)",
    "drift_average": "Average drift from target", "drift_max": "Largest drift from target",
}  # fmt: skip
EXC_TIMING = ("If an order decided at the previous close (for example a rebalance) fills at the "
              "deposit's own open, the deposit is included in that order and invested that day.")
TWR_HELP = ("How the holdings performed, with the effect of when money was added removed. "
            "Use this to compare allocations.")  # fmt: skip
MWR_HELP = ("The annual rate your money actually earned given when each contribution went in. "
            "It depends on timing as well as on the allocation.")  # fmt: skip


def fmt(key: str, value) -> str:
    """The shared formatter: units by statistic, n/a when undefined, no negative zero."""
    return format_value(key, value)


def default_weights(slot: str, tickers: list[str]) -> dict[str, float]:
    n = len(tickers)
    if slot == "A":
        mix = [60.0, 40.0] if n >= 2 else [100.0]
    elif slot == "B":
        mix = [round(100.0 / n, 1)] * n
    else:
        mix = [80.0]
    return {t: (mix[i] if i < len(mix) else 0.0) for i, t in enumerate(tickers)}


def apply_saved_file(payload: dict, tickers: list[str]) -> list[str]:
    """Copy a saved portfolio file into the page's controls. Returns notes for the user."""
    specs, cfg, risk_free = load_portfolio_file(payload)
    notes = []
    for slot, (name, spec) in zip(SLOTS, specs.items(), strict=False):
        st.session_state[f"p_il_on_{slot}"] = True
        st.session_state[f"p_il_name_{slot}"] = name
        st.session_state[f"p_il_reb_{slot}"] = spec.rebalance or "never"
        for t in tickers:
            st.session_state[f"p_il_w_{slot}_{t}"] = round(100.0 * spec.weights.get(t, 0.0), 4)
        absent = [t for t, w in spec.weights.items() if w > 0 and t not in tickers]
        if absent:
            notes.append(f"{name}: {', '.join(absent)} is not in the loaded dataset and was left out.")
    for slot in SLOTS[len(specs):]:
        st.session_state[f"p_il_on_{slot}"] = False
    first = next(iter(specs.values()))
    st.session_state.update({
        "p_il_initial": float(first.initial_amount), "p_il_contrib": float(first.contribution),
        "p_il_freq": first.contribution_frequency, "p_il_slip": float(cfg.slippage_bps),
        "p_il_fee": float(cfg.fee_bps), "p_il_rf": 100.0 * risk_free,
    })  # fmt: skip
    return notes


@st.cache_data(show_spinner=False, max_entries=32)
def run_comparison(_data, fingerprint: str, specs_json: str, cfg_json: str, risk_free: float):
    specs = {n: PortfolioSpec.from_dict(b) for n, b in json.loads(specs_json).items()}
    return compare_portfolios(_data, specs, ExecutionConfig(**json.loads(cfg_json)), risk_free)


header("Investment Lab", "Build a hypothetical portfolio, fund it, and see what that choice has meant.")
data = load_data()
tickers = data.tickers

st.session_state.setdefault("p_il_mode", "Historical comparison")
mode = st.segmented_control("View", ["Historical comparison", "Future wealth"], key="p_il_mode",
                            label_visibility="collapsed",
                            help="Historical comparison: what portfolios did. Future wealth: a plan "
                            "projected forward under stated models.")  # fmt: skip
if mode == "Future wealth":
    from components.future_wealth import render as render_future

    render_future(data)
    st.stop()

# ----------------------------------------------------------------- load a saved file
with st.expander("Load a saved portfolio file"):
    upload = st.file_uploader("Quant Lab portfolio file (.json)", type="json", key="il_upload")
    if st.button("Load into the builder", disabled=upload is None):
        try:
            payload = json.loads(upload.getvalue().decode("utf-8"))
            notes = apply_saved_file(payload, tickers)
        except (ValueError, UnicodeDecodeError) as exc:
            st.error(f"This file could not be loaded: {exc}")
        else:
            st.session_state["_il_loaded"] = {"payload": payload, "notes": notes}
            st.rerun()

# ----------------------------------------------------------------- funding and costs
st.subheader("1. Funding and costs")
f = st.columns(6)
initial = f[0].number_input("Initial amount", 100.0, 1e9, 10_000.0, 1_000.0, key="p_il_initial")
contribution = f[1].number_input("Recurring contribution", 0.0, 1e7, 500.0, 100.0, key="p_il_contrib",
                                 help="Added to cash at the open of the first session of each period "
                                 "and normally invested at the following session's open (sooner "
                                 "if an earlier-decided order fills that open; see Assumptions).")  # fmt: skip
frequency = f[2].selectbox("Contribution every", list(FREQUENCY), format_func=FREQUENCY.get, key="p_il_freq")
slippage = f[3].number_input("Slippage (bps)", 0.0, 100.0, 2.0, 0.5, key="p_il_slip",
                             help="How much worse than the opening price each trade fills. 1 bp = 0.01%.")  # fmt: skip
fee = f[4].number_input("Fee (bps)", 0.0, 100.0, 1.0, 0.5, key="p_il_fee",
                        help="Commission as a share of each trade's value.")  # fmt: skip
risk_free = f[5].number_input("Risk-free rate (%)", 0.0, 20.0, 0.0, 0.25, key="p_il_rf",
                              help="Used in the Sharpe ratio only. Cash in the portfolio earns nothing.") / 100  # fmt: skip

# ----------------------------------------------------------------- portfolio builder
st.subheader("2. Portfolios")
st.caption("Target weights in percent. Whatever is left below 100% is held as cash. The same "
           "funding and costs apply to every portfolio, so the comparison is like for like.")  # fmt: skip
cols = st.columns([1.1, 1, 1, 1])
cols[0].markdown("&nbsp;")
enabled, names = {}, {}
for col, slot in zip(cols[1:], SLOTS, strict=True):
    default_on = slot == "A" or (slot == "B" and len(tickers) >= 2)
    if slot == "A":
        enabled[slot] = True
        col.markdown('<div style="height:2.5rem;display:flex;align-items:center"><b>Your portfolio</b></div>',
                     unsafe_allow_html=True)  # fmt: skip
    else:
        enabled[slot] = col.toggle(f"Compare portfolio {slot}", default_on, key=f"p_il_on_{slot}")
    names[slot] = col.text_input("Name", f"Portfolio {slot}", key=f"p_il_name_{slot}", max_chars=30,
                                 disabled=not enabled[slot], label_visibility="collapsed")  # fmt: skip
weights = {slot: {} for slot in SLOTS}
for t in tickers:
    row = st.columns([1.1, 1, 1, 1])
    row[0].markdown(f"**{t}**")
    for col, slot in zip(row[1:], SLOTS, strict=True):
        weights[slot][t] = col.number_input(f"{t} in {slot} (%)", 0.0, 100.0, default_weights(slot, tickers)[t], 5.0,
                                            key=f"p_il_w_{slot}_{t}", disabled=not enabled[slot],
                                            label_visibility="collapsed")  # fmt: skip
row = st.columns([1.1, 1, 1, 1])
row[0].markdown("**Cash (remainder)**")
problems = []
for col, slot in zip(row[1:], SLOTS, strict=True):
    total = sum(weights[slot].values())
    if not enabled[slot]:
        col.caption("not compared")
    elif total > 100 + 1e-6:
        col.markdown(f":red[over by {total - 100:.1f}%]")
        problems.append(f"**{names[slot]}** adds up to {total:.1f}%. Leverage is not supported: "
                        "reduce the weights to 100% or less.")  # fmt: skip
    else:
        col.markdown(f"{100 - total:.1f}%")
row = st.columns([1.1, 1, 1, 1])
row[0].markdown("**Rebalance to target**")
rebalance = {}
for col, slot in zip(row[1:], SLOTS, strict=True):
    rebalance[slot] = col.selectbox(f"Rebalance {slot}", list(REBALANCE), format_func=REBALANCE.get,
                                    index=3 if slot == "A" else 0, key=f"p_il_reb_{slot}",
                                    disabled=not enabled[slot], label_visibility="collapsed")  # fmt: skip
active = [s for s in SLOTS if enabled[s]]
if len({names[s].strip() for s in active}) < len(active) or any(not names[s].strip() for s in active):
    problems.append("Give each compared portfolio a different, non-empty name.")
for message in problems:
    st.error(message)
if problems:
    st.stop()

specs = {}
for slot in active:
    held = {t: w / 100 for t, w in weights[slot].items() if w > 0}
    if held:
        policy = None if rebalance[slot] == "never" else rebalance[slot]
        specs[names[slot].strip()] = PortfolioSpec(held, initial, contribution, frequency, policy,
                                                   names[slot].strip())  # fmt: skip
primary_name = names["A"].strip()
if primary_name not in specs:
    st.info(f"**{primary_name}** is 100% cash. Give at least one instrument a weight to analyse it.")
    st.stop()
primary = specs[primary_name]
publish_lab_portfolios(specs)  # the Risk, Monte Carlo and Stress pages can analyse these (QA-026)
candidates = {n: s for n, s in benchmark_specs(primary, universe=tickers).items() if n not in specs}
chosen = st.multiselect("Simple benchmarks, funded the same way", list(candidates), list(candidates),
                        key=f"il_bench_{'_'.join(candidates)}",
                        help="Simple alternatives to judge the portfolio against. They use the same "
                        "money, dates and costs. An alternative that would behave exactly like your "
                        "portfolio (for example rebalancing a single holding) is not offered.")  # fmt: skip
if not candidates:
    st.caption("No distinct benchmark is available: every simple alternative would be identical to "
               f"{primary_name}. Load another instrument in the sidebar to compare against it.")  # fmt: skip
all_specs = {**specs, **{n: candidates[n] for n in chosen}}
cfg = ExecutionConfig(initial_capital=initial, slippage_bps=slippage, fee_bps=fee)

try:
    with st.spinner("Simulating every portfolio through the transaction engine..."):
        comparison = run_comparison(
            data, data_fingerprint(data),
            json.dumps({n: s.to_dict() for n, s in all_specs.items()}),  # order kept: yours first
            json.dumps(cfg.__dict__, sort_keys=True), risk_free,
        )  # fmt: skip
except DataError as exc:
    st.error(f"These portfolios cannot be compared on this dataset: {exc}. Load more history or "
             "remove the instrument with the shortest record.")  # fmt: skip
    st.stop()

# ----------------------------------------------------------------- results
start, end = comparison.window
stats, result = comparison.stats[primary_name], comparison.results[primary_name]
loaded = st.session_state.get("_il_loaded")
if loaded:
    same, message = reproduction_status(loaded["payload"], comparison.fingerprint)
    (st.success if same else st.warning)(f"Loaded portfolio file. {message}")
    for note in loaded["notes"]:
        st.caption(f"Note: {note}")

st.subheader(f"3. What {primary_name} did")
st.markdown(
    f'<span class="ql-badge ql-user">HISTORICAL SIMULATION</span><span class="ql-meta">'
    f"{start.date()} to {end.date()} &nbsp;|&nbsp; {len(comparison.data.dates):,} sessions &nbsp;|&nbsp; "
    f"the period in which every selected instrument has prices &nbsp;|&nbsp; all portfolios use this "
    f"same window, calendar and costs</span>",
    unsafe_allow_html=True,
)
k = st.columns(6)
k[0].metric("Final value", fmt("final_value", stats["final_value"]))
k[1].metric("Total paid in", fmt("total_invested", stats["total_invested"]),
            help="Initial amount plus every contribution.")  # fmt: skip
k[2].metric("Gain", fmt("gain", stats["gain"]), help="Final value minus everything paid in, after costs.")
k[3].metric("Time-weighted p.a.", fmt("time_weighted_annual", stats["time_weighted_annual"]), help=TWR_HELP)
k[4].metric("Money-weighted p.a.", fmt("money_weighted_annual", stats["money_weighted_annual"]), help=MWR_HELP)
k[5].metric("Max drawdown", fmt("max_drawdown", stats["max_drawdown"]),
            help="Largest peak-to-trough fall of the holdings, with contributions removed.")  # fmt: skip
if stats["money_weighted_status"] != "ok":
    st.caption(f"Money-weighted return is not defined here ({stats['money_weighted_status'].replace('_', ' ')}).")
elif stats["span_days"] < 365:
    st.caption(f"The window is {stats['span_days']} days: annual rates are extrapolations. Over the "
               f"window itself the money-weighted return was {stats['money_weighted_period']:.2%}.")  # fmt: skip
st.caption("What happened in the past, simulated on adjusted prices (a total-return proxy, not "
           "prices anyone could have traded at). It is not a forecast: a portfolio that led in this "
           "window need not lead in the next.")  # fmt: skip

risk_estimates: dict[str, dict] = {}  # filled in the Risk insights tab, reused by the report
t_growth, t_compare, t_dd, t_risk, t_cost, t_assume, t_export = st.tabs(
    ["Growth", "Compare", "Drawdown & drift", "Risk insights", "Costs & timeline", "Assumptions", "Save & export"]
)

with t_growth:
    view = st.radio("Show", ["Portfolio value (includes money paid in)", "Growth of 1 (time-weighted)"],
                    horizontal=True, label_visibility="collapsed")  # fmt: skip
    if view.startswith("Portfolio value"):
        fig = line_chart(comparison.values(), "Portfolio value at each close", "Value", height=430)
        paid = comparison.contributed()
        fig.add_scatter(x=paid.index, y=paid, name="Total paid in", mode="lines",
                        line=dict(color=theme.MUTED, width=1.4, dash="dash"))  # fmt: skip
        show(fig)
        st.caption("The dashed line is the money paid in. The gap between a portfolio and the dashed "
                   "line is its gain or loss. Rising value here partly reflects new contributions.")  # fmt: skip
    else:
        show(line_chart(comparison.growth_of_one(), "Growth of 1 invested at the start, contributions removed",
                        "Growth of 1", height=430))  # fmt: skip
        st.caption("This removes the effect of adding money, so it compares what the holdings "
                   "themselves did. It is the fair chart for comparing allocations.")  # fmt: skip

with t_compare:
    table = comparison.table(list(ROWS))
    shown = pd.DataFrame({name: [fmt(key, table.loc[key, name]) for key in ROWS] for name in table.columns},
                         index=list(ROWS.values()))  # fmt: skip
    st.dataframe(shown, width="stretch", height=565)
    st.caption("Every column uses the same window, calendar, funding and costs. Returns are "
               "historical; volatility and expected shortfall are measured on this window's daily "
               "returns. A higher past return usually came with deeper falls: read the rows together "
               "instead of ranking by one.")  # fmt: skip
    with st.expander("Time-weighted or money-weighted: which one?"):
        st.markdown(f"- **Time-weighted:** {TWR_HELP}\n- **Money-weighted:** {MWR_HELP}\n\n"
                    "With regular contributions the two differ: money added just before a fall drags "
                    "the money-weighted figure down even though the allocation is the same.")  # fmt: skip

with t_dd:
    dd = comparison.growth_of_one().apply(lambda s: s / s.cummax().clip(lower=1.0) - 1.0)
    show(line_chart(dd, "Drawdown: fall from the highest level reached so far (time-weighted)",
                    "Drawdown", ".0%", 320))  # fmt: skip
    drift = pd.DataFrame({n: allocation_drift(comparison.results[n], comparison.specs[n]) for n in specs})
    show(line_chart(drift, "Allocation drift: largest gap between an actual and a target weight",
                    "Gap from target", ".0%", 300))  # fmt: skip
    st.caption("Drift shows how far a portfolio wanders from its targets between rebalances. "
               "Rebalancing pulls it back at a trading cost; never rebalancing lets winners grow. "
               "Small spikes on contribution days are new cash waiting, usually one session, to be invested.")  # fmt: skip

with t_risk:
    # QA-024: any compared portfolio can be inspected, and all are compared side by side.
    # Every figure on the right comes from the shared fixed-weight estimator (quantlab.risk),
    # the same code the Risk Analytics page uses.
    inspect = st.selectbox("Portfolio to inspect", list(comparison.specs), key="il_risk_pick")
    spec = comparison.specs[inspect]
    target = pd.Series(spec.weights, dtype=float)
    asset_returns = holding_returns(comparison.data.close, target)
    est = estimate_risk(asset_returns, target, 0.95)
    estimate = est.summary()
    realised = comparison.stats[inspect]
    left, right = st.columns(2)
    with left:
        st.markdown('<span class="ql-badge ql-user">HISTORICAL</span> what the simulated account did',
                    unsafe_allow_html=True)  # fmt: skip
        h = st.columns(2)
        h[0].metric("Realised volatility", fmt("volatility", realised["volatility"]))
        h[1].metric("Worst day", fmt("worst_day", realised["worst_day"]))
        h[0].metric("Max drawdown", fmt("max_drawdown", realised["max_drawdown"]))
        h[1].metric("Average of worst 5% of days", fmt("es_95", -realised["es_95"]),
                    help="Expected shortfall: the mean return on the worst 5% of days in this window.")  # fmt: skip
        st.caption("Measured on the account simulation: real fills, costs, drift and contributions. "
                   "A future window can be worse.")  # fmt: skip
    with right:
        st.markdown('<span class="ql-badge ql-frozen">ESTIMATED</span> fixed-weight model at the target '
                    "weights, this window", unsafe_allow_html=True)  # fmt: skip
        e = st.columns(2)
        e[0].metric("Estimated volatility", format_value("volatility", estimate["volatility_annual"]),
                    help="sqrt(w' S w) at the target weights; assumes the weights are held exactly, "
                    "every day.")  # fmt: skip
        e[1].metric("Effective holdings", f"{estimate['effective_holdings']:.1f} of {len(est.weights)}",
                    help="1 / sum of squared weights. Equal to the number of holdings only when "
                    "they are equally weighted.")  # fmt: skip
        e[0].metric("Diversification ratio", format_value("diversification_ratio", estimate["diversification_ratio"]),
                    help="Average of the holdings' own volatilities divided by portfolio "
                    "volatility. 1.00 means no diversification benefit.")  # fmt: skip
        e[1].metric("Average correlation", format_value("average_correlation", estimate["average_correlation"]),
                    help="Mean correlation between pairs of holdings. Not available (n/a) with a "
                    "single holding: a correlation needs two series.")  # fmt: skip
        if len(est.weights) < 2:
            st.caption("One holding: correlation is undefined and there is no diversification "
                       "within the portfolio.")  # fmt: skip
        st.caption("Estimates depend on the window used and assume it is representative.")
    rc = est.contributions
    bar = figure("Share of capital versus share of estimated risk", "Share", 320, ".0%")
    bar.add_bar(x=rc.index, y=rc["weight"] / rc["weight"].sum(), name="Share of invested capital")
    bar.add_bar(x=rc.index, y=rc["pct_of_risk"], name="Share of estimated volatility")
    bar.update_layout(barmode="group", hovermode="x")
    show(bar)
    top = rc["pct_of_risk"].idxmax()
    st.markdown(
        f"**Reading this:** {top} accounts for about **{rc.loc[top, 'pct_of_risk']:.0%}** of "
        f"{inspect}'s estimated volatility with **{rc.loc[top, 'weight'] / rc['weight'].sum():.0%}** "
        f"of the invested capital. The estimate ({estimate['volatility_annual']:.1%}) and the realised "
        f"figure ({realised['volatility']:.1%}) differ because the real account drifts between "
        f"rebalances, holds {spec.cash_weight:.0%} target cash, pays costs and usually waits a session to "
        "invest contributions. The two are different models and are not expected to match."
    )
    st.markdown("**All compared portfolios, side by side**")
    rows = {}
    for name, other in comparison.specs.items():
        w = pd.Series(other.weights, dtype=float)
        o = estimate_risk(holding_returns(comparison.data.close, w), w, 0.95).summary()
        risk_estimates[name] = o
        rows[name] = {
            "Realised volatility (account)": fmt("volatility", comparison.stats[name]["volatility"]),
            "Estimated volatility (fixed weights)": format_value("volatility", o["volatility_annual"]),
            "Realised max drawdown": fmt("max_drawdown", comparison.stats[name]["max_drawdown"]),
            "Effective holdings": format_value("effective_holdings", o["effective_holdings"]),
            "Average correlation": format_value("average_correlation", o["average_correlation"]),
            "Target cash": format_value("cash_weight", other.cash_weight, digits=0),
        }  # fmt: skip
    st.dataframe(pd.DataFrame(rows), width="stretch")
    st.caption(f"Window {start.date()} to {end.date()}. 'Realised' is the account simulation; "
               "'estimated' applies target weights to each day's returns. To study one of these "
               "portfolios further, choose it on the Risk Analytics, Monte Carlo or Stress Test page.")  # fmt: skip

with t_cost:
    cost_rows = ["trading_cost", "turnover", "trade_count"]
    costs = comparison.table(cost_rows)
    st.dataframe(pd.DataFrame({n: [fmt("trading_cost", costs.loc["trading_cost", n]),
                                   fmt("turnover", costs.loc["turnover", n]),
                                   f"{costs.loc['trade_count', n]:,.0f}"] for n in costs.columns},
                              index=["Trading cost paid (fees + slippage)", "Turnover (per year)", "Fills"]),
                 width="stretch")  # fmt: skip
    st.markdown("**When contributions were invested**")
    paid_days = result.cash_flows[result.cash_flows > 0].index[:8]
    timeline = []
    for day in paid_days:
        fills = result.trades[result.trades["decision_date"] == day]
        timeline.append({
            "Contribution arrived (open)": day.date(), "Amount": f"{result.cash_flows.loc[day]:,.0f}",
            "Decision (close)": day.date(),
            "Invested (next open)": fills["date"].iloc[0].date() if len(fills) else "not yet",
            "Bought": f"{fills.loc[fills.side == 'BUY', 'notional'].sum():,.0f}" if len(fills) else "0",
        })  # fmt: skip
    if timeline:
        st.dataframe(pd.DataFrame(timeline), width="stretch", hide_index=True)
        st.caption("Each contribution reaches the account at a session's open, the decision to invest "
                   "it is taken at that close, and it is normally bought at the next session's open. "
                   f"{EXC_TIMING} Nothing trades on information from its own day. (First eight shown.)")  # fmt: skip
    else:
        st.caption("No recurring contribution is set.")
    with st.expander(f"Full trade log for {primary_name} ({len(result.trades)} fills)"):
        ledger = result.trades.copy()
        if len(ledger):
            ledger["date"], ledger["decision_date"] = ledger["date"].dt.date, ledger["decision_date"].dt.date
        st.dataframe(ledger.round(4), width="stretch", height=320, hide_index=True)

with t_assume:
    st.markdown(
        "- **Prices** are split- and dividend-adjusted. They are a historical total-return proxy, "
        "**not executable quotes**: share counts and fill prices are approximations, and dividends "
        "are assumed reinvested with no delay or tax.\n"
        "- **Timing:** every decision is taken after a close and traded at the next session's open.\n"
        "- **Contributions** arrive at the open of the first session of each period and are invested "
        "at the following open, so it normally waits one session in cash. Exception: if an order "
        "decided at the previous close (for example a scheduled rebalance) fills at that same open, "
        "it is sized on the account value including the deposit, so the deposit can be invested "
        "that day. No information from the deposit day is used either way.\n"
        "- **Rebalancing** trades the whole portfolio back to target, sells first, paying costs.\n"
        "- **Not modelled:** taxes, interest on cash, withdrawals, market impact.\n"
        "- **Hindsight:** the instruments were chosen today. Funds that closed are absent.\n"
        "- **This is not advice** and makes no prediction."
    )
    assumptions_expander()

with t_export:
    window = {"start": str(start.date()), "end": str(end.date())}
    saved = portfolio_file(specs, cfg, risk_free, comparison.fingerprint, window)
    record = analysis_record(comparison, st.session_state.get("_data_status"))
    record["risk_estimates"] = {"model": "fixed-weight, target weights, this window", **risk_estimates}
    report = investment_report(record, comparison.values(), comparison.contributed(), risk_estimates,
                               primary_name)  # fmt: skip
    statistics = comparison.table(list(comparison.stats[primary_name]))
    statistics.insert(0, "unit", [KINDS.get(k, "text" if isinstance(comparison.stats[primary_name][k], str)
                                            else "number") for k in statistics.index])
    statistics.insert(0, "name", [label(k) for k in statistics.index])
    st.markdown("**Portfolio file**: definitions and assumptions only. It contains no account or "
                "personal details and can be reloaded above.")  # fmt: skip
    downloads({"Portfolio file (JSON)": (json_bytes(saved), "quantlab_portfolios.json")}, "il_save")
    st.markdown("**Analysis**: everything needed to reproduce the numbers on this page.")
    downloads({
        "Full analysis (JSON)": (json_bytes(record), "investment_lab_analysis.json"),
        "Statistics (CSV)": (csv_bytes(statistics, "statistic"), "statistics.csv"),
        "Values over time (CSV)": (csv_bytes(comparison.values().assign(paid_in=comparison.contributed()), "date"), "portfolio_values.csv"),
        "Summary (HTML)": (report.encode(), "investment_lab_summary.html"),
    }, "il_export")  # fmt: skip
    if can_bundle(comparison.data):
        st.markdown("**Price data**: the exact prices behind these numbers, as CSV files the "
                    "'My own CSV files' source accepts. Upload them and load the portfolio file to "
                    "reproduce this analysis without any data provider.")  # fmt: skip
        downloads({"Price data (ZIP)": (price_bundle(comparison.data, comparison.fingerprint),
                                        "quantlab_prices.zip")}, "il_prices")  # fmt: skip
    else:
        st.caption(f"Price data from {data.metadata.source} is not included in any export: its "
                   "redistribution rights are not established. The dataset fingerprint below "
                   "identifies it.")  # fmt: skip
    st.caption(f"Dataset fingerprint `{comparison.fingerprint}` ({data.metadata.source}). The same file on "
               "the same dataset reproduces these numbers exactly; on refreshed or different data the "
               "page will say so when the file is loaded.")  # fmt: skip
