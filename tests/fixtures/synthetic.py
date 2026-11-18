"""Deterministic, hand-checkable market datasets for offline tests."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from quantlab.data.models import DatasetMetadata, MarketData


def make_data(
    close: dict[str, list[float]],
    open_: dict[str, list[float]] | None = None,
    start: str = "2024-01-01",
    dates: pd.DatetimeIndex | None = None,
) -> MarketData:
    """Build MarketData directly from explicit open/close lists (NaN allowed)."""
    n = len(next(iter(close.values())))
    index = dates if dates is not None else pd.bdate_range(start, periods=n)
    index = pd.DatetimeIndex(index, name="date")
    c = pd.DataFrame(close, index=index, dtype=float)
    o = pd.DataFrame(open_ or close, index=index, dtype=float)
    meta = DatasetMetadata(
        source="test-fixture",
        retrieved_at="2024-01-01T00:00:00+00:00",
        tickers=tuple(c.columns),
        start=str(index[0].date()),
        end=str(index[-1].date()),
        adjustment="none (synthetic)",
        synthetic=True,
    )
    return MarketData(
        open=o, high=np.maximum(o, c), low=np.minimum(o, c), close=c,
        volume=pd.DataFrame(1.0, index=index, columns=c.columns), metadata=meta,
    )  # fmt: skip


def perturb_after(data: MarketData, cutoff: pd.Timestamp, seed: int = 7) -> MarketData:
    """Return a copy whose prices strictly after ``cutoff`` are randomly rescaled."""
    rng = np.random.default_rng(seed)
    after = data.close.index > cutoff
    out = {}
    for field in ("open", "high", "low", "close"):
        df = getattr(data, field).copy()
        factor = rng.uniform(0.5, 1.5, size=(int(after.sum()), df.shape[1]))
        df.loc[after] = df.loc[after].to_numpy() * factor
        out[field] = df
    return replace(data, **out)
