"""Dashboard tests on offline synthetic data, run through Streamlit's own test harness."""

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("streamlit")
pytest.importorskip("plotly")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parents[2] / "app"
PAGES = sorted((APP / "views").glob("*.py"))
SYNTH = "Synthetic demo data"


def render(script, monkeypatch, **state):
    monkeypatch.syspath_prepend(str(APP))
    at = AppTest.from_file(str(script), default_timeout=180)
    at.session_state["p_source"] = SYNTH
    for key, value in state.items():
        at.session_state[key] = value
    return at.run()


def page(name):
    return APP / "views" / f"{name}.py"


def test_there_are_nine_pages_and_the_router_lists_them_all():
    assert len(PAGES) == 9  # the Investment Lab was added to the original eight
    router = (APP / "main.py").read_text()
    for p in PAGES:
        assert f"views/{p.name}" in router
    # Regression: a folder named "pages" next to the entry point makes Streamlit serve a
    # direct link (e.g. /invest) on a fresh server WITHOUT running main.py, so the grouped
    # navigation and logo were missing. The page files therefore must not live in "pages".
    assert not (APP / "pages").exists()


def test_router_starts_on_the_overview(monkeypatch):
    at = render(APP / "main.py", monkeypatch)
    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value == "Quant Lab"


@pytest.mark.parametrize("script", PAGES, ids=lambda p: p.stem)
def test_page_renders(script, monkeypatch):
    at = render(script, monkeypatch)
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]


@pytest.mark.parametrize("script", PAGES, ids=lambda p: p.stem)
def test_synthetic_data_is_always_labelled(script, monkeypatch):
    at = render(script, monkeypatch)
    assert any("SYNTHETIC DEMO DATA" in m.value for m in at.markdown)
    assert any("not market history" in w.value for w in at.warning)


EDGE_STATES = {
    "one_year": {"p_start": date(2024, 1, 1)},  # regression: Risk page slider min == max crash
    "two_months": {"p_start": date(2024, 11, 1)},
    "single_ticker": {"p_syn_tick": "SYN1"},
    "duplicate_and_lowercase_tickers": {"p_syn_tick": "syn1, syn2 ,SYN1"},
    "no_tickers": {"p_syn_tick": " , "},
    "malformed_ticker": {"p_syn_tick": "SYN1, <script>"},
    "too_many_tickers": {"p_syn_tick": ",".join(f"T{i}" for i in range(12))},
}


@pytest.mark.parametrize("script", PAGES, ids=lambda p: p.stem)
@pytest.mark.parametrize("state", EDGE_STATES.values(), ids=EDGE_STATES.keys())
def test_page_never_crashes_on_awkward_inputs(script, state, monkeypatch):
    """Awkward inputs may produce a clear st.error message, never an exception."""
    at = render(script, monkeypatch, **state)
    assert not at.exception, [e.value for e in at.exception]


@pytest.mark.parametrize("bad,expected", [(" , ", "at least one ticker"), ("SYN1, <script>", "Not valid"),
                                          (",".join(f"T{i}" for i in range(12)), "at most 10")])  # fmt: skip
def test_invalid_ticker_input_explains_itself(bad, expected, monkeypatch):
    at = render(page("overview"), monkeypatch, p_syn_tick=bad)
    assert any(expected in e.value for e in at.error)


# ----------------------------------------------------------------- live source and refresh


@pytest.fixture
def live(tmp_path, monkeypatch):
    """The dashboard wired to an offline scripted provider with a settable clock."""
    pytest.importorskip("exchange_calendars")
    monkeypatch.syspath_prepend(str(APP))
    import components.common as common
    from fixtures.live import CALENDAR, Clock, ScriptedYahoo, sessions

    from quantlab.data import LiveDataStore

    clock = Clock("2026-11-12 17:00")
    history = sessions("2023-01-03", "2026-11-12")
    provider = ScriptedYahoo(clock, {"AAA": list(history), "BBB": list(history)})
    store = LiveDataStore(provider, tmp_path, CALENDAR, clock)
    monkeypatch.setattr(common, "live_store", lambda: store)

    def open_page(name="overview", **state):
        return render(page(name), monkeypatch, p_source=common.LIVE, p_tick="AAA, BBB",
                      p_start=date(2023, 1, 1), **state)  # fmt: skip

    return type("Live", (), {"clock": clock, "provider": provider, "store": store,
                             "open": staticmethod(open_page), "common": common})  # fmt: skip


