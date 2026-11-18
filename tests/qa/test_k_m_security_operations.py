"""Suites K and M: security / resilience, and performance / operational behaviour.

Only local, harmless inputs are used. Timing assertions are loose upper bounds that
catch a pathological regression; the measured figures are reported in docs/qa.
"""

import ast
import io
import json
import re
import socket
import subprocess
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fixtures.app import APP, SYNTH, USER, VIEWS, render, texts, view
from fixtures.live import CALENDAR, Clock, ScriptedYahoo

from quantlab.backtesting import backtest_strategy
from quantlab.data import DataError, LiveDataStore, SyntheticProvider
from quantlab.data.providers import CsvProvider, read_ohlcv_csv
from quantlab.execution import ExecutionConfig
from quantlab.portfolio.compare import benchmark_specs, compare_portfolios
from quantlab.portfolio.spec import PortfolioSpec
from quantlab.reporting import csv_bytes, html_report, json_bytes
from quantlab.simulations import simulate
from quantlab.strategies import TrendFollowing

ROOT = Path(__file__).resolve().parents[2]
EVIL = "<img src=x onerror=alert(1)>"
FORMULAS = ("=cmd|'/C calc'!A0", "+SUM(A1:A9)", "-2+3", "@SUM(A1)")


def bars(n=300, **columns):
    days = pd.bdate_range("2020-01-01", periods=n)
    frame = pd.DataFrame({"date": days.strftime("%Y-%m-%d"), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0})
    return frame.assign(**columns)


def parse(text, ticker="X"):
    return read_ohlcv_csv(io.StringIO(text) if isinstance(text, str) else io.BytesIO(text), ticker)


def tracked_files():
    listed = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return [ROOT / line for line in listed.stdout.splitlines() if (ROOT / line).is_file()]


# ================================================================= Suite K: security and resilience


@pytest.mark.parametrize(
    "payload, reason",
    [
        ("", "could not read CSV"),
        (bytes(range(256)) * 40, "could not read CSV"),  # binary renamed to .csv
        (bars().to_csv(index=False, sep=";"), "missing ['open', 'high', 'low', 'close']"),
        ("a,b\n1,2\n", "missing"),
        (bars().assign(date="not a date").to_csv(index=False), "could not parse dates"),
        (bars().astype({"close": object}).assign(close="=1+1").to_csv(index=False), "non-numeric"),
        (bars().astype({"close": object}).assign(close="1e5; DROP TABLE").to_csv(index=False), "non-numeric"),
    ],
)
def test_k01_malformed_uploads_are_rejected_with_a_reason(payload, reason):
    with pytest.raises(DataError) as error:
        parse(payload)
    assert reason in str(error.value) and "Traceback" not in str(error.value)


@pytest.mark.parametrize("column, value, reason", [("close", -5.0, "non-positive"), ("close", np.inf, "non-finite"),
                                                   ("high", 90.0, "high < low")])  # fmt: skip
def test_k02_impossible_prices_in_an_upload_are_refused_not_repaired(column, value, reason):
    with pytest.raises(DataError, match=reason):
        CsvProvider({"X": parse(bars(**{column: value}).to_csv(index=False))}).fetch(["X"])


def test_k03_unicode_bom_timezones_duplicates_and_ordering_are_handled_openly():
    plain = CsvProvider({"X": parse(bars().to_csv(index=False))}).fetch(["X"])
    bom = CsvProvider({"X": parse("﻿" + bars().to_csv(index=False))}).fetch(["X"])
    stamped = bars().assign(date=lambda f: f["date"] + "T16:00:00-05:00")
    zoned = CsvProvider({"X": parse(stamped.to_csv(index=False))}).fetch(["X"])
    reverse = CsvProvider({"X": parse(bars().iloc[::-1].to_csv(index=False))}).fetch(["X"])
    for other in (bom, zoned, reverse):
        assert list(other.dates) == list(plain.dates) and other.dates.tz is None
    twice = bars()
    twice.loc[5, "date"] = twice.loc[4, "date"]
    merged = CsvProvider({"X": parse(twice.to_csv(index=False))}).fetch(["X"])
    assert len(merged.dates) == 299 and any("duplicate" in n for n in merged.metadata.notes)
    assert plain.metadata.source == "user-csv" and not plain.metadata.synthetic


def test_k04_large_upload_is_bounded_by_configuration_and_parses_in_bounded_time():
    config = (ROOT / ".streamlit" / "config.toml").read_text()
    assert re.search(r"maxUploadSize\s*=\s*20\b", config)  # megabytes, enforced by the server
    text = bars(200_000).to_csv(index=False)  # ~7 MB, 790 years of sessions
    began = time.perf_counter()
    frame = parse(text)
    assert len(frame) == 200_000 and time.perf_counter() - began < 20


