"""Offline stand-ins for the live provider: a settable clock and a scripted Yahoo."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantlab.data import SessionCalendar, YFinanceProvider

CALENDAR = SessionCalendar()


def ny(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="America/New_York")


class Clock:
    """A clock tests can set. Called like the real one."""

    def __init__(self, text: str):
        self.now = ny(text)

    def __call__(self) -> pd.Timestamp:
        return self.now

    def set(self, text: str) -> None:
        self.now = ny(text)

    def advance(self, **delta) -> None:
        self.now = self.now + pd.Timedelta(**delta)


def yahoo_frame(dates, base: float = 10.0) -> pd.DataFrame:
    """Daily bars shaped like a yfinance response (timezone-aware New York index)."""
    index = pd.DatetimeIndex(dates).tz_localize("America/New_York")
    n = np.arange(len(index), dtype=float)
    return pd.DataFrame({"Open": base + n, "High": base + n + 1, "Low": base + n - 1,
                         "Close": base + n + 0.5, "Volume": 1e6}, index=index)  # fmt: skip


class ScriptedYahoo(YFinanceProvider):
    """The real provider class with only the network call replaced.

    ``published`` maps ticker -> list of session dates the "provider" currently
    has. ``error`` (an exception) makes every download fail. ``calls`` counts
    download requests per ticker.
    """

    def __init__(self, clock: Clock, published: dict[str, list[str]]):
        super().__init__(calendar=CALENDAR, clock=clock)
        self.published = published
        self.error: Exception | None = None
        self.calls: list[str] = []
        self.delay = 0.0

    def _download(self, ticker, start, end):
        self.calls.append(ticker)
        if self.delay:
            import time

            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        dates = [d for d in self.published.get(ticker, []) if d >= str(start)]
        return yahoo_frame(dates) if dates else pd.DataFrame()

    @property
    def requests(self) -> int:
        return len(self.calls)


def sessions(start: str, end: str) -> list[str]:
    """Every NYSE session date in [start, end]."""
    return [str(d.date()) for d in pd.bdate_range(start, end) if CALENDAR.is_session(d)]
