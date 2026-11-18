# ruff: noqa: E501  (HTML template: long lines keep the markup readable, as in app/ and tests/)
"""A standalone, readable Investment Lab report (QA-002, 003, 022, 036).

Built only from the analysis record (``quantlab.portfolio.compare.analysis_record``),
the value series and optional fixed-weight risk estimates, so the report always
describes exactly what was computed. It is a single HTML file: no scripts, no
external requests, every user-supplied string escaped.

Every figure is labelled as either HISTORICAL (what the simulated account did) or
ESTIMATE (a model of the target weights). Nothing here is a forecast.
"""

from __future__ import annotations

import html

import pandas as pd

from quantlab.reporting.exports import _CSS, _kv_rows, _section, _svg_chart
from quantlab.reporting.format import format_signed, format_value, label

FREQUENCY = {"W": "weekly", "M": "monthly", "Q": "quarterly"}
REBALANCE = {None: "never rebalanced", "M": "rebalanced monthly", "Q": "rebalanced quarterly",
             "A": "rebalanced annually"}  # fmt: skip
GROUPS = {
    "Outcome of the money paid in": ["final_value", "total_invested", "gain", "trading_cost"],
    "Returns (historical)": ["time_weighted_annual", "money_weighted_annual", "time_weighted_total"],
    "Risk (historical, measured on this window)": ["volatility", "max_drawdown",
                                                    "max_drawdown_duration", "es_95", "worst_day",
                                                    "sharpe"],
    "Maintenance": ["turnover", "drift_average", "drift_max"],
}  # fmt: skip
GLOSSARY = {
    "Time-weighted return": "How the holdings performed, with the timing of contributions removed. "
    "The fair figure for comparing allocations.",
    "Money-weighted return": "The annual rate the money actually earned given when each "
    "contribution went in (an internal rate of return). Depends on timing as well as allocation.",
    "Maximum drawdown": "The largest fall from a previous high, in the time-weighted value. It is "
    "the worst loss someone who bought at the top would have seen.",
    "Volatility": "How much daily returns varied, scaled to a year. Higher means a bumpier ride, "
    "not necessarily a worse outcome.",
    "Expected shortfall (95%)": "The average daily loss on the worst 5% of days in the window.",
    "Sharpe ratio": "Average return above the risk-free rate per unit of volatility.",
    "Drift": "How far the actual weights wandered from the targets between rebalances.",
    "Effective number of holdings": "1 / sum of squared weights: how many equal positions the "
    "portfolio's concentration is equivalent to.",
    "Diversification ratio": "Average of the holdings' own volatilities divided by the portfolio's. "
    "1.00 means mixing them did not reduce volatility.",
}


def _allocation(spec: dict) -> str:
    held = [(t, w) for t, w in spec["weights"].items() if w > 0]
    cash = max(0.0, 1.0 - sum(w for _, w in held))
    parts = [f"{t} {w:.1%}" for t, w in held] + ([f"cash {cash:.1%}"] if cash > 1e-9 else [])
    return ", ".join(parts)


def _findings(record: dict, primary: str) -> list[str]:
    """Plain statements of what happened, each traceable to a number in the tables."""
    res = record["results"]
    p = res[primary]
    out = [
        f"{primary} turned {format_value('total_invested', p['total_invested'])} paid in over "
        f"{record['window']['start']} to {record['window']['end']} into "
        f"{format_value('final_value', p['final_value'])}, a gain of "
        f"{format_value('gain', p['gain'])} after "
        f"{format_value('trading_cost', p['trading_cost'])} of trading costs.",
        f"Its holdings returned {format_value('time_weighted_annual', p['time_weighted_annual'])} a "
        f"year (time-weighted); the money paid in earned "
        f"{format_value('money_weighted_annual', p['money_weighted_annual'])} a year "
        "(money-weighted).",
        f"The deepest fall from a previous high was "
        f"{format_value('max_drawdown', p['max_drawdown'])}.",
    ]
    others = [n for n in res if n != primary]
    if others:
        twr = {n: res[n]["time_weighted_annual"] for n in res}
        dd = {n: res[n]["max_drawdown"] for n in res}
        best = max(twr, key=lambda n: twr[n] if pd.notna(twr[n]) else float("-inf"))
        shallow = max(dd, key=lambda n: dd[n] if pd.notna(dd[n]) else float("-inf"))
        out.append(f"Among the {len(res)} portfolios compared, {best} had the highest time-weighted "
                   f"return and {shallow} the shallowest maximum drawdown in this window."
                   + (" They are the same portfolio." if best == shallow else
                      " A higher return came with a deeper fall, which is common."))  # fmt: skip
    out.append("These are historical results for one window. A different period, or the future, "
               "can rank the portfolios differently.")  # fmt: skip
    return out


