"""Capture-price factors after Hirth (2013), *The market value of variable renewables*.

Hirth measures the VALUE FACTOR of wind and solar -- their generation-weighted
capture price over the average system price -- and finds it falls with market
share: wind from ~1.1 at zero share to 0.5-0.8 at 30%, solar reaching the same
by ~15%. The model pays every technology the regional annual-average price, so
the factor is applied on the revenue line. Hirth gives no dispatchable factor;
it follows from revenue conservation: generation-weighted capture prices must
average to the system price, so dispatchable plant takes the residual.
"""

import pandas as pd
import pytest
from altr_model.pipelines.prepare_scenario_asset_and_company_inputs._input_nodes import (
    compute_capture_price_factor,
)

UNITY = 1.0
HIRTH = {
    "method": "hirth2013",
    "wind_intercept": 1.1,
    "wind_slope": -1.5,
    "solar_intercept": 1.1,
    "solar_slope": -3.5,
    "vre_floor": 0.4,
    "dispatchable_cap": 2.0,
}


def _region(techs: dict[str, float], year: int = 2030, geo: str = "EU") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "scenario": "S",
            "scenario_geography": geo,
            "year": year,
            "technology": list(techs),
            "scenario_pathway": list(techs.values()),
        }
    )


def test_method_none_is_a_factor_of_one_everywhere():
    out = compute_capture_price_factor(
        _region({"CoalCap - w/o CCS": 70.0, "WindCap - Onshore": 30.0}),
        {"method": "none"},
    )
    assert (out["capture_price_factor"] == 1.0).all()


def test_wind_at_thirty_percent_share_and_the_dispatchable_residual():
    out = compute_capture_price_factor(
        _region({"CoalCap - w/o CCS": 70.0, "WindCap - Onshore": 30.0}), HIRTH
    ).set_index("technology")["capture_price_factor"]
    assert out["WindCap - Onshore"] == pytest.approx(
        1.1 - 1.5 * 0.3
    )  # 0.65, inside Hirth's 0.5-0.8
    assert out["CoalCap - w/o CCS"] == pytest.approx((1 - 0.3 * 0.65) / 0.7)  # 1.15


def test_generation_weighted_factors_average_to_one():
    """Revenue conservation: the system price is the share-weighted capture price."""
    techs = {
        "CoalCap - w/o CCS": 40.0,
        "GasCap - w/o CCS": 20.0,
        "WindCap - Onshore": 25.0,
        "SolarCap - PV": 15.0,
    }
    out = compute_capture_price_factor(_region(techs), HIRTH).set_index("technology")
    weighted = (out["capture_price_factor"] * out["scenario_pathway"]).sum() / out[
        "scenario_pathway"
    ].sum()
    assert weighted == pytest.approx(UNITY)


def test_solar_at_fifteen_percent_share():
    out = compute_capture_price_factor(
        _region({"CoalCap - w/o CCS": 85.0, "SolarCap - PV": 15.0}), HIRTH
    ).set_index("technology")["capture_price_factor"]
    assert out["SolarCap - PV"] == pytest.approx(1.1 - 3.5 * 0.15)  # 0.575


def test_aggregate_parent_rows_do_not_double_count_the_share():
    """The extract carries `CoalCap` = `CoalCap - w/o CCS` + `CoalCap - w/ CCS`."""
    with_parent = _region(
        {
            "CoalCap": 70.0,
            "CoalCap - w/o CCS": 69.0,
            "CoalCap - w/ CCS": 1.0,
            "WindCap - Onshore": 30.0,
        }
    )
    out = compute_capture_price_factor(with_parent, HIRTH).set_index("technology")[
        "capture_price_factor"
    ]
    assert out["WindCap - Onshore"] == pytest.approx(0.65)
    assert (
        out["CoalCap"] == out["CoalCap - w/o CCS"]
    )  # parent carries the dispatchable factor too


def test_floor_and_cap_bind_at_extreme_shares():
    out = compute_capture_price_factor(
        _region({"CoalCap - w/o CCS": 5.0, "WindCap - Onshore": 95.0}), HIRTH
    ).set_index("technology")["capture_price_factor"]
    assert out["WindCap - Onshore"] == pytest.approx(0.4)
    assert out["CoalCap - w/o CCS"] == pytest.approx(2.0)


def test_an_unknown_method_is_rejected():
    with pytest.raises(ValueError, match="capture_price.method"):
        compute_capture_price_factor(
            _region({"CoalCap - w/o CCS": 1.0}), {"method": "merit_order"}
        )


def test_input_frame_is_not_mutated():
    frame = _region({"CoalCap - w/o CCS": 70.0, "WindCap - Onshore": 30.0})
    before = frame.copy()
    compute_capture_price_factor(frame, HIRTH)
    pd.testing.assert_frame_equal(frame, before)


def test_shares_are_generation_weighted_not_capacity_weighted():
    """The extract's pathway is CAPACITY for power (unit-label bug, a93e2e1):
    100 MW of wind at 0.3 and 100 MW of coal at 0.7 is a 30% wind share, not 50%."""
    frame = _region({"CoalCap - w/o CCS": 100.0, "WindCap - Onshore": 100.0})
    frame["scenario_capacity_factor"] = [0.7, 0.3]
    out = compute_capture_price_factor(frame, HIRTH).set_index("technology")[
        "capture_price_factor"
    ]
    assert out["WindCap - Onshore"] == pytest.approx(1.1 - 1.5 * 0.3)
