"""Package the exact prices behind an analysis, where the data may be redistributed (QA-031).

The bundle is a ZIP holding one ``<TICKER>.csv`` per instrument in the format the
dashboard's "My own CSV files" upload accepts, plus ``bundle.json`` (source and
fingerprint). Uploading those files and loading the saved portfolio file reproduces
the analysis exactly, without the original provider.

Only synthetic data and data the user supplied may be bundled. Provider data (Yahoo
Finance, and the frozen research snapshot derived from it) is NEVER bundled: its
redistribution rights are not established (backlog QA-035). For it, the dataset
fingerprint identifies the data and the provider must be asked again.
"""

from __future__ import annotations

import io
import json
import zipfile

import pandas as pd

from quantlab.data.models import MarketData

BUNDLEABLE_SOURCES = {"synthetic-gbm", "user-csv"}
FIELDS = ("open", "high", "low", "close", "volume")


def can_bundle(data: MarketData) -> bool:
    return bool(data.metadata.synthetic) or data.metadata.source in BUNDLEABLE_SOURCES


def price_bundle(data: MarketData, fingerprint: str) -> bytes:
    """ZIP of per-instrument CSVs plus metadata. Raises PermissionError for provider data."""
    if not can_bundle(data):
        raise PermissionError(
            f"Prices from {data.metadata.source!r} are not packaged: redistribution rights are "
            "not established. The dataset fingerprint identifies the data instead."
        )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for ticker in data.tickers:
            frame = pd.DataFrame({f: getattr(data, f)[ticker] for f in FIELDS})
            frame = frame.dropna(subset=["close"])
            text = frame.to_csv(index_label="date", float_format="%.17g")
            archive.writestr(f"{ticker}.csv", text)
        archive.writestr("bundle.json", json.dumps({
            "source": data.metadata.source, "synthetic": bool(data.metadata.synthetic),
            "tickers": list(data.tickers), "start": str(data.dates[0].date()),
            "end": str(data.dates[-1].date()), "fingerprint": fingerprint,
            "how_to_use": "Upload the CSV files under 'My own CSV files', then load the saved "
            "portfolio file in the Investment Lab.",
        }, indent=2))  # fmt: skip
    return buffer.getvalue()
