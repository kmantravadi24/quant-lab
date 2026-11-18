"""Suites B and C: market-data integrity, freshness, cache, concurrency and recovery.

Everything runs against a scripted provider and a settable clock in a temporary
cache folder. The user's real cache is never touched.
"""

import os
import threading

import numpy as np
import pandas as pd
import pytest
from fixtures.app import LIVE_STATE, render, scripted_live, texts, view
from fixtures.live import CALENDAR, Clock, ScriptedYahoo, sessions, yahoo_frame

import quantlab.data.refresh as refresh_module
from quantlab.data import (
    DataError,
    DataProviderError,
    Freshness,
    InvalidTickerError,
    LiveDataStore,
    NoUsableDataError,
    Outcome,
    SyntheticProvider,
    assess_freshness,
    build_market_data,
)
from quantlab.data.transforms import simple_returns
from quantlab.portfolio.compare import common_window, data_fingerprint

WEEK = ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"]
START = "2026-11-01"


def make(tmp_path, when="2026-11-12 17:00", published=None):
    clock = Clock(when)
    provider = ScriptedYahoo(clock, published or {"SPY": list(WEEK)})
    return LiveDataStore(provider, tmp_path, CALENDAR, clock), provider, clock


class Payload(ScriptedYahoo):
    """Scripted provider whose raw response for one ticker is supplied verbatim."""

    def __init__(self, clock, frame):
        super().__init__(clock, {})
        self.frame = frame

    def _download(self, ticker, start, end):
        self.calls.append(ticker)
        return self.frame


def bars(dates, **overrides):
    frame = yahoo_frame(dates)
    for column, values in overrides.items():
        frame[column] = values
    return frame


# ================================================================= Suite B: data integrity


@pytest.mark.parametrize("column, value", [("Close", -1.0), ("Open", 0.0), ("High", np.inf),
                                           ("Low", -np.inf)])  # fmt: skip
def test_b01_nonpositive_or_infinite_prices_are_rejected_not_repaired(tmp_path, column, value):
    frame = bars(WEEK)
    frame.iloc[2, frame.columns.get_loc(column)] = value
    clock = Clock("2026-11-12 17:00")
    store = LiveDataStore(Payload(clock, frame), tmp_path, CALENDAR, clock)
    with pytest.raises(NoUsableDataError):
        store.get(["SPY"], START)
    assert not any(p.name == "CURRENT" for p in tmp_path.rglob("*"))  # nothing was stored


def test_b02_a_row_without_a_close_is_dropped_and_reported_never_filled(tmp_path):
    frame = bars(WEEK)
    frame.iloc[3, frame.columns.get_loc("Close")] = np.nan  # the placeholder row Yahoo was seen to send
    clock = Clock("2026-11-12 17:00")
    result = LiveDataStore(Payload(clock, frame), tmp_path, CALENDAR, clock).get(["SPY"], START)
    assert result.data.metadata.end == "2026-11-11"
    assert any("no close" in n for n in result.data.metadata.notes)
    assert result.freshness.state is Freshness.AWAITING_PROVIDER and not result.freshness.is_current
    assert pd.Timestamp("2026-11-12") not in result.data.close.index


def test_b03_missing_open_is_kept_as_missing_and_high_below_low_is_rejected():
    frame = bars(WEEK)
    frame.iloc[1, frame.columns.get_loc("Open")] = np.nan
    data = build_market_data({"SPY": frame}, "t", "none")
    assert np.isnan(data.open["SPY"].iloc[1]) and data.close["SPY"].notna().all()
    broken = bars(WEEK)
    broken["High"] = broken["Low"] - 1.0
    with pytest.raises(DataError, match="high < low"):
        build_market_data({"SPY": broken}, "t", "none")