def headline(at) -> str:
    texts = [e.value for group in (at.success, at.info, at.warning, at.caption) for e in group]
    return next(t for t in texts if "completed" in t or "Refresh" in t or "Updated" in t or "Loaded" in t)


def badge(at) -> str:
    return next(m.value for m in at.markdown if 'class="ql-badge' in m.value)


def test_live_page_states_how_current_the_data_is_without_redownloading(live):
    at = live.open()
    assert not at.exception and "YAHOO DAILY DATA" in badge(at) and "to 2026-11-12" in badge(at)
    assert "Loaded" in headline(at) and "current through 2026-11-12" in headline(at)
    assert "new completed session" not in headline(at)
    assert live.provider.requests == 2  # one request per instrument, once
    at.run()
    at.run()
    assert live.provider.requests == 2  # ordinary reruns do not download again
    assert "Latest available completed daily data is current through 2026-11-12" in headline(at)
    status = at.table[0].value.iloc[:, 0]
    assert status["Latest completed exchange session"] == "2026-11-12 (XNYS)"
    assert status["This view was served from"] == "the verified cache"
    assert status["Last successful retrieval"] == "2026-11-12 17:00:00 ET"
    assert "not a live quote feed" in status["Provider"]


def test_refresh_button_makes_a_real_request_and_reports_unchanged(live):
    at = live.open()
    live.clock.advance(minutes=5)
    at.button(key="refresh_live").click().run()
    assert live.provider.requests == 4 and not at.exception
    assert "Checked; unchanged" in headline(at) and "2026-11-12 17:05:00 ET" in headline(at)
    assert not at.success  # nothing new arrived, so nothing is reported as a success
    at.run()  # the outcome of the last request stays visible in the status table
    assert "2026-11-12 17:05:00 ET (unchanged)" in at.table[0].value.iloc[:, 0]["Last provider request"]


def test_refresh_is_rate_limited_and_says_so(live):
    at = live.open()
    live.clock.advance(minutes=5)
    at.button(key="refresh_live").click().run()
    live.clock.advance(seconds=20)
    at.button(key="refresh_live").click().run()
    assert live.provider.requests == 4  # the second click sent nothing
    assert "Refresh limited" in headline(at) and "Try again after 2026-11-12 17:06:00 ET" in headline(at)


def test_a_newly_completed_session_updates_the_dashboard_and_its_calculations(live):
    at = live.open("backtest")
    before = {m.label: m.value for m in at.metric}
    live.provider.published["AAA"].append("2026-11-13")
    live.provider.published["BBB"].append("2026-11-13")
    live.clock.set("2026-11-13 15:59")  # session still open: nothing changes
    at.run()
    assert "to 2026-11-12" in badge(at) and live.provider.requests == 2
    live.clock.set("2026-11-13 16:00")
    at.run()
    assert "to 2026-11-13" in badge(at) and at.success and "1 new completed session" in headline(at)
    after = {m.label: m.value for m in at.metric}
    assert after != before  # the backtest was recomputed on the new observation
    assert any("sessions evaluated" in s.value for s in at.success)


def test_refresh_failure_keeps_the_page_working_on_verified_data(live):
    from quantlab.data import DataProviderError

    at = live.open("backtest")
    live.provider.error = DataProviderError("yfinance failed for AAA: HTTP 429 Too Many Requests")
    live.clock.set("2026-11-13 16:10")
    at.run()
    assert not at.exception and "to 2026-11-12" in badge(at)  # still showing the verified data
    text = next(w.value for w in at.warning if "Refresh failed" in w.value)
    assert "rate limiting" in text and "last verified data" in text and "current through" not in text
    assert len(at.metric) >= 5  # the backtest still rendered
    status = at.table[0].value.iloc[:, 0]
    assert status["Overall status"] == "awaiting provider" and "429" in status["Last error"]


