"""Suite R: forecast validation, the append-only forecast record, and scenario files."""

import json
import math
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from quantlab.data import SyntheticProvider
from quantlab.forecast import WealthPlan, build_model, monthly_returns, simulate_wealth
from quantlab.forecast import validation as v
from quantlab.forecast.ledger import ChainError, ForecastLedger, market_forecast
from quantlab.forecast.scenario import rerun, same_result, scenario_payload

MODELS = {"iid_bootstrap": {}, "block_bootstrap": {"block": 12}, "ewma_filtered": {}, "gaussian_iid": {}}


def gaussian_months(n=240, seed=0, sigma=0.04):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("1990-01-31", periods=n, freq="ME")
    return pd.DataFrame({"AAA": np.expm1(rng.normal(0.006, sigma, n))}, index=dates)


def regime_months(n=300, seed=1):
    """Volatility that persists for years: calm 2%, stormy 9% a month."""
    rng = np.random.default_rng(seed)
    sigma = np.where((np.arange(n) // 36) % 2 == 0, 0.02, 0.09)
    dates = pd.date_range("1980-01-31", periods=n, freq="ME")
    return pd.DataFrame({"AAA": np.expm1(rng.normal(0.005, sigma))}, index=dates)


def test_r01_crps_matches_its_closed_form_and_definition():
    rng = np.random.default_rng(0)
    sample = rng.standard_normal(200_000)
    for y in (-1.5, 0.0, 0.7):
        exact = y * (2 * norm.cdf(y) - 1) + 2 * norm.pdf(y) - 1 / math.sqrt(math.pi)
        assert v.crps_ensemble(sample, y) == pytest.approx(exact, abs=0.004)
    small = np.array([0.1, -0.2, 0.4])
    brute = np.abs(small - 0.05).mean() - 0.5 * np.abs(small[:, None] - small[None, :]).mean()
    assert v.crps_ensemble(small, 0.05) == pytest.approx(brute, rel=1e-12)
    assert v.crps_ensemble(np.array([0.3]), 0.1) == pytest.approx(0.2)  # a point forecast: absolute error
    assert v.pinball(0.1, 0.0, 0.05) == pytest.approx(0.095) and v.pinball(-0.1, 0.0, 0.95) == pytest.approx(0.095)


def test_r02_diebold_mariano_and_ks_reference_values():
    rng = np.random.default_rng(3)
    assert math.isnan(v.diebold_mariano(np.zeros(50), 0)[0])  # identical losses: undefined, not 'significant'
    d = rng.normal(0.0, 1.0, 400)
    stat, p = v.diebold_mariano(d, 0)
    assert stat == pytest.approx(d.mean() / (d.std() / math.sqrt(400)), rel=1e-12) and 0 < p < 1
    assert v.diebold_mariano(d + 0.5, 0)[1] < 1e-6
    u = np.linspace(0.0005, 0.9995, 1000)
    assert v.ks_uniform(u) < 0.002 and v.ks_uniform(np.full(100, 0.5)) == pytest.approx(0.5, abs=0.011)


def test_r03_walk_forward_never_uses_data_after_the_origin():
    data = gaussian_months(180)
    base = v.walk_forward(data, {"AAA": 1.0}, MODELS, (1, 12), {"rolling 60": 60, "expanding": None}, 200, step=6)
    origin = pd.Timestamp("2000-06-30")
    changed = data.copy()
    changed.loc[changed.index > origin, "AAA"] *= -3.0  # rewrite the entire future
    again = v.walk_forward(changed, {"AAA": 1.0}, MODELS, (1, 12), {"rolling 60": 60, "expanding": None}, 200, step=6)
    cols = ["q05", "q25", "q50", "q75", "q95", "p_loss", "train_months"]
    for frame in (base, again):
        assert (frame["origin"] < data.index[-1]).all()
    early = lambda f: f[f["origin"] <= origin].reset_index(drop=True)[cols]  # noqa: E731
    pd.testing.assert_frame_equal(early(base), early(again))  # forecasts unchanged...
    assert not np.allclose(base.loc[base["origin"] == origin, "realized"], again.loc[again["origin"] == origin, "realized"])
    rolling = base[base["window"] == "rolling 60"]
    assert (rolling["train_months"] == 60).all()
    expanding = base[base["window"] == "expanding"]
    assert (expanding["train_months"] == expanding["origin"].map(lambda d: (data.index <= d).sum())).all()


def test_r04_realized_outcomes_are_the_next_h_months():
    data = gaussian_months(120)
    f = v.walk_forward(data, {"AAA": 1.0}, {"gaussian_iid": {}}, (12,), {"expanding": None}, 100, step=12)
    for _, row in f.iterrows():
        i = data.index.get_loc(row["origin"])
        assert row["realized"] == pytest.approx(np.prod(1 + data["AAA"].iloc[i + 1 : i + 13]) - 1, rel=1e-12)


def test_r05_correctly_specified_models_are_calibrated_and_complexity_is_not_rewarded():
    data = gaussian_months(360, seed=5)
    f = v.walk_forward(data, {"AAA": 1.0}, MODELS, (1,), {"expanding": None}, 1000, step=1)
    scores = v.score_table(f)
    for _, row in scores.iterrows():
        assert 0.84 <= row["coverage_90"] <= 0.96, row["model"]
        assert 0.40 <= row["coverage_50"] <= 0.60, row["model"]
        assert not row["beats_baseline"]  # iid normal data: nothing can beat the true model
    text = " ".join(v.conclusions(scores))
    assert "did not differ significantly from the normal baseline" in text


def test_r06_the_evaluation_has_power_when_volatility_is_persistent():
    """Sanity of the method: with long volatility regimes EWMA should help at 1 month."""
    data = regime_months()
    f = v.walk_forward(data, {"AAA": 1.0}, {"ewma_filtered": {"lam": 0.9}, "gaussian_iid": {}}, (1,),
                       {"rolling 60": 60}, 1000, step=1)  # fmt: skip
    scores = v.score_table(f).set_index("model")
    assert scores.loc["ewma_filtered", "crps_skill_vs_baseline"] > 0.03
    assert scores.loc["ewma_filtered", "beats_baseline"]
    periods = v.period_coverage(f)
    assert set(periods["model"]) == {"ewma_filtered", "gaussian_iid"}
    bins = v.calibration_bins(f)
    assert (bins["forecasts"] > 0).all() and bins["observed"].between(0, 1).all()


def test_r07_holm_adjustment_is_applied_before_any_claim():
    data = gaussian_months(240, seed=9)
    scores = v.score_table(v.walk_forward(data, {"AAA": 1.0}, MODELS, (1,), {"expanding": None}, 300, step=2))
    tested = scores[scores["model"] != "gaussian_iid"]
    assert (tested["dm_p_holm"] >= tested["dm_p"] - 1e-12).all()
    assert not scores.loc[scores["model"] == "gaussian_iid", "beats_baseline"].any()


# ----------------------------------------------------------------- forecast record


def fake_forecast(ledger, month="2024-12-31"):
    returns = gaussian_months(120)
    model = build_model("iid_bootstrap", returns)
    payload = {"plan": {"name": "p"}, "model": model.describe(), "data": {"source": "test", "last_month": month},
               "market": market_forecast(model, {"AAA": 1.0}, pd.Timestamp(month), (1, 3), 500, 1)}  # fmt: skip
    return ledger.record(payload, now=datetime(2025, 1, 2, tzinfo=UTC))


def test_r08_ledger_is_append_only_and_chained(tmp_path):
    ledger = ForecastLedger(tmp_path)
    first = fake_forecast(ledger)
    before = (tmp_path / "forecasts.jsonl").read_bytes()
    second = fake_forecast(ledger, "2025-01-31")
    after = (tmp_path / "forecasts.jsonl").read_bytes()
    assert after.startswith(before)  # earlier bytes never rewritten
    assert second["prev_hash"] == first["entry_hash"] and ledger.verify() == []
    assert first["recorded_at"] == "2025-01-02T00:00:00+00:00"
    targets = [h["target_month"] for h in first["market"]["horizons"]]
    assert targets == ["2025-01-31", "2025-03-31"]


@pytest.mark.parametrize("tamper", ["edit", "delete", "reorder"])
def test_r09_any_tampering_is_detected_and_blocks_further_appends(tmp_path, tamper):
    ledger = ForecastLedger(tmp_path)
    for month in ("2024-10-31", "2024-11-30", "2024-12-31"):
        fake_forecast(ledger, month)
    path = tmp_path / "forecasts.jsonl"
    lines = path.read_text().splitlines()
    if tamper == "edit":
        entry = json.loads(lines[1])
        entry["market"]["horizons"][0]["percentiles"][49] += 0.01  # nudge the median
        lines[1] = json.dumps(entry)
    elif tamper == "delete":
        del lines[1]
    else:
        lines[0], lines[1] = lines[1], lines[0]
    path.write_text("\n".join(lines) + "\n")
    assert ledger.verify()
    with pytest.raises(ChainError):
        fake_forecast(ledger)


def test_r10_due_forecasts_are_evaluated_once_against_realised_months(tmp_path):
    ledger = ForecastLedger(tmp_path)
    entry = fake_forecast(ledger, "2024-12-31")
    realised = pd.DataFrame({"AAA": [0.01, -0.02, 0.03]}, index=pd.to_datetime(["2025-01-31", "2025-02-28", "2025-03-31"]))
    assert len(ledger.due(pd.Timestamp("2025-01-31"))) == 1  # only the 1-month horizon is due
    first = ledger.evaluate_due(realised.iloc[:1])
    assert len(first) == 1 and first[0]["realized_return"] == pytest.approx(0.01)
    second = ledger.evaluate_due(realised)
    assert [e["horizon_months"] for e in second] == [3]
    assert second[0]["realized_return"] == pytest.approx(1.01 * 0.98 * 1.03 - 1)
    assert ledger.evaluate_due(realised) == []  # never evaluated twice
    assert all(e["forecast_hash"] == entry["entry_hash"] for e in ledger.evaluations.entries())
    assert 0.0 <= second[0]["pit"] <= 1.0 and ledger.verify() == []


# ----------------------------------------------------------------- scenario files


def test_r11_scenario_file_reruns_to_identical_numbers():
    data = SyntheticProvider(7).fetch(["AAA", "BBB"], "2000-01-01", "2024-12-31")
    returns = monthly_returns(data.close, ["AAA", "BBB"]).iloc[-120:]
    plan = WealthPlan({"AAA": 0.7, "BBB": 0.2}, 5_000, 400, "M", 0.03, "A", 5, 0.001, 0.01, 0.025, 10, "first 100k")
    model = build_model("block_bootstrap", returns, block=12.0)
    result = simulate_wealth(plan, model, 800, 11, shock=-0.3, shock_month=13)
    payload = json.loads(json.dumps(scenario_payload(result, "block_bootstrap", {"block": 12.0}, 120,
                                                     data.metadata.to_dict(), "fp", 100_000.0), default=str))  # fmt: skip
    again = rerun(payload, data.close)
    assert np.array_equal(again.values, result.values) and same_result(payload, again)
    assert payload["summary"]["goal"]["goal"] == 100_000.0 and payload["data"]["synthetic"] is True
    assert len(payload["percentiles_by_month"]["p50"]) == 121
    with pytest.raises(ValueError):
        rerun({"schema": "other"}, data.close)


def test_r12_long_horizons_with_few_independent_outcomes_make_no_claim():
    """Regression: on i.i.d. normal data the 36-month test once produced false 'wins'."""
    data = gaussian_months(400, seed=21)
    f = v.walk_forward(data, {"AAA": 1.0}, MODELS, (36,), {"expanding": None}, 400, step=1)
    scores = v.score_table(f)
    assert (scores["independent_outcomes"] < v.MIN_INDEPENDENT).all()
    assert not scores["beats_baseline"].any() and not scores["worse_than_baseline"].any()
    assert "too few independent outcomes" in v.conclusions(scores)[0]


def test_r13_hln_correction_shrinks_the_statistic_for_long_horizons():
    rng = np.random.default_rng(4)
    d = rng.normal(0.1, 1.0, 300)
    plain, _ = v.diebold_mariano(d, 11)
    corrected, p = v.diebold_mariano(d, 11, horizon=12)
    n, h = 300, 12
    assert corrected == pytest.approx(plain * math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n), rel=1e-12)
    assert 0 < p < 1


def test_r14_runtime_distribution_functions_match_scipy():
    """The forecast package avoids SciPy at run time; its replacements must agree with SciPy."""
    from scipy import stats

    from quantlab.forecast import _stats

    for x in (-4.0, -1.3, 0.0, 0.7, 2.5):
        assert _stats.norm_cdf(x) == pytest.approx(stats.norm.cdf(x), abs=1e-15)
        for df in (1, 3, 19, 30, 344):
            assert _stats.t_cdf(x, df) == pytest.approx(stats.t.cdf(x, df), abs=1e-12)
    for n in (20, 500, 2000, 20000):
        for p in (0.01, 0.05, 0.5, 0.95):
            for q in (0.025, 0.975):
                assert _stats.binom_ppf(q, n, p) == int(stats.binom.ppf(q, n, p)), (n, p, q)


def test_r15_the_forecast_package_imports_without_scipy():
    import subprocess
    import sys

    code = ("import sys; import quantlab.forecast, quantlab.forecast.validation, quantlab.forecast.ledger; "
            "print('scipy' in sys.modules)")  # fmt: skip
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_r16_record_summary_matches_the_stored_scores():
    """The page's statements about validation are computed from the record, never typed in."""
    from pathlib import Path

    folder = Path(__file__).resolve().parents[2] / "experiments" / "results"
    stored = sorted(folder.glob("forecast_validation_*.json"))
    path = ([p for p in stored if "synthetic" not in p.stem] or stored)[0]  # same choice as the page
    record = json.loads(path.read_text())
    digest = v.summarise_record(record)
    for h in (1, 12, 36):
        cells = [row for r in record["results"].values() for row in r["scores"] if row["horizon"] == h]
        by_model = {}
        for row in cells:
            by_model.setdefault(row["model"], []).append(row["coverage_90"])
        means = [sum(x) / len(x) for x in by_model.values()]
        assert digest["horizons"][h]["coverage_90_low"] == pytest.approx(min(means))
        assert digest["horizons"][h]["coverage_90_high"] == pytest.approx(max(means))
        assert digest["horizons"][h]["tests_run"] == sum(1 for r in cells if r["model"] != "gaussian_iid" and r["testable"])
        assert len(digest["horizons"][h]["wins"]) == sum(1 for r in cells if r["beats_baseline"])
    assert digest["horizons"][36]["tests_run"] == 0 and digest["synthetic"] is path.stem.endswith("_synthetic")
