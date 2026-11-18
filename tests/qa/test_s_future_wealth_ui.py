"""Suite S: the Future Wealth section of the Investment Lab, driven headless."""

import json
import re

import numpy as np
import pytest
from fixtures.app import metrics, render, texts, view

from quantlab.data import SyntheticProvider
from quantlab.forecast import WealthPlan, build_model, monthly_returns, simulate_wealth, summary


def future(monkeypatch, tmp_path, **state):
    monkeypatch.setenv("QUANTLAB_FORECAST_DIR", str(tmp_path / "ledger"))
    return render(view("invest"), monkeypatch, p_il_mode="Future wealth", **state)


def test_s01_historical_comparison_stays_the_default(monkeypatch):
    at = render(view("invest"), monkeypatch)
    assert not at.exception and at.session_state["p_il_mode"] == "Historical comparison"
    assert "Final value" in metrics(at) and "FUTURE WEALTH" not in texts(at)


def test_s02_future_wealth_renders_every_section_with_honest_labels(monkeypatch, tmp_path):
    at = future(monkeypatch, tmp_path)
    assert not at.exception and not at.error
    shown = metrics(at)
    for label in ("Median after 10 yr", "5th to 95th percentile", "Reach $100k by year 10", "Hold it at the end",
                  "End below what you paid in", "Total you pay in"):  # fmt: skip
        assert label in shown, label
    page = texts(at)
    for phrase in ("This is not a forecast", "MODEL: HISTORICAL RUNS OF MONTHS", "What drives this projection",
                   "Two kinds of uncertainty", "Model uncertainty dominates", "Event order each month",
                   "same simulated markets", "This is not advice"):  # fmt: skip
        assert phrase in page, phrase
    assert "(95%)" in next(m.delta for m in at.metric if m.label == "Hold it at the end")
    assert len(at.tabs) >= 9 and not any("nan" in v.lower() for v in shown.values())


def test_s03_headline_numbers_are_the_library_numbers(monkeypatch, tmp_path):
    at = future(monkeypatch, tmp_path)
    data = SyntheticProvider(seed=7).fetch(["SYN1", "SYN2", "SYN3", "SYN4", "SYN5"], "2005-01-01")
    plan = WealthPlan({"SYN1": 0.6, "SYN2": 0.4}, 5_000.0, 500.0, "M", 0.03, "A", 5.0, 0.001, 0.0, 0.025, 10.0,
                      "Your plan")  # fmt: skip
    model = build_model("block_bootstrap", monthly_returns(data.close, ["SYN1", "SYN2"]), block=12.0)
    s = summary(simulate_wealth(plan, model, 2000, 42), 100_000.0)
    shown = metrics(at)
    assert shown["Hold it at the end"] == f"{s['goal']['p_hold']:.0%}"
    assert shown["Reach $100k by year 10"] == f"{s['goal']['p_reach']:.0%}"
    assert shown["Total you pay in"] == f"${s['total_contributed'] / 1e3:,.0f}k"


def test_s04_plan_inputs_change_the_projection_and_invalid_mixes_are_refused(monkeypatch, tmp_path):
    base = metrics(future(monkeypatch, tmp_path))
    richer = metrics(future(monkeypatch, tmp_path, p_fw_contrib=1000.0))
    assert richer["Total you pay in"] != base["Total you pay in"]
    over = future(monkeypatch, tmp_path, p_fw_w_SYN1=80.0, p_fw_w_SYN2=40.0)
    assert any("Leverage is not supported" in e.value for e in over.error) and not over.exception


def test_s05_all_cash_zero_contribution_and_long_horizon_plans(monkeypatch, tmp_path):
    cash = future(monkeypatch, tmp_path, **{f"p_fw_w_SYN{i}": 0.0 for i in range(1, 6)})
    assert not cash.exception and metrics(cash)["End below what you paid in"] == "0%"
    lump = future(monkeypatch, tmp_path, p_fw_contrib=0.0, p_fw_initial=50_000.0, p_fw_horizon=30)
    assert not lump.exception and "Median after 30 yr" in metrics(lump)
    nothing = future(monkeypatch, tmp_path, p_fw_contrib=0.0, p_fw_initial=0.0)
    assert any("cannot be simulated" in e.value for e in nothing.error) and not nothing.exception


def test_s06_model_and_crash_settings(monkeypatch, tmp_path):
    ewma = future(monkeypatch, tmp_path, p_fw_model="ewma_filtered")
    assert any("conditions on today's volatility" in w.value for w in ewma.warning)
    crash = future(monkeypatch, tmp_path, p_fw_crash=True, p_fw_shock=-50)
    assert "crash of -50% in month 1" in texts(crash)


def test_s07_compare_tab_uses_common_random_numbers(monkeypatch, tmp_path):
    at = future(monkeypatch, tmp_path)
    table = next(d.value for d in at.dataframe if "$200/month" in d.value.columns)
    assert list(table.columns) == ["$200/month", "$500/month", "$1,000/month"]
    assert len(set(table.loc["End below paid in"])) == 1  # same markets, same mix: same loss frequency