def investment_report(
    record: dict,
    values: pd.DataFrame,
    contributed: pd.Series | None = None,
    risk: dict[str, dict] | None = None,
    primary: str | None = None,
) -> str:
    """The Investment Lab report as one self-contained HTML document."""
    esc = html.escape
    portfolios = record["portfolios"]
    results = record["results"]
    primary = primary or next(iter(portfolios))
    names = list(results)
    window = record["window"]
    data = record["data"]
    first = portfolios[primary]

    banner = ""
    if data.get("synthetic"):
        banner = ('<p class="warn"><b>SYNTHETIC DATA.</b> These figures come from simulated prices. '
                  "They demonstrate the method and say nothing about real markets.</p>")  # fmt: skip
    funding = (f"{format_value('initial_amount', first['initial_amount'])} at the start, then "
               f"{format_value('contributions', first['contribution'])} "
               f"{FREQUENCY.get(first['contribution_frequency'], first['contribution_frequency'])}"
               if first["contribution"] > 0 else
               f"{format_value('initial_amount', first['initial_amount'])} at the start, no further "
               "contributions")  # fmt: skip
    ex = record["execution"]
    alloc_rows = "".join(
        f"<tr><td>{esc(n)}{' (yours)' if n == primary else ''}</td><td>{esc(_allocation(s))}</td>"
        f"<td>{esc(REBALANCE.get(s.get('rebalance'), str(s.get('rebalance'))))}</td></tr>"
        for n, s in portfolios.items()
    )
    head = "".join(f"<th>{esc(n)}</th>" for n in names)
    tables = []
    for group, keys in GROUPS.items():
        rows = "".join(
            f"<tr><td>{esc(label(k))}</td>"
            + "".join(f'<td class="num">{esc(format_value(k, results[n].get(k)))}</td>' for n in names)
            + "</tr>"
            for k in keys if any(k in results[n] for n in names)
        )
        tables.append(f"<h3>{esc(group)}</h3><table><tr><th></th>{head}</tr>{rows}</table>")
    versus = ""
    others = [n for n in names if n != primary]
    if others:
        p = results[primary]
        rows = "".join(
            f"<tr><td>{esc(n)}</td>"
            f'<td class="num">{esc(format_signed("time_weighted_annual", p["time_weighted_annual"] - results[n]["time_weighted_annual"]))}</td>'
            f'<td class="num">{esc(format_signed("max_drawdown", p["max_drawdown"] - results[n]["max_drawdown"]))}</td>'
            f'<td class="num">{esc(format_signed("final_value", p["final_value"] - results[n]["final_value"], "money"))}</td></tr>'
            for n in others
        )  # fmt: skip
        versus = (f"<p>Each row is <b>{esc(primary)} minus</b> the named portfolio. A positive "
                  "return or final-value difference favours "
                  f"{esc(primary)}; a positive drawdown difference means {esc(primary)} fell less "
                  "(drawdowns are negative numbers).</p><table><tr><th>Compared with</th>"
                  "<th>Time-weighted return (annual)</th><th>Maximum drawdown</th>"
                  f"<th>Final value</th></tr>{rows}</table>")  # fmt: skip
    risk_html = ""
    if risk:
        keys = ["volatility_annual", "effective_holdings", "diversification_ratio",
                "average_correlation", "cash_weight"]  # fmt: skip
        rows = "".join(
            f"<tr><td>{esc(label(k))}</td>"
            + "".join(f'<td class="num">{esc(format_value(k, risk[n].get(k)))}</td>' for n in risk)
            + "</tr>" for k in keys
        )  # fmt: skip
        risk_html = (
            "<p><b>ESTIMATE.</b> These figures apply each portfolio's target weights to every "
            "day's returns in the window (a fixed-weight model: rebalanced daily, no contributions, "
            "no costs, cash earning 0%). They describe the allocation; the historical figures above "
            "describe the simulated account, which drifts, pays costs and invests contributions a "
            "session late. The two are different models and are not expected to match.</p>"
            f"<table><tr><th></th>{''.join(f'<th>{esc(n)}</th>' for n in risk)}</tr>{rows}</table>"
        )
    curves = values.copy()
    if contributed is not None:
        curves["Total paid in"] = contributed
    limitations = [
        "Historical simulation on adjusted prices (a total-return proxy, not executable quotes). "
        "Dividends are assumed reinvested with no delay or tax.",
        "Decisions are taken after a close and traded at the next session's open, with the stated "
        "slippage and commission. Market impact is not modelled.",
        "Uninvested cash earns nothing. Taxes and withdrawals are not modelled.",
        "The instruments were chosen today, with hindsight; funds that closed are absent.",
        f"One window ({window['start']} to {window['end']}, {window['sessions']:,} sessions): the "
        "period in which every instrument used by any compared portfolio has prices. A different "
        "window can change every number and the ranking.",
        "This is not a forecast and not investment advice.",
    ]
    repro = {
        "generated_at": record.get("generated_at"),
        "fingerprint": data.get("fingerprint"),
        "source": data.get("source"),
        "tickers": data.get("tickers"),
        "adjustment": data.get("adjustment"),
        "retrieved_at": data.get("retrieved_at"),
        "synthetic": data.get("synthetic"),
        "Report format": record.get("schema"),
        **record.get("environment", {}),
    }
    glossary = "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in GLOSSARY.items())
    findings = "".join(f"<li>{esc(f)}</li>" for f in _findings(record, primary))
    title = f"Investment Lab report: {primary}"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{esc(title)}</title>
{_CSS}<style>dt{{font-weight:600;margin-top:.5rem}}dd{{margin-left:0}}h3{{margin-bottom:.3rem}}
.tag{{font-size:.75rem;font-weight:700;letter-spacing:.04em;padding:.1rem .4rem;border:1px solid #889;border-radius:3px}}</style>
</head><body>
<h1>{esc(title)}</h1>
<p class="muted">Generated {esc(str(record.get("generated_at", "")))} by Quant Lab. A historical
simulation of hypothetical portfolios. Not a forecast and not investment advice.</p>
{banner}
<h2>Key findings</h2><ul>{findings}</ul>
<h2>What was simulated</h2><table>
<tr><td>Evaluation period</td><td>{esc(window["start"])} to {esc(window["end"])}
({window["sessions"]:,} trading sessions)</td></tr>
<tr><td>Funding (every portfolio)</td><td>{esc(funding)}</td></tr>
<tr><td>Trading costs</td><td>{esc(format_value(None, ex.get("slippage_bps"), digits=1))} bp slippage
and {esc(format_value(None, ex.get("fee_bps"), digits=1))} bp commission on every trade</td></tr>
<tr><td>Order timing</td><td>{esc(str(record.get("timing", "")))}</td></tr>
<tr><td>Risk-free rate (Sharpe only)</td><td>{esc(format_value("cagr", record.get("risk_free", 0.0)))}</td></tr>
</table>
<h2>Portfolios and allocations</h2><table><tr><th>Portfolio</th><th>Target allocation</th>
<th>Maintenance</th></tr>{alloc_rows}</table>
<h2>Value over time</h2>{_svg_chart(curves)}
<p class="muted">Portfolio value at each close, including money paid in. The gap above "Total paid in" is the gain.</p>
<h2>Results <span class="tag">HISTORICAL</span></h2>{"".join(tables)}
{_section("Compared with the alternatives", versus)}
{_section("Risk of the allocation (model estimate)", risk_html)}
<h2>Limitations</h2><ul>{"".join(f"<li>{esc(n)}</li>" for n in limitations)}</ul>
<h2>How to read the terms</h2><dl>{glossary}</dl>
<h2>Reproducibility</h2><table>{_kv_rows(repro)}</table>
<p class="muted">Load the saved portfolio file into the Investment Lab with the dataset that has this
fingerprint to reproduce every number exactly. Price data is not included in this report.</p>
</body></html>"""
