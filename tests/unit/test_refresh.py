"""Phase 2: session-aware refresh of live daily data.

No test touches the network or the wall clock. NYSE facts used: 2026-11-26 is
Thanksgiving (closed); 2026-11-27 closes at 13:00; US daylight saving starts on
2026-03-08, so the 16:00 close moves from 21:00 UTC to 20:00 UTC.
"""

import os
import threading
import time
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("exchange_calendars")

from fixtures.live import CALENDAR, Clock, ScriptedYahoo  # noqa: E402

import quantlab.data.refresh as refresh_module  # noqa: E402
from quantlab.data import (  # noqa: E402
    DataProviderError,
    Freshness,
    LiveDataStore,
    NoUsableDataError,
    Outcome,
    RefreshPolicy,
)

MON_THU = ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"]
FRI = "2026-11-13"
START = "2026-11-01"


def make(tmp_path, when="2026-11-12 17:00", published=None, policy=None):
    clock = Clock(when)
    provider = ScriptedYahoo(clock, published or {"SPY": list(MON_THU)})
    store = LiveDataStore(provider, tmp_path, CALENDAR, clock, policy)
    return store, provider, clock


def end_of(result) -> str:
    return result.data.metadata.end


# ----------------------------------------------------------------- when is the provider contacted?


def test_first_load_downloads_then_the_cache_is_reused(tmp_path):
    store, provider, clock = make(tmp_path)
    first = store.get(["SPY"], START)
    assert (first.outcome, first.served_from, provider.requests) == (Outcome.UPDATED, "provider", 1)
    assert end_of(first) == "2026-11-12" and first.freshness.is_current
    assert first.retrieved_at == clock.now.tz_convert("UTC") == first.last_attempt_at
    # A first download is not described as "N new sessions".
    assert first.new_observations == {} and "**Loaded**" in first.headline()[1]
    assert "new completed session" not in first.headline()[1]
    clock.advance(minutes=1)
    again = store.get(["SPY"], START)
    assert (again.outcome, again.served_from, provider.requests) == (Outcome.CACHED, "cache", 1)
    assert again.data is first.data  # served from memory: no disk read, nothing to recompute
    assert again.retrieved_at == first.retrieved_at and again.next_check_at is None


def test_a_session_in_progress_never_triggers_a_download_or_enters_the_data(tmp_path):
    store, provider, clock = make(tmp_path)
    store.get(["SPY"], START)
    provider.published["SPY"].append(FRI)  # the provider already shows a partial Friday candle
    for moment in ("2026-11-13 08:00", "2026-11-13 09:30", "2026-11-13 12:00", "2026-11-13 15:59:59"):
        clock.set(moment)
        result = store.get(["SPY"], START)
        assert result.outcome is Outcome.CACHED and end_of(result) == "2026-11-12", moment
        assert result.freshness.is_current  # Thursday is the latest *completed* session
    assert provider.requests == 1
    # A manual refresh during the session reaches the provider but still excludes the open candle.
    forced = store.get(["SPY"], START, force=True)
    assert forced.outcome is Outcome.UNCHANGED and end_of(forced) == "2026-11-12"
    assert provider.requests == 2


def test_the_official_close_is_the_moment_a_new_session_is_wanted(tmp_path):
    store, provider, clock = make(tmp_path)
    store.get(["SPY"], START)
    provider.published["SPY"].append(FRI)
    clock.set("2026-11-13 16:00:00")
    result = store.get(["SPY"], START)
    assert (result.outcome, provider.requests, end_of(result)) == (Outcome.UPDATED, 2, FRI)
    assert result.new_observations == {"SPY": 1} and result.freshness.is_current
    level, text = result.headline()
    assert level == "ok" and "**Updated**" in text and "1 new completed session" in text
    assert "2026-11-13 16:00:00 ET" in text