def test_b04_duplicate_and_out_of_order_rows_are_normalised_and_disclosed():
    frame = bars(["2026-11-11", "2026-11-09", "2026-11-10", "2026-11-09"])
    data = build_market_data({"SPY": frame}, "t", "none")
    assert [str(d.date()) for d in data.dates] == ["2026-11-09", "2026-11-10", "2026-11-11"]
    assert data.close["SPY"].iloc[0] == frame["Close"].iloc[3]  # the last duplicate wins
    assert any("duplicate" in n for n in data.metadata.notes)


def test_b05_a_missing_session_is_never_forward_filled_into_a_return():
    frames = {"A": bars(WEEK), "B": bars([WEEK[0], WEEK[1], WEEK[3]])}  # B has no bar on the 11th
    data = build_market_data(frames, "t", "none")
    assert np.isnan(data.close.loc["2026-11-11", "B"])
    returns = simple_returns(data.close)
    assert np.isnan(returns.loc["2026-11-11", "B"]) and np.isnan(returns.loc["2026-11-12", "B"])
    assert any("B: 1 session" in n for n in data.metadata.notes)
    before = data.close.copy()
    assess_freshness(data, pd.Timestamp("2026-11-12 22:00", tz="UTC"), CALENDAR)
    pd.testing.assert_frame_equal(data.close, before)


@pytest.mark.parametrize("payload", [
    pd.DataFrame(), pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex(["2026-11-12"])),
    pd.DataFrame({"Open": ["x"], "High": ["y"], "Low": ["z"], "Close": ["w"], "Volume": [1]},
                 index=pd.DatetimeIndex(["2026-11-12"])),
    None,
])  # fmt: skip
def test_b06_empty_or_malformed_provider_responses_never_become_data(tmp_path, payload):
    clock = Clock("2026-11-12 17:00")
    store = LiveDataStore(Payload(clock, payload), tmp_path, CALENDAR, clock)
    with pytest.raises(NoUsableDataError):
        store.get(["SPY"], START)


@pytest.mark.parametrize("error, phrase", [
    (DataProviderError("HTTP Error 429: Too Many Requests"), "rate limiting"),
    (DataProviderError("HTTP Error 503: Service Unavailable"), "503"),
    (ConnectionError("Connection reset by peer"), "Connection reset"),
    (TimeoutError("timed out"), "timed out"),
    (InvalidTickerError("SPY: provider returned no data (invalid ticker or provider outage)"), "no data"),
])  # fmt: skip
def test_b07_failures_are_classified_as_far_as_the_evidence_allows(tmp_path, error, phrase):
    store, provider, clock = make(tmp_path)
    store.get(["SPY"], START)
    provider.error = error
    clock.set("2026-11-13 16:05")
    result = store.get(["SPY"], START)
    assert result.outcome is Outcome.FAILED and phrase in result.last_error
    assert result.data.metadata.end == "2026-11-12" and not result.freshness.is_current


def test_b08_an_incomplete_session_never_enters_the_verified_dataset(tmp_path):
    days = sessions("2026-10-01", "2026-11-30")
    store, provider, clock = make(tmp_path, "2026-10-01 12:00", {"SPY": days, "TLT": days})
    for _ in range(24 * 30):  # hourly for thirty days; the provider already "knows" every later bar
        try:
            result = store.get(["SPY", "TLT"], "2026-10-01", force=(clock.now.hour == 10))
        except NoUsableDataError:
            clock.advance(hours=1)
            continue
        completed = CALENDAR.last_completed_session(clock.now)
        assert result.data.dates.max() <= completed
        if result.freshness.is_current:  # "current" is claimed only with every completed session
            assert all(result.data.close[t].last_valid_index() == completed for t in ("SPY", "TLT"))
        clock.advance(hours=1)


