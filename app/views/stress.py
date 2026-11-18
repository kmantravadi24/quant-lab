from datetime import UTC, datetime

import numpy as np
import pandas as pd
import streamlit as st
from components.common import downloads, figure, header, load_data, show
from components.portfolio import portfolio_input

from quantlab.portfolio.compare import data_fingerprint
from quantlab.reporting import csv_bytes, json_bytes
from quantlab.reporting.experiment import environment
from quantlab.risk import apply_scenario, scenario_summary

header("Stress Test", "What a set of hypothetical price shocks would do to the portfolio today.")
data = load_data()
chosen = portfolio_input(data.tickers)
value = st.number_input("Portfolio value", 1_000.0, 1e9, 100_000.0, 1_000.0, key="p_value")
# Only holdings can be shocked; unheld instruments are irrelevant. An all-cash portfolio keeps
# every instrument as a column so the table can show that no shock changes its value.
tickers = list(chosen.held.index) or list(data.tickers)
if chosen.held.empty:
    st.info("The portfolio is 100% cash: no price shock can change its value.")
holdings = (chosen.weights[tickers] * value).rename("value")
holdings["CASH"] = value - holdings.sum()

st.warning("**Every scenario here is hypothetical.** You set each shock independently: nothing on "
           "this page models how assets actually move together, so a scenario is only as realistic "
           "as the combination you enter. Cash is held at its value: it is never shocked and earns "
           "nothing.")  # fmt: skip

st.subheader("Scenarios")
seed = pd.DataFrame(0.0, index=["Broad sell-off", f"{tickers[0]} crash", f"{tickers[-1]} shock"], columns=tickers)
seed.loc["Broad sell-off"] = -10.0
seed.iloc[1, 0] = -30.0
seed.iloc[2, -1] = -20.0
seed = seed[~seed.index.duplicated()]
seed.index.name = "Scenario"
edited = st.data_editor(seed, num_rows="dynamic", width="stretch", key=f"scen_{'_'.join(tickers)}",
                        column_config={t: st.column_config.NumberColumn(f"{t} (%)", min_value=-100.0,
                                                                         max_value=500.0, format="%.1f")
                                       for t in tickers})  # fmt: skip
st.caption("Percentage price change applied to each holding. Edit any cell, or add a row for a new "
           "scenario. A blank cell means no change for that holding.")  # fmt: skip
edited = edited[edited.index.notna()].dropna(how="all")
# A blank cell is an explicit 'no change' here, stated above; the library itself refuses NaN (QA-009).
edited = edited.fillna(0.0)
if edited.empty:
    st.info("Add at least one scenario row above.")
    st.stop()
if edited.index.duplicated().any():
    st.error("Two scenarios have the same name. Give each row a different name.")
    st.stop()
if not np.isfinite(edited.to_numpy(dtype=float)).all():
    st.error("Every shock must be a finite number.")
    st.stop()
if (edited < -100).to_numpy().any():
    st.error("A holding cannot lose more than 100%.")
    st.stop()

scenarios = {str(name): (row / 100).to_dict() for name, row in edited.iterrows()}
summary = scenario_summary(holdings, scenarios)
st.subheader("Result")
st.caption(f"**{chosen.name}**, worth {value:,.0f} today: "
           + ", ".join(f"{t} {w:.1%}" for t, w in chosen.held.items())
           + f", cash {max(0.0, 1 - chosen.weights.sum()):.1%}.")  # fmt: skip
st.dataframe(summary.rename(columns={"value_before": "Value before", "value_after": "Value after",
                                     "pnl": "Gain / loss", "pnl_pct": "Gain / loss (%)"})
             .style.format({"Value before": "{:,.0f}", "Value after": "{:,.0f}",
                            "Gain / loss": "{:+,.0f}", "Gain / loss (%)": "{:+.2%}"}), width="stretch")  # fmt: skip
detail = {name: apply_scenario(holdings, shocks) for name, shocks in scenarios.items()}
bar = figure("Gain or loss by scenario, split by holding", "Gain / loss", 360)
for t in tickers:
    bar.add_bar(x=list(scenarios), y=[detail[s].loc[t, "pnl"] for s in scenarios], name=t)
bar.update_layout(barmode="relative", hovermode="x")
show(bar)

pick = st.selectbox("Scenario detail", list(scenarios))
st.dataframe(detail[pick].rename(columns={"value_before": "Value before", "shock": "Shock", "pnl": "Gain / loss",
                                          "value_after": "Value after", "contribution_pct": "Effect on portfolio"})
             .style.format({"Value before": "{:,.0f}", "Shock": "{:+.1%}", "Gain / loss": "{:+,.0f}",
                            "Value after": "{:,.0f}", "Effect on portfolio": "{:+.2%}"}), width="stretch")  # fmt: skip
st.caption("Effect on portfolio = holding gain or loss / total portfolio value before the shock. "
           "Losses scale in proportion to weights: doubling a weight doubles that holding's effect.")  # fmt: skip
all_detail = pd.concat(detail, names=["scenario", "holding"])
meta = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "portfolio": chosen.describe(),
        "portfolio_value": value, "scenarios": scenarios,
        "model": "hypothetical instantaneous shocks, applied independently per holding; cash unshocked",
        "results": summary.to_dict(orient="index"),
        "data": {**data.metadata.to_dict(), "fingerprint": data_fingerprint(data)},
        "environment": environment()}  # fmt: skip
downloads({"Scenario comparison (CSV)": (csv_bytes(summary, "scenario"), "stress_summary.csv"),
           "Holding-level detail (CSV)": (csv_bytes(all_detail), "stress_detail.csv"),
           "Scenarios and settings (JSON)": (json_bytes(meta), "stress_scenarios.json")}, "stress")  # fmt: skip
