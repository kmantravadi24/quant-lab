"""Investment Lab: Future Wealth. A funded plan projected forward under stated return models.

Everything numerical comes from ``quantlab.forecast`` (account simulation, goals,
sensitivity, validation, ledger). This module only collects inputs and explains results.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from components import theme
from components.common import ROOT, cache_dir, downloads, figure, public_demo, show
from quantlab.forecast import (
    LABELS,
    MILESTONES,
    SUITABILITY,
    WealthPlan,
    build_model,
    compare_plans,
    decomposition,
    goal_probabilities,
    monthly_returns,
    required_contribution,
    required_contribution_deterministic,
    sensitivity,
    simulate_wealth,
    summary,
)
from quantlab.forecast.ledger import ChainError, ForecastLedger, market_forecast
from quantlab.forecast.scenario import scenario_payload
from quantlab.forecast.validation import conclusions, score_table, summarise_record, walk_forward
from quantlab.portfolio.compare import data_fingerprint
from quantlab.reporting import csv_bytes, json_bytes
from quantlab.simulations import wilson_interval

HORIZONS = [1, 2, 3, 5, 7, 10, 15, 20, 25, 30]
GOALS = {"$100,000": 100_000.0, "$250,000": 250_000.0, "$500,000": 500_000.0,
         "$1,000,000": 1_000_000.0, "Custom": None}  # fmt: skip
REBALANCE = {"A": "Annually", "Q": "Quarterly", "M": "Monthly", "never": "Never (new money buys the mix)"}
FREQUENCY = {"M": "Monthly", "Q": "Quarterly", "A": "Annually"}
LOOKBACKS = {"All available history": None, "Last 20 years": 240, "Last 10 years": 120, "Last 5 years": 60}
PATHS = [500, 1000, 2000, 5000, 10000, 20000]


def money(x: float) -> str:
    if x is None or not np.isfinite(x):
        return "n/a"
    return f"${x:,.0f}"


def short_money(x: float) -> str:
    if abs(x) >= 1e6:
        return f"${x / 1e6:,.2f}M"
    if abs(x) >= 1e3:
        return f"${x / 1e3:,.0f}k"
    return f"${x:,.0f}"


def pct_range(p: float, n: int) -> str:
    lo, hi = wilson_interval(p, n)
    if hi < 0.1 or lo > 0.9:  # near 0 or 1, whole percents hide the information
        return f"{lo:.1%}–{hi:.1%} (95%)"
    return f"{lo:.0%}–{hi:.0%} (95%)"




def forecast_dir() -> Path:
    configured = os.environ.get("QUANTLAB_FORECAST_DIR", "").strip()
    return Path(configured).expanduser() if configured else cache_dir() / "forecasts"


@st.cache_data(show_spinner=False, max_entries=64)
def _simulate(_returns, fingerprint: str, plan_json: str, model: str, params_json: str,
              lookback: int | None, paths: int, seed: int, shock: float | None, shock_month: int):  # fmt: skip
    plan = WealthPlan.from_dict(json.loads(plan_json))
    window = _returns if lookback is None else _returns.iloc[-lookback:]
    fitted = build_model(model, window[plan_tickers(plan, _returns)], **json.loads(params_json))
    return simulate_wealth(plan, fitted, paths, seed, shock=shock, shock_month=shock_month)


def plan_tickers(plan: WealthPlan, returns: pd.DataFrame) -> list[str]:
    """Model the held instruments (plus nothing else) so unheld ones never cut the history."""
    held = plan.tickers or [returns.columns[0]]  # an all-cash plan still needs a market to skip
    return [t for t in returns.columns if t in held]


def run(ctx: dict, plan: WealthPlan, model: str | None = None, params: dict | None = None,
        lookback="same", paths: int | None = None, shock=None, shock_month: int = 1):  # fmt: skip
    model = model or ctx["model"]
    params = ctx["params"] if params is None else params
    lookback = ctx["lookback"] if lookback == "same" else lookback
    return _simulate(ctx["returns"], ctx["fingerprint"], json.dumps(plan.to_dict(), sort_keys=True),
                     model, json.dumps(params, sort_keys=True), lookback, paths or ctx["paths"],
                     ctx["seed"], shock, shock_month)  # fmt: skip


@st.cache_data(show_spinner=False, max_entries=16)
def _required(_returns, fingerprint: str, plan_json: str, model: str, params_json: str,
              lookback: int | None, goal: float, probability: float, real: bool):  # fmt: skip
    plan = WealthPlan.from_dict(json.loads(plan_json))
    window = _returns if lookback is None else _returns.iloc[-lookback:]
    fitted = build_model(model, window[plan_tickers(plan, _returns)], **json.loads(params_json))
    return required_contribution(plan, fitted, goal, probability, n_paths=500, seed=11, real=real, tolerance=5.0)


@st.cache_data(show_spinner=False, max_entries=8)
def _sensitivity(_returns, fingerprint: str, plan_json: str, goal: float, lookbacks_json: str, block: float):
    plan = WealthPlan.from_dict(json.loads(plan_json))
    models = {"iid_bootstrap": {}, "block_bootstrap": {"block": block}, "ewma_filtered": {}, "gaussian_iid": {}}
    return sensitivity(plan, _returns[plan_tickers(plan, _returns)], models, json.loads(lookbacks_json),
                       n_paths=1000, seed=5, goal=goal)  # fmt: skip


@st.cache_data(show_spinner=False, max_entries=4)
def _quick_validation(_returns, fingerprint: str, weights_json: str):
    weights = json.loads(weights_json)
    models = {"iid_bootstrap": {}, "block_bootstrap": {"block": 12}, "ewma_filtered": {}, "gaussian_iid": {}}
    forecasts = walk_forward(_returns, weights, models, (1, 12), {"expanding": None}, 300, step=3)
    return forecasts, score_table(forecasts)


def validation_digest() -> dict | None:
    record = stored_validation()
    try:
        return summarise_record(record) if record else None
    except (KeyError, ValueError):
        return None


def stored_validation() -> dict | None:
    folder = ROOT / "experiments" / "results"
    real = sorted(folder.glob("forecast_validation_*.json"))
    real = [p for p in real if not p.stem.endswith("_synthetic")] or real
    if not real:
        return None
    try:
        return json.loads(real[-1].read_text())
    except (OSError, ValueError):
        return None


# ----------------------------------------------------------------------------- inputs


def _inputs(tickers: list[str]) -> dict:
    st.markdown("**1. Your plan**")
    c = st.columns(5)
    initial = c[0].number_input("Starting amount ($)", 0.0, 1e9, 5_000.0, 1_000.0, key="p_fw_initial",
                                help="Money invested on day one.")  # fmt: skip
    contribution = c[1].number_input("Regular contribution ($)", 0.0, 1e7, 500.0, 50.0, key="p_fw_contrib",
                                     help="Added at the start of every month (or every quarter or "
                                     "year, see costs and timing below).")  # fmt: skip
    growth = c[2].number_input("Yearly increase in contribution (%)", -20.0, 50.0, 3.0, 0.5, key="p_fw_growth",
                               help="Raise the contribution by this much every 12 months, for "
                               "example in line with pay rises.") / 100  # fmt: skip
    horizon = c[3].select_slider("Horizon (years)", HORIZONS, 10, key="p_fw_horizon")
    goal_label = c[4].selectbox("Goal", list(GOALS), key="p_fw_goal")
    goal = GOALS[goal_label]
    if goal is None:
        goal = st.number_input("Custom goal ($)", 1_000.0, 1e10, 150_000.0, 5_000.0, key="p_fw_goal_custom")
    real_goal = st.toggle("Goal in today's money (after inflation)", False, key="p_fw_real",
                          help="Off: the goal is a dollar amount at the time. On: it is what that "
                          "amount buys today, so it rises with inflation.")  # fmt: skip

    st.markdown("**2. What you hold** (percent; the rest is cash)")
    defaults = {t: st.session_state.get(f"p_il_w_A_{t}") for t in tickers}
    if all(v is None for v in defaults.values()):
        defaults = {t: (60.0 if i == 0 else 40.0 if i == 1 else 0.0) for i, t in enumerate(tickers)}
        if len(tickers) == 1:
            defaults = {tickers[0]: 100.0}
    cols = st.columns(min(len(tickers), 6))
    weights = {}
    for i, t in enumerate(tickers):
        weights[t] = cols[i % len(cols)].number_input(f"{t} (%)", 0.0, 100.0, float(defaults[t] or 0.0), 5.0,
                                                      key=f"p_fw_w_{t}") / 100  # fmt: skip
    total = sum(weights.values())
    if total > 1 + 1e-9:
        st.error(f"The allocation adds up to {total:.1%}. Leverage is not supported: reduce it to 100% or less.")
        st.stop()
    st.caption(f"Invested {total:.0%} | Cash {1 - total:.0%}. Defaults come from Portfolio A in the "
               "historical builder when you have set one there.")  # fmt: skip

    with st.expander("Costs, cash, inflation and timing"):
        k = st.columns(6)
        cost = k[0].number_input("Trading cost (bp)", 0.0, 200.0, 5.0, 1.0, key="p_fw_cost",
                                 help="Spread and commission on every dollar bought or sold. 1 bp = 0.01%.")  # fmt: skip
        fee = k[1].number_input("Annual fund fee (%)", 0.0, 3.0, 0.10, 0.05, key="p_fw_fee",
                                help="Expense ratio or advisory fee on invested money, charged monthly.") / 100  # fmt: skip
        cash_yield = k[2].number_input("Cash interest (%/yr)", 0.0, 10.0, 0.0, 0.25, key="p_fw_cash",
                                       help="What the cash part earns. 0 is conservative.") / 100  # fmt: skip
        inflation = k[3].number_input("Inflation (%/yr)", 0.0, 15.0, 2.5, 0.25, key="p_fw_infl",
                                      help="Only used to show results in today's money.") / 100  # fmt: skip
        reb = k[4].selectbox("Rebalance", list(REBALANCE), format_func=REBALANCE.get, key="p_fw_reb")
        freq = k[5].selectbox("Contribution every", list(FREQUENCY), format_func=FREQUENCY.get, key="p_fw_freq")

    with st.expander("Model and simulation settings (advanced)"):
        a = st.columns(5)
        model = a[0].selectbox("Return model", list(LABELS), index=1, format_func=LABELS.get, key="p_fw_model",
                               help="How future months are drawn from history. See the "
                               "'Model sensitivity' tab for how much this choice matters.")  # fmt: skip
        lookback_label = a[1].selectbox("History used", list(LOOKBACKS), key="p_fw_lookback")
        block = a[2].number_input("Mean block length (months)", 2.0, 60.0, 12.0, 1.0, key="p_fw_block",
                                  disabled=model != "block_bootstrap")  # fmt: skip
        lam = a[3].number_input("EWMA decay", 0.80, 0.99, 0.97, 0.01, key="p_fw_lam",
                                disabled=model != "ewma_filtered")  # fmt: skip
        paths = a[4].select_slider("Simulated paths", PATHS, 2000, key="p_fw_paths",
                                   help="More paths shrink sampling noise only; they do not make "
                                   "the model more right.")  # fmt: skip
        b = st.columns(3)
        seed = b[0].number_input("Random seed", 0, 2**31 - 1, 42, key="p_fw_seed")
        crash = b[1].toggle("Add a market crash scenario", False, key="p_fw_crash")
        shock = b[2].slider("Crash size (%)", -80, -10, -35, 5, key="p_fw_shock", disabled=not crash)
    params = {"block_bootstrap": {"block": float(block)}, "ewma_filtered": {"lam": float(lam)}}.get(model, {})
    try:
        plan = WealthPlan(weights={t: w for t, w in weights.items() if w > 0} or {tickers[0]: 0.0},
                          initial_amount=initial, contribution=contribution,
                          frequency=freq, contribution_growth=growth,
                          rebalance=None if reb == "never" else reb, cost_bps=cost, annual_fee=fee,
                          cash_yield=cash_yield, inflation=inflation, horizon_years=float(horizon),
                          name="Your plan")  # fmt: skip
    except ValueError as exc:
        st.error(f"This plan cannot be simulated: {exc}.")
        st.stop()
    return {"plan": plan, "goal": float(goal), "real_goal": real_goal, "model": model, "params": params,
            "lookback": LOOKBACKS[lookback_label], "lookback_label": lookback_label, "paths": int(paths),
            "seed": int(seed), "shock": float(shock) / 100 if crash else None}  # fmt: skip


# ----------------------------------------------------------------------------- page


def render(data) -> None:
    st.markdown(
        '<span class="ql-badge ql-user">FUTURE WEALTH</span><span class="ql-meta">a funded plan '
        "simulated forward month by month: deposits, trading costs, fees and rebalancing on "
        "simulated returns drawn from history</span>",
        unsafe_allow_html=True,
    )
    st.caption("This is not a forecast. It shows the spread of outcomes your plan would have if the "
               "future resembled the chosen history in the chosen way. Read the sensitivity and "
               "validation tabs before relying on any number.")  # fmt: skip
    tickers = data.tickers
    ctx = _inputs(tickers)
    plan = ctx["plan"]
    # Only the instruments the plan holds limit the history (as on every other page).
    returns = monthly_returns(data.close, [t for t in tickers if t in (plan.tickers or tickers[:1])])
    if len(returns) < 36:
        st.error(f"Only {len(returns)} complete months are common to the instruments this plan holds; "
                 "at least 36 are needed. Load more history or change the holdings.")  # fmt: skip
        st.stop()
    if ctx["lookback"] is not None and ctx["lookback"] > len(returns):
        ctx["lookback"] = None
        st.caption(f"Only {len(returns)} months are available, so all of them are used.")
    ctx.update(returns=returns, fingerprint=data_fingerprint(data))
    with st.spinner("Simulating the plan month by month..."):
        result = run(ctx, plan, shock=ctx["shock"])
    s = summary(result, ctx["goal"], ctx["real_goal"])
    g = s["goal"]
    n = result.n_paths
    window = result.model
    goal_text = money(ctx["goal"]) + (" in today's money" if ctx["real_goal"] else "")

    st.markdown(
        f'<span class="ql-badge ql-frozen">MODEL: {LABELS[ctx["model"]].upper()}</span>'
        f'<span class="ql-meta">history {window["window_start"]} to {window["window_end"]} '
        f'({window["window_months"]} months) | {n:,} paths | seed {ctx["seed"]}'
        + (f' | crash of {ctx["shock"]:.0%} in month 1' if ctx["shock"] else "") + "</span>",
        unsafe_allow_html=True,
    )
    k = st.columns(3) + st.columns(3)
    k[0].metric("Median after " + f"{plan.horizon_years:g} yr", short_money(s["median_terminal"]),
                f"{short_money(s['median_terminal_real'])} in today's money", delta_color="off", delta_arrow="off",
                help="Half the simulated paths end above this, half below.")  # fmt: skip
    k[1].metric("5th to 95th percentile", f"{short_money(s['p5_terminal'])} – {short_money(s['p95_terminal'])}",
                help="Nine in ten simulated paths end in this range.")  # fmt: skip
    k[2].metric(f"Reach {short_money(ctx['goal'])} by year {plan.horizon_years:g}", f"{g['p_reach']:.0%}",
                pct_range(g["p_reach"], n), delta_color="off", delta_arrow="off",
                help="Share of paths at or above the goal at any month end within the horizon. The "
                "range is sampling noise only.")  # fmt: skip
    k[3].metric("Hold it at the end", f"{g['p_hold']:.0%}", pct_range(g["p_hold"], n), delta_color="off",
                delta_arrow="off", help="Share of paths at or above the goal at the final month.")  # fmt: skip
    k[4].metric("End below what you paid in", f"{s['p_below_contributions']:.0%}",
                pct_range(s["p_below_contributions"], n), delta_color="off", delta_arrow="off",
                help="Share of paths whose final value is less than the total deposited.")  # fmt: skip
    k[5].metric("Total you pay in", short_money(s["total_contributed"]),
                help="Starting amount plus every contribution, before any growth.")  # fmt: skip

    dec = decomposition(result, 50)
    drag = s["median_costs"] + s["median_fees"]
    explain = [
        f"**What drives this projection.** Of the median ending value of {money(dec['ending_value'])}, "
        f"**{money(dec['deposits'])}** is money you put in and **{money(dec['growth'])}** is investment "
        f"growth ({dec['growth_share']:.0%} of the total).",
        f"The growth comes from {window['window_months']} months of history ({window['window_start']} to "
        f"{window['window_end']}) replayed {LABELS[ctx['model']].lower()}; a different window can change "
        "it a lot (see 'Model sensitivity').",
        f"Trading costs and fees take about {money(drag)} on the median path; cash earns "
        f"{plan.cash_yield:.1%} and {plan.cash_weight:.0%} of the plan is held as cash.",
        f"Inflation of {plan.inflation:.1%} a year means {money(s['median_terminal'])} at the end buys "
        f"what {money(s['median_terminal_real'])} buys today.",
    ]
    st.markdown(" ".join(explain))
    warn = []
    if ctx["model"] == "ewma_filtered" and plan.horizon_years > 2:
        warn.append("The EWMA model conditions on today's volatility; over "
                    f"{plan.horizon_years:g} years that information fades. Treat it as a sensitivity.")  # fmt: skip
    if plan.horizon_years >= 3:
        digest = validation_digest()
        long = digest and not digest["synthetic"] and digest["horizons"].get(12)
        if long and long["coverage_90_high"] < 0.9:
            warn.append(f"In walk-forward tests on {digest['first_month']} to {digest['last_month']} data, "
                        f"12-month 90% ranges contained the outcome only "
                        f"{long['coverage_90_low']:.0%}–{long['coverage_90_high']:.0%} of the time on average: "
                        "long-horizon ranges are likely too narrow.")  # fmt: skip
        elif not digest or digest["synthetic"]:
            warn.append("No real-data validation of long-horizon ranges is available: treat them as "
                        "illustrations, not calibrated forecasts.")  # fmt: skip
    if ctx["model"] == "gaussian_iid":
        warn.append("The normal model has thin tails and understates crashes.")
    for w in warn:
        st.warning(w)

    tabs = st.tabs(["Projection", "Milestones", "Deposits vs growth", "Downside", "Compare plans",
                    "Required contribution", "Model sensitivity", "Validation", "Assumptions & export"])  # fmt: skip
    years = np.arange(result.months + 1) / 12

    with tabs[0]:
        real = st.toggle("Show in today's money", False, key="fw_fan_real")
        bands = result.percentile_bands(real=real)
        paid = result.contributed / (result.deflator() if real else 1.0)
        fan = figure("Simulated account value: percentile bands", "Value ($)", 460, x_title="Years from now")
        fan.add_scatter(x=years, y=bands[4], line=dict(width=0), showlegend=False, hoverinfo="skip")
        fan.add_scatter(x=years, y=bands[0], fill="tonexty", fillcolor="rgba(91,141,239,0.14)",
                        line=dict(width=0), name="5th–95th percentile")  # fmt: skip
        fan.add_scatter(x=years, y=bands[3], line=dict(width=0), showlegend=False, hoverinfo="skip")
        fan.add_scatter(x=years, y=bands[1], fill="tonexty", fillcolor="rgba(91,141,239,0.30)",
                        line=dict(width=0), name="25th–75th percentile")  # fmt: skip
        fan.add_scatter(x=years, y=bands[2], line=dict(color=theme.ACCENT, width=2.4), name="Median")
        fan.add_scatter(x=years, y=paid, line=dict(color=theme.MUTED, width=1.5, dash="dash"), name="Total paid in")
        goal_line = ctx["goal"] if (real or not ctx["real_goal"]) else None
        if goal_line:
            fan.add_hline(y=goal_line, line_dash="dot", line_color=theme.BENCH, annotation_text=f"goal {short_money(goal_line)}")
        show(fan)
        st.caption("Each band is the spread across simulated paths at that point in time, not one path. "
                   "The dashed line is money paid in: above it is growth, below it is loss.")  # fmt: skip

    with tabs[1]:
        goals = sorted({*MILESTONES, ctx["goal"]})
        rows, curves = [], {}
        for target in goals:
            gp = goal_probabilities(result, target, ctx["real_goal"])
            med = gp["median_months_to_goal"]
            rows.append({"Milestone": money(target) + (" (your goal)" if target == ctx["goal"] else ""),
                         f"Reached by year {plan.horizon_years:g}": f"{gp['p_reach']:.0%}",
                         "Held at the end": f"{gp['p_hold']:.0%}",
                         "Median time to reach": f"{med / 12:.1f} years" if med else "beyond the horizon",
                         "Sampling range (reach)": pct_range(gp["p_reach"], n)})  # fmt: skip
            curves[money(target)] = gp["p_reached_by_year"]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        chart = figure("Chance of having reached each milestone, by year", "Probability", 360, ".0%", x_title="Year")
        for i, (label, by_year) in enumerate(curves.items()):
            chart.add_scatter(x=list(by_year), y=list(by_year.values()), name=label, mode="lines+markers",
                              line=dict(color=theme.SERIES[i % len(theme.SERIES)]))  # fmt: skip
        show(chart)
        st.caption("'Reached' counts any month end at or above the milestone, even if the account later "
                   "fell back; 'held' counts only the final month. Month-end values only.")  # fmt: skip

    with tabs[2]:
        median = np.median(result.values, axis=0)
        growth_line = median - result.contributed
        stack = figure("Median path: money paid in versus growth", "Value ($)", 380, x_title="Years from now")
        stack.add_scatter(x=years, y=result.contributed, stackgroup="one", name="Money paid in",
                          line=dict(color=theme.MUTED))  # fmt: skip
        stack.add_scatter(x=years, y=np.maximum(growth_line, 0), stackgroup="one", name="Investment growth",
                          line=dict(color=theme.POSITIVE))  # fmt: skip
        show(stack)
        table = pd.DataFrame([decomposition(result, q) for q in (5, 25, 50, 75, 95)])
        st.dataframe(pd.DataFrame({
            "Outcome": ["Poor (5th pct)", "Below median (25th)", "Median", "Above median (75th)", "Good (95th)"],
            "Ending value": table["ending_value"].map(money), "Paid in": table["deposits"].map(money),
            "Growth": table["growth"].map(money),
            "Growth share": table["growth_share"].map(lambda v: "n/a" if pd.isna(v) else f"{v:.0%}"),
        }), hide_index=True, width="stretch")  # fmt: skip
        st.caption("Early on, almost all of the value is your own money; growth matters more the longer "
                   "it compounds. In poor outcomes growth can be negative.")  # fmt: skip

    with tabs[3]:
        d = st.columns(4)
        d[0].metric("1-in-100 bad outcome", short_money(s["p1_terminal"]))
        d[1].metric("1-in-20 bad outcome", short_money(s["p5_terminal"]))
        d[2].metric("Median worst fall on the way", f"{s['median_max_drawdown']:.0%}",
                    help="Largest peak-to-trough fall of the investment return (deposits removed).")  # fmt: skip
        d[3].metric("Paths with a fall worse than 30%", f"{s['p_drawdown_worse_than_30pct']:.0%}")
        hist = figure("Worst fall along each path", "Paths", 300, x_title="Maximum drawdown")
        hist.add_histogram(x=result.twr_max_drawdown, nbinsx=50, marker_color=theme.NEGATIVE, name="Paths")
        hist.update_xaxes(tickformat=".0%")
        show(hist)
        st.markdown("**Sequence risk: the same 35% crash at the start versus near the end**")
        base = run(ctx, plan, shock=None)
        early = run(ctx, plan, shock=-0.35, shock_month=1)
        late = run(ctx, plan, shock=-0.35, shock_month=max(1, result.months - 11))
        st.dataframe(pd.DataFrame({
            "Scenario": ["No added crash", "35% crash in month 1", f"35% crash in month {max(1, result.months - 11)}"],
            "Median ending value": [money(np.median(r.terminal)) for r in (base, early, late)],
            "Ending below paid in": [f"{(r.terminal < r.contributed[-1]).mean():.0%}" for r in (base, early, late)],
        }), hide_index=True, width="stretch")  # fmt: skip
        st.caption("A crash early hits little money and is followed by cheap purchases; the same crash "
                   "near the end hits the whole balance. Crash scenarios are added on top of the model's "
                   "own bad months; they are not probabilities.")  # fmt: skip

    with tabs[4]:
        axis = st.selectbox("Compare by", ["Monthly contribution", "Allocation", "Fees", "Contribution growth",
                                          "Cash share"], key="fw_compare")  # fmt: skip
        risky = {t: w for t, w in plan.weights.items() if w > 0}
        scale = sum(risky.values()) or 1.0
        all_in = {t: w / scale for t, w in risky.items()} if risky else {tickers[0]: 1.0}
        variants = {
            "Monthly contribution": {f"${c:,.0f}/month": replace(plan, contribution=float(c)) for c in (200, 500, 1000)},
            "Allocation": {"Your mix": plan, "100% invested, same mix": replace(plan, weights=all_in),
                           "Equal weight, all instruments": replace(plan, weights={t: 1 / len(tickers) for t in tickers}),
                           f"100% {tickers[0]}": replace(plan, weights={tickers[0]: 1.0})},
            "Fees": {f"{f:.2%} a year": replace(plan, annual_fee=f) for f in (0.0005, 0.005, 0.01)},
            "Contribution growth": {f"{g:.0%} a year": replace(plan, contribution_growth=g) for g in (0.0, 0.03, 0.05)},
            "Cash share": {f"{c:.0%} cash": replace(plan, weights={t: w * (1 - c) for t, w in all_in.items()})
                           for c in (0.0, 0.2, 0.4)},
        }[axis]  # fmt: skip
        held = sorted({t for p in variants.values() for t in p.tickers}) or list(returns.columns)
        if any(t not in returns.columns for t in held):
            joint = monthly_returns(data.close, held)
            st.caption(f"These plans hold {', '.join(held)}: compared on the {len(joint)} months all of "
                       "them have, so every plan faces the same simulated markets.")  # fmt: skip
        else:
            joint = returns[held]
        fitted = build_model(ctx["model"], joint if ctx["lookback"] is None else joint.iloc[-ctx["lookback"]:], **ctx["params"])
        compared = compare_plans(variants, fitted, min(ctx["paths"], 2000), ctx["seed"], ctx["goal"], ctx["real_goal"])
        st.dataframe(pd.DataFrame({name: {
            "Total paid in": money(c["summary"]["total_contributed"]),
            "Median ending value": money(c["summary"]["median_terminal"]),
            "5th percentile": money(c["summary"]["p5_terminal"]),
            "95th percentile": money(c["summary"]["p95_terminal"]),
            f"Hold {short_money(ctx['goal'])} at the end": f"{c['summary']['goal']['p_hold']:.0%}",
            "End below paid in": f"{c['summary']['p_below_contributions']:.0%}",
            "Median worst fall": f"{c['summary']['median_max_drawdown']:.0%}",
            "Median costs + fees": money(c["summary"]["median_costs"] + c["summary"]["median_fees"]),
        } for name, c in compared.items()}), width="stretch")  # fmt: skip
        overlay = figure("Median path of each plan", "Value ($)", 340, x_title="Years from now")
        for i, (name, c) in enumerate(compared.items()):
            overlay.add_scatter(x=np.arange(c["result"].months + 1) / 12, y=np.median(c["result"].values, axis=0),
                                name=name, line=dict(color=theme.SERIES[i % len(theme.SERIES)]))  # fmt: skip
        show(overlay)
        st.caption("Every plan faces exactly the same simulated markets (common random numbers), so the "
                   "differences come from the decision, not from luck. Probabilities still depend on the model.")  # fmt: skip

    with tabs[5]:
        st.markdown(f"**How much to contribute to end with {goal_text} after {plan.horizon_years:g} years**")
        rows = []
        for rate in (0.04, 0.06, 0.08):
            need = required_contribution_deterministic(plan, ctx["goal"] * ((1 + plan.inflation) ** plan.horizon_years
                                                                            if ctx["real_goal"] else 1.0), rate)  # fmt: skip
            rows.append({"Assumption": f"Every year returns exactly {rate:.0%} (no costs, no bad years)",
                         f"Required per {FREQUENCY[plan.frequency].lower()[:-2] if plan.frequency != 'M' else 'month'}": money(need)})  # fmt: skip
        for prob in (0.5, 0.75, 0.9):
            out = _required(returns, ctx["fingerprint"], json.dumps(plan.to_dict(), sort_keys=True), ctx["model"],
                            json.dumps(ctx["params"], sort_keys=True), ctx["lookback"], ctx["goal"], prob, ctx["real_goal"])  # fmt: skip
            label = money(out["contribution"]) if out["bracketed"] else "not reachable within limits"
            rows.append({"Assumption": f"{prob:.0%} of simulated paths end at or above the goal ({LABELS[ctx['model']].lower()})",
                         list(rows[0])[1]: label})  # fmt: skip
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption(f"Keeps your starting amount, yearly increase of {plan.contribution_growth:.0%}, costs and "
                   "fees. The constant-return rows are arithmetic, not predictions. The simulated rows use 500 "
                   "paths and the same markets for every amount tried, so they rise smoothly with the "
                   "required probability; they inherit every limitation of the model.")  # fmt: skip

    with tabs[6]:
        looks = {label: m for label, m in LOOKBACKS.items() if m is None or m < len(returns)}
        looks = {label: (m or len(returns)) for label, m in looks.items()}
        rows = _sensitivity(returns, ctx["fingerprint"], json.dumps(plan.to_dict(), sort_keys=True), ctx["goal"],
                            json.dumps(looks), float(ctx["params"].get("block", 12.0)))  # fmt: skip
        table = pd.DataFrame(rows)
        st.dataframe(pd.DataFrame({
            "History": table["lookback"] + " (" + table["window_start"] + " to " + table["window_end"] + ")",
            "Model": table["model"].map(LABELS), "Median ending value": table["median_terminal"].map(money),
            "5th percentile": table["p5_terminal"].map(money),
            f"Hold {short_money(ctx['goal'])}": table["p_hold_goal"].map(lambda v: f"{v:.0%}"),
            "End below paid in": table["p_below_contributions"].map(lambda v: f"{v:.0%}"),
        }), hide_index=True, width="stretch")  # fmt: skip
        spread = table["p_hold_goal"].max() - table["p_hold_goal"].min()
        typical = np.mean([(lambda lo_hi: (lo_hi[1] - lo_hi[0]) / 2)(wilson_interval(p, 1000)) for p in table["p_hold_goal"]])
        st.markdown(f"**Two kinds of uncertainty.** The chance of holding the goal ranges from "
                    f"{table['p_hold_goal'].min():.0%} to {table['p_hold_goal'].max():.0%} across these models "
                    f"and histories (a spread of {spread:.0%} points). Sampling noise from using 1,000 paths is "
                    f"only about ±{typical:.0%} points. **Model uncertainty dominates**: no setting here is the "
                    "right one, and more paths do not fix it.")  # fmt: skip
        st.caption("Suitability: " + " ".join(f"{LABELS[m]}: {SUITABILITY[m]}" for m in LABELS))

    with tabs[7]:
        record = stored_validation()
        if record:
            src = "synthetic data (pipeline check only)" if record.get("synthetic") else record["data"].get("source", "")
            st.markdown(f"**Walk-forward validation** (protocol `{record['protocol_hash']}`, {src}, data "
                        f"fingerprint `{record['data'].get('fingerprint')}`). Each forecast used only data "
                        "available at its date and was scored against what happened next.")  # fmt: skip
            for label, res in record["results"].items():
                with st.expander(f"Portfolio {label}: months {res['monthly_window'][0]} to {res['monthly_window'][1]}",
                                 expanded=label == next(iter(record["results"]))):  # fmt: skip
                    sc = pd.DataFrame(res["scores"])
                    st.dataframe(pd.DataFrame({
                        "Horizon (months)": sc["horizon"], "Window": sc["window"], "Model": sc["model"].map(LABELS),
                        "Independent outcomes": sc["independent_outcomes"],
                        "90% range contained outcome": sc["coverage_90"].map(lambda v: f"{v:.0%}"),
                        "Score vs normal baseline": sc["crps_skill_vs_baseline"].map(lambda v: f"{v:+.1%}"),
                        "Verdict": np.where(sc["beats_baseline"], "better (significant)",
                                            np.where(sc["worse_than_baseline"], "worse (significant)",
                                                     np.where(sc["testable"], "no significant difference", "too few outcomes to test"))),
                    }), hide_index=True, width="stretch")  # fmt: skip
                    for line in res["conclusions"]:
                        st.caption(line)
            digest = summarise_record(record)
            parts = []
            for h, d in sorted(digest["horizons"].items()):
                text = (f"at {h} month{'s' if h > 1 else ''}, 90% ranges contained the outcome "
                        f"{d['coverage_90_low']:.0%}–{d['coverage_90_high']:.0%} of the time on average")
                if d["tests_run"] == 0:
                    text += " (too few independent periods to compare models)"
                elif d["wins"]:
                    text += f"; {len(d['wins'])} of {d['tests_run']} model tests beat the normal baseline"
                else:
                    text += f"; no model beat the normal baseline in {d['tests_run']} tests"
                parts.append(text)
            st.info(f"**What this means for your projection.** On {digest['first_month']} to "
                    f"{digest['last_month']} data{' (SYNTHETIC: pipeline check only)' if digest['synthetic'] else ''}, "
                    + "; ".join(parts) + ". Coverage below 90% means the ranges were too narrow. Horizons "
                    "beyond 36 months cannot be checked with this history at all. Read the ranges on this "
                    "page as illustrations under stated assumptions, not guarantees. Nothing here is a "
                    "predictive edge.")  # fmt: skip
        else:
            st.caption("No stored validation record. Run `python experiments/forecast_validation.py`.")
        if st.button("Run a quick walk-forward check on the loaded data", key="fw_validate"):
            weights = {t: w for t, w in plan.weights.items() if w > 0} or {tickers[0]: 1.0}
            norm = sum(weights.values())
            forecasts, quick = _quick_validation(returns, ctx["fingerprint"], json.dumps({t: w / norm for t, w in weights.items()}))
            st.dataframe(quick[["horizon", "model", "forecasts", "independent_outcomes", "coverage_90",
                                "crps_skill_vs_baseline", "beats_baseline", "testable"]], hide_index=True)  # fmt: skip
            for line in conclusions(quick):
                st.caption(line)

    with tabs[8]:
        st.markdown(
            "**Event order each month** (the same on every path): 1. your contribution arrives; "
            "2. trading at the start of the month: in a rebalance month the whole account is traded back "
            "to target, otherwise only new cash is invested in the target mix, and every dollar traded "
            "pays the trading cost; 3. (crash scenario only) every holding falls by the crash size; "
            "4. a month of returns from the model, and interest on cash; 5. the fund fee; 6. the account "
            "is valued.\n\n"
            f"**Model.** {window['description']}. {SUITABILITY[ctx['model']]}\n\n"
            "**Not modelled.** Taxes, withdrawals, changes of plan, intra-month prices, and any future that "
            "differs from the sampled history in ways the model cannot represent. **This is not advice.**"
        )
        payload = scenario_payload(result, ctx["model"], ctx["params"], ctx["lookback"], data.metadata.to_dict(),
                                   ctx["fingerprint"], ctx["goal"], ctx["real_goal"])  # fmt: skip
        bands_frame = pd.DataFrame(result.percentile_bands().T, columns=["p5", "p25", "p50", "p75", "p95"])
        bands_frame.insert(0, "paid_in", result.contributed)
        bands_frame.index.name = "month"
        downloads({"Scenario (JSON, re-runnable)": (json_bytes(payload), "future_wealth_scenario.json"),
                   "Percentiles by month (CSV)": (csv_bytes(bands_frame, "month"), "future_wealth_percentiles.csv")},
                  "fw_export")  # fmt: skip
        st.markdown("**Forecast record.** Record this projection's market forecast in an append-only, "
                    "hash-chained log so it can be checked against what actually happens.")  # fmt: skip
        if public_demo():
            st.info("Forecast recording is switched off on this public demo: it would write to a shared "
                    "server disk that any visitor could fill and that is wiped on every restart. Download "
                    "the scenario above, or run Quant Lab yourself to keep a private forecast record.")  # fmt: skip
            return
        ledger = ForecastLedger(forecast_dir())
        problems = ledger.verify()
        c = st.columns(3)
        if c[0].button("Record this forecast", key="fw_record", disabled=bool(problems)):
            fitted = build_model(ctx["model"], (returns if ctx["lookback"] is None else returns.iloc[-ctx["lookback"]:])[plan_tickers(plan, returns)], **ctx["params"])
            weights = {t: w for t, w in plan.weights.items() if w > 0}
            try:
                entry = ledger.record({
                    "plan": plan.to_dict(), "model": fitted.describe(),
                    "data": {**data.metadata.to_dict(), "fingerprint": ctx["fingerprint"],
                             "last_month": str(returns.index[-1].date())},
                    "market": market_forecast(fitted, weights or {tickers[0]: 0.0}, returns.index[-1], (1, 12, 36), 2000, ctx["seed"]),
                    "wealth": {"months": result.months, "median": s["median_terminal"], "p5": s["p5_terminal"], "p95": s["p95_terminal"]},
                })  # fmt: skip
                st.success(f"Recorded forecast {entry['entry_hash'][:12]} at {entry['recorded_at']}.")
            except (ChainError, OSError) as exc:
                st.error(f"The forecast could not be recorded: {exc}")
        if c[1].button("Check due forecasts against the loaded data", key="fw_evaluate", disabled=bool(problems)):
            done = ledger.evaluate_due(monthly_returns(data.close))
            st.success(f"{len(done)} forecast horizon(s) evaluated and appended.")
        entries = ledger.forecasts.entries() if not problems else []
        c[2].caption(f"{len(entries)} forecast(s) recorded; "
                     + ("chain intact." if not problems else "CHAIN BROKEN: " + "; ".join(problems)))  # fmt: skip
        if data.metadata.synthetic:
            st.caption("The loaded data are synthetic: recorded forecasts would be about simulated prices.")