def test_b09_stale_and_missing_data_is_identified_per_instrument(tmp_path):
    published = {"SPY": [*WEEK, "2026-11-13"], "TLT": list(WEEK), "GLD": WEEK[:2]}
    store, provider, clock = make(tmp_path, "2026-11-13 19:00", published)
    result = store.get(["SPY", "TLT", "GLD"], START)
    rows = {i.ticker: (i.state, i.sessions_behind) for i in result.freshness.instruments}
    assert rows == {"SPY": (Freshness.CURRENT, 0), "TLT": (Freshness.STALE, 1),
                    "GLD": (Freshness.STALE, 3)}  # fmt: skip
    assert not result.freshness.is_current and "TLT" in result.headline()[1]


def test_b10_synthetic_data_never_replaces_real_data_silently(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(view("overview").parents[1]))
    clock, provider, store = scripted_live(tmp_path, monkeypatch)
    provider.error = DataProviderError("network unreachable")
    at = render(view("overview"), monkeypatch, **LIVE_STATE)
    assert not at.exception and any("No usable data" in e.value for e in at.error)
    assert "SYNTHETIC" not in texts(at) and not at.metric  # no synthetic numbers appear
    assert at.session_state["p_source"] == LIVE_STATE["p_source"]  # the source was not switched
    for dataset in (SyntheticProvider(1).fetch(["X"], "2024-01-01", "2024-03-01"),):
        assert dataset.metadata.synthetic and "SYNTHETIC" in " ".join(dataset.metadata.notes)


def test_b11_a_live_refresh_cannot_change_the_frozen_study_inputs(tmp_path):
    import hashlib
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "experiments" / "MANIFEST.json").read_text())["dataset"]
    folder = root / manifest["path"]
    if not folder.exists():
        pytest.skip("the private reference dataset is not part of this checkout")
    before = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in folder.iterdir()}
    assert before == manifest["sha256"]  # the frozen files are exactly the recorded ones
    store, provider, clock = make(tmp_path, published={"SPY": list(WEEK), "QQQ": list(WEEK), "IWM": list(WEEK)})
    store.get(["SPY", "QQQ", "IWM"], START)
    clock.advance(minutes=5)
    store.get(["SPY", "QQQ", "IWM"], START, force=True)
    after = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in folder.iterdir()}
    assert after == before and tmp_path.resolve() not in folder.resolve().parents
    assert not str(store.cache_dir.resolve()).startswith(str((root / "experiments").resolve()))


def test_b12_late_listed_instrument_window_characterisation():
    """QA-010 (the 'BND' observation): how one short-history instrument changes each window."""
    nan = np.nan
    rng = np.random.default_rng(4)
    long = (100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400)))).tolist()
    index = pd.bdate_range("2005-01-03", periods=400)
    from fixtures.synthetic import make_data

    data = make_data({"SPY": long, "BND": [nan] * 250 + long[:150]}, dates=index)
    # Investment Lab: only instruments that are actually held restrict the window.
    assert len(common_window(data, ["SPY"]).dates) == 400
    assert len(common_window(data, ["SPY", "BND"]).dates) == 150
    # Risk / Monte Carlo / Stress pages: every LOADED instrument restricts it, held or not.
    assert len(simple_returns(data.close).dropna(how="any")) == 149


def _risk_page_sessions(monkeypatch, frames, weights) -> int:
    """Number of sessions the Risk page says it estimated on, for uploaded data."""
    import re

    from fixtures.app import USER

    at = render(view("risk"), monkeypatch, p_source=USER, user_frames=frames, **weights)
    assert not at.exception
    caption = next(c.value for c in at.caption if "Historical estimate on" in c.value)
    return int(re.search(r"\(([\d,]+) sessions\)", caption).group(1).replace(",", ""))


def _unequal_history_frames():
    rng = np.random.default_rng(4)
    index = pd.bdate_range("2023-01-02", periods=400)
    prices = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400)))
    frame = pd.DataFrame({"open": prices, "high": prices * 1.01, "low": prices * 0.99,
                          "close": prices, "volume": 1.0}, index=index)  # fmt: skip
    return {"SPY": frame, "BND": frame.iloc[250:] * 0.5}