def test_no_cache_and_no_provider_is_reported_as_no_usable_data(live):
    from quantlab.data import DataProviderError

    live.provider.error = DataProviderError("network unreachable")
    at = live.open()
    assert not at.exception
    assert any("No usable data" in e.value and "network unreachable" in e.value for e in at.error)
    assert any(b.label == "Switch to synthetic demo data" for b in at.button)
    assert not any('class="ql-badge' in m.value for m in at.markdown)  # nothing is shown as data


@pytest.mark.parametrize("name", ["invest", "market", "strategy", "backtest", "risk", "monte_carlo", "stress", "research"])
def test_every_page_works_on_the_refreshable_source(live, name):
    at = live.open(name)
    assert not at.exception and not at.error
    assert "YAHOO DAILY DATA" in badge(at)


def test_other_sources_have_no_refresh_control_and_never_touch_the_store(live, monkeypatch):
    synthetic = render(page("overview"), monkeypatch)
    assert not any(b.key == "refresh_live" for b in synthetic.button)
    assert not any("completed daily data" in c.value for c in synthetic.caption)
    assert not synthetic.table  # no market-data status panel
    assert live.provider.requests == 0
    if any((APP.parent / "experiments" / "data").glob("*/metadata.json")):
        frozen = render(page("overview"), monkeypatch, p_source=live.common.FROZEN)
        assert not frozen.exception and not any(b.key == "refresh_live" for b in frozen.button)
        assert "FROZEN RESEARCH SNAPSHOT" in badge(frozen) and live.provider.requests == 0


def test_synthetic_instruments_never_carry_real_ticker_names(monkeypatch):
    at = render(page("overview"), monkeypatch)
    meta = next(m.value for m in at.markdown if "SYNTHETIC DEMO DATA" in m.value)
    assert "SYN1, SYN2, SYN3, SYN4, SYN5" in meta
    for real in ("SPY", "QQQ", "IWM", "TLT", "GLD"):
        assert real not in meta


def test_risk_page_rejects_leverage_and_handles_all_cash(monkeypatch):
    at = render(page("risk"), monkeypatch)
    at.number_input(key="p_w_SYN1").set_value(90.0).run()
    assert any("Leverage is not supported" in e.value for e in at.error) and not at.exception
    at = render(page("risk"), monkeypatch)
    for ticker in ("SYN1", "SYN2", "SYN3", "SYN4", "SYN5"):
        at.number_input(key=f"p_w_{ticker}").set_value(0.0)
    at.run()
    assert any("100% cash" in i.value for i in at.info) and not at.exception


@pytest.mark.parametrize("kind", ["Trend following", "Mean reversion", "Cross-sectional momentum"])
@pytest.mark.parametrize("name", ["strategy", "backtest"])
def test_every_strategy_runs_on_both_strategy_pages(kind, name, monkeypatch):
    at = render(page(name), monkeypatch, p_kind=kind)
    assert not at.exception and not at.error
    assert all(m.value not in ("nan", "nan%") for m in at.metric)


@pytest.mark.parametrize("state,message", [
    ({"p_fast": 200, "p_slow": 50}, "fast window must be shorter"),
    ({"p_kind": "Mean reversion", "p_mr_in": 1.0, "p_mr_out": 2.0}, "entry z-score must be larger"),
    ({"p_assets": []}, None),
])  # fmt: skip
def test_impossible_strategy_parameters_are_explained(state, message, monkeypatch):
    at = render(page("backtest"), monkeypatch, **state)
    assert not at.exception
    if message:
        assert any(message in e.value for e in at.error)


