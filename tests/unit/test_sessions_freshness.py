"""Phase 1 of forward testing: completed-session detection and data freshness.

Every test injects the current time; nothing depends on the wall clock or the network.
Calendar facts used (NYSE): Thanksgiving 2026-11-26 is a holiday; 2026-11-27 closes
early at 13:00; 2025-01-09 was a one-off closure (national day of mourning);
2012-10-29 and 30 were closed for Hurricane Sandy.
"""

import numpy as np
import pandas as pd
import pytest
from fixtures.synthetic import make_data

pytest.importorskip("exchange_calendars")

from quantlab.data import (  # noqa: E402
    CachedProvider,
    CalendarError,
    DataProviderError,
    Freshness,
    InvalidTickerError,
    SessionCalendar,
    YFinanceProvider,
    assess_freshness,
)

CAL = SessionCalendar()


def ny(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="America/New_York")


def day(text: str) -> pd.Timestamp:
    return pd.Timestamp(text)


# ----------------------------------------------------------------- completed sessions


@pytest.mark.parametrize(
    "now, completed, in_progress",
    [
        ("2026-11-13 09:29:59", "2026-11-12", None),  # Friday, one second before the open
        ("2026-11-13 09:30:00", "2026-11-12", "2026-11-13"),  # the open
        ("2026-11-13 15:59:59", "2026-11-12", "2026-11-13"),  # one second before the close
        ("2026-11-13 16:00:00", "2026-11-13", None),  # the official close: complete
        ("2026-11-13 23:30:00", "2026-11-13", None),  # Friday night
        ("2026-11-14 12:00:00", "2026-11-13", None),  # Saturday
        ("2026-11-15 12:00:00", "2026-11-13", None),  # Sunday
        ("2026-11-16 08:00:00", "2026-11-13", None),  # Monday before the open
        ("2026-11-16 12:00:00", "2026-11-13", "2026-11-16"),  # Monday midday
        ("2026-11-26 12:00:00", "2026-11-25", None),  # Thanksgiving: no session at all
        ("2026-11-27 12:59:59", "2026-11-25", "2026-11-27"),  # early-close day, before 13:00
        ("2026-11-27 13:00:00", "2026-11-27", None),  # early close reached
        ("2026-11-27 15:00:00", "2026-11-27", None),  # would still be "open" on a normal day
        ("2025-01-09 17:00:00", "2025-01-08", None),  # one-off closure on a Thursday
        ("2012-10-30 20:00:00", "2012-10-26", None),  # second day of the Sandy closure
    ],
)
def test_last_completed_session(now, completed, in_progress):
    status = CAL.status(ny(now))
    assert status.last_completed == day(completed)
    assert status.in_progress == (None if in_progress is None else day(in_progress))
    assert status.market_open is (in_progress is not None)
    assert status.last_completed_close <= status.as_of < status.next_open


def test_session_close_times_respect_early_closes_and_daylight_saving():
    assert CAL.session_close("2026-11-13") == pd.Timestamp("2026-11-13 21:00", tz="UTC")  # EST
    assert CAL.session_close("2026-07-01") == pd.Timestamp("2026-07-01 20:00", tz="UTC")  # EDT
    assert CAL.session_close("2026-11-27") == pd.Timestamp("2026-11-27 18:00", tz="UTC")  # 13:00
    assert CAL.is_session("2026-11-25") and not CAL.is_session("2026-11-26")
    assert not CAL.is_session("2026-11-14") and not CAL.is_session("2025-01-09")
    with pytest.raises(CalendarError):
        CAL.session_close("2026-11-26")


def test_next_session_skips_weekends_and_holidays():
    assert CAL.status(ny("2026-11-13 17:00")).next_session == day("2026-11-16")
    assert CAL.status(ny("2026-11-25 17:00")).next_session == day("2026-11-27")
    # During a session, "next" is the one after the session in progress.
    assert CAL.status(ny("2026-11-16 12:00")).next_session == day("2026-11-17")
    assert CAL.previous_session(day("2026-11-27")) == day("2026-11-25")
    assert CAL.sessions_between(day("2026-11-20"), day("2026-11-27")) == 4  # 23, 24, 25, 27


def test_the_same_instant_gives_the_same_answer_in_any_time_zone():
    instant = pd.Timestamp("2026-11-13 21:00:00", tz="UTC")  # exactly the close
    for zone in ("UTC", "America/New_York", "Asia/Tokyo", "Europe/London", "America/Los_Angeles"):
        assert CAL.last_completed_session(instant.tz_convert(zone)) == day("2026-11-13")
    # In Tokyo it is already Saturday morning, but the session that just closed is Friday's.
    assert instant.tz_convert("Asia/Tokyo").date().isoformat() == "2026-11-14"
    before = instant - pd.Timedelta(seconds=1)
    assert CAL.last_completed_session(before.tz_convert("Asia/Tokyo")) == day("2026-11-12")


