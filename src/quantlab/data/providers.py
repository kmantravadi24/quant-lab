"""Data providers. Add a new source by implementing ``DataProvider.fetch``."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

from quantlab.data.cleaning import (
    FIELDS,
    DataError,
    DataProviderError,
    InvalidTickerError,
    build_market_data,
)
from quantlab.data.models import ADJUSTED_OHLC, DatasetMetadata, MarketData
from quantlab.data.sessions import CalendarError, SessionCalendar

DEFAULT_UNIVERSE = ["SPY", "QQQ", "IWM", "TLT", "GLD"]


class DataProvider(Protocol):
    def fetch(self, tickers: list[str], start: str, end: str | None = None) -> MarketData: ...


class YFinanceProvider:
    """Yahoo Finance daily bars with ``auto_adjust=True``.

    Convention: every OHLC field is multiplied by AdjClose/Close, so splits and
    cash dividends are folded into the price history (dividends are treated as
    reinvested at the close of the ex-date). See docs/methodology.md for limits:
    adjusted prices are revised whenever a new dividend is paid, so this is not
    point-in-time data.
    """

    name = "yfinance"

    def __init__(
        self,
        calendar: SessionCalendar | None = None,
        clock: Callable[[], pd.Timestamp] | None = None,
    ):
        """``clock`` returns the current timezone-aware time; inject it for deterministic tests.

        The exchange calendar decides which sessions are complete. It is the NYSE
        calendar by default, which is right for US-listed stocks and ETFs only.
        """
        self._calendar = calendar
        self._clock = clock or (lambda: pd.Timestamp.now(tz="UTC"))

    def _download(self, ticker: str, start: str, end: str | None) -> pd.DataFrame:
        """One instrument's adjusted daily bars from Yahoo. Overridden by offline tests."""
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover
            raise DataProviderError("yfinance missing: pip install quantlab[data]") from exc
        try:
            return yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)
        except Exception as exc:
            raise DataProviderError(f"yfinance failed for {ticker}: {exc}") from exc

    def fetch(self, tickers: list[str], start: str, end: str | None = None) -> MarketData:
        now = self._clock()
        try:
            calendar = self._calendar or SessionCalendar()
            completed = calendar.last_completed_session(now)
        except CalendarError as exc:
            raise DataProviderError(f"Cannot determine completed sessions: {exc}") from exc
        frames: dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            raw = self._download(ticker, start, end)
            if raw is None or raw.empty:
                raise InvalidTickerError(
                    f"{ticker}: provider returned no data (invalid ticker or provider outage)"
                )
            # A daily bar is an observation only once its session has officially closed.
            index = pd.DatetimeIndex(raw.index)
            dates = (index.tz_localize(None) if index.tz is not None else index).normalize()
            raw = raw[dates <= completed]
            if raw.empty:
                raise InvalidTickerError(f"{ticker}: no completed sessions in the requested range")
            frames[ticker] = raw[["Open", "High", "Low", "Close", "Volume"]]
        return build_market_data(
            frames,
            source=self.name,
            adjustment=ADJUSTED_OHLC,
            notes=(
                f"as of {pd.Timestamp(now).tz_convert('UTC').isoformat(timespec='seconds')} the "
                f"last completed {calendar.exchange} session was {completed.date()}; "
                "bars for later (incomplete) sessions are excluded",
            ),
        )


class SyntheticProvider:
    """Seeded geometric-Brownian-motion bars. NOT market data.

    For tests, demos and offline smoke runs only. The metadata flag
    ``synthetic=True`` travels with the dataset so results cannot be mistaken
    for empirical findings.
    """

    name = "synthetic-gbm"

    def __init__(self, seed: int = 0, annual_drift: float = 0.06, annual_vol: float = 0.18):
        self.seed, self.mu, self.sigma = seed, annual_drift, annual_vol

    def fetch(self, tickers: list[str], start: str, end: str | None = None) -> MarketData:
        end = end or "2024-12-31"
        index = pd.bdate_range(start, end)
        rng = np.random.default_rng(self.seed)
        dt = 1 / 252
        frames = {}
        for ticker in tickers:
            z = rng.standard_normal(len(index))
            log_ret = (self.mu - 0.5 * self.sigma**2) * dt + self.sigma * np.sqrt(dt) * z
            close = 100 * np.exp(np.cumsum(log_ret))
            gap = np.exp(0.3 * self.sigma * np.sqrt(dt) * rng.standard_normal(len(index)))
            open_ = np.r_[100.0, close[:-1]] * gap
            frames[ticker] = pd.DataFrame(
                {
                    "open": open_,
                    "high": np.maximum(open_, close) * 1.002,
                    "low": np.minimum(open_, close) * 0.998,
                    "close": close,
                    "volume": 1e6,
                },
                index=index,
            )
        return build_market_data(
            frames,
            source=self.name,
            adjustment="none (synthetic)",
            synthetic=True,
            notes=(f"SYNTHETIC GBM seed={self.seed}; not market data",),
        )


USER_SUPPLIED = "as supplied by the user; adjustment not verified by Quant Lab"