def test_insufficient_history_is_reported_not_hidden(monkeypatch):
    at = render(page("backtest"), monkeypatch, p_start=date(2024, 6, 1))
    assert not at.exception
    assert any("never traded" in w.value for w in at.warning)


def test_backtest_numbers_and_exports_match_the_library(monkeypatch):
    from quantlab.analytics import performance_summary
    from quantlab.backtesting import backtest_strategy
    from quantlab.data import SyntheticProvider
    from quantlab.execution import ExecutionConfig
    from quantlab.strategies import TrendFollowing

    at = render(page("backtest"), monkeypatch)
    data = SyntheticProvider(7).fetch(["SYN1", "SYN2", "SYN3", "SYN4", "SYN5"], "2005-01-01")
    res = backtest_strategy(TrendFollowing(50, 200, ("SYN1",)), data, ExecutionConfig())
    stats = performance_summary(res.returns)
    shown = {m.label: m.value for m in at.metric}
    assert shown["CAGR"] == f"{stats['cagr']:.2%}"
    assert shown["Max drawdown"] == f"{stats['max_drawdown']:.2%}"
    assert shown["Sharpe ratio"] == f"{stats['sharpe']:.2f}"
    assert shown["Fills"] == f"{len(res.trades):,}"
    labels = [b.label for b in at.get("download_button")]
    for expected in ("Equity & returns (CSV)", "Statistics (CSV)", "Trade log (CSV)", "Statistics (JSON)",
                     "Configuration (JSON)", "Research summary (HTML)"):  # fmt: skip
        assert expected in labels


def test_changing_costs_changes_the_result(monkeypatch):
    cheap = render(page("backtest"), monkeypatch, p_slip=0.0, p_fee=0.0)
    dear = render(page("backtest"), monkeypatch, p_slip=50.0, p_fee=50.0)
    pct = lambda at: float({m.label: m.value for m in at.metric}["CAGR"].rstrip("%"))  # noqa: E731
    assert pct(dear) < pct(cheap)


def test_monte_carlo_is_reproducible_from_its_seed(monkeypatch):
    def fingerprint(at):
        return next(c.value for c in at.caption if "Run fingerprint" in c.value)

    a, b = render(page("monte_carlo"), monkeypatch), render(page("monte_carlo"), monkeypatch)
    assert fingerprint(a) == fingerprint(b)
    seed_box = next(n for n in b.number_input if n.label == "Random seed")
    seed_box.set_value(43).run()
    assert fingerprint(b) != fingerprint(a) and not b.exception


def test_oversized_simulation_is_refused_with_an_explanation(monkeypatch):
    at = render(page("monte_carlo"), monkeypatch)
    next(n for n in at.number_input if n.label == "Simulated paths").set_value(20_000)
    next(n for n in at.number_input if n.label == "Horizon (sessions)").set_value(2520)
    at.run()
    assert not at.exception
    assert any("above this app's limit" in e.value for e in at.error)


@pytest.mark.skipif(not list((APP.parent / "experiments" / "results").glob("trend_vs_buyhold_*.json")),
                    reason="the restricted-data study record is not part of this copy")
def test_published_study_page_shows_the_recorded_numbers(monkeypatch):
    root = APP.parent
    record = json.loads(next((root / "experiments" / "results").glob("trend_vs_buyhold_*.json")).read_text())
    rows = {r.get("name") or r.get("index"): r for r in record["results"]["assets"]["SPY"]["out_of_sample"]}
    at = render(page("research"), monkeypatch)
    table = at.dataframe[0].value
    assert table.loc["CAGR", "Trend 50/200"] == f"{rows['trend_50_200']['cagr']:.2%}"
    assert table.loc["Max drawdown", "Buy and hold"] == f"{rows['buy_and_hold']['max_drawdown']:.2%}"
    assert any("no longer untouched" in w.value for w in at.warning)
    # regression: statuses were misaligned and displayed as None
    intervals = at.dataframe[1].value
    assert list(intervals["Status"]) == ["confirmatory"] * 3 + ["exploratory"] * 2
    assert list(intervals["Excl. 0"]) == ["no", "yes", "yes", "yes", "no"]
    assert isinstance(table, pd.DataFrame)


