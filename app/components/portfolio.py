"""The portfolio every analysis page works on (QA-026).

There is one definition of a portfolio: ``quantlab.portfolio.PortfolioSpec``.
The Investment Lab publishes the portfolios it is comparing here, and the Risk,
Monte Carlo and Stress pages offer them in a selector next to a "custom weights"
option. Those pages use only the target WEIGHTS of a spec: they are fixed-weight
statistical models, not the account simulation, and they say so.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

import pandas as pd
import streamlit as st

from quantlab.portfolio.spec import PortfolioSpec
from quantlab.risk.estimate import MODEL_DESCRIPTION

LAB_KEY = "lab_portfolios"  # {name: PortfolioSpec.to_dict()} published by the Investment Lab
CUSTOM = "Custom weights (below)"
PREFIX = "Investment Lab: "


@dataclass(frozen=True)
class ChosenPortfolio:
    weights: pd.Series  # every loaded instrument, zero when not held; the remainder is cash
    name: str
    source: str  # "custom" or "investment_lab"
    spec: dict | None  # the Investment Lab definition, when that is the source

    @property
    def held(self) -> pd.Series:
        return self.weights[self.weights > 0]

    def describe(self) -> dict:
        """For exports: exactly which portfolio was analysed."""
        return {"name": self.name, "source": self.source,
                "weights": {t: float(w) for t, w in self.held.items()},
                "cash": float(max(0.0, 1.0 - self.weights.sum())),
                "investment_lab_definition": self.spec}  # fmt: skip


def publish_lab_portfolios(specs: dict[str, PortfolioSpec]) -> None:
    """Called by the Investment Lab so other pages can analyse the same portfolios."""
    st.session_state[LAB_KEY] = {name: spec.to_dict() for name, spec in specs.items()}


def lab_portfolios() -> dict[str, dict]:
    return dict(st.session_state.get(LAB_KEY) or {})


def _custom_weights(tickers: list[str]) -> pd.Series:
    cols = st.columns(min(len(tickers), 5))
    default = round(100 / len(tickers), 1)
    pct = {}
    for i, t in enumerate(tickers):
        pct[t] = cols[i % len(cols)].number_input(f"{t} (%)", 0.0, 100.0, default, 1.0, key=f"p_w_{t}")
    total = sum(pct.values())
    if total > 100 + 1e-6:
        st.error(f"Weights add up to {total:.1f}%. Leverage is not supported: reduce the total "
                 "to 100% or less.")  # fmt: skip
        st.stop()
    return pd.Series(pct, dtype=float) / 100


def portfolio_input(tickers: list[str]) -> ChosenPortfolio:
    """Choose the portfolio to analyse: one defined in the Investment Lab, or custom weights."""
    st.subheader("Portfolio")
    shared = lab_portfolios()
    options = [CUSTOM] + [PREFIX + name for name in shared]
    if st.session_state.get("p_portfolio") not in options:
        st.session_state["p_portfolio"] = options[1] if len(options) > 1 else CUSTOM
    choice = st.selectbox(
        "Portfolio to analyse", options, key="p_portfolio",
        help="Portfolios you defined in the Investment Lab appear here, so every page can "
        "analyse the same allocation. Custom weights are shared by Risk, Monte Carlo and Stress.",
    )  # fmt: skip
    if choice == CUSTOM:
        weights = _custom_weights(tickers)
        chosen = ChosenPortfolio(weights, "Custom weights", "custom", None)
    else:
        name = choice[len(PREFIX):]
        spec = shared[name]
        absent = [t for t, w in spec["weights"].items() if w > 0 and t not in tickers]
        if absent:
            st.error(f"**{name}** holds {', '.join(absent)}, which is not in the loaded dataset. "
                     "Load it in the sidebar, or choose another portfolio.")  # fmt: skip
            st.stop()
        weights = pd.Series({t: float(spec["weights"].get(t, 0.0)) for t in tickers}, dtype=float)
        chosen = ChosenPortfolio(weights, name, "investment_lab", spec)
        held = ", ".join(f"{t} {w:.1%}" for t, w in chosen.held.items())
        st.caption(f"Target weights from the Investment Lab: {held}; cash "
                   f"{max(0.0, 1 - weights.sum()):.1%}. Change them in the Investment Lab.")  # fmt: skip
    invested = float(chosen.weights.sum())
    st.caption(f"Invested {invested:.1%} | Cash {1 - invested:.1%} | long-only, no leverage.")
    return chosen


def model_badge(extra: str = "") -> None:
    """State which model a page uses, so it is never confused with the account simulation."""
    st.markdown(
        f'<span class="ql-badge ql-frozen">MODEL: FIXED WEIGHTS</span><span class="ql-meta">'
        f"{html.escape(MODEL_DESCRIPTION)} {html.escape(extra)}</span>",
        unsafe_allow_html=True,
    )
