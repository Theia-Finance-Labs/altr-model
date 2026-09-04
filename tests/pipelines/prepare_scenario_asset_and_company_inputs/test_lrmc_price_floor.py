"""Long-run-marginal-cost price floor (`price_floor.method: lrmc`).

IAM electricity prices are annual marginal-cost shadow prices; under WITCH,
MESSAGE and REMIND they sit BELOW the full cost of the plants those pathways
keep building. In long-run equilibrium the average price must at least cover
the levelised cost of the price-setting entrant, or nothing gets built. The
floor is that levelised cost, computed from the scenario's own technology
columns for the region-year's price-setting thermal technology, and applied
as a single market price to every technology in the region-year.
"""

import pandas as pd
import pytest
from altr_model.pipelines.prepare_scenario_asset_and_company_inputs._input_nodes import (
    apply_lrmc_price_floor,
    capital_recovery_factor,
)

LRMC = {"method": "lrmc", "discount_rate": 0.08}
HOURS = 8760


def _row(
    tech,
    price,
    pathway,
    fuel=0.0,
    eff=1.0,
    om=0.0,
    capex=0.0,
    cf=0.5,
    life=40.0,
    geo="EU",
    year=2030,
):
    return {
        "scenario": "S",
        "scenario_geography": geo,
        "year": year,
        "technology": tech,
        "scenario_price": price,
        "power_price_excarbon_usd_per_mwh": price,
        "scenario_pathway": pathway,
        "fuel_price": fuel,
        "efficiency_decimal": eff,
        "om_cost_usd_per_mw_per_yr": om,
        "capital_cost_usd_per_mw": capex,
        "scenario_capacity_factor": cf,
        "lifetime_years": life,
    }


# A coal plant: fuel 17.8, O&M 7.8 and capital 14.6 per MWh at 8% -> LRMC ~40.2 (the WITCH China 2030 case)
COAL = dict(fuel=6.76, eff=0.38, om=47_694.0, capex=1_069_744.0, cf=0.70, life=40.0)


def _coal_lrmc(price_irrelevant=None):
    hours = COAL["cf"] * HOURS
    return (
        COAL["fuel"] / COAL["eff"]
        + COAL["om"] / hours
        + COAL["capex"] * capital_recovery_factor(0.08, 40.0) / hours
    )


def test_capital_recovery_factor_is_the_annuity_formula():
    assert capital_recovery_factor(0.08, 40.0) == pytest.approx(0.08386, abs=1e-5)
    assert capital_recovery_factor(0.08, 1000.0) == pytest.approx(
        0.08, abs=1e-6
    )  # near-perpetuity: interest only


def test_method_none_leaves_the_price_alone_and_reports_no_floor():
    frame = pd.DataFrame(
        [
            _row("CoalCap - w/o CCS", 25.3, 70.0, **COAL),
            _row("WindCap - Onshore", 25.3, 30.0),
        ]
    )
    out = apply_lrmc_price_floor(frame, {"method": "none"})
    assert (out["power_price_excarbon_usd_per_mwh"] == 25.3).all()
    assert (out["price_floor_lrmc"] == 0.0).all()


def test_a_short_run_price_is_lifted_to_the_price_setters_lrmc_for_every_technology():
    frame = pd.DataFrame(
        [
            _row("CoalCap - w/o CCS", 25.3, 70.0, **COAL),
            _row("WindCap - Onshore", 25.3, 30.0),
        ]
    )
    out = apply_lrmc_price_floor(frame, LRMC).set_index("technology")
    assert out.loc["CoalCap - w/o CCS", "price_floor_lrmc"] == pytest.approx(
        _coal_lrmc(), rel=1e-6
    )
    assert out.loc[
        "CoalCap - w/o CCS", "power_price_excarbon_usd_per_mwh"
    ] == pytest.approx(_coal_lrmc(), rel=1e-6)
    # one market price: the wind row is lifted to the same number
    assert out.loc[
        "WindCap - Onshore", "power_price_excarbon_usd_per_mwh"
    ] == pytest.approx(_coal_lrmc(), rel=1e-6)
    # the raw IAM price is kept for audit
    assert (out["scenario_price"] == 25.3).all()


