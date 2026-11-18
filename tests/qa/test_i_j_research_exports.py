"""Suites I and J: research integrity, and reporting / export correctness."""

import hashlib
import io
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fixtures.app import render, texts, view
from fixtures.synthetic import perturb_after

from quantlab.analytics import metrics as m
from quantlab.analytics import performance_summary
from quantlab.backtesting import backtest_strategy
from quantlab.data import SyntheticProvider
from quantlab.execution import ExecutionConfig
from quantlab.portfolio.compare import (
    analysis_record,
    benchmark_specs,
    compare_portfolios,
    load_portfolio_file,
    portfolio_file,
)
from quantlab.portfolio.spec import PortfolioSpec
from quantlab.reporting import backtest_bundle, config_hash, html_report
from quantlab.research import (
    TrialRegistry,
    bonferroni,
    bootstrap_ci,
    chronological_split,
    cost_sensitivity,
    holm,
    parameter_grid,
)
from quantlab.strategies import BuyAndHold, TrendFollowing

ROOT = Path(__file__).resolve().parents[2]
RECORD = next((ROOT / "experiments" / "results").glob("trend_vs_buyhold_*.json"), None)
needs_record = pytest.mark.skipif(RECORD is None, reason="the restricted-data study record is not part of this copy")


@pytest.fixture(scope="module")
def market():
    return SyntheticProvider(31).fetch(["AAA", "BBB"], "2012-01-01", "2021-12-31")


@pytest.fixture(scope="module")
def lab(market):
    spec = PortfolioSpec({"AAA": 0.6, "BBB": 0.4}, 10_000, 500.0, "M", "A", "Core")
    return compare_portfolios(market, {"Core": spec, **benchmark_specs(spec)}, ExecutionConfig(slippage_bps=2, fee_bps=1))


# ================================================================= Suite I: research integrity


def test_i01_decisions_fill_at_the_next_session_and_warm_up_is_respected(market):
    result = backtest_strategy(TrendFollowing(50, 200, ("AAA",)), market)
    sessions = list(market.dates)
    for _, trade in result.trades.iterrows():
        assert sessions.index(trade["date"]) == sessions.index(trade["decision_date"]) + 1
        assert trade["reference_price"] == market.open.loc[trade["date"], "AAA"]
    assert result.trades["decision_date"].min() >= market.dates[199]  # no signal before 200 closes
    assert result.holdings.iloc[:200].to_numpy().sum() == 0


def test_i02_split_is_chronological_and_the_grid_cannot_see_the_test_period(market):
    split = chronological_split(market.dates, "2017-12-29")
    assert split.development[1] < split.test[0] and split.development[0] == market.dates[0]
    assert set(split.slice(pd.Series(0, index=market.dates), "development").index).isdisjoint(
        split.slice(pd.Series(0, index=market.dates), "test").index)  # fmt: skip
    grid = {"fast": [10, 20, 50], "slow": [50, 100, 200]}

    def run(data, registry=None):
        return parameter_grid(lambda fast, slow: TrendFollowing(fast, slow, ("AAA",)), grid, data,
                              ExecutionConfig(), *split.development, registry=registry)  # fmt: skip

    registry = TrialRegistry()
    table = run(market, registry)
    valid = [(f, s) for f in grid["fast"] for s in grid["slow"] if f < s]
    assert len(table) == len(valid) == 8 == registry.count  # complete, and every trial is counted
    assert sorted(zip(table["fast"], table["slow"], strict=True)) == sorted(valid)
    pd.testing.assert_frame_equal(table, run(perturb_after(market, split.development[1])))
    run(market, registry)  # exploring again adds to the count: repeated looks are not free
    assert registry.count == 16 and registry.distinct_configurations() == 8


def test_i03_multiple_comparison_adjustments_by_hand():
    p = [0.004, 0.03, 0.02, 0.5]
    assert bonferroni(p) == pytest.approx([0.016, 0.12, 0.08, 1.0])
    # Holm: sorted 0.004x4=.016, 0.02x3=.06, 0.03x2=.06, 0.5x1=.5 (monotone already)
    assert holm(p) == pytest.approx([0.016, 0.06, 0.06, 0.5])
    assert all(h <= b + 1e-15 for h, b in zip(holm(p), bonferroni(p), strict=True))