def test_provider_publication_delay_is_retried_with_backoff_not_in_a_loop(tmp_path):
    store, provider, clock = make(tmp_path)
    store.get(["SPY"], START)
    clock.set("2026-11-13 16:00")  # closed, but the provider has not published Friday yet
    late = store.get(["SPY"], START)
    assert late.outcome is Outcome.UNCHANGED and end_of(late) == "2026-11-12"
    assert late.freshness.state is Freshness.AWAITING_PROVIDER and not late.freshness.is_current
    assert late.next_check_at == clock.now.tz_convert("UTC") + pd.Timedelta(minutes=15)
    assert "Checked; unchanged" in late.headline()[1] and "has not yet published" in late.headline()[1]

    clock.set("2026-11-13 16:14:59")  # many page loads inside the cooldown: no request
    for _ in range(50):
        waiting = store.get(["SPY"], START)
    assert provider.requests == 2 and waiting.outcome is Outcome.CACHED
    assert "Next automatic check after 2026-11-13 16:15:00 ET" in waiting.headline()[1]

    clock.set("2026-11-13 16:15")  # second attempt, still nothing: wait doubles to 30 minutes
    second = store.get(["SPY"], START)
    assert provider.requests == 3 and second.next_check_at == clock.now.tz_convert("UTC") + pd.Timedelta(minutes=30)
    clock.set("2026-11-13 16:44")
    assert store.get(["SPY"], START).outcome is Outcome.CACHED and provider.requests == 3

    provider.published["SPY"].append(FRI)  # published at last
    clock.set("2026-11-13 16:45")
    done = store.get(["SPY"], START)
    assert (done.outcome, end_of(done), provider.requests) == (Outcome.UPDATED, FRI, 4)
    assert done.next_check_at is None
    clock.advance(hours=3)
    assert store.get(["SPY"], START).outcome is Outcome.CACHED and provider.requests == 4


def test_a_bar_that_never_arrives_costs_a_bounded_number_of_requests(tmp_path):
    store, provider, clock = make(tmp_path)
    store.get(["SPY"], START)
    clock.set("2026-11-13 16:00")
    gaps, last = [], None
    for _ in range(12 * 24 * 2):  # a page load every 5 minutes for two days, bar never published
        before = provider.requests
        result = store.get(["SPY"], START)
        assert end_of(result) == "2026-11-12" and not result.freshness.is_current  # never "current"
        if provider.requests > before:
            if last is not None:
                gaps.append(clock.now - last)
            last = clock.now
        clock.advance(minutes=5)
    assert provider.requests - 1 <= 13  # not 576
    assert max(gaps) <= pd.Timedelta(hours=6) + pd.Timedelta(minutes=5)  # capped back-off
    assert gaps == sorted(gaps)  # waits only ever lengthen


@pytest.mark.parametrize(
    "moments",
    [
        ["2026-11-13 20:00", "2026-11-14 03:00", "2026-11-14 12:00", "2026-11-15 12:00",
         "2026-11-16 03:00", "2026-11-16 09:29"],  # Friday night, weekend, Monday pre-open
        ["2026-11-16 09:30", "2026-11-16 12:00", "2026-11-16 15:59"],  # Monday session in progress
    ],
)  # fmt: skip
def test_overnight_weekend_and_open_market_cause_no_requests(tmp_path, moments):
    store, provider, clock = make(tmp_path, "2026-11-13 16:30", {"SPY": [*MON_THU, FRI]})
    store.get(["SPY"], START)
    for moment in moments:
        clock.set(moment)
        for _ in range(5):
            result = store.get(["SPY"], START)
            assert result.outcome is Outcome.CACHED and result.freshness.is_current, moment
    assert provider.requests == 1


