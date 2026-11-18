"""Shared market-data model used by every module in the platform.

A ``MarketData`` object is a set of aligned *wide* panels (sessions x tickers)
on the union trading calendar. A NaN means "this instrument has no observation
for that session". Missing values are never filled in here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pandas as pd

ADJUSTED_OHLC = (
    "Split- and dividend-adjusted OHLC (all four fields scaled by AdjClose/Close). "
    "A total-return-oriented research proxy, not executable historical quotes."
)


@dataclass(frozen=True)
class DatasetMetadata:
    """Provenance that must travel with every dataset."""

    source: str
    retrieved_at: str  # ISO-8601 UTC timestamp
    tickers: tuple[str, ...]
    start: str
    end: str
    adjustment: str
    synthetic: bool = False
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "retrieved_at": self.retrieved_at,
            "tickers": list(self.tickers),
            "start": self.start,
            "end": self.end,
            "adjustment": self.adjustment,
            "synthetic": self.synthetic,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class MarketData:
    """Aligned OHLCV panels plus provenance."""

    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame
    metadata: DatasetMetadata

    @property
    def tickers(self) -> list[str]:
        return list(self.close.columns)

    @property
    def dates(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.close.index)

    def _map(self, fn) -> MarketData:
        out = {f: fn(getattr(self, f)) for f in ("open", "high", "low", "close", "volume")}
        close = out["close"]
        meta = replace(
            self.metadata,
            tickers=tuple(close.columns),
            start=str(close.index[0].date()) if len(close) else "",
            end=str(close.index[-1].date()) if len(close) else "",
        )
        return MarketData(metadata=meta, **out)

    def truncate(self, as_of: str | pd.Timestamp) -> MarketData:
        """Information cutoff: keep only sessions on or before ``as_of``."""
        cutoff = pd.Timestamp(as_of)
        return self._map(lambda df: df.loc[df.index <= cutoff])

    def window(self, start: str | pd.Timestamp | None, end: str | pd.Timestamp | None):
        return self._map(lambda df: df.loc[start:end])

    def select(self, tickers: list[str]) -> MarketData:
        missing = [t for t in tickers if t not in self.close.columns]
        if missing:
            raise KeyError(f"Tickers not in dataset: {missing}")
        sub = self._map(lambda df: df[list(tickers)])
        # Drop sessions on which none of the selected instruments traded.
        keep = sub.close.notna().any(axis=1)
        return sub._map(lambda df: df.loc[keep])