def test_a_price_already_above_the_lrmc_is_unchanged():
    frame = pd.DataFrame(
        [
            _row("CoalCap - w/o CCS", 130.0, 70.0, **COAL),
            _row("WindCap - Onshore", 130.0, 30.0),
        ]
    )
    out = apply_lrmc_price_floor(frame, LRMC)
    assert (out["power_price_excarbon_usd_per_mwh"] == 130.0).all()
    assert (
        out["price_floor_lrmc"] < 130.0
    ).all()  # reported even when it does not bind


def test_the_price_setter_is_the_thermal_technology_with_the_largest_generation():
    gas = dict(fuel=30.0, eff=0.55, om=32_000.0, capex=820_000.0, cf=0.5, life=35.0)
    frame = pd.DataFrame(
        [
            _row("CoalCap - w/o CCS", 25.0, 20.0, **COAL),
            _row("GasCap - w/o CCS", 25.0, 60.0, **gas),
            _row(
                "HydroCap",
                25.0,
                100.0,
                om=60_000.0,
                capex=2_400_000.0,
                cf=0.45,
                life=70.0,
            ),  # largest overall, not thermal
        ]
    )
    out = apply_lrmc_price_floor(frame, LRMC).set_index("technology")
    hours = gas["cf"] * HOURS
    gas_lrmc = (
        gas["fuel"] / gas["eff"]
        + gas["om"] / hours
        + gas["capex"] * capital_recovery_factor(0.08, 35.0) / hours
    )
    assert out.loc["GasCap - w/o CCS", "price_floor_lrmc"] == pytest.approx(
        gas_lrmc, rel=1e-6
    )
    assert (out["price_setter_technology"] == "GasCap - w/o CCS").all()


def test_aggregate_parent_rows_never_set_the_price():
    frame = pd.DataFrame(
        [
            _row(
                "CoalCap", 25.0, 71.0, **COAL
            ),  # parent = w/o + w/ CCS, always the largest
            _row("CoalCap - w/o CCS", 25.0, 70.0, **COAL),
            _row("CoalCap - w/ CCS", 25.0, 1.0, **{**COAL, "capex": 2_275_000.0}),
        ]
    )
    out = apply_lrmc_price_floor(frame, LRMC)
    assert (out["price_setter_technology"] == "CoalCap - w/o CCS").all()


def test_a_region_year_without_thermal_generation_gets_no_floor():
    frame = pd.DataFrame(
        [
            _row("HydroCap", 25.0, 80.0, capex=2_400_000.0, cf=0.45, life=70.0),
            _row("WindCap - Onshore", 25.0, 20.0),
        ]
    )
    out = apply_lrmc_price_floor(frame, LRMC)
    assert (out["power_price_excarbon_usd_per_mwh"] == 25.0).all()
    assert (out["price_floor_lrmc"] == 0.0).all()


def test_floors_are_per_scenario_region_year():
    frame = pd.DataFrame(
        [
            _row("CoalCap - w/o CCS", 25.3, 70.0, geo="CHN", **COAL),
            _row("CoalCap - w/o CCS", 90.0, 70.0, geo="EU", **COAL),
        ]
    )
    out = apply_lrmc_price_floor(frame, LRMC).set_index("scenario_geography")
    assert out.loc["CHN", "power_price_excarbon_usd_per_mwh"] == pytest.approx(
        _coal_lrmc(), rel=1e-6
    )
    assert out.loc["EU", "power_price_excarbon_usd_per_mwh"] == 90.0


@pytest.mark.parametrize(
    "params",
    [
        {"method": "merit_order"},
        {"method": "lrmc", "discount_rate": 0.0},
        {"method": "lrmc", "discount_rate": 1.5},
    ],
)
def test_bad_parameters_are_rejected(params):
    frame = pd.DataFrame([_row("CoalCap - w/o CCS", 25.3, 70.0, **COAL)])
    with pytest.raises(ValueError, match="price_floor"):
        apply_lrmc_price_floor(frame, params)


def test_input_frame_is_not_mutated():
    frame = pd.DataFrame([_row("CoalCap - w/o CCS", 25.3, 70.0, **COAL)])
    before = frame.copy()
    apply_lrmc_price_floor(frame, LRMC)
    pd.testing.assert_frame_equal(frame, before)