def test_holiday_and_early_close(tmp_path):
    days = ["2026-11-23", "2026-11-24", "2026-11-25"]
    store, provider, clock = make(tmp_path, "2026-11-25 17:00", {"SPY": list(days)})
    store.get(["SPY"], START)
    for moment in ("2026-11-26 10:00", "2026-11-26 16:30", "2026-11-27 09:00", "2026-11-27 12:59:59"):
        clock.set(moment)  # Thanksgiving, then the half day before its 13:00 close
        assert store.get(["SPY"], START).outcome is Outcome.CACHED, moment
    assert provider.requests == 1
    provider.published["SPY"].append("2026-11-27")
    clock.set("2026-11-27 13:00")  # the official early close, three hours before the usual time
    result = store.get(["SPY"], START)
    assert (result.outcome, end_of(result), provider.requests) == (Outcome.UPDATED, "2026-11-27", 2)


def test_daylight_saving_moves_the_close_in_utc(tmp_path):
    store, provider, clock = make(tmp_path, "2026-03-06 17:00", {"SPY": ["2026-03-05", "2026-03-06"]})
    store.get(["SPY"], "2026-03-01")
    provider.published["SPY"].append("2026-03-09")
    clock.now = pd.Timestamp("2026-03-09 19:59:59", tz="UTC")  # 15:59:59 EDT
    assert store.get(["SPY"], "2026-03-01").outcome is Outcome.CACHED and provider.requests == 1
    clock.now = pd.Timestamp("2026-03-09 20:00:00", tz="UTC")  # 16:00 EDT; was 21:00 UTC on Friday
    assert store.get(["SPY"], "2026-03-01").outcome is Outcome.UPDATED and provider.requests == 2


def test_age_alone_triggers_a_recheck_only_at_the_configured_age(tmp_path):
    store, provider, clock = make(tmp_path, "2026-11-13 16:30", {"SPY": [*MON_THU, FRI]})
    store.get(["SPY"], START)
    clock.set("2026-11-15 12:00")  # Sunday, 43 hours later: current, and younger than 7 days
    assert store.get(["SPY"], START).outcome is Outcome.CACHED and provider.requests == 1
    impatient = LiveDataStore(provider, tmp_path, CALENDAR, clock,
                              RefreshPolicy(max_age=pd.Timedelta(hours=24)))  # fmt: skip
    result = impatient.get(["SPY"], START)
    assert result.outcome is Outcome.UNCHANGED and provider.requests == 2  # re-verified, same data
    assert impatient.get(["SPY"], START).outcome is Outcome.CACHED and provider.requests == 2


# ----------------------------------------------------------------- manual refresh


def test_manual_refresh_contacts_the_provider_and_respects_its_cooldown(tmp_path):
    store, provider, clock = make(tmp_path)
    store.get(["SPY"], START)
    clock.advance(minutes=10)
    forced = store.get(["SPY"], START, force=True)  # cache was valid: only a manual refresh asks
    assert forced.outcome is Outcome.UNCHANGED and forced.served_from == "provider"
    assert provider.requests == 2 and forced.last_attempt_at == clock.now.tz_convert("UTC")
    assert "Checked; unchanged" in forced.headline()[1]

    clock.advance(seconds=30)
    limited = store.get(["SPY"], START, force=True)
    assert limited.outcome is Outcome.LIMITED and provider.requests == 2
    level, text = limited.headline()
    assert level == "info" and "Refresh limited" in text
    assert limited.next_check_at == forced.last_attempt_at + pd.Timedelta(seconds=60)
    assert store.get(["SPY"], START).outcome is Outcome.CACHED  # an ordinary load is unaffected

    clock.advance(seconds=30)
    assert store.get(["SPY"], START, force=True).outcome is Outcome.UNCHANGED and provider.requests == 3