def read_ohlcv_csv(source, ticker: str = "file") -> pd.DataFrame:
    """Parse one instrument's daily bars from a CSV path or file-like object.

    Required columns (any capitalisation): a date column (``date``, ``datetime``
    or ``timestamp``, otherwise the first column) plus ``open``, ``high``,
    ``low``, ``close``. ``volume`` is optional. If an ``adj close`` column is
    present, all four prices are scaled by adj close / close, the same
    convention the Yahoo provider uses.
    """
    try:
        # Cells are read as text and converted with Python's correctly rounded float(), so each
        # decimal becomes exactly the float that produced it and a price bundle exported by
        # Quant Lab reproduces an analysis bit for bit (QA-031). Pandas' default fast parser can
        # differ in the last bit, and its 'float_precision' option is deprecated in pandas 3.1.
        df = pd.read_csv(source, dtype=str, keep_default_na=True)
    except Exception as exc:
        raise DataError(f"{ticker}: could not read CSV ({exc})") from exc
    df.columns = [str(c).strip().lower() for c in df.columns]
    date_col = next((c for c in ("date", "datetime", "timestamp") if c in df.columns), None)
    date_col = date_col or (df.columns[0] if len(df.columns) else None)
    missing = [c for c in ("open", "high", "low", "close") if c not in df.columns]
    if date_col is None or missing:
        raise DataError(
            f"{ticker}: CSV needs a date column and open/high/low/close; missing {missing}"
        )
    try:
        df.index = pd.to_datetime(df[date_col])
    except Exception as exc:
        raise DataError(f"{ticker}: could not parse dates in column '{date_col}'") from exc
    try:
        prices = df[["open", "high", "low", "close"]].astype(float)
        adj = df["adj close"].astype(float) if "adj close" in df.columns else None
        volume = df["volume"].astype(float) if "volume" in df.columns else np.nan
    except (TypeError, ValueError) as exc:
        raise DataError(f"{ticker}: non-numeric price data ({exc})") from exc
    if adj is not None:
        prices = prices.mul(adj / prices["close"], axis=0)
    return prices.assign(volume=volume)


class CsvProvider:
    """User-supplied data: a folder holding one ``<TICKER>.csv`` per instrument, or a
    mapping of ticker to an already parsed frame. See ``read_ohlcv_csv`` for the format."""

    name = "user-csv"

    def __init__(self, source: str | Path | dict[str, pd.DataFrame]):
        self.source = source

    def available(self) -> list[str]:
        if isinstance(self.source, dict):
            return list(self.source)
        return sorted(p.stem.upper() for p in Path(self.source).glob("*.csv"))

    def fetch(self, tickers: list[str], start: str | None = None, end: str | None = None):
        frames = {}
        for ticker in tickers:
            if isinstance(self.source, dict):
                if ticker not in self.source:
                    raise InvalidTickerError(f"{ticker}: not among the supplied datasets")
                frame = self.source[ticker]
            else:
                matches = [p for p in Path(self.source).glob("*.csv") if p.stem.upper() == ticker]
                if not matches:
                    raise InvalidTickerError(f"{ticker}: no {ticker}.csv in {self.source}")
                frame = read_ohlcv_csv(matches[0], ticker)
            frame = frame.sort_index().loc[start:end]
            frames[ticker] = frame
        return build_market_data(
            frames, source=self.name, adjustment=USER_SUPPLIED,
            notes=("user-supplied data; provenance and adjustments are the user's responsibility",),
        )  # fmt: skip


def load_dataset(path: Path) -> MarketData:
    """Read a dataset folder (one CSV per field plus ``metadata.json``)."""
    meta = json.loads((path / "metadata.json").read_text())
    meta["tickers"], meta["notes"] = tuple(meta["tickers"]), tuple(meta["notes"])
    panels = {f: pd.read_csv(path / f"{f}.csv", index_col="date", parse_dates=True) for f in FIELDS}
    return MarketData(metadata=DatasetMetadata(**meta), **panels)


def save_dataset(path: Path, data: MarketData) -> None:
    """Write a dataset folder. ``metadata.json`` is written last, so its presence marks a
    complete write."""
    path.mkdir(parents=True, exist_ok=True)
    for f in FIELDS:
        getattr(data, f).to_csv(path / f"{f}.csv", index_label="date")
    (path / "metadata.json").write_text(json.dumps(data.metadata.to_dict(), indent=2))


def dataset_key(provider_name: str, tickers: list[str], start: str, end: str | None) -> str:
    return f"{provider_name}__{'-'.join(sorted(tickers))}__{start}__{end or 'latest'}"


class CachedProvider:
    """On-disk CSV cache around another provider.

    A cache entry older than ``max_age_hours`` is stale and is refetched. If the
    refetch fails the error propagates; stale data is only served when
    ``allow_stale=True``, and then the dataset notes say so.
    """

    def __init__(
        self,
        inner: DataProvider,
        cache_dir: str | Path = ".data_cache",
        max_age_hours: float = 24.0,
        allow_stale: bool = False,
    ):
        self.inner = inner
        self.cache_dir = Path(cache_dir)
        self.max_age_hours = max_age_hours
        self.allow_stale = allow_stale

    def _key(self, tickers: list[str], start: str, end: str | None) -> Path:
        name = getattr(self.inner, "name", type(self.inner).__name__)
        return self.cache_dir / dataset_key(name, tickers, start, end)

    def _load(self, path: Path) -> MarketData:
        return load_dataset(path)

    def _save(self, path: Path, data: MarketData) -> None:
        save_dataset(path, data)

    def fetch(self, tickers: list[str], start: str, end: str | None = None) -> MarketData:
        path = self._key(tickers, start, end)
        cached = self._load(path) if (path / "metadata.json").exists() else None
        if cached is not None:
            age = datetime.now(UTC) - datetime.fromisoformat(cached.metadata.retrieved_at)
            cached = cached._map(lambda df: df[list(tickers)])  # honour the requested order
            if age.total_seconds() <= self.max_age_hours * 3600:
                return cached
        try:
            fresh = self.inner.fetch(tickers, start, end)
        except DataProviderError:
            if cached is not None and self.allow_stale:
                from dataclasses import replace

                note = f"STALE CACHE served (retrieved {cached.metadata.retrieved_at})"
                meta = replace(cached.metadata, notes=cached.metadata.notes + (note,))
                return replace(cached, metadata=meta)
            raise
        self._save(path, fresh)
        return fresh