# ----------------------------------------------------------------- Investment Lab


def lab(monkeypatch, **state):
    return render(page("invest"), monkeypatch, **state)


def metrics(at) -> dict:
    return {m.label: m.value for m in at.metric}


def compare_table(at) -> pd.DataFrame:
    return next(d.value for d in at.dataframe if "Final value" in d.value.index)


def expected_default_comparison():
    from quantlab.data import SyntheticProvider
    from quantlab.execution import ExecutionConfig
    from quantlab.portfolio.compare import benchmark_specs, compare_portfolios
    from quantlab.portfolio.spec import PortfolioSpec

    names = ["SYN1", "SYN2", "SYN3", "SYN4", "SYN5"]
    data = SyntheticProvider(7).fetch(names, "2005-01-01")
    a = PortfolioSpec({"SYN1": 0.6, "SYN2": 0.4}, 10_000.0, 500.0, "M", "A", "Portfolio A")
    b = PortfolioSpec({n: 0.2 for n in names}, 10_000.0, 500.0, "M", None, "Portfolio B")
    cfg = ExecutionConfig(initial_capital=10_000.0, slippage_bps=2.0, fee_bps=1.0)
    return compare_portfolios(data, {"Portfolio A": a, "Portfolio B": b, **benchmark_specs(a)}, cfg, 0.0)


def test_investment_lab_shows_exactly_what_the_engine_computes(monkeypatch):
    at = lab(monkeypatch)
    assert not at.exception and not at.error
    expected = expected_default_comparison()
    stats = expected.stats["Portfolio A"]
    shown = metrics(at)
    assert shown["Final value"] == f"{stats['final_value']:,.0f}"
    assert shown["Total paid in"] == f"{stats['total_invested']:,.0f}"
    assert shown["Gain"] == f"{stats['gain']:,.0f}"
    assert shown["Time-weighted p.a."] == f"{stats['time_weighted_annual']:.2%}"
    assert shown["Money-weighted p.a."] == f"{stats['money_weighted_annual']:.2%}"
    assert shown["Max drawdown"] == f"{stats['max_drawdown']:.2%}"
    table = compare_table(at)
    assert list(table.columns) == ["Portfolio A", "Portfolio B", "100% SYN1", "Equal weight",
                                   "Same weights, never rebalanced"]  # fmt: skip
    for name in table.columns:  # every column is the engine's number, not an approximation
        assert table.loc["Final value", name] == f"{expected.stats[name]['final_value']:,.0f}"
        assert table.loc["Largest drift from target", name] == f"{expected.stats[name]['drift_max']:.2%}"
    assert len(set(table.loc["Total paid in"])) == 1  # identical funding for all
    window = next(m.value for m in at.markdown if "HISTORICAL SIMULATION" in m.value)
    assert "2005-01-03 to 2024-12-31" in window and "same window, calendar and costs" in window


def test_changing_an_allocation_changes_the_results_and_the_cash_remainder(monkeypatch):
    at = lab(monkeypatch)
    before = metrics(at)["Final value"]
    at.number_input(key="p_il_w_A_SYN1").set_value(30.0).run()
    assert not at.exception and metrics(at)["Final value"] != before
    assert any(m.value == "30.0%" for m in at.markdown)  # 30 + 40 leaves 30% in cash
    at.number_input(key="p_il_w_A_SYN2").set_value(90.0).run()
    assert any("adds up to 120.0%" in e.value and "Leverage is not supported" in e.value for e in at.error)
    assert not at.metric  # nothing is computed for an invalid portfolio