def test_refresh_is_targeted_to_one_dataset(tmp_path):
    published = {"SPY": list(MON_THU), "TLT": list(MON_THU)}
    store, provider, clock = make(tmp_path, published=published)
    spy, tlt = store.get(["SPY"], START), store.get(["TLT"], START)
    tlt_pointer = next(p for p in tmp_path.iterdir() if "TLT" in p.name) / "CURRENT"
    before = tlt_pointer.read_text()
    provider.calls.clear()
    clock.advance(minutes=5)
    store.get(["SPY"], START, force=True)
    assert provider.calls == ["SPY"]  # only the selected universe was requested
    assert tlt_pointer.read_text() == before  # the other dataset on disk is untouched
    assert store.get(["TLT"], START).data is tlt.data and provider.calls == ["SPY"]  # and in memory
    assert store.get(["SPY"], START).data is not spy.data  # the refreshed one was replaced
    # A different history start is a different dataset too.
    assert store.get(["SPY"], "2026-11-10").outcome is Outcome.UPDATED


# ----------------------------------------------------------------- provider behaviour


def test_one_lagging_instrument_is_reported_and_not_filled(tmp_path):
    published = {"SPY": list(MON_THU), "TLT": list(MON_THU)}
    store, provider, clock = make(tmp_path, published=published)
    store.get(["SPY", "TLT"], START)
    provider.published["SPY"].append(FRI)  # TLT's Friday bar is late
    clock.set("2026-11-13 16:10")
    result = store.get(["SPY", "TLT"], START)
    assert result.outcome is Outcome.UPDATED and result.new_observations == {"SPY": 1, "TLT": 0}
    states = {i.ticker: i.state for i in result.freshness.instruments}
    assert states == {"SPY": Freshness.CURRENT, "TLT": Freshness.AWAITING_PROVIDER}
    assert pd.isna(result.data.close.loc[FRI, "TLT"])  # the missing price stays missing
    assert not result.freshness.is_current and result.next_check_at is not None
    assert "TLT" in result.headline()[1]


@pytest.mark.parametrize(
    "error, expected",
    [
        (DataProviderError("yfinance failed for SPY: HTTP 429 Too Many Requests"), "rate limiting"),
        (TimeoutError("read timed out after 10s"), "timed out"),
        (None, "provider returned no data"),  # empty response
    ],
)
def test_provider_failure_keeps_the_verified_cache_and_says_so(tmp_path, error, expected):
    store, provider, clock = make(tmp_path)
    good = store.get(["SPY"], START)
    pointer = next(tmp_path.iterdir()) / "CURRENT"
    version = pointer.read_text()
    if error is None:
        provider.published = {}
    else:
        provider.error = error
    clock.set("2026-11-13 16:05")
    failed = store.get(["SPY"], START)
    assert failed.outcome is Outcome.FAILED and failed.served_from == "cache"
    pd.testing.assert_frame_equal(failed.data.close, good.data.close)  # last verified data intact
    assert pointer.read_text() == version and failed.retrieved_at == good.retrieved_at
    level, text = failed.headline()
    assert level == "warning" and "**Refresh failed**" in text and expected in text
    assert "Showing the last verified data" in text and "current through" not in text
    assert not failed.freshness.is_current  # old data is not relabelled as current
    # Failure is retried after the cooldown, not on every load, and recovery is clean.
    assert store.get(["SPY"], START).outcome is Outcome.CACHED
    provider.error, provider.published = None, {"SPY": [*MON_THU, FRI]}
    clock.set("2026-11-13 16:20")
    recovered = store.get(["SPY"], START)
    assert recovered.outcome is Outcome.UPDATED and recovered.last_error is None


def test_malformed_or_truncated_responses_are_rejected(tmp_path):
    store, provider, clock = make(tmp_path)
    good = store.get(["SPY"], START)
    clock.advance(minutes=5)
    provider.published["SPY"] = MON_THU[:2]  # the provider "loses" two sessions of history
    truncated = store.get(["SPY"], START, force=True)
    assert truncated.outcome is Outcome.FAILED and "ends before the verified cache" in truncated.last_error
    assert end_of(truncated) == end_of(good)

    clock.advance(minutes=5)
    provider._download = lambda t, s, e: pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex(["2026-11-12"]))
    malformed = store.get(["SPY"], START, force=True)  # payload without open/high/low/volume
    assert malformed.outcome is Outcome.FAILED and end_of(malformed) == end_of(good)


