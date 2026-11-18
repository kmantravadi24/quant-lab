import io
import json

import numpy as np
import pandas as pd
import pytest

from quantlab.analytics import performance_summary
from quantlab.backtesting import backtest_strategy
from quantlab.data import (
    CsvProvider,
    DataError,
    InvalidTickerError,
    SyntheticProvider,
    read_ohlcv_csv,
)
from quantlab.execution import ExecutionConfig
from quantlab.reporting import backtest_bundle, cost_summary, html_report
from quantlab.strategies import BuyAndHold, TrendFollowing

CSV = """Date,Open,High,Low,Close,Adj Close,Volume
2024-01-03,10,11,9,10,5,100
2024-01-02,8,9,7,8,4,100
"""


def test_user_csv_parsing_and_adjustment():
    df = read_ohlcv_csv(io.StringIO(CSV), "X")
    # Adj Close is half of Close, so every price is halved; rows may arrive unsorted.
    assert df.loc["2024-01-03", "open"] == 5.0 and df.loc["2024-01-02", "high"] == 4.5
    data = CsvProvider({"X": df}).fetch(["X"])
    assert list(data.close["X"]) == [4.0, 5.0]  # sorted by date
    assert data.metadata.source == "user-csv" and not data.metadata.synthetic
    assert "not verified" in data.metadata.adjustment


def test_user_csv_without_volume_or_adj_close():
    df = read_ohlcv_csv(io.StringIO("date,open,high,low,close\n2024-01-02,1,2,1,2\n"))
    assert df["close"].iloc[0] == 2.0 and np.isnan(df["volume"].iloc[0])


@pytest.mark.parametrize(
    "text",
    ["date,open,high,low\n2024-01-02,1,2,1\n", "date,open,high,low,close\nnot-a-date,1,2,1,2\n",
     "date,open,high,low,close\n2024-01-02,1,2,1,abc\n", ""],
)  # fmt: skip
def test_bad_user_csv_gives_a_clear_data_error(text):
    with pytest.raises(DataError):
        read_ohlcv_csv(io.StringIO(text), "X")


def test_csv_provider_folder_and_unknown_ticker(tmp_path):
    (tmp_path / "abc.csv").write_text("date,open,high,low,close\n2024-01-02,1,2,1,2\n")
    provider = CsvProvider(tmp_path)
    assert provider.available() == ["ABC"]
    assert provider.fetch(["ABC"]).tickers == ["ABC"]
    with pytest.raises(InvalidTickerError):
        provider.fetch(["ZZZ"])
    bad = CsvProvider(
        {"X": read_ohlcv_csv(io.StringIO("date,open,high,low,close\n2024-01-02,1,2,3,2\n"))}
    )
    with pytest.raises(DataError):  # high < low is rejected, not repaired
        bad.fetch(["X"])


@pytest.fixture(scope="module")
def run():
    data = SyntheticProvider(3).fetch(["SPY"], "2016-01-01", "2020-12-31")
    cfg = ExecutionConfig(slippage_bps=5, fee_bps=2)
    strategy = TrendFollowing(20, 60, ("SPY",))
    res = backtest_strategy(strategy, data, cfg)
    bench = backtest_strategy(BuyAndHold({"SPY": 1.0}), data, cfg)
    stats = {
        "Strategy": performance_summary(res.returns),
        "Benchmark": performance_summary(bench.returns),
    }
    return data, strategy, res, bench, stats


def test_backtest_exports_round_trip_the_actual_results(run):
    data, strategy, res, bench, stats = run
    files = backtest_bundle(strategy, res, bench, stats, data.metadata.to_dict())
    assert set(files) == {"equity_curve.csv", "statistics.csv", "statistics.json", "trades.csv",
                          "config.json"}  # fmt: skip
    equity = pd.read_csv(io.BytesIO(files["equity_curve.csv"]), index_col="date", parse_dates=True)
    np.testing.assert_allclose(equity["strategy_equity"], res.equity)
    np.testing.assert_allclose(equity["benchmark_equity"], bench.equity)
    trades = pd.read_csv(io.BytesIO(files["trades.csv"]))
    assert len(trades) == len(res.trades) and trades["fee"].sum() == pytest.approx(
        res.trades["fee"].sum()
    )
    stats_json = json.loads(files["statistics.json"])
    assert stats_json["Strategy"]["cagr"] == pytest.approx(stats["Strategy"]["cagr"])
    config = json.loads(files["config.json"])
    assert config["strategy"] == {"type": "TrendFollowing", "parameters": {
        "fast": 20, "slow": 60, "tickers": ["SPY"], "name": "trend_following"}}  # fmt: skip
    assert config["execution"]["slippage_bps"] == 5 and config["data"]["synthetic"] is True
    assert "T+1" in config["timing"]


def test_cost_summary_by_hand(run):
    _, _, res, _, _ = run
    costs = cost_summary(res)
    # slippage is 5 bps of the reference notional; fee is 2 bps of the filled notional
    ref_notional = (res.trades["shares"] * res.trades["reference_price"]).sum()
    assert costs["slippage_paid"] == pytest.approx(ref_notional * 5e-4)
    assert costs["fees_paid"] == pytest.approx(res.trades["notional"].sum() * 2e-4)
    assert costs["total_cost"] == pytest.approx(costs["fees_paid"] + costs["slippage_paid"])
    assert cost_summary(run[3])["fills"] == 1


def test_html_report_is_self_contained_and_flags_synthetic_data(run):
    data, strategy, res, bench, stats = run
    config = json.loads(
        backtest_bundle(strategy, res, bench, stats, data.metadata.to_dict())["config.json"]
    )
    page = html_report(
        "Trend <test>", stats, pd.DataFrame({"Strategy": res.equity}), config, ["note & more"]
    )
    assert page.startswith("<!doctype html>") and "SYNTHETIC DATA" in page
    assert "<script" not in page and "http" not in page.split("<body>")[1].replace(
        "https://github", ""
    )
    assert "Trend &lt;test&gt;" in page and "note &amp; more" in page  # escaped
    assert f"{stats['Strategy']['cagr']:.2%}" in page and "<polyline" in page
    real = dict(config, data=dict(config["data"], synthetic=False))
    assert "SYNTHETIC DATA" not in html_report(
        "t", stats, pd.DataFrame({"S": res.equity}), real, []
    )


def test_bundled_sample_files_load_and_are_documented_as_synthetic():
    from pathlib import Path

    folder = Path(__file__).resolve().parents[2] / "examples" / "sample_data"
    provider = CsvProvider(folder)
    assert provider.available() == ["DEMOA", "DEMOB"]
    data = provider.fetch(["DEMOA", "DEMOB"])
    assert len(data.dates) > 1000 and not data.close.isna().any().any()
    assert "not market data" in (folder / "README.md").read_text()


def test_no_restricted_dataset_is_required_by_the_package():
    """The library and the sample workflow must not reference the private data folder."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    for path in (root / "src").rglob("*.py"):
        assert "experiments/data" not in path.read_text(), path