def test_b12a_risk_page_window_with_an_unheld_short_history_instrument(monkeypatch):
    """QA-010 (fixed): holding 100% SPY, a loaded-but-unheld BND no longer cuts the sample
    from 252 to 149 sessions; the page says why."""
    frames = _unequal_history_frames()
    assert _risk_page_sessions(monkeypatch, frames, {"p_w_SPY": 100.0, "p_w_BND": 0.0}) == 252
    assert _risk_page_sessions(monkeypatch, {"SPY": frames["SPY"]}, {"p_w_SPY": 100.0}) == 252
    # Holding BND as well legitimately limits the window to BND's history.
    assert _risk_page_sessions(monkeypatch, frames, {"p_w_SPY": 50.0, "p_w_BND": 50.0}) == 149


def test_b12b_unheld_instrument_does_not_shorten_any_fixed_weight_page(monkeypatch):
    from fixtures.app import USER

    frames = _unequal_history_frames()
    state = {"p_source": USER, "user_frames": frames, "p_w_SPY": 100.0, "p_w_BND": 0.0}
    risk = render(view("risk"), monkeypatch, **state)
    assert "BND is loaded but not held" in " ".join(c.value for c in risk.caption)
    mc = render(view("monte_carlo"), monkeypatch, **state)
    assert not mc.exception
    assert "252 past days" in " ".join(i.value for i in mc.info)  # one year of SPY, not 149
    stress = render(view("stress"), monkeypatch, **state)
    assert not stress.exception
    assert all("BND" not in str(c) for d in stress.dataframe for c in d.value.columns)


def test_b13_revised_history_is_stored_and_reported(tmp_path, monkeypatch):
    """QA-007 (fixed): a revision is stored (it is the provider's current data) AND reported."""
    import fixtures.live as live

    store, provider, clock = make(tmp_path)
    first = store.get(["SPY"], START)
    original = live.yahoo_frame
    monkeypatch.setattr(live, "yahoo_frame", lambda dates, base=10.0: original(dates, base=10.5))
    clock.advance(minutes=5)
    second = store.get(["SPY"], START, force=True)
    assert second.outcome is Outcome.REVISED
    assert not second.data.close.equals(first.data.close)
    assert data_fingerprint(second.data) != data_fingerprint(first.data)
    revision = second.revisions["SPY"]
    assert revision["sessions"] == len(first.data.dates) and revision["largest_change"] > 0.01
    level, sentence = second.headline()
    assert level == "warning" and "History revised" in sentence and "will not reproduce" in sentence
    assert second.to_dict()["revisions"]["SPY"]["sessions"] == revision["sessions"]


def test_b13b_a_revision_of_history_is_reported_and_an_identical_refetch_is_not(tmp_path, monkeypatch):
    import fixtures.live as live

    store, provider, clock = make(tmp_path)
    store.get(["SPY"], START)
    clock.advance(minutes=5)
    same = store.get(["SPY"], START, force=True)  # identical data: CSV round trip is not a revision
    assert same.outcome is Outcome.UNCHANGED and same.revisions == {} and same.notes == ()
    original = live.yahoo_frame
    monkeypatch.setattr(live, "yahoo_frame", lambda dates, base=10.0: original(dates, base=10.5))
    clock.advance(minutes=5)
    result = store.get(["SPY"], START, force=True)
    assert any("revis" in n.lower() for n in result.notes) or "revis" in result.headline()[1].lower()


def test_b14_partial_instrument_response_characterisation(tmp_path):
    """QA-017: one unavailable instrument fails the whole selection; valid data is kept."""
    store, provider, clock = make(tmp_path, published={"SPY": list(WEEK), "TLT": list(WEEK)})
    store.get(["SPY", "TLT"], START)
    provider.published = {"SPY": [*WEEK, "2026-11-13"]}  # TLT disappears from the provider
    clock.set("2026-11-13 16:10")
    result = store.get(["SPY", "TLT"], START)
    assert result.outcome is Outcome.FAILED and "TLT" in result.last_error
    assert result.data.metadata.end == "2026-11-12"  # SPY's new bar is not used either