def test_s08_recording_a_forecast_appends_to_the_ledger(monkeypatch, tmp_path):
    at = future(monkeypatch, tmp_path)
    at.button(key="fw_record").click().run()
    assert not at.exception and any("Recorded forecast" in s.value for s in at.success)
    lines = (tmp_path / "ledger" / "forecasts.jsonl").read_text().splitlines()
    entry = json.loads(lines[0])
    assert entry["prev_hash"] is None and entry["data"]["synthetic"] is True
    assert [h["months"] for h in entry["market"]["horizons"]] == [1, 12, 36]
    assert np.all(np.diff(entry["market"]["horizons"][1]["percentiles"]) >= 0)
    at.button(key="fw_record").click().run()
    assert len((tmp_path / "ledger" / "forecasts.jsonl").read_text().splitlines()) == 2


def test_s09_validation_tab_reports_the_stored_study(monkeypatch, tmp_path):
    at = future(monkeypatch, tmp_path)
    page = texts(at)
    assert "Walk-forward validation" in page and "Nothing here is a predictive edge" in page
    import json as _json

    from fixtures.app import APP

    from quantlab.forecast.validation import summarise_record

    stored = sorted((APP.parent / "experiments" / "results").glob("forecast_validation_*.json"))
    path = ([p for p in stored if "synthetic" not in p.stem] or stored)[0]  # same choice as the page
    d = summarise_record(_json.loads(path.read_text()))["horizons"][12]
    assert f"90% ranges contained the outcome {d['coverage_90_low']:.0%}–{d['coverage_90_high']:.0%}" in page
    assert not re.search(r"\d\d–\d\d%", view("invest").read_text())  # no figure typed into the source
    verdicts = [d.value for d in at.dataframe if "Verdict" in d.value.columns]
    assert verdicts and set(verdicts[0]["Verdict"]) <= {"better (significant)", "worse (significant)",
                                                        "no significant difference", "too few outcomes to test"}  # fmt: skip


@pytest.mark.parametrize("years", [1, 3, 5, 10, 20])
def test_s10_the_standard_horizons_render(monkeypatch, tmp_path, years):
    at = future(monkeypatch, tmp_path, p_fw_horizon=years, p_fw_paths=500)
    assert not at.exception and f"Median after {years} yr" in metrics(at)


def test_s11_overview_ignores_result_files_of_other_studies(monkeypatch):
    """Regression: forecast-validation records in experiments/results broke the Overview."""
    from fixtures.app import APP

    folder = APP.parent / "experiments" / "results"
    assert list(folder.glob("forecast_validation_*.json"))  # the situation that caused the crash is present
    at = render(view("overview"), monkeypatch)
    assert not at.exception and "Latest recorded experiment" in [h.value for h in at.subheader]


def test_s12_public_demo_disables_server_writes(monkeypatch, tmp_path):
    """On a shared public deployment no visitor may append to the server's forecast record."""
    monkeypatch.setenv("QUANTLAB_PUBLIC_DEMO", "1")
    at = future(monkeypatch, tmp_path)
    assert not at.exception and "Forecast recording is switched off on this public demo" in texts(at)
    assert not [b for b in at.button if b.key in ("fw_record", "fw_evaluate")]
    assert not (tmp_path / "ledger").exists()
    assert "Median after 10 yr" in metrics(at)  # everything else still works


def test_s13_synthetic_validation_is_never_presented_as_real_evidence(monkeypatch, tmp_path):
    """Public copy: only the synthetic record exists. Its coverage must not be quoted as a finding."""
    import shutil

    from fixtures.app import APP

    monkeypatch.syspath_prepend(str(APP))
    import components.future_wealth as fw

    results = tmp_path / "root" / "experiments" / "results"
    results.mkdir(parents=True)
    for p in (APP.parent / "experiments" / "results").glob("forecast_validation_*_synthetic.json"):
        shutil.copy(p, results / p.name)
    monkeypatch.setattr(fw, "ROOT", tmp_path / "root")
    at = future(monkeypatch, tmp_path)
    warnings = " ".join(w.value for w in at.warning)
    assert not at.exception and "No real-data validation of long-horizon ranges" in warnings
    assert "ranges contained the outcome only" not in warnings
    assert "SYNTHETIC: pipeline check only" in texts(at)


def test_s14_public_demo_relays_no_third_party_market_data(monkeypatch):
    """A public server must not fetch and redistribute Yahoo data: synthetic and own CSV only."""
    monkeypatch.setenv("QUANTLAB_PUBLIC_DEMO", "1")
    monkeypatch.setenv("QUANTLAB_DEFAULT_SOURCE", "live")  # even if misconfigured
    at = render(view("overview"), monkeypatch)
    source = next(s for s in at.selectbox if s.label == "Source")
    assert not at.exception and source.options == ["Synthetic demo data", "My own CSV files"]
    assert source.value == "Synthetic demo data"
