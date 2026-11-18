"""Chronological research splits. Time series are never shuffled."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ResearchSplit:
    """Development / (optional) validation / final out-of-sample date ranges, inclusive."""

    development: tuple[pd.Timestamp, pd.Timestamp]
    validation: tuple[pd.Timestamp, pd.Timestamp] | None
    test: tuple[pd.Timestamp, pd.Timestamp]

    def slice(self, series: pd.Series | pd.DataFrame, part: str):
        bounds = getattr(self, part)
        if bounds is None:
            raise ValueError(f"No {part} period defined")
        return series.loc[bounds[0] : bounds[1]]

    def to_dict(self) -> dict:
        fmt = lambda b: None if b is None else [str(b[0].date()), str(b[1].date())]  # noqa: E731
        return {p: fmt(getattr(self, p)) for p in ("development", "validation", "test")}


def chronological_split(
    index: pd.DatetimeIndex, dev_end: str, val_end: str | None = None
) -> ResearchSplit:
    """Split sessions into dev (<= dev_end), validation (<= val_end) and test (the rest)."""
    index = pd.DatetimeIndex(index).sort_values()
    dev = index[index <= pd.Timestamp(dev_end)]
    rest = index[index > pd.Timestamp(dev_end)]
    if len(dev) == 0 or len(rest) == 0:
        raise ValueError("dev_end must fall strictly inside the sample")
    validation = None
    if val_end is not None:
        val = rest[rest <= pd.Timestamp(val_end)]
        rest = rest[rest > pd.Timestamp(val_end)]
        if len(val) == 0 or len(rest) == 0:
            raise ValueError("val_end must fall strictly between dev_end and the sample end")
        validation = (val[0], val[-1])
    return ResearchSplit((dev[0], dev[-1]), validation, (rest[0], rest[-1]))


def calendar_subperiods(index: pd.DatetimeIndex, years: int = 5) -> list[tuple[str, str]]:
    """Non-overlapping calendar blocks of ``years`` years covering the sample."""
    index = pd.DatetimeIndex(index)
    out = []
    start_year = index[0].year
    while start_year <= index[-1].year:
        block = index[(index.year >= start_year) & (index.year < start_year + years)]
        if len(block):
            out.append((str(block[0].date()), str(block[-1].date())))
        start_year += years
    return out