def test_i04_bootstrap_is_reproducible_paired_and_sensitive_to_block_length(market):
    trend = backtest_strategy(TrendFollowing(50, 200, ("AAA",)), market)
    bench = backtest_strategy(BuyAndHold({"AAA": 1.0}), market)
    pair = pd.DataFrame({"s": trend.returns, "b": bench.returns})

    def stat(d):
        return m.historical_es(d["b"]) - m.historical_es(d["s"])

    one = bootstrap_ci(pair, stat, n_boot=300, block=21, seed=7)
    two = bootstrap_ci(pair, stat, n_boot=300, block=21, seed=7)
    assert (one.lower, one.upper, one.estimate) == (two.lower, two.upper, two.estimate)
    other_seed = bootstrap_ci(pair, stat, n_boot=300, block=21, seed=8)
    assert (other_seed.lower, other_seed.upper) != (one.lower, one.upper)
    assert abs(other_seed.lower - one.lower) < (one.upper - one.lower)  # seeds differ by noise only
    assert one.lower <= one.estimate <= one.upper
    # Pairing: identical series give a difference of exactly zero in every resample.
    same = bootstrap_ci(pd.DataFrame({"s": bench.returns, "b": bench.returns}), stat, n_boot=100, seed=1)
    assert same.lower == same.upper == 0.0
    widths = [bootstrap_ci(pair, stat, n_boot=300, block=b, seed=7) for b in (5, 63)]
    assert widths[0].upper - widths[0].lower != widths[1].upper - widths[1].lower


def test_i05_transaction_costs_only_ever_reduce_returns(market):
    table = cost_sensitivity(TrendFollowing(20, 60, ("AAA",)), market, [0, 5, 20, 80])
    assert table["cagr"].is_monotonic_decreasing and table["total_return"].is_monotonic_decreasing
    assert (table["turnover"].round(6) > 0).all()


@needs_record
def test_i06_the_published_record_and_frozen_dataset_are_intact():
    record = json.loads(RECORD.read_text())
    assert RECORD.name == f"trend_vs_buyhold_{record['config_hash']}.json"
    assert config_hash(record["config"]) == record["config_hash"]  # the protocol was not edited
    cfg = record["config"]
    assert cfg["primary_params"] == {"fast": 50, "slow": 200} and cfg["dev_end"] == "2012-12-31"
    assert cfg["bootstrap"] == {"method": "stationary", "block": 63, "n_boot": 2000, "seed": 20260101}
    assert cfg["primary_metrics"] == ["max_drawdown", "es_95", "downside_deviation"]
    results = record["results"]
    assert results["configurations_selected_using_out_of_sample_data"] == 0
    assert (results["trials_evaluated"], results["distinct_configurations"]) == (28, 21)
    rows = {r["index"]: r for r in results["assets"]["SPY"]["out_of_sample"]}
    assert rows["trend_50_200"]["max_drawdown"] == pytest.approx(rows["buy_and_hold"]["max_drawdown"], abs=1e-12)
    manifest = json.loads((ROOT / "experiments" / "MANIFEST.json").read_text())
    assert manifest["dataset"]["close_fingerprint"] == results["data_fingerprint_close"]
    assert manifest["rights"]["status"] == "NOT ESTABLISHED"
    folder = ROOT / manifest["dataset"]["path"]
    if folder.exists():  # the private dataset: every file must match its recorded checksum
        for name, digest in manifest["dataset"]["sha256"].items():
            assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, name


@needs_record
def test_i07_sign_convention_of_published_improvements():
    """In the record, a positive value always favours trend following (benchmark minus
    strategy for losses). The estimates must be consistent with the published tables."""
    record = json.loads(RECORD.read_text())
    spy = record["results"]["assets"]["SPY"]
    rows = {r["index"]: r for r in spy["out_of_sample"]}
    trend, bench = rows["trend_50_200"], rows["buy_and_hold"]
    improvement = {r["index"]: r["estimate"] for r in spy["improvement_intervals"]}
    assert improvement["es_95"] == pytest.approx(bench["es_95"] - trend["es_95"])  # reversed on purpose
    assert improvement["downside_deviation"] == pytest.approx(bench["downside_deviation"] - trend["downside_deviation"])
    assert improvement["max_drawdown"] == pytest.approx(trend["max_drawdown"] - bench["max_drawdown"], abs=1e-9)
    assert improvement["cagr"] == pytest.approx(trend["cagr"] - bench["cagr"])
    assert improvement["es_95"] > 0 and improvement["cagr"] < 0


