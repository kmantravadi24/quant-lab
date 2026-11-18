"""Export the current analysis as CSV, JSON and a standalone HTML summary.

Everything here is derived from the objects passed in, so an export always
describes the experiment that is actually on screen.
"""

from __future__ import annotations

import html
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime

import pandas as pd

from quantlab.analytics.metrics import drawdown_series
from quantlab.backtesting.engine import BacktestResult
from quantlab.reporting.experiment import _jsonable, environment
from quantlab.reporting.format import KINDS, PERCENT, format_value, label

PERCENT_KEYS = {k for k, kind in KINDS.items() if kind == PERCENT}


FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def neutralise(value):
    """Make a text cell inert in spreadsheets (QA-004, OWASP "CSV injection").

    Text beginning with = + - @ tab or carriage return is prefixed with an apostrophe,
    which spreadsheet programs display as text instead of evaluating. Numbers are never
    changed, so a negative return stays a number.
    """
    if isinstance(value, str) and value.startswith(FORMULA_START):
        return "'" + value
    return value


def safe_frame(df: pd.DataFrame | pd.Series) -> pd.DataFrame:
    """A copy of ``df`` whose text cells, column names and index labels are inert."""
    frame = df.to_frame() if isinstance(df, pd.Series) else df.copy()
    frame.columns = [neutralise(c) for c in frame.columns]
    if frame.index.dtype == object or pd.api.types.is_string_dtype(frame.index):
        labels = [neutralise(i) for i in frame.index]
        frame.index = pd.Index(labels, name=neutralise(frame.index.name))
    for column in frame.columns:
        if frame[column].dtype == object or pd.api.types.is_string_dtype(frame[column]):
            frame[column] = frame[column].map(neutralise)
    return frame


def csv_bytes(df: pd.DataFrame | pd.Series, index_label: str | None = None,
              index: bool = True) -> bytes:  # fmt: skip
    """CSV export with spreadsheet formulas neutralised. Every CSV the app offers uses this."""
    label = neutralise(index_label) if index_label else index_label
    return safe_frame(df).to_csv(index_label=label, index=index).encode()


def json_bytes(obj) -> bytes:
    return json.dumps(_jsonable(obj), indent=2).encode()


def describe_strategy(strategy) -> dict:
    params = asdict(strategy) if is_dataclass(strategy) else dict(vars(strategy))
    return {"type": type(strategy).__name__, "parameters": params}


def experiment_config(strategy, result: BacktestResult, data_metadata: dict, **extra) -> dict:
    """Everything needed to say what was run: strategy, execution, data, environment."""
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "strategy": describe_strategy(strategy),
        "execution": result.config_dict(),
        "timing": "signal at close of session T; fill at open of session T+1",
        "data": data_metadata,
        "environment": environment(),
        **extra,
    }


def equity_table(result: BacktestResult, benchmark: BacktestResult | None = None) -> pd.DataFrame:
    out = pd.DataFrame({
        "strategy_equity": result.equity,
        "strategy_return": result.returns,
        "strategy_drawdown": drawdown_series(result.returns),
        "strategy_cash": result.cash,
    })  # fmt: skip
    if benchmark is not None:
        out["benchmark_equity"] = benchmark.equity
        out["benchmark_return"] = benchmark.returns
        out["benchmark_drawdown"] = drawdown_series(benchmark.returns)
    return out.rename_axis("date")


def statistics_table(stats: dict[str, dict[str, float]]) -> pd.DataFrame:
    """Raw (unformatted) statistics, one column per named run."""
    return pd.DataFrame(stats).rename_axis("statistic")


def cost_summary(result: BacktestResult) -> dict[str, float]:
    """Total explicit trading costs paid, in currency and relative to initial capital."""
    fees = float(result.trades["fee"].sum()) if len(result.trades) else 0.0
    slip = float(result.trades["slippage_cost"].sum()) if len(result.trades) else 0.0
    capital = result.config.initial_capital
    return {
        "fills": float(len(result.trades)),
        "traded_notional": float(result.trades["notional"].sum()) if len(result.trades) else 0.0,
        "fees_paid": fees,
        "slippage_paid": slip,
        "total_cost": fees + slip,
        "total_cost_pct_of_initial_capital": (fees + slip) / capital,
    }