def test_naive_and_out_of_range_timestamps_are_refused():
    with pytest.raises(ValueError, match="timezone-aware"):
        CAL.status(pd.Timestamp("2026-11-13 16:00"))
    with pytest.raises(ValueError, match="timezone-aware"):
        assess_freshness({"A": day("2026-11-13")}, pd.Timestamp("2026-11-13 16:00"), CAL)
    with pytest.raises(CalendarError):
        CAL.status(pd.Timestamp("1990-01-02 12:00", tz="UTC"))
    with pytest.raises(CalendarError):
        CAL.status(pd.Timestamp("2099-01-02 12:00", tz="UTC"))


# ----------------------------------------------------------------- freshness


@pytest.mark.parametrize(
    "now, last, state, behind",
    [
        ("2026-11-13 16:30", "2026-11-13", Freshness.CURRENT, 0),
        ("2026-11-16 12:00", "2026-11-13", Freshness.CURRENT, 0),  # market open: Friday is right
        ("2026-11-13 16:00", "2026-11-12", Freshness.AWAITING_PROVIDER, 1),  # just closed
        ("2026-11-13 17:59", "2026-11-12", Freshness.AWAITING_PROVIDER, 1),  # inside 2 h grace
        ("2026-11-13 18:00", "2026-11-12", Freshness.STALE, 1),  # grace over
        ("2026-11-14 10:00", "2026-11-12", Freshness.STALE, 1),  # next morning
        ("2026-11-13 16:30", "2026-11-11", Freshness.STALE, 2),  # two behind: never "awaiting"
        ("2026-11-27 13:30", "2026-11-25", Freshness.AWAITING_PROVIDER, 1),  # holiday not counted
        ("2026-11-27 16:00", "2026-11-25", Freshness.STALE, 1),  # 3 h after the 13:00 close
        ("2026-11-26 12:00", "2026-11-25", Freshness.CURRENT, 0),  # holiday: nothing new expected
        ("2026-11-13 12:00", "2026-11-13", Freshness.INCOMPLETE, 0),  # bar for an open session
    ],
)
def test_freshness_states(now, last, state, behind):
    report = assess_freshness({"X": day(last)}, ny(now), CAL)
    item = report.instruments[0]
    assert (item.state, item.sessions_behind) == (state, behind)
    assert report.state is state and report.is_current is (state is Freshness.CURRENT)


def test_publication_grace_is_configurable():
    obs, now = {"X": day("2026-11-12")}, ny("2026-11-13 18:30")
    assert assess_freshness(obs, now, CAL).state is Freshness.STALE
    patient = assess_freshness(obs, now, CAL, publication_grace=pd.Timedelta(hours=4))
    assert patient.state is Freshness.AWAITING_PROVIDER
    assert assess_freshness(obs, now, CAL, pd.Timedelta(0)).state is Freshness.STALE


def test_instruments_are_assessed_separately_and_nothing_is_filled():
    nan = np.nan
    dates = pd.DatetimeIndex(["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"])
    data = make_data(
        {"UP": [1.0, 2.0, 3.0, 4.0], "LAG": [1.0, 2.0, 3.0, nan], "OLD": [1.0, nan, nan, nan],
         "NONE": [nan, nan, nan, nan]},
        dates=dates,
    )  # fmt: skip
    before = data.close.copy()
    report = assess_freshness(data, ny("2026-11-13 16:30"), CAL)
    states = {i.ticker: (i.state, i.sessions_behind) for i in report.instruments}
    assert states == {
        "UP": (Freshness.CURRENT, 0),
        "LAG": (Freshness.AWAITING_PROVIDER, 1),
        "OLD": (Freshness.STALE, 3),
        "NONE": (Freshness.NO_DATA, 0),
    }
    assert report.state is Freshness.NO_DATA  # the dataset is as good as its worst instrument
    assert report.by_state(Freshness.STALE) == ["OLD"]
    pd.testing.assert_frame_equal(data.close, before)  # the assessment changed nothing
    assert data.close["LAG"].isna().iloc[-1]  # the missing price is still missing


def test_report_wording_distinguishes_the_situations():
    def say(last, now):
        return assess_freshness({"X": day(last)}, ny(now), CAL).summary()

    assert say("2026-11-13", "2026-11-13 16:30") == (
        "ok", "Data is current through 2026-11-13, the last completed session.")  # fmt: skip
    level, text = say("2026-11-13", "2026-11-16 12:00")
    assert level == "ok" and "2026-11-16 session is still in progress" in text
    level, text = say("2026-11-12", "2026-11-13 16:10")
    assert level == "info" and "has not yet published" in text
    level, text = say("2026-11-06", "2026-11-13 16:10")
    assert level == "warning" and "out of date" in text and "5 completed session" in text
    level, text = say("2026-11-13", "2026-11-13 12:00")
    assert level == "warning" and "not a valid daily observation" in text
    report = assess_freshness({"X": day("2026-11-12")}, ny("2026-11-13 16:10"), CAL)
    as_dict = report.to_dict()
    assert as_dict["expected_session"] == "2026-11-13" and as_dict["state"] == "awaiting_provider"
    assert as_dict["instruments"] == [{"ticker": "X", "last_observation": "2026-11-12",
                                       "state": "awaiting_provider", "sessions_behind": 1}]  # fmt: skip