def test_i08_validation_lab_rows_state_their_own_subtraction(monkeypatch):
    """QA-013 (fixed): each row says how it is computed; the ES row is buy & hold minus trend."""
    at = render(view("research"), monkeypatch, p_syn_tick="SYN1")
    table = next(d.value for d in at.dataframe if "Computed as" in d.value.columns and "CAGR" in d.value.index)
    assert list(table.index) == ["Max drawdown (shallower is +)", "1-day ES 95% (smaller is +)", "CAGR"]
    assert table.loc["1-day ES 95% (smaller is +)", "Computed as"].startswith("buy & hold - trend")
    assert table.loc["CAGR", "Computed as"] == "trend - buy & hold"
    source = view("research").read_text()
    assert 'm.historical_es(d["b"]) - m.historical_es(d["s"])' in source  # the numbers did not change


def test_i08b_validation_lab_header_does_not_claim_one_subtraction_for_all_rows(monkeypatch):
    at = render(view("research"), monkeypatch, p_syn_tick="SYN1")
    tables = [d.value for d in at.dataframe]
    assert not any("Trend minus buy & hold" in t.columns for t in tables)


@needs_record
def test_i09_published_study_caption_describes_the_improvement_convention(monkeypatch):
    """QA-014 (fixed)."""
    at = render(view("research"), monkeypatch)
    caption = next(c.value for c in at.caption if "Improvement is oriented" in c.value)
    assert "trend minus buy-and-hold" in caption and "buy-and-hold minus trend" in caption
    table = next(d.value for d in at.dataframe if "Status" in d.value.columns)
    record = json.loads(RECORD.read_text())["results"]["assets"]["SPY"]["improvement_intervals"]
    signs = {r["index"]: r["estimate"] for r in record}
    assert table.loc["es 95", "Computed as"].startswith("buy & hold - trend")
    assert table.loc["es 95", "Improvement"] == f"{signs['es_95']:+.2%}"  # value unchanged: +0.29%


@needs_record
def test_i10_published_study_page_separates_confirmatory_from_exploratory(monkeypatch):
    at = render(view("research"), monkeypatch)
    page = texts(at)
    assert "no longer untouched" in page and "nothing here is a forecast" in page
    table = next(d.value for d in at.dataframe if "Status" in d.value.columns)
    assert list(table["Status"]) == ["confirmatory"] * 3 + ["exploratory"] * 2
    assert "Exploratory." in page  # the interactive lab is labelled as such


# ================================================================= Suite J: exports


def test_j01_investment_lab_record_contains_what_reproduction_needs(lab):
    record = json.loads(json.dumps(analysis_record(lab, {"outcome": "cached"}), default=str))
    assert record["schema"] and record["generated_at"].endswith("+00:00")  # explicit UTC timestamp
    assert record["portfolios"]["Core"]["weights"] == {"AAA": 0.6, "BBB": 0.4}  # allocations included
    assert record["execution"]["slippage_bps"] == 2 and record["execution"]["fee_bps"] == 1
    assert set(record["window"]) == {"start", "end", "sessions"}
    assert len(record["data"]["fingerprint"]) == 16 and record["data"]["source"] == "synthetic-gbm"
    assert record["data"]["synthetic"] is True and record["environment"]["quantlab"]
    assert any("Not a forecast" in n for n in record["notes"]) and "next session's open" in record["timing"]
    for name, stats in record["results"].items():
        assert stats["final_value"] == lab.stats[name]["final_value"]  # exported == computed
    text = json.dumps(record).lower()
    for claim in ("guarantee", "will outperform", "recommended", "confidence score"):
        assert claim not in text


def test_j02_portfolio_file_round_trip_and_corrupt_files(lab):
    mine = {"Core": lab.specs["Core"]}
    saved = portfolio_file(mine, lab.config, lab.risk_free, lab.fingerprint)
    specs, cfg, rf = load_portfolio_file(json.loads(json.dumps(saved)))
    assert specs == mine and cfg == lab.config and rf == lab.risk_free
    for corrupt in ("", "{", "[]", "null", '{"schema": 1}', json.dumps({**saved, "portfolios": "x"}),
                    json.dumps({**saved, "portfolios": {"a": {"weights": {"A": "lots"}}}}),
                    json.dumps({**saved, "portfolios": {"a": {"weights": {"A": 1e400}}}})):  # fmt: skip
        with pytest.raises(ValueError):
            load_portfolio_file(json.loads(corrupt) if corrupt else {})


def test_j03_undefined_values_are_exported_safely(market):
    from quantlab.reporting.exports import json_bytes

    flat = pd.Series([0.0] * 30)
    stats = performance_summary(flat)
    assert math.isnan(stats["sharpe"])
    exported = json.loads(json_bytes({"Flat": stats}))  # must be valid JSON: NaN is not
    assert exported["Flat"]["sharpe"] is None and exported["Flat"]["volatility"] == 0.0
    page = html_report("t", {"Flat": stats}, pd.DataFrame({"Flat": (1 + flat).cumprod()}), {"data": {}}, [])
    assert "nan" not in page.lower().replace("n/a", "") and "n/a" in page


