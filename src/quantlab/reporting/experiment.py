"""Reproducible experiment records: what was run, on what data, with which code."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

import quantlab


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, pd.DataFrame):
        return _jsonable(obj.reset_index().to_dict(orient="records"))
    if isinstance(obj, pd.Series):
        return _jsonable(obj.to_dict())
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    return obj


def config_hash(config: dict) -> str:
    """Short stable hash of a configuration, used to name experiment outputs."""
    payload = json.dumps(_jsonable(config), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()[:12]


def git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()


def git_dirty() -> bool | None:
    """True if tracked files differ from the commit, i.e. the commit does not describe the code."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            capture_output=True, text=True, check=True, timeout=5,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    return bool(out.stdout.strip())


def environment() -> dict:
    return {
        "quantlab": quantlab.__version__,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "git_commit": git_commit(),
        "git_dirty": git_dirty(),
    }


def save_experiment(
    name: str, config: dict, data_metadata: dict, results: dict, out_dir: str | Path
) -> Path:
    """Write a self-describing JSON record and return its path."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    record = {
        "experiment": name,
        "config_hash": config_hash(config),
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "environment": environment(),
        "config": config,
        "data": data_metadata,
        "results": results,
    }
    path = out / f"{name}_{record['config_hash']}.json"
    path.write_text(json.dumps(_jsonable(record), indent=2))
    return path


def markdown_table(df: pd.DataFrame, formats: dict[str, str] | None = None) -> str:
    """Render a DataFrame as a GitHub markdown table (no extra dependency)."""
    formats = formats or {}
    if df.index.nlevels == 1 and df.index.name is None:
        df = df.rename_axis("name")
    flat = df.reset_index()
    header = "| " + " | ".join(str(c) for c in flat.columns) + " |"
    rule = "|" + "|".join("---" for _ in flat.columns) + "|"
    lines = [header, rule]
    for _, row in flat.iterrows():
        cells = []
        for c, v in row.items():
            if isinstance(v, (float, np.floating)):
                cells.append("n/a" if not np.isfinite(v) else format(v, formats.get(c, ".3f")))
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)
