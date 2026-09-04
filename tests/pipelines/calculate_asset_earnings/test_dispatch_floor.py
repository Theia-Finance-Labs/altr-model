"""Rational-dispatch floor (`dispatch_floor: own_variable_cost`).

A dispatchable plant only runs in hours where the price covers its fuel, so the
hours the scenario says it runs are hours with a price of at least its own
variable cost. The model otherwise pays every technology the annual-average
price and so books fuel burnt at a loss for every hour of the year (WITCH
baseline: 34% of gas and 78% of oil asset-years). The floor bounds the
technology's capture price below by its own fuel cost per MWh; it never touches
a plant without fuel, and it never pays fixed costs.
"""

import pandas as pd
import pytest

from altr_model.pipelines.calculate_asset_earnings.nodes import compute_ops_block

YEARS = [2025, 2026]


def _block(price, fuel_price, efficiency, capacity_factor=0.5, capture=1.0):
    return pd.DataFrame(
        {
            "asset_id": "A",
            "company_id": "C",
            "scenario_geography": "EU",
            "sector": "Power",
            "technology": "GasCap - w/o CCS",
            "year": YEARS,
            "trajectory_type": "baseline",
            "asset_trajectory": [100.0, 100.0],
            "capacity_factor": capacity_factor,
            "emission_factor": 0.4,
            "power_price_excarbon_usd_per_mwh": price,
            "fuel_price_usd_per_mwh_fuel": fuel_price,
            "efficiency_decimal": efficiency,
            "fom_usd_per_mw_yr": 30_000.0,
            "carbon_price_usd_per_tco2": 0.0,
            "capex_total": 0.0,
            "growth_capex": 0.0,
            "decom_cost": 0.0,
            "alignment_type": "misaligned_high_carbon",
            "capture_price_factor": capture,
        }
    )


def _ops(block, dispatch_floor):
    return compute_ops_block(
        block,
        market_passthrough=0.0,
        apply_continued_om_baseline=False,
        apply_continued_om_shock=False,
        carbon_cost_method="full_ef",
        dispatch_floor=dispatch_floor,
    )


def test_method_none_leaves_revenue_at_the_average_price():
    out = _ops(
        _block(price=25.0, fuel_price=27.0, efficiency=0.5), "none"
    )  # fuel/MWh = 54 > 25
    assert out["revenue"].tolist() == pytest.approx((out["Q"] * 25.0).tolist())


def test_a_price_below_own_fuel_cost_is_lifted_to_the_fuel_cost():
    out = _ops(_block(price=25.0, fuel_price=27.0, efficiency=0.5), "own_variable_cost")
    assert out["revenue"].tolist() == pytest.approx((out["Q"] * 54.0).tolist())
    # the energy margin is exactly zero, fixed costs still bite
    assert (out["revenue"] - out["var_cost"]).tolist() == pytest.approx([0.0, 0.0])
    assert (out["EBITDA"] < 0).all()


def test_a_price_above_own_fuel_cost_is_untouched():
    out = _ops(_block(price=70.0, fuel_price=27.0, efficiency=0.5), "own_variable_cost")
    assert out["revenue"].tolist() == pytest.approx((out["Q"] * 70.0).tolist())


def test_a_plant_without_fuel_is_never_floored():
    out = _ops(_block(price=25.0, fuel_price=0.0, efficiency=1.0), "own_variable_cost")
    assert out["revenue"].tolist() == pytest.approx((out["Q"] * 25.0).tolist())


def test_the_floor_applies_after_the_capture_factor():
    # captured price 25 x 1.5 = 37.5 < fuel 54 -> floor binds at 54
    out = _ops(
        _block(price=25.0, fuel_price=27.0, efficiency=0.5, capture=1.5),
        "own_variable_cost",
    )
    assert out["revenue"].tolist() == pytest.approx((out["Q"] * 54.0).tolist())
    # captured price 40 x 1.5 = 60 > 54 -> capture wins
    out = _ops(
        _block(price=40.0, fuel_price=27.0, efficiency=0.5, capture=1.5),
        "own_variable_cost",
    )
    assert out["revenue"].tolist() == pytest.approx((out["Q"] * 60.0).tolist())


def test_an_unknown_method_is_rejected():
    with pytest.raises(ValueError, match="dispatch_floor"):
        _ops(_block(price=25.0, fuel_price=27.0, efficiency=0.5), "merit_order")
