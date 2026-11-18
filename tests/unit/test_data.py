import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quantlab.data import (
    CachedProvider,
    DataError,
    DataProviderError,
    InsufficientHistoryError,
    InvalidTickerError,
    SyntheticProvider,
    build_market_data,
    require_history,
)
from quantlab.data import transforms as tf


def raw(dates, close):
    c = np.asarray(close, dtype=float)
    return pd.DataFrame(
        {"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 100.0},
        index=pd.DatetimeIndex(dates),
    )


def test_duplicates_timezones_and_sorting():
    days = ["2024-01-03", "2024-01-02", "2024-01-03"]
    dates = pd.to_datetime(days).tz_localize("America/New_York")
    data = build_market_data({"A": raw(dates, [3, 2, 4])}, "t", "none")
    assert list(data.dates) == list(pd.to_datetime(["2024-01-02", "2024-01-03"]))
    assert data.close["A"].tolist() == [2.0, 4.0]  # last duplicate kept
    assert any("duplicate" in n for n in data.metadata.notes)
    assert data.dates.tz is None


def test_union_calendar_keeps_gaps_as_nan():
    a = raw(["2024-01-02", "2024-01-03", "2024-01-04"], [1, 2, 3])
    b = raw(["2024-01-02", "2024-01-04"], [5, 6])
    data = build_market_data({"A": a, "B": b}, "t", "none")
    assert np.isnan(data.close.loc["2024-01-03", "B"])  # not forward-filled
    assert data.metadata.tickers == ("A", "B")
    assert data.metadata.start == "2024-01-02" and data.metadata.end == "2024-01-04"
    assert data.metadata.source == "t" and data.metadata.retrieved_at


def test_invalid_inputs_raise():
    with pytest.raises(InvalidTickerError):
        build_market_data({"A": pd.DataFrame()}, "t", "none")
    with pytest.raises(DataError):
        build_market_data({"A": raw(["2024-01-02"], [-1])}, "t", "none")
    with pytest.raises(DataError):
        build_market_data({"A": raw(["2024-01-02"], [1]).drop(columns="Open")}, "t", "none")
    bad = raw(["2024-01-02"], [1])
    bad["High"] = 0.5
    with pytest.raises(DataError):
        build_market_data({"A": bad}, "t", "none")
    data = build_market_data({"A": raw(["2024-01-02", "2024-01-03"], [1, 2])}, "t", "none")
    with pytest.raises(InsufficientHistoryError):
        require_history(data, 10)


def test_truncate_and_select():
    data = SyntheticProvider(0).fetch(["A", "B"], "2024-01-01", "2024-03-29")
    cut = data.truncate("2024-02-15")
    assert cut.dates.max() <= pd.Timestamp("2024-02-15") and cut.metadata.end <= "2024-02-15"
    assert data.select(["B"]).tickers == ["B"]
    with pytest.raises(KeyError):
        data.select(["ZZZ"])
    assert data.metadata.synthetic


def test_transforms_by_hand():
    p = pd.Series([100.0, 110.0, 99.0])
    assert tf.simple_returns(p).tolist()[1:] == pytest.approx([0.10, -0.10])
    assert tf.log_returns(p).iloc[1] == pytest.approx(np.log(1.1))
    # log returns add over time; simple returns compound
    assert tf.log_returns(p).sum() == pytest.approx(np.log(0.99))
    assert tf.cumulative_returns(tf.simple_returns(p)).iloc[-1] == pytest.approx(-0.01)
    assert tf.moving_average(p, 2).tolist()[1:] == pytest.approx([105.0, 104.5])
    assert np.isnan(tf.moving_average(p, 2).iloc[0])
    gap = pd.Series([100.0, np.nan, 121.0])
    assert tf.simple_returns(gap).isna().all()  # no return is invented across a gap
    df = pd.DataFrame({"A": [np.nan, 50.0, 55.0], "B": [10.0, 11.0, 12.0]})
    assert tf.normalize(df).iloc[1].tolist() == pytest.approx([100.0, 110.0])


class Flaky:
    name = "flaky"

    def __init__(self):
        self.calls, self.fail = 0, False
        self.inner = SyntheticProvider(1)

    def fetch(self, tickers, start, end=None):
        self.calls += 1
        if self.fail:
            raise DataProviderError("provider down")
        return self.inner.fetch(tickers, start, end)


def test_cache_hit_stale_refetch_and_provider_failure(tmp_path):
    flaky = Flaky()
    cached = CachedProvider(flaky, tmp_path, max_age_hours=1)
    first = cached.fetch(["A"], "2024-01-01", "2024-02-01")
    second = cached.fetch(["A"], "2024-01-01", "2024-02-01")
    assert flaky.calls == 1  # fresh cache hit
    pd.testing.assert_frame_equal(first.close, second.close, check_freq=False)
    assert second.metadata == first.metadata

    # Age the cache entry artificially.
    meta_path = next(tmp_path.glob("*/metadata.json"))
    meta = json.loads(meta_path.read_text())
    meta["retrieved_at"] = "2000-01-01T00:00:00+00:00"
    meta_path.write_text(json.dumps(meta))
    cached.fetch(["A"], "2024-01-01", "2024-02-01")
    assert flaky.calls == 2  # stale -> refetched

    meta_path.write_text(json.dumps(meta))
    flaky.fail = True
    with pytest.raises(DataProviderError):  # stale + provider down -> loud failure
        cached.fetch(["A"], "2024-01-01", "2024-02-01")
    lenient = replace_allow_stale(cached)
    stale = lenient.fetch(["A"], "2024-01-01", "2024-02-01")
    assert any("STALE" in n for n in stale.metadata.notes)


def replace_allow_stale(c: CachedProvider) -> CachedProvider:
    return CachedProvider(c.inner, c.cache_dir, c.max_age_hours, allow_stale=True)


def test_metadata_is_immutable():
    data = SyntheticProvider(0).fetch(["A"], "2024-01-01", "2024-01-31")
    with pytest.raises(AttributeError):
        data.metadata.source = "x"
    assert replace(data.metadata, source="x").source == "x"
