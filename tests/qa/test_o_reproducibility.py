"""Suite O (remediation): reproducibility and operational hardening (QA-031, 032, 038, 041)."""

import io
import re
import zipfile
from pathlib import Path

import pytest
from fixtures.app import render, texts, view

from quantlab.data import SyntheticProvider
from quantlab.data.models import DatasetMetadata
from quantlab.data.providers import CsvProvider, read_ohlcv_csv
from quantlab.execution import ExecutionConfig
from quantlab.portfolio.compare import benchmark_specs, compare_portfolios
from quantlab.portfolio.spec import PortfolioSpec
from quantlab.reporting.bundle import can_bundle, price_bundle

ROOT = Path(__file__).resolve().parents[2]


def comparison(data):
    spec = PortfolioSpec({"SYN1": 0.6, "SYN2": 0.4}, 10_000, 500.0, "M", "A", "A")
    return compare_portfolios(data, {"A": spec, **benchmark_specs(spec)}, ExecutionConfig(slippage_bps=2, fee_bps=1))


def test_o01_price_bundle_reproduces_the_analysis_exactly_through_the_upload_path():
    """QA-031 (fixed): bundle -> 'My own CSV files' -> identical fingerprint and every result."""
    original = comparison(SyntheticProvider(7).fetch(["SYN1", "SYN2"], "2015-01-01", "2020-12-31"))
    archive = zipfile.ZipFile(io.BytesIO(price_bundle(original.data, original.fingerprint)))
    assert sorted(archive.namelist()) == ["SYN1.csv", "SYN2.csv", "bundle.json"]
    frames = {n[:-4]: read_ohlcv_csv(io.BytesIO(archive.read(n)), n[:-4]) for n in archive.namelist() if n.endswith(".csv")}
    again = comparison(CsvProvider(frames).fetch(list(frames)))
    assert again.fingerprint == original.fingerprint
    for name in original.stats:
        for key, value in original.stats[name].items():
            assert again.stats[name][key] == value or (value != value and again.stats[name][key] != again.stats[name][key]), (name, key)
    assert '"fingerprint": "' + original.fingerprint + '"' in archive.read("bundle.json").decode()


def test_o02_provider_data_is_never_bundled():
    """QA-035 boundary: Yahoo-derived data (live or the frozen snapshot) is not packaged."""
    data = SyntheticProvider(7).fetch(["SYN1"], "2019-01-01", "2020-12-31")
    from dataclasses import replace

    meta = data.metadata.to_dict()
    for source in ("yfinance", "yahoo-finance"):
        yahoo = replace(data, metadata=replace(data.metadata, source=source, synthetic=False))
        assert not can_bundle(yahoo)
        with pytest.raises(PermissionError, match="redistribution rights are not established"):
            price_bundle(yahoo, "x")
    assert meta["synthetic"] is True and can_bundle(data)
    assert DatasetMetadata  # imported for the type used above


def test_o03_investment_lab_offers_the_bundle_only_when_allowed(monkeypatch):
    at = render(view("invest"), monkeypatch)
    assert "Price data" in texts(at)  # synthetic: offered
    source = view("invest").read_text()
    assert "if can_bundle(comparison.data):" in source and "redistribution rights are not established" in source


def test_o04_cache_folder_is_configurable(monkeypatch, tmp_path):
    """QA-038 (fixed)."""
    monkeypatch.syspath_prepend(str(ROOT / "app"))
    import components.common as common

    monkeypatch.delenv("QUANTLAB_CACHE_DIR", raising=False)
    assert common.cache_dir() == common.ROOT / ".data_cache"
    monkeypatch.setenv("QUANTLAB_CACHE_DIR", str(tmp_path / "persistent"))
    assert common.cache_dir() == tmp_path / "persistent"
    monkeypatch.setenv("QUANTLAB_CACHE_DIR", "  ")
    assert common.cache_dir() == common.ROOT / ".data_cache"


def test_o05_lock_files_pin_every_dependency_with_hashes():
    """QA-032 (fixed): two hash-locked environments, both tested in CI."""
    for name in ("lock.txt", "study-py313.txt"):
        text = (ROOT / "requirements" / name).read_text()
        pins = re.findall(r"^([A-Za-z0-9_.\-]+)==([^\s;]+)", text, re.MULTILINE)
        assert len(pins) > 30, name
        blocks = [b for b in re.split(r"\n(?=[A-Za-z0-9_.\-]+==)", text.strip()) if "==" in b.split("\n")[0]]
        assert all("--hash=sha256:" in b for b in blocks), name
        for runtime in ("numpy", "pandas", "exchange-calendars", "yfinance", "pytest", "hypothesis"):
            assert any(p[0].lower().replace("_", "-") == runtime for p in pins), (name, runtime)
    study = (ROOT / "requirements" / "study-py313.txt").read_text()
    assert re.search(r"^numpy==2\.5\.3 ", study, re.MULTILINE) and re.search(r"^pandas==3\.0\.5 ", study, re.MULTILINE)


def test_o06_ci_runs_locked_exact_audit_and_scheduled_jobs():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    for needle in ("tools/verify_clean_env.sh python", "--require-hashes -r requirements/study-py313.txt",
                   'grep -q "largest absolute difference 0$"', "pip-audit -r requirements/lock.txt",
                   "pip-audit -r requirements/study-py313.txt", "schedule:", "cron:"):  # fmt: skip
        assert needle in ci, needle
    script = (ROOT / "tools" / "verify_clean_env.sh").read_text()
    assert "--require-hashes -r requirements/lock.txt" in script and "pip check" in script
