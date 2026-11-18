"""Validation and alignment of raw per-ticker OHLCV frames."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from quantlab.data.models import DatasetMetadata, MarketData

FIELDS = ("open", "high", "low", "close", "volume")


class DataError(Exception):
    """Base class for data problems."""


class InvalidTickerError(DataError):
    """The provider returned no usable observations for a ticker."""


class InsufficientHistoryError(DataError):
    """Fewer observations than a calculation requires."""


class DataProviderError(DataError):
    """The upstream data source failed."""


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def clean_ticker_frame(ticker: str, raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Validate one ticker's OHLCV frame. Returns (clean frame, notes).

    Policy
    - index -> tz-naive, normalized session dates, sorted ascending
    - duplicate timestamps: keep the last record, and say so in the notes
    - rows with no close are dropped (a session without a close is not an observation)
    - non-positive prices or high < low are errors, not something to repair
    - nothing is forward-filled or interpolated
    """
    if raw is None or raw.empty:
        raise InvalidTickerError(f"{ticker}: no data returned")
    df = raw.rename(columns=str.lower)
    missing = [f for f in FIELDS if f not in df.columns]
    if missing:
        raise DataError(f"{ticker}: missing columns {missing}")
    df = df[list(FIELDS)].astype(float)
    idx = pd.DatetimeIndex(pd.to_datetime(df.index))
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    df.index = idx.normalize()
    df = df.sort_index()

    notes: list[str] = []
    dup = int(df.index.duplicated(keep="last").sum())
    if dup:
        notes.append(f"{ticker}: dropped {dup} duplicate timestamp(s), kept last")
        df = df.loc[~df.index.duplicated(keep="last")]
    no_close = int(df["close"].isna().sum())
    if no_close:
        notes.append(f"{ticker}: dropped {no_close} row(s) with no close")
        df = df.loc[df["close"].notna()]
    if df.empty:
        raise InvalidTickerError(f"{ticker}: no valid observations")

    prices = df[["open", "high", "low", "close"]]
    if (prices <= 0).any().any():
        raise DataError(f"{ticker}: non-positive price encountered")
    if (df["high"] < df["low"]).any():
        raise DataError(f"{ticker}: high < low encountered")
    if not np.isfinite(prices.to_numpy()[~np.isnan(prices.to_numpy())]).all():
        raise DataError(f"{ticker}: non-finite price encountered")
    return df, notes


def build_market_data(
    frames: dict[str, pd.DataFrame],
    source: str,
    adjustment: str,
    synthetic: bool = False,
    retrieved_at: str | None = None,
    notes: tuple[str, ...] = (),
) -> MarketData:
    """Clean each ticker and align all tickers on the union calendar (NaN = no observation)."""
    if not frames:
        raise DataError("No tickers supplied")
    cleaned: dict[str, pd.DataFrame] = {}
    all_notes = list(notes)
    for ticker, raw in frames.items():
        cleaned[ticker], n = clean_ticker_frame(ticker, raw)
        all_notes.extend(n)
    calendar = sorted(set().union(*(df.index for df in cleaned.values())))
    index = pd.DatetimeIndex(calendar, name="date")
    panels = {
        f: pd.DataFrame({t: df[f].reindex(index) for t, df in cleaned.items()}, index=index)
        for f in FIELDS
    }
    gaps = panels["close"].isna().sum()
    for t, g in gaps.items():
        if g:
            all_notes.append(f"{t}: {int(g)} session(s) on the union calendar without data")
    meta = DatasetMetadata(
        source=source,
        retrieved_at=retrieved_at or utc_now_iso(),
        tickers=tuple(cleaned),
        start=str(index[0].date()),
        end=str(index[-1].date()),
        adjustment=adjustment,
        synthetic=synthetic,
        notes=tuple(all_notes),
    )
    return MarketData(metadata=meta, **panels)


def require_history(data: MarketData, min_sessions: int) -> None:
    """Raise if any instrument has fewer than ``min_sessions`` closes."""
    counts = data.close.notna().sum()
    short = counts[counts < min_sessions]
    if len(short):
        raise InsufficientHistoryError(
            f"Need {min_sessions} sessions; have {short.to_dict()}"
        )