def test_k05_html_report_escapes_every_user_controlled_string():
    curves = pd.DataFrame({EVIL: [1.0, 1.1]}, index=pd.bdate_range("2020-01-01", periods=2))
    config = {"data": {"source": EVIL, "tickers": [EVIL], "notes": [EVIL]}, "strategy": {"type": EVIL},
              "execution": {EVIL: EVIL}}  # fmt: skip
    page = html_report("<script>alert(1)</script>", {EVIL: {"cagr": 0.1}}, curves, config, [EVIL], {"cagr": EVIL})
    assert "<script" not in page and "<img" not in page and "onerror=alert(1)&gt;" in page
    assert "http://" not in page and "https://" not in page  # self-contained: nothing is fetched


def test_k06_json_exports_are_strict_json_and_inert():
    exported = json_bytes({"a": float("inf"), "b": float("nan"), "c": EVIL, "d": pd.Timestamp("2020-01-01")})
    parsed = json.loads(exported, parse_constant=lambda name: pytest.fail(f"non-standard JSON token {name}"))
    assert parsed["a"] is None and parsed["b"] is None and parsed["c"] == EVIL


def test_k07_csv_formula_cells_are_neutralised_and_numbers_are_untouched():
    """QA-004 (fixed): text starting with = + - @ is prefixed with an apostrophe."""
    for name in FORMULAS:
        table = pd.DataFrame({name: [1.0], "note": [name]}, index=pd.Index([name], name="statistic"))
        parsed = pd.read_csv(io.BytesIO(csv_bytes(table, "statistic")))
        assert list(parsed.columns) == ["statistic", "'" + name, "note"]
        assert parsed.loc[0, "statistic"] == "'" + name and parsed.loc[0, "note"] == "'" + name
    numbers = pd.DataFrame({"return": [-0.25, 0.1]}, index=pd.Index(["a", "b"], name="row"))
    assert pd.read_csv(io.BytesIO(csv_bytes(numbers, "row")))["return"].tolist() == [-0.25, 0.1]


def test_k07b_csv_exports_neutralise_leading_formula_characters():
    market = SyntheticProvider(3).fetch(["AAA"], "2019-01-01", "2020-12-31")
    spec = PortfolioSpec({"AAA": 1.0}, 10_000, 0.0, "M", None, FORMULAS[0])  # was invalid in QA run
    result = compare_portfolios(market, {FORMULAS[0]: spec}, ExecutionConfig())
    header = csv_bytes(result.table(["final_value"]), "statistic").decode().splitlines()[0]
    assert not any(cell.strip('"').startswith(("=", "+", "-", "@")) for cell in header.split(",")[1:])
    trades = backtest_strategy(TrendFollowing(20, 60, ("AAA",)), market).trades.assign(note="=1+1")
    assert "'=1+1" in csv_bytes(trades, index=False).decode()  # the trade log route too


@pytest.mark.parametrize("start", ["../../../escaped", "2020-01-01/../../x", "", "2020-13-45", "20200101"])
def test_k08_store_refuses_a_start_that_is_not_a_date(tmp_path, start):
    """QA-005 (fixed): nothing but an ISO date reaches the folder name."""
    cache, clock = tmp_path / "deep" / "cache", Clock("2026-11-12 17:00")
    store = LiveDataStore(ScriptedYahoo(clock, {"SPY": ["2026-11-10", "2026-11-11", "2026-11-12"]}), cache, CALENDAR, clock)
    with pytest.raises(ValueError):
        store.get(["SPY"], start)
    assert not any(tmp_path.rglob("CURRENT"))  # nothing was written anywhere


@pytest.mark.parametrize("ticker", ["../SPY", "SPY/../../x", "A B", "", "X" * 40, "SPY\\..\\x"])
def test_k08b_store_refuses_tickers_that_are_not_plain_symbols(tmp_path, ticker):
    clock = Clock("2026-11-12 17:00")
    store = LiveDataStore(ScriptedYahoo(clock, {"SPY": ["2026-11-12"]}), tmp_path / "deep" / "cache", CALENDAR, clock)
    with pytest.raises(ValueError):
        store.get([ticker], "2026-11-01")
    assert store.get(["SPY"], "2026-11-01").data is not None  # a valid request still works


def corrupted_store(tmp_path):
    clock = Clock("2026-11-12 17:00")
    provider = ScriptedYahoo(clock, {"SPY": ["2026-11-10", "2026-11-11", "2026-11-12"]})
    LiveDataStore(provider, tmp_path, CALENDAR, clock).get(["SPY"], "2026-11-01")
    folder = next(p for p in tmp_path.iterdir() if p.is_dir())
    (folder / (folder / "CURRENT").read_text().strip() / "open.csv").unlink()
    clock.advance(minutes=30)
    return LiveDataStore(provider, tmp_path, CALENDAR, clock).get(["SPY"], "2026-11-01")


