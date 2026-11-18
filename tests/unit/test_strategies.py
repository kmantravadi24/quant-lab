import numpy as np
import pandas as pd
import pytest
from fixtures.synthetic import make_data

from quantlab.strategies import (
    BuyAndHold,
    CrossSectionalMomentum,
    MeanReversion,
    TrendFollowing,
)


def test_trend_signal_by_hand():
    #  close   10    11    12    13    12     11    10    9
    #  SMA2     -  10.5  11.5  12.5  12.5   11.5  10.5  9.5
    #  SMA3     -     -    11    12  12.33    12    11   10
    #  signal   0     0     1     1     1      0     0    0
    data = make_data({"A": [10, 11, 12, 13, 12, 11, 10, 9]})
    out = TrendFollowing(2, 3).generate(data)
    assert out.signals["A"].tolist() == [0, 0, 1, 1, 1, 0, 0, 0]
    assert list(out.weights.index) == [data.dates[2], data.dates[5]]
    assert out.weights["A"].tolist() == [1.0, 0.0]


def test_trend_parameter_validation():
    with pytest.raises(ValueError):
        TrendFollowing(200, 50)


def test_mean_reversion_state_machine_by_hand():
    # lookback 3, enter z <= -1, exit z >= 0
    # i=2: window 10,10,10 -> std 0 -> z undefined -> stay flat
    # i=3: window 10,10,7  -> mean 9, std 1.732, z = -1.155 -> ENTER
    # i=4: window 10,7,8   -> mean 8.33, std 1.528, z = -0.218 -> hold
    # i=5: window 7,8,10   -> z = +1.091 -> EXIT
    data = make_data({"A": [10, 10, 10, 7, 8, 10, 12]})
    out = MeanReversion(lookback=3, entry_z=1.0, exit_z=0.0).generate(data)
    assert out.signals["A"].tolist() == [0, 0, 0, 1, 1, 0, 0]
    assert out.diagnostics["zscore"]["A"].iloc[3] == pytest.approx(-2 / np.sqrt(3))
    assert list(out.weights.index) == [data.dates[3], data.dates[5]]


def test_momentum_ranking_and_rebalance_date():
    dates = pd.bdate_range("2024-01-29", "2024-02-05")  # Jan 29,30,31 | Feb 1,2,5
    data = make_data(
        {"A": [10, 11, 12, 13, 14, 15], "B": [10] * 6, "C": [10, 9, 8, 7, 6, 5]}, dates=dates
    )
    out = CrossSectionalMomentum(lookback=2, top_n=2, rebalance="M").generate(data)
    # Only decision: first session of February. Scores: A 13/11-1, B 0, C 7/9-1 -> pick A, B.
    assert list(out.weights.index) == [pd.Timestamp("2024-02-01")]
    assert out.weights.iloc[0].to_dict() == {"A": 0.5, "B": 0.5, "C": 0.0}
    assert out.diagnostics["score"].loc["2024-02-01", "A"] == pytest.approx(13 / 11 - 1)


def test_momentum_inverse_vol_weights_sum_to_one():
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2023-01-02", periods=120)
    closes = {t: (100 * np.exp(np.cumsum(rng.normal(0, s, 120)))).tolist()
              for t, s in {"A": 0.01, "B": 0.02, "C": 0.03}.items()}  # fmt: skip
    out = CrossSectionalMomentum(20, top_n=2, weighting="inverse_vol").generate(
        make_data(closes, dates=dates)
    )
    assert len(out.weights) > 0
    np.testing.assert_allclose(out.weights.sum(axis=1).to_numpy(), 1.0)


def test_momentum_skips_decision_when_history_is_insufficient():
    dates = pd.bdate_range("2024-01-29", "2024-02-05")
    data = make_data({"A": [10, 11, 12, 13, 14, 15], "B": [10] * 6}, dates=dates)
    out = CrossSectionalMomentum(lookback=50, top_n=2).generate(data)
    assert out.weights.empty


def test_buy_and_hold_waits_for_all_assets():
    nan = np.nan
    data = make_data({"A": [10, 10, 10, 10], "B": [nan, nan, 5, 5]})
    out = BuyAndHold({"A": 0.5, "B": 0.5}).generate(data)
    assert list(out.weights.index) == [data.dates[2]]
    with pytest.raises(KeyError):
        BuyAndHold({"ZZZ": 1.0}).generate(data)
