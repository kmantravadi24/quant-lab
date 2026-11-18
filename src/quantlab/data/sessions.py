"""Exchange trading sessions: which session is complete at a given instant?

A daily bar is only an observation once its session has officially closed.
This module answers that question from an exchange calendar (regular days,
weekends, holidays, early closes and one-off closures), always relative to an
explicit timezone-aware timestamp so behaviour is deterministic and testable.

Sessions are labelled, as everywhere else in Quant Lab, by a timezone-naive
midnight timestamp of the session date.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

DEFAULT_EXCHANGE = "XNYS"  # New York Stock Exchange; also the right calendar for US-listed ETFs


class CalendarError(Exception):
    """The calendar cannot answer (missing dependency, or an instant outside its range)."""


def require_aware(now: pd.Timestamp) -> pd.Timestamp:
    """Return ``now`` in UTC, refusing naive timestamps: 'now' without a zone is ambiguous."""
    now = pd.Timestamp(now)
    if now.tzinfo is None:
        raise ValueError("A timezone-aware timestamp is required (for example tz='UTC').")
    return now.tz_convert("UTC")


@dataclass(frozen=True)
class SessionStatus:
    """The state of the exchange at one instant."""

    as_of: pd.Timestamp  # UTC
    last_completed: pd.Timestamp  # most recent session whose official close is <= as_of
    last_completed_close: pd.Timestamp  # UTC
    in_progress: pd.Timestamp | None  # session that has opened but not yet closed, if any
    next_session: pd.Timestamp  # first session that opens after as_of
    next_open: pd.Timestamp  # UTC

    @property
    def market_open(self) -> bool:
        return self.in_progress is not None


class SessionCalendar:
    """Thin, testable wrapper around ``exchange_calendars`` for one exchange."""

    def __init__(self, exchange: str = DEFAULT_EXCHANGE):
        try:
            import exchange_calendars as xcals
        except ImportError as exc:  # pragma: no cover
            raise CalendarError(
                "exchange_calendars is not installed: pip install 'quantlab[data]'"
            ) from exc
        self.exchange = exchange
        calendar = xcals.get_calendar(exchange)
        self.timezone = str(calendar.tz)
        # Session label (naive date) -> official open / close instants in UTC.
        self._opens = pd.Series(calendar.opens.dt.tz_convert("UTC"))
        self._closes = pd.Series(calendar.closes.dt.tz_convert("UTC"))
        self._sessions = pd.DatetimeIndex(self._closes.index)

    def _check_range(self, now: pd.Timestamp) -> None:
        if not self._closes.iloc[0] <= now < self._opens.iloc[-1]:
            raise CalendarError(
                f"{now} is outside the {self.exchange} calendar "
                f"({self._sessions[0].date()} to {self._sessions[-1].date()})."
            )

    def is_session(self, date: str | pd.Timestamp) -> bool:
        return pd.Timestamp(date).normalize().tz_localize(None) in self._sessions

    def session_close(self, session: str | pd.Timestamp) -> pd.Timestamp:
        """Official close of a session, in UTC (earlier than usual on early-close days)."""
        try:
            return self._closes.loc[pd.Timestamp(session)]
        except KeyError as exc:
            raise CalendarError(f"{session} is not a {self.exchange} session") from exc

    def status(self, now: pd.Timestamp) -> SessionStatus:
        """Which session is complete, which is in progress, and which opens next."""
        now = require_aware(now)
        self._check_range(now)
        done = int(self._closes.searchsorted(now, side="right")) - 1  # close <= now
        opened = int(self._opens.searchsorted(now, side="right")) - 1  # open <= now
        in_progress = self._sessions[opened] if opened > done else None
        upcoming = opened + 1
        return SessionStatus(
            as_of=now,
            last_completed=self._sessions[done],
            last_completed_close=self._closes.iloc[done],
            in_progress=in_progress,
            next_session=self._sessions[upcoming],
            next_open=self._opens.iloc[upcoming],
        )

    def last_completed_session(self, now: pd.Timestamp) -> pd.Timestamp:
        """Most recent session whose official closing time is at or before ``now``."""
        return self.status(now).last_completed

    def sessions_between(self, after: pd.Timestamp, through: pd.Timestamp) -> int:
        """Number of sessions in the half-open interval (after, through]."""
        lo = int(self._sessions.searchsorted(pd.Timestamp(after), side="right"))
        hi = int(self._sessions.searchsorted(pd.Timestamp(through), side="right"))
        return max(0, hi - lo)

    def previous_session(self, session: pd.Timestamp) -> pd.Timestamp:
        position = int(self._sessions.searchsorted(pd.Timestamp(session), side="left"))
        if position == 0:
            raise CalendarError(f"No session before {session} in the {self.exchange} calendar")
        return self._sessions[position - 1]