def test_k09_cache_recovery_still_works_and_names_the_problem(tmp_path):
    result = corrupted_store(tmp_path)
    assert any("unusable" in note and "open.csv" in note for note in result.notes)
    assert result.data is not None


def test_k09b_user_facing_notes_contain_no_server_paths(tmp_path):
    """QA-008 (fixed): only the file name is shown, never the server's directory layout."""
    result = corrupted_store(tmp_path)
    assert not any(str(tmp_path) in note for note in result.notes)
    from quantlab.data.refresh import describe_error, safe_message

    assert safe_message("cannot open '/srv/app/.data_cache/a/v-1/close.csv'") == "cannot open 'close.csv'"
    assert "/home/" not in describe_error(PermissionError(13, "Permission denied", "/home/u/x/y.lock"))


def user_page(monkeypatch, ticker):
    frames = {ticker: parse(bars().to_csv(index=False), "X")}
    return render(view("overview"), monkeypatch, p_source=USER, user_frames=frames)


def test_k10_instrument_names_are_escaped_in_the_data_source_badge(monkeypatch):
    """QA-015 (fixed): even a name that bypassed upload validation is rendered inert."""
    at = user_page(monkeypatch, EVIL.upper())
    assert not at.exception
    badge = next(m.value for m in at.markdown if 'class="ql-badge' in m.value)
    assert "&lt;IMG SRC=X ONERROR=ALERT(1)&gt;" in badge


def test_k10b_badge_escapes_instrument_names_and_uploads_must_be_named_as_tickers(monkeypatch):
    at = user_page(monkeypatch, EVIL.upper())
    badge = next(m.value for m in at.markdown if 'class="ql-badge' in m.value)
    assert "<IMG" not in badge
    source = (ROOT / "app" / "components" / "common.py").read_text()
    upload = source[source.index("def _user_data"):source.index("def load_data")]
    assert "TICKER_RE.match(ticker)" in upload  # file names are validated like typed tickers


def test_k11_no_dynamic_code_execution_shell_or_unsafe_deserialisation():
    banned_calls = {"eval", "exec", "compile", "__import__"}
    banned_modules = {"pickle", "marshal", "shelve", "yaml", "dill"}
    shells = []
    for path in [*ROOT.glob("src/**/*.py"), *ROOT.glob("app/**/*.py")]:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in banned_calls, f"{path}: {node.func.id}()"
            if isinstance(node, ast.Call):
                assert not any(k.arg == "shell" for k in node.keywords), f"{path}: shell= argument"
            if isinstance(node, ast.Import):
                shells += [path.name for a in node.names if a.name == "subprocess"]
                assert not {a.name for a in node.names} & banned_modules, path
            if isinstance(node, ast.ImportFrom):
                assert node.module not in banned_modules, path
            if isinstance(node, ast.Attribute) and node.attr in {"read_pickle", "to_pickle", "system", "popen"}:
                pytest.fail(f"{path}: .{node.attr}")
    # One module runs fixed argument lists (git commit id, installed versions) for provenance.
    assert shells == ["experiment.py"]


def test_k12_raw_html_is_only_used_in_known_places():
    """Every unsafe_allow_html call is a place where unescaped input would matter. The list is
    fixed here so a new one has to be reviewed."""
    found = {}
    for path in ROOT.glob("app/**/*.py"):
        count = path.read_text().count("unsafe_allow_html=True")
        if count:
            found[str(path.relative_to(ROOT))] = count
    assert found == {"app/components/common.py": 3, "app/components/portfolio.py": 1,
                     "app/components/future_wealth.py": 2,  # constant labels, dates and numbers only
                     "app/views/invest.py": 4, "app/views/overview.py": 1}, found  # fmt: skip