def test_failure_without_any_cache_raises_and_is_not_hammered(tmp_path):
    store, provider, clock = make(tmp_path, published={})
    with pytest.raises(NoUsableDataError, match="provider returned no data"):
        store.get(["ZZZZ"], START)
    assert provider.requests == 1
    clock.advance(seconds=30)
    with pytest.raises(NoUsableDataError, match="next attempt after"):
        store.get(["ZZZZ"], START)  # inside the cooldown: no second request
    assert provider.requests == 1
    provider.published = {"ZZZZ": list(MON_THU)}
    clock.advance(seconds=31)
    assert store.get(["ZZZZ"], START).outcome is Outcome.UPDATED and provider.requests == 2


# ----------------------------------------------------------------- cache integrity


def test_an_interrupted_write_leaves_the_previous_dataset_in_use(tmp_path, monkeypatch):
    store, provider, clock = make(tmp_path)
    good = store.get(["SPY"], START)
    folder = next(tmp_path.iterdir())
    version = (folder / "CURRENT").read_text()
    provider.published["SPY"].append(FRI)
    clock.set("2026-11-13 16:05")

    def dies_half_way(path, data):
        path.mkdir(parents=True)
        (path / "open.csv").write_text("date,SPY\n2026-11-")  # truncated, no metadata.json
        raise OSError("disk full")

    monkeypatch.setattr(refresh_module, "save_dataset", dies_half_way)
    result = store.get(["SPY"], START)
    assert result.outcome is Outcome.FAILED and "disk full" in result.last_error
    assert (folder / "CURRENT").read_text() == version and end_of(result) == "2026-11-12"
    monkeypatch.undo()

    restarted = LiveDataStore(provider, tmp_path, CALENDAR, clock)  # a new process after the crash
    after = restarted.get(["SPY"], START)
    pd.testing.assert_frame_equal(after.data.close, good.data.close, check_freq=False)
    clock.advance(minutes=20)
    assert restarted.get(["SPY"], START).outcome is Outcome.UPDATED
    assert all((folder / v / "metadata.json").exists() for v in restarted._versions(folder))  # debris gone


def test_a_corrupt_current_version_falls_back_to_the_previous_one(tmp_path):
    store, provider, clock = make(tmp_path)
    store.get(["SPY"], START)
    provider.published["SPY"].append(FRI)
    clock.set("2026-11-13 16:05")
    store.get(["SPY"], START)
    folder = next(tmp_path.iterdir())
    current = (folder / "CURRENT").read_text()
    (folder / current / "close.csv").write_text("\x00\x00 not a csv \x00")

    restarted = LiveDataStore(provider, tmp_path, CALENDAR, clock)
    provider.error = DataProviderError("provider down")  # so only the cache can answer
    clock.advance(minutes=1)
    result = restarted.get(["SPY"], START)
    assert end_of(result) == "2026-11-12"  # the previous verified version
    assert any("recovered the previous verified dataset" in n for n in result.notes)
    assert not result.freshness.is_current  # and it is honestly reported as behind


def test_a_corrupt_cache_with_no_fallback_is_refetched_or_reported(tmp_path):
    store, provider, clock = make(tmp_path)
    store.get(["SPY"], START)
    folder = next(tmp_path.iterdir())
    (folder / (folder / "CURRENT").read_text() / "metadata.json").write_text("{ broken")
    (folder / "refresh_state.json").write_text("also broken")  # unreadable state is tolerated
    clock.advance(minutes=1)
    fresh_store = LiveDataStore(provider, tmp_path, CALENDAR, clock)
    result = fresh_store.get(["SPY"], START)
    assert result.outcome is Outcome.UPDATED and provider.requests == 2
    assert any("unusable" in n for n in result.notes)

    (folder / (folder / "CURRENT").read_text() / "metadata.json").write_text("{ broken")
    for old in fresh_store._versions(folder):
        if old != (folder / "CURRENT").read_text():
            (folder / old / "metadata.json").write_text("{ broken")
    provider.error = DataProviderError("provider down")
    clock.advance(minutes=5)
    with pytest.raises(NoUsableDataError, match="provider down"):
        LiveDataStore(provider, tmp_path, CALENDAR, clock).get(["SPY"], START)


