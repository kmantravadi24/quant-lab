"""Is a dataset up to date? Compare what the exchange says should exist with what we hold.

Four situations must not be confused:

CURRENT            the latest observation is the last completed session
AWAITING_PROVIDER  that session closed recently and the provider has not published it yet
STALE              one or more completed sessions are missing and the delay is no longer plausible
INCOMPLETE         an observation exists for a session that has not closed (not a valid daily bar)
NO_DATA            the instrument has no observation at all

While a session is in progress, data through the previous session is CURRENT:
the report says separately that the market is open. Nothing here fills,
forwards or estimates a missing price.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import pandas as pd

from quantlab.data.models import MarketData
from quantlab.data.sessions import SessionCalendar, SessionStatus, require_aware

DEFAULT_PUBLICATION_GRACE = pd.Timedelta(hours=2)


class Freshness(StrEnum):
    CURRENT = "current"
    AWAITING_PROVIDER = "awaiting_provider"
    STALE = "stale"
    INCOMPLETE = "incomplete_session"
    NO_DATA = "no_data"


# Worst first: the dataset as a whole is only as good as its worst instrument.
_SEVERITY = [Freshness.NO_DATA, Freshness.INCOMPLETE, Freshness.STALE,
             Freshness.AWAITING_PROVIDER, Freshness.CURRENT]  # fmt: skip


@dataclass(frozen=True)
class InstrumentFreshness:
    ticker: str
    last_observation: pd.Timestamp | None
    state: Freshness
    sessions_behind: int  # completed sessions with no observation; 0 when current

    def to_dict(self) -> dict:
        last = None if self.last_observation is None else str(self.last_observation.date())
        return {"ticker": self.ticker, "last_observation": last, "state": self.state.value,
                "sessions_behind": self.sessions_behind}  # fmt: skip


@dataclass(frozen=True)
class FreshnessReport:
    exchange: str
    session: SessionStatus
    publication_grace: pd.Timedelta
    instruments: tuple[InstrumentFreshness, ...]

    @property
    def expected_session(self) -> pd.Timestamp:
        return self.session.last_completed

    @property
    def state(self) -> Freshness:
        """The worst state among the instruments."""
        present = {i.state for i in self.instruments}
        return next((s for s in _SEVERITY if s in present), Freshness.NO_DATA)

    @property
    def is_current(self) -> bool:
        return self.state is Freshness.CURRENT

    def by_state(self, state: Freshness) -> list[str]:
        return [i.ticker for i in self.instruments if i.state is state]

    def to_dict(self) -> dict:
        s = self.session
        return {
            "exchange": self.exchange,
            "as_of": s.as_of.isoformat(),
            "expected_session": str(s.last_completed.date()),
            "expected_session_close": s.last_completed_close.isoformat(),
            "session_in_progress": None if s.in_progress is None else str(s.in_progress.date()),
            "next_session": str(s.next_session.date()),
            "publication_grace_minutes": self.publication_grace.total_seconds() / 60,
            "state": self.state.value,
            "instruments": [i.to_dict() for i in self.instruments],
        }

    def summary(self) -> tuple[str, str]:
        """(level, sentence) for display: level is 'ok', 'info' or 'warning'."""
        s = self.session
        expected = s.last_completed.date()
        market = (
            f" The {s.in_progress.date()} session is still in progress and is not included."
            if s.market_open
            else ""
        )
        state = self.state
        if state is Freshness.CURRENT:
            return "ok", f"Data is current through {expected}, the last completed session.{market}"
        if state is Freshness.AWAITING_PROVIDER:
            names = ", ".join(self.by_state(Freshness.AWAITING_PROVIDER))
            return "info", (
                f"The {expected} session has closed but the provider has not yet published it "
                f"for: {names}. This is normal shortly after the close; refresh later.{market}"
            )
        if state is Freshness.STALE:
            worst = max(i.sessions_behind for i in self.instruments)
            names = ", ".join(self.by_state(Freshness.STALE))
            return "warning", (
                f"Data is out of date: the last completed session is {expected}, but up to "
                f"{worst} completed session(s) are missing for: {names}. Do not treat it as "
                f"current.{market}"
            )
        if state is Freshness.INCOMPLETE:
            names = ", ".join(self.by_state(Freshness.INCOMPLETE))
            return "warning", (
                f"{names} contains an observation dated after {expected}, the last completed "
                "session. A bar for a session that has not closed is not a valid daily observation."
            )
        names = ", ".join(self.by_state(Freshness.NO_DATA))
        return "warning", f"No observations at all for: {names}."


def last_observations(data: MarketData) -> dict[str, pd.Timestamp | None]:
    """Date of each instrument's latest actual close. Gaps are not filled."""
    return {t: data.close[t].last_valid_index() for t in data.tickers}


def assess_freshness(
    observations: MarketData | dict[str, pd.Timestamp | None],
    now: pd.Timestamp,
    calendar: SessionCalendar | None = None,
    publication_grace: pd.Timedelta = DEFAULT_PUBLICATION_GRACE,
) -> FreshnessReport:
    """Classify each instrument against the last session completed as of ``now``.

    ``publication_grace`` is how long after the official close a missing bar is
    put down to the provider not having published yet, rather than to stale data.
    """
    now = require_aware(now)
    calendar = calendar or SessionCalendar()
    status = calendar.status(now)
    expected = status.last_completed
    within_grace = now < status.last_completed_close + publication_grace
    if isinstance(observations, MarketData):
        observations = last_observations(observations)

    rows = []
    for ticker, last in observations.items():
        if last is None or pd.isna(last):
            rows.append(InstrumentFreshness(ticker, None, Freshness.NO_DATA, 0))
            continue
        last = pd.Timestamp(last).normalize()
        behind = calendar.sessions_between(last, expected)
        if last > expected:
            state = Freshness.INCOMPLETE
        elif behind == 0:
            state = Freshness.CURRENT
        elif behind == 1 and within_grace:
            state = Freshness.AWAITING_PROVIDER
        else:
            state = Freshness.STALE
        rows.append(InstrumentFreshness(ticker, last, state, behind))
    return FreshnessReport(calendar.exchange, status, publication_grace, tuple(rows))