# ================================================================= Suite C: cache and recovery


def test_c01_repeated_reruns_use_memory_and_never_redownload(tmp_path):
    store, provider, clock = make(tmp_path)
    first = store.get(["SPY"], START)
    for _ in range(200):
        clock.advance(seconds=20)
        assert store.get(["SPY"], START).data is first.data
    assert provider.requests == 1


def test_c02_restart_recovers_data_cooldown_and_attempt_history(tmp_path):
    store, provider, clock = make(tmp_path)
    store.get(["SPY"], START)
    clock.set("2026-11-13 16:00")  # closed; provider has nothing new
    store.get(["SPY"], START)
    restarted = LiveDataStore(provider, tmp_path, CALENDAR, clock)  # a fresh process
    clock.advance(minutes=5)
    result = restarted.get(["SPY"], START)
    assert result.outcome is Outcome.CACHED and provider.requests == 2  # cooldown survived
    assert result.last_attempt_outcome == "unchanged" and result.next_check_at is not None
    assert result.data.metadata.end == "2026-11-12"


def test_c03_recovering_from_an_invalid_selection_back_to_a_valid_one(tmp_path):
    store, provider, clock = make(tmp_path)
    good = store.get(["SPY"], START)
    with pytest.raises(NoUsableDataError):
        store.get(["SPY", "NOPE"], START)
    clock.advance(seconds=5)
    again = store.get(["SPY"], START)  # the valid dataset is unaffected by the failed one
    assert again.outcome is Outcome.CACHED and again.data is good.data and again.last_error is None


def test_c04_many_simultaneous_users_cause_one_download_and_see_one_dataset(tmp_path):
    store, provider, _ = make(tmp_path)
    provider.delay = 0.05
    results, errors = [], []

    def user():
        try:
            results.append(store.get(["SPY"], START))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=user) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and provider.requests == 1
    assert len({id(r.data) for r in results}) == 1
    assert sum(r.outcome is Outcome.UPDATED for r in results) == 1


def test_c05_interrupted_write_and_corruption_never_lose_the_verified_dataset(tmp_path, monkeypatch):
    store, provider, clock = make(tmp_path)
    good = store.get(["SPY"], START)
    folder = next(tmp_path.iterdir())
    provider.published["SPY"].append("2026-11-13")
    clock.set("2026-11-13 16:05")

    def half_written(path, data):
        path.mkdir(parents=True)
        (path / "close.csv").write_text("date,SPY\n2026-11-0")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(refresh_module, "save_dataset", half_written)
    failed = store.get(["SPY"], START)
    monkeypatch.undo()
    assert failed.outcome is Outcome.FAILED and "No space left" in failed.last_error
    pd.testing.assert_frame_equal(failed.data.close, good.data.close)
    survivor = LiveDataStore(provider, tmp_path, CALENDAR, clock).get(["SPY"], START)
    pd.testing.assert_frame_equal(survivor.data.close, good.data.close, check_freq=False)
    # Now corrupt the live version itself: with no fallback left it is refetched, not served.
    current = (folder / "CURRENT").read_text()
    (folder / current / "open.csv").write_bytes(b"\xff\xfe garbage")
    clock.advance(minutes=30)
    healed = LiveDataStore(provider, tmp_path, CALENDAR, clock).get(["SPY"], START)
    assert healed.outcome is Outcome.UPDATED and healed.data.metadata.end == "2026-11-13"
    assert any("unusable" in n for n in healed.notes)