# ----------------------------------------------------------------- concurrency


def test_two_simultaneous_loads_make_one_provider_request(tmp_path):
    store, provider, _ = make(tmp_path)
    provider.delay = 0.2
    results, errors = [], []

    def load():
        try:
            results.append(store.get(["SPY"], START))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=load) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and provider.requests == 1
    assert sorted(r.outcome for r in results) == [Outcome.CACHED] * 3 + [Outcome.UPDATED]
    assert all(end_of(r) == "2026-11-12" for r in results)


def test_another_process_holding_the_lock_serves_cache_and_an_abandoned_lock_is_broken(tmp_path):
    store, provider, clock = make(tmp_path)
    store.get(["SPY"], START)
    folder = next(tmp_path.iterdir())
    lock = folder / ".lock"
    lock.write_text("4242")  # some other process is refreshing right now
    provider.published["SPY"].append(FRI)
    clock.set("2026-11-13 16:05")
    busy = store.get(["SPY"], START)
    assert busy.outcome is Outcome.CACHED and provider.requests == 1
    assert any("another process is refreshing" in n for n in busy.notes)
    old = time.time() - 600
    os.utime(lock, (old, old))  # the other process died ten minutes ago
    result = store.get(["SPY"], START)
    assert result.outcome is Outcome.UPDATED and not lock.exists()


# ----------------------------------------------------------------- invariants


def test_served_data_never_extends_past_the_last_completed_session(tmp_path):
    days = [str(d.date()) for d in pd.bdate_range("2026-11-02", "2026-11-30") if CALENDAR.is_session(d)]
    store, provider, clock = make(tmp_path, "2026-11-10 12:00", {"SPY": days})  # provider knows the "future"
    for _ in range(24 * 12):  # every two hours for 24 days, with occasional manual refreshes
        result = store.get(["SPY"], START, force=(clock.now.hour == 18))
        completed = CALENDAR.last_completed_session(clock.now)
        assert result.data.dates.max() <= completed
        assert result.freshness.is_current or result.outcome is not Outcome.UPDATED
        clock.advance(hours=2)
    assert end_of(result) == "2026-11-30"


def test_store_drops_unfinished_sessions_even_if_a_provider_does_not(tmp_path):
    """A provider with no notion of sessions (here: synthetic bars) cannot leak an open candle."""
    from quantlab.data import SyntheticProvider

    clock = Clock("2024-06-12 12:00")  # Wednesday, session in progress

    class Careless:
        name = "careless"

        def fetch(self, tickers, start, end=None):
            return SyntheticProvider(1).fetch(tickers, start, "2024-06-14")  # includes Wed-Fri

    result = LiveDataStore(Careless(), tmp_path, CALENDAR, clock).get(["X"], "2024-05-01")
    assert end_of(result) == "2024-06-11" and result.freshness.is_current
    assert result.data.dates.max() == pd.Timestamp("2024-06-11")


def test_result_export_contains_the_provenance_fields(tmp_path):
    store, provider, clock = make(tmp_path)
    info = store.get(["SPY"], START).to_dict()
    assert info["provider"] == "yfinance" and info["served_from"] == "provider"
    assert info["outcome"] == "updated" and info["last_attempt_outcome"] == "updated"
    assert info["freshness"]["expected_session"] == "2026-11-12"
    assert info["retrieved_at"] == info["last_attempt_at"] == "2026-11-12T22:00:00+00:00"
    assert Path(tmp_path).exists()
