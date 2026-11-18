"""Session-aware store for the latest available completed daily data from a live provider.

Used only for the live provider. Frozen research snapshots, uploaded files and
synthetic data never pass through here.

What the store separates
------------------------
* the exchange closing a session              (the calendar)
* the provider publishing that session's bar  (may lag the close)
* a request to the provider succeeding        (may fail, or be rate limited)
* the verified cache being replaced           (atomic; a failure never touches it)
* downstream code seeing the new data         (the returned ``LoadResult``)

When is the provider contacted?
-------------------------------
Automatically, only if the verified cache is missing a completed session for
some instrument, or is older than ``max_age`` (prices are occasionally revised),
or does not exist. Never merely because time has passed on a weekend, a holiday,
overnight, or while a session is in progress. After an attempt that brings no
progress (provider has not published, or the request failed) the next automatic
attempt waits ``retry_cooldown``, doubling each time up to ``max_retry_cooldown``,
so a late bar cannot cause a request on every page load. A manual refresh always
contacts the provider unless one was made within ``manual_cooldown``.

On disk each dataset is a folder of complete, immutable versions plus a pointer
file that is switched with an atomic rename, so an interrupted write can never
leave a half-written dataset in use. The previous version is kept as a fallback
if the current one is found to be unreadable.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path

import pandas as pd

from quantlab.data.cleaning import DataError
from quantlab.data.freshness import (
    DEFAULT_PUBLICATION_GRACE,
    Freshness,
    FreshnessReport,
    assess_freshness,
    last_observations,
)
from quantlab.data.models import MarketData
from quantlab.data.providers import DataProvider, dataset_key, load_dataset, save_dataset
from quantlab.data.sessions import SessionCalendar, require_aware

POINTER, STATE, LOCK = "CURRENT", "refresh_state.json", ".lock"
DISPLAY_ZONE = "America/New_York"
TICKER = re.compile(r"^[A-Za-z0-9.\-=^]{1,15}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REVISION_TOLERANCE = 1e-8  # relative change below this is CSV round-trip noise, not a revision
_PATH = re.compile(r"""(?:[A-Za-z]:)?(?:[\\/][^\\/\s'"]+){2,}""")


def safe_message(text: str) -> str:
    """Remove server file-system paths from a message shown to users (QA-008).

    Each absolute path is replaced by its last component, e.g.
    ``'/srv/app/.data_cache/x/v-1/close.csv'`` -> ``'close.csv'``.
    """
    return _PATH.sub(lambda m: re.split(r"[\\/]", m.group(0))[-1], text)


def validate_request(tickers: list[str], start: str) -> tuple[list[str], str]:
    """Reject anything that is not a plain ticker list and an ISO date (QA-005).

    Both end up in a folder name; nothing else may reach the file system.
    """
    if not tickers:
        raise ValueError("At least one ticker is required")
    bad = [t for t in tickers if not isinstance(t, str) or not TICKER.match(t)]
    if bad:
        raise ValueError(f"Invalid ticker(s): {bad!r}")
    if not isinstance(start, str) or not DATE.match(start):
        raise ValueError(f"start must be an ISO date (YYYY-MM-DD), got {start!r}")
    try:
        pd.Timestamp(start)
    except ValueError as exc:
        raise ValueError(f"start is not a valid date: {start!r}") from exc
    return list(tickers), start


class CacheNotWritableError(OSError):
    """The cache folder cannot be written, so attempts cannot be recorded safely."""


class Outcome(StrEnum):
    UPDATED = "updated"  # provider request succeeded and brought newer completed observations
    UNCHANGED = "unchanged"  # provider request succeeded; nothing newer was available
    CACHED = "cached"  # no request was made; the verified cache was served
    LIMITED = "limited"  # a manual refresh was refused because of the cooldown
    FAILED = "failed"  # provider request failed; the last verified cache was served
    REVISED = "revised"  # provider request succeeded; earlier history changed, nothing newer


class NoUsableDataError(DataError):
    """Neither the provider nor the cache can supply a valid dataset."""


@dataclass(frozen=True)
class RefreshPolicy:
    publication_grace: pd.Timedelta = DEFAULT_PUBLICATION_GRACE
    retry_cooldown: pd.Timedelta = pd.Timedelta(minutes=15)
    max_retry_cooldown: pd.Timedelta = pd.Timedelta(hours=6)
    manual_cooldown: pd.Timedelta = pd.Timedelta(seconds=60)
    max_age: pd.Timedelta = pd.Timedelta(days=7)
    lock_timeout_seconds: float = 120.0  # a lock older than this is treated as abandoned

    def backoff(self, attempts_without_progress: int) -> pd.Timedelta:
        if attempts_without_progress <= 0:
            return pd.Timedelta(0)
        wait = self.retry_cooldown * 2 ** (attempts_without_progress - 1)
        return min(wait, self.max_retry_cooldown)


@dataclass(frozen=True)
class LoadResult:
    """A dataset together with the truth about where it came from and how current it is."""

    data: MarketData
    outcome: Outcome
    served_from: str  # "provider" (this call fetched it) or "cache"
    freshness: FreshnessReport
    as_of: pd.Timestamp
    retrieved_at: pd.Timestamp  # when the served data was last successfully retrieved
    last_attempt_at: pd.Timestamp | None  # most recent provider request, successful or not
    last_attempt_outcome: str | None
    last_error: str | None
    next_check_at: pd.Timestamp | None  # earliest next automatic request, if one is pending
    new_observations: dict[str, int] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    revisions: dict[str, dict] = field(default_factory=dict)  # ticker -> what changed (QA-007)

    def revision_sentence(self) -> str:
        if not self.revisions:
            return ""
        parts = [
            f"{t}: {r['sessions']} session(s) between {r['first']} and {r['last']}, largest "
            f"change {r['largest_change']:.2%}"
            for t, r in self.revisions.items()
        ]
        return ("**History revised:** the provider changed earlier prices (" + "; ".join(parts)
                + "). Analyses made on the earlier data will not reproduce exactly on this data.")

    def headline(self) -> tuple[str, str]:
        """(level, sentence): what happened on this load, then how current the data is."""
        level, fresh = self.freshness.summary()
        fresh = fresh.replace("Data is current", "Latest available completed daily data is current")
        stamp = fmt_time(self.last_attempt_at)
        revised = f" {self.revision_sentence()}" if self.revisions else ""
        if self.outcome is Outcome.REVISED:
            return "warning", (f"**Checked** at {stamp}: no newer completed daily data.{revised} "
                               f"{fresh}")  # fmt: skip
        if self.outcome is Outcome.UPDATED and not self.new_observations:
            # First download of this selection: there was nothing to add to.
            loaded = f"**Loaded** at {stamp}: downloaded this dataset from the provider."
            return level, f"{loaded} {fresh}"
        if self.outcome is Outcome.UPDATED:
            added = max(self.new_observations.values())
            return ("warning" if revised else level), (
                f"**Updated** at {stamp}: retrieved {added} new completed session(s) "
                f"from the provider.{revised} {fresh}"
            )
        if self.outcome is Outcome.UNCHANGED:
            return level, (f"**Checked; unchanged** at {stamp}: the provider had no newer "
                           f"completed daily data. {fresh}")  # fmt: skip
        if self.outcome is Outcome.LIMITED:
            return "info", (f"**Refresh limited:** the provider was last contacted at {stamp}. "
                            f"Try again after {fmt_time(self.next_check_at)}. {fresh}")  # fmt: skip
        if self.outcome is Outcome.FAILED:
            return "warning", (
                f"**Refresh failed** at {stamp}: {self.last_error}. Showing the last verified "
                f"data, retrieved {fmt_time(self.retrieved_at)}. {fresh}"
            )
        pending = ""
        if self.next_check_at is not None and not self.freshness.is_current:
            pending = f" Next automatic check after {fmt_time(self.next_check_at)}."
        return level, f"{fresh}{pending}"

    def to_dict(self) -> dict:
        def iso(t):
            return None if t is None else t.isoformat(timespec="seconds")

        return {
            "outcome": self.outcome.value,
            "served_from": self.served_from,
            "provider": self.data.metadata.source,
            "as_of": iso(self.as_of),
            "retrieved_at": iso(self.retrieved_at),
            "last_attempt_at": iso(self.last_attempt_at),
            "last_attempt_outcome": self.last_attempt_outcome,
            "last_error": self.last_error,
            "next_check_at": iso(self.next_check_at),
            "new_observations": self.new_observations,
            "revisions": self.revisions,
            "notes": list(self.notes),
            "freshness": self.freshness.to_dict(),
        }


def fmt_time(moment: pd.Timestamp | None) -> str:
    if moment is None:
        return "never"
    return moment.tz_convert(DISPLAY_ZONE).strftime("%Y-%m-%d %H:%M:%S ET")


def describe_error(exc: Exception) -> str:
    """One readable line without server paths; rate limiting is named as such."""
    text = safe_message(" ".join(str(exc).split()))
    if any(mark in text.lower() for mark in ("429", "too many requests", "rate limit")):
        return f"the provider is rate limiting requests ({text[:160]})"
    return text[:240] or type(exc).__name__


class LiveDataStore:
    """Verified, versioned cache in front of a live provider, refreshed by completed session."""

    def __init__(
        self,
        provider: DataProvider,
        cache_dir: str | Path,
        calendar: SessionCalendar | None = None,
        clock: Callable[[], pd.Timestamp] | None = None,
        policy: RefreshPolicy | None = None,
    ):
        self.provider = provider
        self.cache_dir = Path(cache_dir)
        self.calendar = calendar or SessionCalendar()
        self.clock = clock or (lambda: pd.Timestamp.now(tz="UTC"))
        self.policy = policy or RefreshPolicy()
        self._memory: dict[str, tuple[str, MarketData]] = {}  # key -> (version, dataset)
        self._guards: dict[str, threading.Lock] = {}
        self._guards_lock = threading.Lock()

    # ------------------------------------------------------------------ paths and state

    def _folder(self, tickers: list[str], start: str) -> Path:
        name = getattr(self.provider, "name", type(self.provider).__name__)
        return self.cache_dir / dataset_key(name, tickers, start, None)

    def _read_state(self, folder: Path) -> dict:
        try:
            return json.loads((folder / STATE).read_text())
        except (OSError, ValueError):
            return {}  # missing or unreadable state only costs one extra provider request

    def _write_state(self, folder: Path, state: dict) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f"{STATE}.{uuid.uuid4().hex}.tmp"
        tmp.write_text(json.dumps(state, indent=2))
        os.replace(tmp, folder / STATE)

    # ------------------------------------------------------------------ verified cache

    def _versions(self, folder: Path) -> list[str]:
        if not folder.is_dir():
            return []
        return sorted(p.name for p in folder.iterdir() if p.is_dir() and p.name.startswith("v-"))

    def _load_version(self, folder: Path, version: str, tickers: list[str]) -> MarketData:
        data = load_dataset(folder / version)
        if set(data.tickers) != set(tickers) or len(data.dates) == 0:
            raise ValueError("cached dataset does not match the request")
        if not (data.open.index.equals(data.close.index) and data.close.shape[1] == len(tickers)):
            raise ValueError("cached panels are inconsistent")
        return data._map(lambda df: df[list(tickers)])

    def _load_cache(self, folder: Path, tickers: list[str]) -> tuple[MarketData | None, list[str]]:
        """The verified dataset, or the previous version if the current one is unreadable."""
        notes: list[str] = []
        try:
            current = (folder / POINTER).read_text().strip()
        except OSError:
            return None, notes
        cached = self._memory.get(str(folder))
        if cached and cached[0] == current:
            return cached[1], notes
        candidates = [current] + [v for v in reversed(self._versions(folder)) if v != current]
        for version in candidates:
            try:
                data = self._load_version(folder, version, tickers)
            except Exception as exc:  # unreadable, truncated or mismatched: never served
                reason = safe_message(f"{type(exc).__name__}: {exc}")
                notes.append(f"cache version {version} was unusable and was ignored ({reason})")
                continue
            if version != current:
                notes.append(f"recovered the previous verified dataset ({version})")
                self._point_to(folder, version)
            self._memory[str(folder)] = (version, data)
            return data, notes
        notes.append("no usable cached dataset remained")
        return None, notes

    def _point_to(self, folder: Path, version: str) -> None:
        tmp = folder / f"{POINTER}.{uuid.uuid4().hex}.tmp"
        tmp.write_text(version)
        os.replace(tmp, folder / POINTER)  # atomic: readers see the old or the new version

    def _commit(self, folder: Path, data: MarketData, now: pd.Timestamp) -> None:
        """Write a complete new version, then switch the pointer. Old versions go afterwards."""
        version = f"v-{now.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
        save_dataset(folder / version, data)
        self._load_version(folder, version, data.tickers)  # read back before trusting it
        pointer = folder / POINTER
        previous = pointer.read_text().strip() if pointer.exists() else None
        self._point_to(folder, version)
        self._memory[str(folder)] = (version, data)
        for old in self._versions(folder):
            if old not in (version, previous):  # keep one fallback
                shutil.rmtree(folder / old, ignore_errors=True)

    # ------------------------------------------------------------------ locking

    def _guard(self, key: str) -> threading.Lock:
        with self._guards_lock:
            return self._guards.setdefault(key, threading.Lock())

    def _acquire_file_lock(self, folder: Path) -> bool:
        folder.mkdir(parents=True, exist_ok=True)
        lock = folder / LOCK
        for _ in range(2):
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return True
            except FileExistsError:
                try:
                    age = time.time() - lock.stat().st_mtime
                except OSError:
                    continue
                abandoned = age > self.policy.lock_timeout_seconds
                if not abandoned:
                    return False
                lock.unlink(missing_ok=True)
        return False

    # ------------------------------------------------------------------ the public call

    def get(self, tickers: list[str], start: str, force: bool = False) -> LoadResult:
        """Return the dataset, contacting the provider only when the policy calls for it.

        ``force=True`` is a manual refresh. Raises ``NoUsableDataError`` when neither
        the provider nor the cache can supply a valid dataset.
        """
        tickers, start = validate_request(list(tickers), start)
        folder = self._folder(tickers, start)
        root = self.cache_dir.resolve()
        if root not in folder.resolve().parents:  # defence in depth after validation
            raise ValueError("Resolved cache folder lies outside the cache directory")
        with self._guard(str(folder)):  # one request at a time per dataset in this process
            return self._get(folder, tickers, start, force)

    def _get(self, folder: Path, tickers: list[str], start: str, force: bool) -> LoadResult:
        now = require_aware(self.clock())
        status = self.calendar.status(now)
        state = self._read_state(folder)
        cached, notes = self._load_cache(folder, tickers)
        last_attempt = _ts(state.get("last_attempt_at"))
        stalled = int(state.get("attempts_without_progress", 0))
        if state.get("expected_session") != str(status.last_completed.date()):
            stalled = 0  # a new session completed: earlier patience no longer applies

        report = None if cached is None else self._assess(cached, now)
        if cached is None:
            wanted, wait = True, self.policy.manual_cooldown if state.get("last_error") else None
        else:
            behind = any(i.sessions_behind > 0 for i in report.instruments)
            too_old = now - _ts(cached.metadata.retrieved_at) > self.policy.max_age
            wanted, wait = behind or too_old, self.policy.backoff(stalled)
        if force:
            wanted, wait = True, self.policy.manual_cooldown
        next_allowed = None if (last_attempt is None or wait is None) else last_attempt + wait
        blocked = next_allowed is not None and now < next_allowed

        if not wanted or blocked:
            if cached is None:
                raise NoUsableDataError(
                    f"{state.get('last_error', 'No data is available')}. The provider was "
                    f"contacted at {fmt_time(last_attempt)}; next attempt after "
                    f"{fmt_time(next_allowed)}."
                )
            outcome = Outcome.LIMITED if (force and blocked) else Outcome.CACHED
            pending = next_allowed if (wanted and blocked) else None
            return self._result(cached, report, outcome, "cache", now, state, pending, notes)

        try:
            locked = self._acquire_file_lock(folder)
        except OSError as exc:
            return self._unwritable(cached, report, now, state, exc, notes)
        if not locked:
            if cached is None:
                raise NoUsableDataError(
                    "Another refresh of this dataset is in progress; retry shortly."
                )
            notes.append("another process is refreshing this dataset; served the verified cache")
            return self._result(cached, report, Outcome.CACHED, "cache", now, state, None, notes)
        try:
            return self._refresh(folder, tickers, start, now, status, cached, state, stalled, notes)
        except CacheNotWritableError as exc:
            return self._unwritable(cached, report, now, state, exc.__cause__ or exc, notes)
        finally:
            with contextlib.suppress(OSError):
                (folder / LOCK).unlink(missing_ok=True)

    def _refresh(self, folder, tickers, start, now, status, cached, state, stalled, notes):
        expected = str(status.last_completed.date())
        attempt = {**state, "last_attempt_at": now.isoformat(), "expected_session": expected}
        # Recorded before the request, so a crash mid-request still counts towards the cooldown.
        # If it cannot be recorded, the provider is not contacted at all (QA-006): an attempt
        # that leaves no trace could be repeated on every page view and hit rate limits.
        try:
            self._write_state(folder, {**attempt, "last_attempt_outcome": "started"})
        except OSError as exc:
            raise CacheNotWritableError(str(exc)) from exc
        try:
            fresh = self.provider.fetch(tickers, start)
            # Second line of defence: whatever the provider returned, nothing dated after the
            # last officially completed session is ever stored or served.
            fresh = fresh.truncate(status.last_completed)
            if len(fresh.dates) == 0:
                raise DataError("provider returned no completed sessions")
            fresh = replace(fresh, metadata=replace(fresh.metadata, retrieved_at=now.isoformat()))
            self._reject_if_worse(fresh, cached)
            gained = _gained(fresh, cached)
            revisions = _revisions(fresh, cached)
            self._commit(folder, fresh, now)  # a failed write is a failed refresh
        except Exception as exc:  # provider, validation or write failure: the cache is untouched
            error = describe_error(exc)
            state = {**attempt, "last_attempt_outcome": Outcome.FAILED.value, "last_error": error,
                     "attempts_without_progress": stalled + 1}  # fmt: skip
            self._save_state(folder, state, notes)
            retry = now + self.policy.backoff(stalled + 1)
            if cached is None:
                raise NoUsableDataError(
                    f"{error}. No verified cached data exists for this selection. "
                    f"Next attempt after {fmt_time(now + self.policy.manual_cooldown)}."
                ) from exc
            report = self._assess(cached, now)
            return self._result(cached, report, Outcome.FAILED, "cache", now, state, retry, notes)

        report = self._assess(fresh, now)
        progressed = cached is None or any(gained.values())
        still_behind = any(i.sessions_behind > 0 for i in report.instruments)
        if progressed:
            outcome = Outcome.UPDATED
        else:
            outcome = Outcome.REVISED if revisions else Outcome.UNCHANGED
        if revisions:
            notes.append("provider revised earlier history: " + ", ".join(
                f"{t} ({r['sessions']} sessions, largest change {r['largest_change']:.2%})"
                for t, r in revisions.items()))  # fmt: skip
        # Patience counter: reset when nothing is missing; otherwise grow while no progress is made.
        waiting = 0 if not still_behind else (1 if progressed else stalled + 1)
        state = {
            **attempt,
            "last_attempt_outcome": outcome.value,
            "last_error": None,
            "last_success_at": now.isoformat(),
            "attempts_without_progress": waiting,
        }
        self._save_state(folder, state, notes)
        retry = now + self.policy.backoff(waiting) if still_behind else None
        return self._result(fresh, report, outcome, "provider", now, state, retry, notes, gained,
                            revisions)  # fmt: skip

    # ------------------------------------------------------------------ helpers

    def _assess(self, data: MarketData, now: pd.Timestamp) -> FreshnessReport:
        return assess_freshness(data, now, self.calendar, self.policy.publication_grace)

    @staticmethod
    def _reject_if_worse(fresh: MarketData, cached: MarketData | None) -> None:
        """A response that loses history the verified cache has is not accepted."""
        if cached is None:
            return
        new, old = last_observations(fresh), last_observations(cached)
        for ticker in cached.tickers:
            if ticker not in fresh.tickers or new[ticker] is None:
                raise DataError(f"provider response has no data for {ticker}")
            if old[ticker] is not None and new[ticker] < old[ticker]:
                raise DataError(f"provider response for {ticker} ends before the verified cache")
            if fresh.close[ticker].notna().sum() < cached.close[ticker].notna().sum():
                raise DataError(
                    f"provider response for {ticker} has fewer observations than the cache"
                )

    def _save_state(self, folder: Path, state: dict, notes: list[str]) -> None:
        """Best-effort state write after the provider was contacted; a failure is reported."""
        try:
            self._write_state(folder, state)
        except OSError as exc:
            notes.append("the refresh record could not be saved (" + describe_error(exc) + ")")

    def _unwritable(self, cached, report, now, state, exc, notes) -> LoadResult:
        """The cache folder cannot be written: serve verified data, never contact the provider."""
        reason = f"the cache folder cannot be written ({describe_error(exc)})"
        if cached is None:
            raise NoUsableDataError(
                f"{reason[0].upper()}{reason[1:]}, so no download was attempted and there is no "
                "verified data to show. Set QUANTLAB_CACHE_DIR to a writable folder."
            ) from exc
        notes.append(reason + "; no refresh was attempted")
        failed = {**state, "last_attempt_outcome": Outcome.FAILED.value, "last_error": reason}
        return self._result(cached, report, Outcome.FAILED, "cache", now, failed, None, notes)

    def _result(self, data, report, outcome, served, now, state, next_check, notes, gained=None,
                revisions=None):  # fmt: skip
        return LoadResult(
            data=data, outcome=outcome, served_from=served, freshness=report, as_of=now,
            retrieved_at=_ts(data.metadata.retrieved_at),
            last_attempt_at=_ts(state.get("last_attempt_at")),
            last_attempt_outcome=state.get("last_attempt_outcome"),
            last_error=state.get("last_error"), next_check_at=next_check,
            new_observations=gained or {}, notes=tuple(notes), revisions=revisions or {},
        )  # fmt: skip


def _ts(text: str | None) -> pd.Timestamp | None:
    if not text:
        return None
    stamp = pd.Timestamp(text)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def _revisions(fresh: MarketData, cached: MarketData | None) -> dict[str, dict]:
    """Earlier closes that the provider changed, per instrument (QA-007).

    Compares every session present in both datasets. Adjusted-price providers restate
    history after dividends and splits, so this is expected occasionally; it is reported,
    never hidden. Changes below ``REVISION_TOLERANCE`` (relative) are storage noise.
    """
    if cached is None:
        return {}
    out = {}
    for t in cached.tickers:
        if t not in fresh.tickers:
            continue
        old, new = cached.close[t].dropna(), fresh.close[t].dropna()
        common = old.index.intersection(new.index)
        if len(common) == 0:
            continue
        change = (new.loc[common] / old.loc[common] - 1.0).abs()
        moved = change[change > REVISION_TOLERANCE]
        if len(moved):
            out[t] = {
                "sessions": int(len(moved)), "first": str(moved.index[0].date()),
                "last": str(moved.index[-1].date()), "largest_change": float(moved.max()),
            }  # fmt: skip
    return out


def _gained(fresh: MarketData, cached: MarketData | None) -> dict[str, int]:
    """Completed observations each instrument gained relative to the verified cache."""
    if cached is None:
        return {}  # a first download adds nothing to an existing dataset
    old = last_observations(cached)
    out = {}
    for t in fresh.tickers:
        series = fresh.close[t].dropna()
        out[t] = int((series.index > old[t]).sum()) if old.get(t) is not None else len(series)
    return out


__all__ = ["CacheNotWritableError", "Freshness", "LiveDataStore", "LoadResult",
           "NoUsableDataError", "Outcome", "RefreshPolicy", "describe_error", "fmt_time",
           "safe_message", "validate_request"]  # fmt: skip