def test_j04_backtest_html_formats_percentages_and_flags_synthetic_data(market):
    cfg = ExecutionConfig(slippage_bps=2, fee_bps=1)
    strategy = TrendFollowing(50, 200, ("AAA",))
    res, bench = backtest_strategy(strategy, market, cfg), backtest_strategy(BuyAndHold({"AAA": 1.0}), market, cfg)
    stats = {"Trend": performance_summary(res.returns), "Buy & hold": performance_summary(bench.returns)}
    files = backtest_bundle(strategy, res, bench, stats, market.metadata.to_dict())
    page = html_report("x", stats, pd.DataFrame({"Trend": res.equity}), json.loads(files["config.json"]), [])
    assert f"{stats['Trend']['cagr']:.2%}" in page and f"{stats['Trend']['max_drawdown']:.2%}" in page
    assert "SYNTHETIC DATA" in page and "<script" not in page
    exported = pd.read_csv(io.BytesIO(files["statistics.csv"]), index_col="statistic")
    assert exported.loc["cagr", "Trend"] == pytest.approx(stats["Trend"]["cagr"])  # raw, unrounded


def lab_report(lab, risk=True):
    from quantlab.reporting.investment_report import investment_report
    from quantlab.risk import estimate_risk, holding_returns

    record = analysis_record(lab)
    estimates = {}
    for name, spec in lab.specs.items():
        w = pd.Series(spec.weights, dtype=float)
        estimates[name] = estimate_risk(holding_returns(lab.data.close, w), w).summary()
    return record, investment_report(record, lab.values(), lab.contributed(), estimates if risk else None, "Core")


def test_j05_generic_html_uses_units_and_plain_names(lab):
    """QA-002 / QA-036 (fixed) for the generic report used by the Backtesting page."""
    record = analysis_record(lab)
    page = html_report("Lab", lab.stats, lab.values(), {"data": record["data"], "execution": record["execution"]}, [])
    row = re.search(r"<tr><td>Time-weighted return \(annual\)</td>(.*?)</tr>", page).group(1)
    shown = re.findall(r'<td class="num">([^<]*)</td>', row)
    assert shown[0] == f"{lab.stats['Core']['time_weighted_annual']:.2%}"
    assert ">time_weighted_annual<" not in page and ">slippage_bps<" not in page
    assert "Slippage (basis points)" in page


def test_j05b_investment_lab_report_shows_returns_as_percentages(lab):
    record, page = lab_report(lab)
    assert f"{lab.stats['Core']['time_weighted_annual']:.2%}" in page
    assert f"{lab.stats['Core']['money_weighted_annual']:.2%}" in page
    assert f"{lab.stats['Core']['final_value']:,.0f}" in page


def test_j05c_html_omits_a_section_with_no_content(lab):
    """QA-003 (fixed)."""
    record = analysis_record(lab)
    page = html_report("Lab", lab.stats, lab.values(), {"data": record["data"], "execution": record["execution"]}, [])
    assert "<h2>Strategy</h2>" not in page and "<h2>Notes and limitations</h2>" not in page
    _, report = lab_report(lab, risk=False)
    assert "Risk of the allocation" not in report  # no estimates passed: no empty section


def test_j05d_report_states_allocations_funding_period_and_reproducibility(lab):
    """QA-022, QA-036 (fixed): a standalone report a reader can act on."""
    record, page = lab_report(lab)
    for needed in ("AAA 60.0%, BBB 40.0%", "rebalanced annually", "10,000 at the start, then 500 monthly",
                   f"{record['window']['start']} to {record['window']['end']}", "Key findings",
                   "Compared with the alternatives", "Core minus", "Limitations", "How to read the terms",
                   record["data"]["fingerprint"], "HISTORICAL", "ESTIMATE", "SYNTHETIC DATA",
                   "not investment advice"):  # fmt: skip
        assert needed in page, needed
    assert "<script" not in page and "http://" not in page and "https://" not in page
    for internal in ("time_weighted_annual", "money_weighted_annual", "max_drawdown_duration"):
        assert internal not in page, internal
    assert not re.search(r"\bnan\b", page, re.IGNORECASE)  # undefined values read 'n/a'

    source = view("invest").read_text()
    assert "investment_report(record" in source  # the page offers this report