# ----------------------------------------------------------------- provider integration


class OfflineYahoo(YFinanceProvider):
    """The real provider with the network call replaced by fixture frames shaped like Yahoo's."""

    def __init__(self, frames, now):
        super().__init__(calendar=CAL, clock=lambda: now)
        self.frames = frames

    def _download(self, ticker, start, end):
        return self.frames.get(ticker, pd.DataFrame())


def yahoo_frame(dates):
    index = pd.DatetimeIndex(dates).tz_localize("America/New_York")  # Yahoo labels bars this way
    n = len(index)
    return pd.DataFrame({"Open": np.arange(n) + 10.0, "High": np.arange(n) + 11.0,
                         "Low": np.arange(n) + 9.0, "Close": np.arange(n) + 10.5,
                         "Volume": 1e6}, index=index)  # fmt: skip


WEEK = ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"]


def test_provider_excludes_a_bar_until_its_session_has_closed():
    frames = {"SPY": yahoo_frame(WEEK)}  # the provider already shows a partial Friday bar
    during = OfflineYahoo(frames, ny("2026-11-13 15:59")).fetch(["SPY"], "2026-11-01")
    assert during.metadata.end == "2026-11-12" and len(during.dates) == 4
    after = OfflineYahoo(frames, ny("2026-11-13 16:00")).fetch(["SPY"], "2026-11-01")
    assert after.metadata.end == "2026-11-13" and len(after.dates) == 5
    assert "last completed XNYS session was 2026-11-13" in after.metadata.notes[0]
    assert after.dates.tz is None  # same session labelling as every other data source


def test_provider_on_an_early_close_day():
    days = ["2026-11-24", "2026-11-25", "2026-11-27"]
    frames = {"SPY": yahoo_frame(days)}
    assert OfflineYahoo(frames, ny("2026-11-27 12:30")).fetch(["SPY"], "2026-11-01").metadata.end == "2026-11-25"
    assert OfflineYahoo(frames, ny("2026-11-27 13:05")).fetch(["SPY"], "2026-11-01").metadata.end == "2026-11-27"


def test_delayed_publication_is_reported_not_papered_over():
    frames = {"SPY": yahoo_frame(WEEK), "TLT": yahoo_frame(WEEK[:4])}  # TLT's Friday bar is late
    now = ny("2026-11-13 16:20")
    data = OfflineYahoo(frames, now).fetch(["SPY", "TLT"], "2026-11-01")
    assert np.isnan(data.close.loc["2026-11-13", "TLT"])  # no value invented for the late bar
    report = assess_freshness(data, now, CAL)
    assert {i.ticker: i.state for i in report.instruments} == {
        "SPY": Freshness.CURRENT, "TLT": Freshness.AWAITING_PROVIDER}  # fmt: skip
    later = assess_freshness(data, ny("2026-11-14 09:00"), CAL)
    assert later.by_state(Freshness.STALE) == ["TLT"]


def test_unavailable_provider_data_raises_and_calendar_failure_is_explained():
    with pytest.raises(InvalidTickerError):
        OfflineYahoo({}, ny("2026-11-13 17:00")).fetch(["ZZZZ"], "2026-11-01")
    only_today = {"SPY": yahoo_frame(["2026-11-13"])}
    with pytest.raises(InvalidTickerError, match="no completed sessions"):
        OfflineYahoo(only_today, ny("2026-11-13 10:00")).fetch(["SPY"], "2026-11-13")
    with pytest.raises(DataProviderError, match="Cannot determine completed sessions"):
        OfflineYahoo(only_today, pd.Timestamp("2099-01-01", tz="UTC")).fetch(["SPY"], "2026-11-01")


def test_cached_provider_still_wraps_the_calendar_aware_provider(tmp_path):
    inner = OfflineYahoo({"SPY": yahoo_frame(WEEK)}, ny("2026-11-13 17:00"))
    cached = CachedProvider(inner, tmp_path, max_age_hours=1e9)
    first = cached.fetch(["SPY"], "2026-11-01")
    again = cached.fetch(["SPY"], "2026-11-01")
    pd.testing.assert_frame_equal(first.close, again.close, check_freq=False)
    assert again.metadata.source == "yfinance" and again.metadata.end == "2026-11-13"