def test_c06_expired_cache_is_rechecked_once_and_no_cache_startup_downloads_once(tmp_path):
    store, provider, clock = make(tmp_path, "2026-11-13 17:00", {"SPY": [*WEEK, "2026-11-13"]})
    assert store.get(["SPY"], START).outcome is Outcome.UPDATED  # no-cache startup
    clock.set("2026-11-21 12:00")  # eight days later, a Saturday; provider has the new week
    provider.published["SPY"] += sessions("2026-11-16", "2026-11-20")
    result = store.get(["SPY"], START)
    assert result.outcome is Outcome.UPDATED and result.new_observations == {"SPY": 5}
    assert provider.requests == 2
    assert store.get(["SPY"], START).outcome is Outcome.CACHED and provider.requests == 2


def test_c07_unwritable_cache_serves_verified_data_and_never_contacts_the_provider(tmp_path, monkeypatch):
    """QA-006 (fixed): a lock that cannot be created no longer raises PermissionError."""
    store, provider, clock = make(tmp_path)
    store.get(["SPY"], START)
    provider.published["SPY"].append("2026-11-13")
    clock.set("2026-11-13 16:05")
    real_open = os.open
    before = provider.requests

    def denied(path, flags, *args, **kwargs):
        if flags & os.O_CREAT:
            raise PermissionError(13, "Permission denied", str(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", denied)
    result = store.get(["SPY"], START)
    assert result.outcome is Outcome.FAILED and result.data.metadata.end == "2026-11-12"
    assert provider.requests == before  # an attempt that cannot be recorded is not made
    assert "cannot be written" in result.last_error and str(tmp_path) not in result.headline()[1]
    monkeypatch.undo()
    assert store.get(["SPY"], START).data.metadata.end == "2026-11-13"  # recovers once writable


def test_c07b_unwritable_cache_serves_the_verified_dataset_with_a_warning(tmp_path, monkeypatch):
    store, provider, clock = make(tmp_path)
    store.get(["SPY"], START)
    provider.published["SPY"].append("2026-11-13")
    clock.set("2026-11-13 16:05")
    monkeypatch.setattr(refresh_module.LiveDataStore, "_write_state",
                        lambda self, folder, state: (_ for _ in ()).throw(PermissionError(13, "denied")))  # fmt: skip
    result = store.get(["SPY"], START)
    assert result.outcome is Outcome.FAILED and result.data.metadata.end == "2026-11-12"
    assert result.headline()[0] == "warning" and "cannot be written" in result.headline()[1]


def test_c07c_unwritable_cache_with_nothing_cached_explains_how_to_fix_it(tmp_path, monkeypatch):
    store, provider, clock = make(tmp_path)
    monkeypatch.setattr(refresh_module.LiveDataStore, "_write_state",
                        lambda self, folder, state: (_ for _ in ()).throw(PermissionError(13, "denied")))  # fmt: skip
    with pytest.raises(NoUsableDataError, match="QUANTLAB_CACHE_DIR"):
        store.get(["SPY"], START)
    assert provider.requests == 0


def test_c08_dashboard_refresh_states_end_to_end(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(view("overview").parents[1]))
    clock, provider, store = scripted_live(tmp_path, monkeypatch)
    at = render(view("overview"), monkeypatch, **LIVE_STATE)
    assert "Loaded" in texts(at) and provider.requests == 2
    for _ in range(5):  # reruns: no downloads
        at.run()
    assert provider.requests == 2
    clock.advance(minutes=3)
    at.button(key="refresh_live").click().run()
    assert "Checked; unchanged" in texts(at) and provider.requests == 4
    clock.advance(seconds=10)
    at.button(key="refresh_live").click().run()
    assert "Refresh limited" in texts(at) and provider.requests == 4
    provider.error = DataProviderError("HTTP Error 429: Too Many Requests")
    clock.set("2026-11-13 16:30")
    at.run()
    page = texts(at)
    assert "Refresh failed" in page and "rate limiting" in page and "current through" not in page
    assert not at.exception and 'class="ql-badge' in page  # still showing the verified data