def test_j05e_report_findings_match_the_numbers(lab):
    record, page = lab_report(lab)
    core = lab.stats["Core"]
    assert f"turned {core['total_invested']:,.0f} paid in" in page
    assert f"into {core['final_value']:,.0f}" in page
    best = max(lab.stats, key=lambda n: lab.stats[n]["time_weighted_annual"])
    assert f"{best} had the highest time-weighted return" in page
    other = next(n for n in lab.stats if n != "Core")
    diff = core["time_weighted_annual"] - lab.stats[other]["time_weighted_annual"]
    from quantlab.reporting.format import format_signed

    assert format_signed("time_weighted_annual", diff) in page


def test_j06_risk_monte_carlo_and_stress_exports_carry_reproducibility_metadata():
    """QA-023 (fixed)."""
    for name, start, end in (("risk", "summary = {", 'downloads({"Risk metrics (JSON)"'),
                             ("monte_carlo", "summary = {", 'downloads({"Simulation summary (JSON)"'),
                             ("stress", "meta = {", 'downloads({"Scenario comparison (CSV)"')):  # fmt: skip
        source = view(name).read_text()
        block = source[source.index(start) : source.index(end)]
        for needed in ('"generated_at"', '"portfolio"', "data_fingerprint(data)", '"environment"', '"model"'):
            assert needed in block, (name, needed)


def test_j06b_risk_export_carries_window_confidence_weights_and_fingerprint(monkeypatch):
    import json as _json

    at = render(view("risk"), monkeypatch)
    assert not at.exception
    source = view("risk").read_text()
    block = source[source.index("summary = {") : source.index('downloads({"Risk metrics (JSON)"')]
    assert '"estimation_window"' in block and "**s" in block and "chosen.describe()" in block
    assert _json.dumps({"ok": True})


def test_j07_formatting_of_percentages_and_undefined_values():
    from quantlab.reporting.exports import _fmt

    assert _fmt("cagr", 0.123456) == "12.35%" and _fmt("max_drawdown", -0.3372) == "-33.72%"
    assert _fmt("sharpe", 0.7326) == "0.73" and _fmt("n_obs", 3479.0) == "3,479"
    assert _fmt("sharpe", float("nan")) == "n/a" and _fmt("cagr", None) == "n/a"
    assert _fmt("time_weighted_annual", 0.0712) == "7.12%" and _fmt("final_value", 12345.6) == "12,346"
    assert _fmt("sharpe", float("inf")) == "n/a"


def test_j07b_rounded_zero_carries_no_minus_sign():
    """QA-012 (fixed)."""
    from quantlab.reporting.exports import _fmt
    from quantlab.reporting.format import format_signed, format_significant

    assert _fmt("sharpe", -0.0004) == "0.00" and _fmt("cagr", -0.00001) == "0.00%"
    assert _fmt("sharpe", -0.006) == "-0.01"  # a real negative keeps its sign
    assert format_signed("cagr", -0.00001) == "0.00%" and format_signed("cagr", 0.0123) == "+1.23%"
    assert format_significant(-0.0) == "0" and format_significant(4.1234e-05) == "4.12e-05"


def test_j07c_covariance_is_shown_to_significant_figures(monkeypatch):
    """QA-025 (fixed): low-variance entries keep three significant figures."""
    at = render(view("risk"), monkeypatch)
    cov = next(d.value for d in at.dataframe if list(d.value.index) == list(d.value.columns))
    cells = [str(v) for v in cov.to_numpy().ravel()]
    assert all(c == "0" or len(c.replace("-", "").replace("0.", "").lstrip("0").split("e")[0].replace(".", "")) <= 3
               for c in cells), cells  # fmt: skip
    assert not any(c in ("-0.0000", "0.0000") for c in cells)


@needs_record
def test_j08_research_markdown_and_manifest_are_consistent_with_the_record():
    record = json.loads(RECORD.read_text())
    report = (ROOT / "reports" / "trend_vs_buyhold.md").read_text()
    rows = {r["index"]: r for r in record["results"]["assets"]["SPY"]["out_of_sample"]}
    assert f"{rows['trend_50_200']['cagr']:.2%}" in report and f"{rows['buy_and_hold']['cagr']:.2%}" in report
    assert record["results"]["data_fingerprint_close"] in report
    assert record["data"]["adjustment"] in report and "fills at open T+1" in report
    manifest = json.loads((ROOT / "experiments" / "MANIFEST.json").read_text())
    assert RECORD.name in " ".join(d["path"] for d in manifest["dependent_outputs"])
    assert manifest["record"]["config_hash"] == record["config_hash"]
    assert np.isfinite(rows["trend_50_200"]["sharpe"])