def backtest_bundle(
    strategy,
    result: BacktestResult,
    benchmark: BacktestResult,
    stats: dict[str, dict[str, float]],
    data_metadata: dict,
    **extra,
) -> dict[str, bytes]:
    """File name -> content for every backtest export."""
    config = experiment_config(strategy, result, data_metadata, costs=cost_summary(result), **extra)
    return {
        "equity_curve.csv": csv_bytes(equity_table(result, benchmark)),
        "statistics.csv": csv_bytes(statistics_table(stats)),
        "statistics.json": json_bytes(stats),
        "trades.csv": csv_bytes(result.trades, index=False),
        "config.json": json_bytes(config),
    }


def _fmt(key: str, value) -> str:
    """Report formatting; see :mod:`quantlab.reporting.format`."""
    return format_value(key, value)


def _svg_chart(curves: pd.DataFrame, width: int = 900, height: int = 300) -> str:
    """Minimal inline SVG line chart so the report needs no JavaScript or network.

    The legend wraps onto as many rows as it needs, so every series is named.
    """
    colors = ["#2F6FED", "#D98A1F", "#2E9E78", "#C94F4D", "#7A5CC7", "#5B6472"]
    data = curves.dropna(how="all")
    step = max(1, len(data) // 600)
    data = data.iloc[::step]
    lo, hi = float(data.min().min()), float(data.max().max())
    span = (hi - lo) or 1.0
    pad = 46
    slot = 220  # legend width per series
    per_row = max(1, (width - pad) // slot)
    rows = -(-len(data.columns) // per_row)
    top = 16 * rows + 8  # room for the legend above the plot
    total = height + top
    plot_h = height - pad
    parts = [f'<svg viewBox="0 0 {width} {total}" role="img" aria-label="Value over time">']
    for i, col in enumerate(data.columns):
        color = colors[i % len(colors)]
        name = str(col)
        short = name if len(name) <= 30 else name[:29] + "…"
        x, y = pad + 8 + slot * (i % per_row), 14 + 16 * (i // per_row)
        parts.append(f'<rect x="{x}" y="{y - 9}" width="10" height="3" fill="{color}"/>'
                     f'<text x="{x + 14}" y="{y}" font-size="12" fill="{color}">'
                     f"<title>{html.escape(name)}</title>{html.escape(short)}</text>")  # fmt: skip
    for frac in (0, 0.5, 1):
        y = top + (1 - frac) * plot_h
        parts.append(f'<line x1="{pad}" x2="{width}" y1="{y:.1f}" y2="{y:.1f}" stroke="#ddd"/>')
        parts.append(f'<text x="{pad - 6}" y="{y + 4:.1f}" text-anchor="end" font-size="11" '
                     f'fill="#555">{lo + frac * span:,.0f}</text>')  # fmt: skip
    for i, col in enumerate(data.columns):
        s = data[col].dropna()
        xs = [pad + (width - pad) * data.index.get_loc(d) / max(1, len(data) - 1) for d in s.index]
        ys = [top + (1 - (v - lo) / span) * plot_h for v in s]
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys, strict=True))
        color = colors[i % len(colors)]
        parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="1.6" points="{pts}"/>')
    first, last = str(data.index[0])[:10], str(data.index[-1])[:10]
    parts.append(f'<text x="{pad}" y="{total - 2}" font-size="11" fill="#555">{first}</text>')
    parts.append(f'<text x="{width}" y="{total - 2}" font-size="11" fill="#555" '
                 f'text-anchor="end">{last}</text></svg>')  # fmt: skip
    return "".join(parts)


_CSS = "<style>" + "".join([
    "body{font:15px/1.5 system-ui,sans-serif;max-width:960px;margin:2rem auto;",
    "padding:0 1rem;color:#1b1f27}",
    "h1{margin-bottom:0}",
    "h2{margin-top:2rem;border-bottom:1px solid #ddd}",
    "table{border-collapse:collapse;width:100%}",
    "td,th{padding:.35rem .6rem;border-bottom:1px solid #eee;text-align:left;vertical-align:top}",
    ".num,th:not(:first-child){text-align:right;font-variant-numeric:tabular-nums}",
    ".muted{color:#667}",
    ".warn{background:#fff3cd;padding:.6rem .8rem;border-left:4px solid #d98a1f}",
    "td:first-child{white-space:nowrap}",
]) + "</style>"


def _kv_rows(d: dict) -> str:
    """Appendix rows with plain-language names; values are shown as text, never as JSON."""
    esc = html.escape
    rows = []
    for k, v in d.items():
        if isinstance(v, (list, tuple)):
            text = ", ".join(str(x) for x in v) or "none"
        elif isinstance(v, dict):
            text = "; ".join(f"{label(str(a))}: {b}" for a, b in v.items()) or "none"
        elif isinstance(v, bool):
            text = "yes" if v else "no"
        elif v is None:
            text = "not recorded"
        else:
            text = format_value(str(k), v) if isinstance(v, (int, float)) else str(v)
        rows.append(f"<tr><td>{esc(label(str(k)))}</td><td>{esc(text)}</td></tr>")
    return "".join(rows)


def _section(title: str, body: str) -> str:
    """A report section, or nothing at all when there is nothing to say (QA-003)."""
    return f"<h2>{html.escape(title)}</h2>{body}" if body.strip() else ""


def html_report(
    title: str,
    stats: dict[str, dict[str, float]],
    curves: pd.DataFrame,
    config: dict,
    notes: list[str],
    labels: dict[str, str] | None = None,
) -> str:
    """A single self-contained HTML page: no scripts, no external requests.

    Numbers use the shared formatter (units by statistic, "n/a" for undefined values),
    statistic names are plain language, and empty sections are omitted.
    """
    labels = labels or {}
    esc = html.escape
    data = config.get("data", {})
    banner = ""
    if data.get("synthetic"):
        banner = ('<p class="warn">SYNTHETIC DATA. These figures come from simulated prices and '
                  "say nothing about real markets.</p>")  # fmt: skip
    names = list(stats)
    keys = list(next(iter(stats.values())))
    head = "".join(f"<th>{esc(n)}</th>" for n in names)
    rows = "".join(
        f"<tr><td>{esc(labels.get(k, label(k)))}</td>"
        + "".join(f'<td class="num">{esc(_fmt(k, stats[n].get(k)))}</td>' for n in names)
        + "</tr>"
        for k in keys
    )
    strategy = config.get("strategy") or {}
    strategy_rows = ""
    if strategy.get("type"):
        strategy_rows = (f"<table><tr><td>Strategy</td><td>{esc(str(strategy['type']))}</td></tr>"
                         f"{_kv_rows(strategy.get('parameters', {}))}</table>")  # fmt: skip
    notes_html = "<ul>" + "".join(f"<li>{esc(n)}</li>" for n in notes) + "</ul>" if notes else ""
    execution = _kv_rows(config.get("execution", {})) + _kv_rows(config.get("costs", {}))
    if config.get("timing"):
        execution += f"<tr><td>Order timing</td><td>{esc(str(config['timing']))}</td></tr>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{esc(title)}</title>
{_CSS}</head><body>
<h1>{esc(title)}</h1><p class="muted">Quant Lab research summary, generated
{esc(str(config.get("generated_at", "")))}. Historical simulation, not a forecast or advice.</p>
{banner}
<h2>Equity</h2>{_svg_chart(curves)}
<h2>Statistics</h2><table><tr><th>Statistic</th>{head}</tr>{rows}</table>
{_section("Strategy", strategy_rows)}
{_section("Execution assumptions", f"<table>{execution}</table>" if execution else "")}
{_section("Data", f"<table>{_kv_rows(data)}</table>" if data else "")}
{_section("Notes and limitations", notes_html)}
{_section("Environment", f"<table>{_kv_rows(config.get('environment', {}))}</table>"
          if config.get("environment") else "")}
</body></html>"""
