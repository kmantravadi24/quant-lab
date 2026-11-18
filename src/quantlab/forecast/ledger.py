"""Append-only, timestamped record of forecasts, so they can be checked against reality later.

Each forecast is one JSON line in ``forecasts.jsonl``. Every line carries the SHA-256
hash of the previous line and of its own content, forming a chain: editing, deleting
or reordering any earlier line breaks the chain and ``verify`` reports it. The file is
only ever opened for appending; nothing in this module rewrites a recorded forecast.

Evaluations (what actually happened once a forecast's target date has passed) are
written to a separate append-only chain, ``evaluations.jsonl``, which refers to the
forecast by its hash. A forecast is evaluated at most once.

What is recorded is a forecast of the PORTFOLIO'S cumulative return (target weights,
rebalanced monthly, before costs) at each horizon, as percentiles 1..99, because that
can be checked against realised prices without knowing future contributions. The
projected wealth percentiles are recorded too, conditional on the stated plan.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from quantlab.forecast.validation import portfolio_path

SCHEMA = "quantlab.forecast_record/1"
GRID = list(range(1, 100))  # stored percentiles


def _canonical(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _digest(obj: dict) -> str:
    return hashlib.sha256(_canonical(obj).encode()).hexdigest()


class ChainError(ValueError):
    """The ledger was modified after it was written."""


class _Chain:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextlib.contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.with_suffix(self.path.suffix + ".lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for n, line in enumerate(self.path.read_text().splitlines(), start=1):
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError as exc:
                    raise ChainError(f"line {n} is not valid JSON") from exc
        return out

    def verify(self) -> list[str]:
        """Every problem found; an empty list means the chain is intact."""
        problems, previous = [], None
        try:
            entries = self.entries()
        except ChainError as exc:
            return [str(exc)]
        for n, entry in enumerate(entries, start=1):
            body = {k: v for k, v in entry.items() if k != "entry_hash"}
            if entry.get("prev_hash") != previous:
                problems.append(
                    f"entry {n}: previous-hash link is broken (an entry was removed, "
                    "inserted or reordered)"
                )
            if _digest(body) != entry.get("entry_hash"):
                problems.append(f"entry {n}: content does not match its hash (it was edited)")
            previous = entry.get("entry_hash")
        return problems

    def append(self, body: dict) -> dict:
        with self._locked():
            problems = self.verify()
            if problems:
                raise ChainError("Refusing to append to a modified ledger: " + "; ".join(problems))
            entries = self.entries()
            entry = {**body, "prev_hash": entries[-1]["entry_hash"] if entries else None}
            entry["entry_hash"] = _digest(entry)
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                os.write(fd, (_canonical(entry) + "\n").encode())
                os.fsync(fd)
            finally:
                os.close(fd)
        return entry


class ForecastLedger:
    """Forecasts and their later evaluations, in two append-only hash chains."""

    def __init__(self, folder: str | Path):
        self.folder = Path(folder)
        self.forecasts = _Chain(self.folder / "forecasts.jsonl")
        self.evaluations = _Chain(self.folder / "evaluations.jsonl")

    def verify(self) -> list[str]:
        return [f"forecasts: {p}" for p in self.forecasts.verify()] + [
            f"evaluations: {p}" for p in self.evaluations.verify()
        ]

    def record(self, payload: dict, now: datetime | None = None) -> dict:
        stamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds")
        return self.forecasts.append({"schema": SCHEMA, "recorded_at": stamp, **payload})

    def due(self, last_month: pd.Timestamp) -> list[dict]:
        """Recorded forecasts whose target month has passed and that are not yet evaluated."""
        done = {(e["forecast_hash"], e["horizon_months"]) for e in self.evaluations.entries()}
        out = []
        for entry in self.forecasts.entries():
            for h in entry["market"]["horizons"]:
                target = pd.Timestamp(h["target_month"])
                if target <= last_month and (entry["entry_hash"], h["months"]) not in done:
                    out.append({"forecast": entry, "horizon": h})
        return out

    def evaluate_due(self, monthly: pd.DataFrame, now: datetime | None = None) -> list[dict]:
        """Score every due forecast against realised monthly returns and append the results.

        ``monthly`` holds realised monthly returns (month-end index) for the instruments.
        A forecast is only evaluated when every month of its horizon is present.
        """
        written = []
        if monthly.empty:
            return written
        for item in self.due(monthly.index[-1]):
            entry, h = item["forecast"], item["horizon"]
            weights = entry["market"]["weights"]
            start = pd.Timestamp(entry["data"]["last_month"])
            months = monthly[
                (monthly.index > start) & (monthly.index <= pd.Timestamp(h["target_month"]))
            ]
            if len(months) != h["months"] or any(t not in months.columns for t in weights):
                continue
            w = np.array([weights[t] for t in weights])
            realized = float(np.prod(1 + months[list(weights)].to_numpy() @ w) - 1)
            grid = np.array(h["percentiles"])
            pit = float(np.interp(realized, grid, np.array(GRID) / 100, left=0.0, right=1.0))
            stamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds")
            written.append(
                self.evaluations.append(
                    {
                        "evaluated_at": stamp,
                        "forecast_hash": entry["entry_hash"],
                        "horizon_months": h["months"],
                        "target_month": h["target_month"],
                        "realized_return": realized,
                        "pit": pit,
                        "inside_90": bool(grid[4] <= realized <= grid[94]),
                        "inside_50": bool(grid[24] <= realized <= grid[74]),
                    }
                )
            )
        return written


def market_forecast(
    model,
    weights: dict[str, float],
    last_month: pd.Timestamp,
    horizons=(1, 12, 36),
    n_paths: int = 2000,
    seed: int = 42,
) -> dict:
    """Percentiles of the portfolio's cumulative return at each horizon, from ``model``."""
    held = {t: float(w) for t, w in weights.items() if w > 0}
    w = np.array([held[t] for t in held])
    columns = [model.tickers.index(t) for t in held]
    draws = model.sample(n_paths, max(horizons), seed)[:, :, columns]
    out = []
    for h in horizons:
        cumulative = portfolio_path(draws[:, :h, :], w)
        target = (pd.Timestamp(last_month).to_period("M") + h).to_timestamp(how="end").normalize()
        out.append(
            {
                "months": h,
                "target_month": str(target.date()),
                "percentiles": np.percentile(cumulative, GRID).round(8).tolist(),
            }
        )
    return {"weights": held, "horizons": out, "paths": n_paths, "seed": seed}