def test_k13_no_credentials_or_private_keys_in_tracked_files():
    patterns = [r"AKIA[0-9A-Z]{16}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"ghp_[A-Za-z0-9]{36}",
                r"sk-[A-Za-z0-9]{32,}", r"xox[baprs]-[A-Za-z0-9-]{10,}",
                r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*[\"'][A-Za-z0-9+/_\-]{16,}[\"']"]  # fmt: skip
    hits = []
    for path in tracked_files():
        if path.suffix in {".csv", ".png", ".jpg", ".ico"} or path == Path(__file__):
            continue
        text = path.read_text(errors="ignore")
        hits += [f"{path.name}: {p}" for p in patterns if re.search(p, text)]
    assert not hits, hits
    names = {p.name for p in tracked_files()}
    assert not names & {".env", "secrets.toml", "credentials.json", "id_rsa"}
    ignored = (ROOT / ".gitignore").read_text()
    assert ".env" in ignored or "secrets" in ignored


def test_k14_pages_never_show_a_traceback_for_bad_input(monkeypatch):
    for name, state in [("invest", {"p_il_w_A_SYN1": 90.0, "p_il_w_A_SYN2": 90.0}),
                        ("stress", {}), ("risk", {})]:  # fmt: skip
        at = render(view(name), monkeypatch, **state)
        assert not at.exception, name
        assert "Traceback" not in texts(at) and "/home/" not in texts(at)


def test_k15_the_library_needs_no_network_and_opens_no_socket(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    for name in ("overview", "invest", "backtest", "risk", "monte_carlo", "stress"):
        at = render(view(name), monkeypatch, p_source=SYNTH)
        assert not at.exception, name


# ================================================================= Suite M: performance and operations


@pytest.fixture(scope="module")
def decade():
    return SyntheticProvider(11).fetch(["AAA", "BBB", "CCC"], "2010-01-01", "2024-12-31")


def timed(fn):
    began = time.perf_counter()
    out = fn()
    return out, time.perf_counter() - began


def test_m01_core_computations_finish_within_loose_bounds(decade):
    _, backtest = timed(lambda: backtest_strategy(TrendFollowing(50, 200, ("AAA",)), decade))
    spec = PortfolioSpec({"AAA": 0.5, "BBB": 0.3, "CCC": 0.2}, 10_000, 500.0, "M", "Q", "P")
    _, lab = timed(lambda: compare_portfolios(decade, {"P": spec, **benchmark_specs(spec)}, ExecutionConfig()))
    returns = decade.close["AAA"].pct_change().dropna()
    paths, monte = timed(lambda: simulate(returns, horizon=252, n_paths=5000, method="block", block=21, seed=1))
    assert backtest < 20 and lab < 30 and monte < 30  # typical: well under 2 s each
    assert paths.paths.shape[0] == 5000


def test_m02_backtest_cost_grows_roughly_linearly_with_history():
    short = SyntheticProvider(5).fetch(["AAA"], "2015-01-01", "2019-12-31")
    long = SyntheticProvider(5).fetch(["AAA"], "1995-01-01", "2019-12-31")
    strategy = TrendFollowing(20, 60, ("AAA",))
    best = {}
    for label, data in (("short", short), ("long", long)):
        best[label] = min(timed(lambda d=data: backtest_strategy(strategy, d))[1] for _ in range(3))
    assert len(long.dates) / len(short.dates) == pytest.approx(5, rel=0.05)
    assert best["long"] / best["short"] < 15  # five times the data must not cost 15x: no quadratic step


def test_m03_every_page_renders_from_a_cold_start_within_a_bound(monkeypatch):
    slow = {}
    for path in VIEWS:
        at, seconds = timed(lambda p=path: render(p, monkeypatch))
        assert not at.exception, path.name
        slow[path.stem] = seconds
    assert len(slow) == 9 and max(slow.values()) < 60, slow


def test_m04_router_registers_nine_pages_and_stable_urls():
    source = (APP / "main.py").read_text()
    pages = re.findall(r'st\.Page\("views/(\w+)\.py"', source)
    assert len(pages) == 9 == len(set(pages))  # the file stem is the URL path, so stems must be unique
    assert sorted(pages) == sorted(p.stem for p in VIEWS)


def test_m05_importing_the_library_does_not_load_the_dashboard_or_the_data_provider():
    code = ("import sys, quantlab, quantlab.backtesting, quantlab.analytics, quantlab.risk, "
            "quantlab.portfolio, quantlab.simulations, quantlab.research, quantlab.reporting;"
            "print(sorted(m for m in ('streamlit','yfinance','plotly','scipy','hypothesis') if m in sys.modules))")  # fmt: skip
    import sys

    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT / "src", check=True)
    assert out.stdout.strip() == "[]"


def test_m06_ci_runs_the_supported_versions_lint_tests_and_study_verification():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    for needle in ('"3.11", "3.12", "3.13"', "ruff check .", "python -m pytest", "trend_vs_buyhold.py --verify",
                   "python -m build --wheel"):  # fmt: skip
        assert needle in ci, needle


def test_m07_dependencies_are_declared_and_dev_tools_stay_out_of_the_runtime():
    import tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    runtime = " ".join(project["dependencies"])
    assert "numpy" in runtime and "pandas" in runtime
    for tool in ("pytest", "ruff", "hypothesis", "scipy", "streamlit", "yfinance"):
        assert tool not in runtime, tool
    assert any("hypothesis" in d for d in project["optional-dependencies"]["dev"])
    assert project["requires-python"].startswith(">=3.11")