def test_third_portfolio_benchmarks_and_names(monkeypatch):
    at = lab(monkeypatch, p_il_on_C=True, p_il_name_C="Cautious")
    assert "Cautious" in compare_table(at).columns and len(compare_table(at).columns) == 6
    at = lab(monkeypatch, p_il_name_B="Portfolio A")
    assert any("different, non-empty name" in e.value for e in at.error) and not at.exception
    # regression: every rebalancing box shows a real choice, never an empty placeholder
    boxes = {b.key: b.value for b in at.selectbox if str(b.key).startswith("p_il_reb_")}
    assert boxes == {"p_il_reb_A": "A", "p_il_reb_B": "never", "p_il_reb_C": "never"}
    alone = lab(monkeypatch, p_il_on_B=False)
    assert list(compare_table(alone).columns)[0] == "Portfolio A" and "Portfolio B" not in compare_table(alone).columns


def test_contribution_settings_flow_through_and_timeline_shows_next_open_investment(monkeypatch):
    none = lab(monkeypatch, p_il_contrib=0.0)
    assert metrics(none)["Total paid in"] == "10,000"
    assert any("No recurring contribution" in c.value for c in none.caption)
    at = lab(monkeypatch, p_il_contrib=250.0, p_il_freq="Q")
    timeline = next(d.value for d in at.dataframe if "Contribution arrived (open)" in d.value.columns)
    assert len(timeline) == 8 and set(timeline["Amount"]) == {"250"}
    assert (timeline["Invested (next open)"] > timeline["Contribution arrived (open)"]).all()
    assert (timeline["Decision (close)"] == timeline["Contribution arrived (open)"]).all()
    quarters = pd.to_datetime(timeline["Contribution arrived (open)"]).dt.month
    assert set(quarters) <= {1, 4, 7, 10}


def test_costs_reduce_the_outcome_and_rebalancing_reduces_drift(monkeypatch):
    def value(at, row, column="Portfolio A"):
        return float(compare_table(at).loc[row, column].replace(",", "").rstrip("%"))

    cheap, dear = lab(monkeypatch, p_il_slip=0.0, p_il_fee=0.0), lab(monkeypatch, p_il_slip=40.0, p_il_fee=40.0)
    assert value(dear, "Final value") < value(cheap, "Final value")
    assert value(dear, "Trading cost paid") > value(cheap, "Trading cost paid") == 0.0
    never, monthly = lab(monkeypatch, p_il_reb_A="never"), lab(monkeypatch, p_il_reb_A="M")
    assert value(monthly, "Average drift from target") < value(never, "Average drift from target")


def test_all_cash_and_short_history_are_explained_not_crashed(monkeypatch):
    cash = lab(monkeypatch, p_il_w_A_SYN1=0.0, p_il_w_A_SYN2=0.0)
    assert not cash.exception and any("100% cash" in i.value for i in cash.info)
    short = lab(monkeypatch, p_start=date(2024, 11, 20))
    assert not short.exception
    assert any("cannot be compared on this dataset" in e.value for e in short.error)


def test_investment_lab_labels_estimates_history_and_data_honestly(monkeypatch):
    at = lab(monkeypatch)
    text = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert "SYNTHETIC DEMO DATA" in text and "HISTORICAL" in text and "ESTIMATED" in text
    assert "not executable quotes" in text and "not a forecast" in text
    assert "This is not advice" in text
    for banned in ("guarantee", "will outperform", "recommended allocation", "confidence score"):
        assert banned not in text.lower()
    labels = [b.label for b in at.get("download_button")]
    for expected in ("Portfolio file (JSON)", "Full analysis (JSON)", "Statistics (CSV)",
                     "Values over time (CSV)", "Summary (HTML)"):  # fmt: skip
        assert expected in labels


def test_investment_lab_reports_stale_provider_data(live):
    at = live.open("invest")
    live.provider.error = __import__("quantlab.data", fromlist=["DataProviderError"]).DataProviderError("down")
    live.clock.set("2026-11-16 12:00")  # a full session has been missed
    at.run()
    assert not at.exception and any("Refresh failed" in w.value for w in at.warning)
    assert "Final value" in metrics(at)  # still usable on the last verified data, with the warning
