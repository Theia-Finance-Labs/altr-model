"""Long-run-marginal-cost price floor (`price_floor.method: lrmc`).

IAM electricity prices are annual marginal-cost shadow prices; under WITCH,
MESSAGE and REMIND they sit BELOW the full cost of the plants those pathways
keep building. In long-run equilibrium the average price must at least cover
the levelised cost of the price-setting entrant, or nothing gets built. The
floor is that levelised cost, computed from the BASELINE scenario's own
technology columns for the region-year's price-setting thermal technology, and
applied as a single market price to every technology in the region-year, in
every scenario of the run.
"""

from pathlib import Path

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


def _coal_lrmc():
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
    out = apply_lrmc_price_floor(frame, LRMC, "S").set_index("technology")
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
    out = apply_lrmc_price_floor(frame, LRMC, "S")
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
    out = apply_lrmc_price_floor(frame, LRMC, "S").set_index("technology")
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
    out = apply_lrmc_price_floor(frame, LRMC, "S")
    assert (out["price_setter_technology"] == "CoalCap - w/o CCS").all()


def test_a_region_year_without_thermal_generation_gets_no_floor():
    frame = pd.DataFrame(
        [
            _row("HydroCap", 25.0, 80.0, capex=2_400_000.0, cf=0.45, life=70.0),
            _row("WindCap - Onshore", 25.0, 20.0),
        ]
    )
    out = apply_lrmc_price_floor(frame, LRMC, "S")
    assert (out["power_price_excarbon_usd_per_mwh"] == 25.0).all()
    assert (out["price_floor_lrmc"] == 0.0).all()


def test_floors_are_per_region_year():
    frame = pd.DataFrame(
        [
            _row("CoalCap - w/o CCS", 25.3, 70.0, geo="CHN", **COAL),
            _row("CoalCap - w/o CCS", 90.0, 70.0, geo="EU", **COAL),
        ]
    )
    out = apply_lrmc_price_floor(frame, LRMC, "S").set_index("scenario_geography")
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
        apply_lrmc_price_floor(frame, params, "S")


def test_input_frame_is_not_mutated():
    frame = pd.DataFrame([_row("CoalCap - w/o CCS", 25.3, 70.0, **COAL)])
    before = frame.copy()
    apply_lrmc_price_floor(frame, LRMC, "S")
    pd.testing.assert_frame_equal(frame, before)


# ── guards and cardinality (Santa round-1 findings) ─────────────────────────


@pytest.mark.parametrize(
    "broken",
    [
        {"cf": 0.0},
        {"cf": -1.0},
        {"cf": float("nan")},
        {"eff": 0.0},
        {"eff": float("nan")},
        {"life": 0.0},
        {"life": -5.0},
        {"fuel": float("nan")},
        {"capex": float("nan")},
        {"capex": float("inf")},
        {"om": float("inf")},
    ],
)
def test_an_unusable_setter_row_yields_no_floor_and_an_untouched_price(broken):
    frame = pd.DataFrame(
        [
            _row("CoalCap - w/o CCS", 25.0, 70.0, **{**COAL, **broken}),
            _row("WindCap - Onshore", 25.0, 30.0),
        ]
    )
    out = apply_lrmc_price_floor(frame, LRMC, "S")
    assert (out["price_floor_lrmc"] == 0.0).all()
    assert (out["power_price_excarbon_usd_per_mwh"] == 25.0).all()
    assert out["price_setter_technology"].isna().all()
    assert len(out) == len(frame)


def test_zero_or_missing_generation_never_sets_the_price():
    gas = dict(fuel=30.0, eff=0.55, om=32_000.0, capex=820_000.0, cf=0.5, life=35.0)
    frame = pd.DataFrame(
        [
            _row(
                "CoalCap - w/o CCS", 25.0, 0.0, **COAL
            ),  # would win on size if zero counted
            _row("OilCap - w/o CCS", 25.0, float("nan"), **COAL),
            _row("GasCap - w/o CCS", 25.0, 5.0, **gas),
        ]
    )
    out = apply_lrmc_price_floor(frame, LRMC, "S")
    assert (out["price_setter_technology"] == "GasCap - w/o CCS").all()
    all_zero = pd.DataFrame(
        [
            _row("CoalCap - w/o CCS", 25.0, 0.0, **COAL),
            _row("WindCap - Onshore", 25.0, 30.0),
        ]
    )
    out0 = apply_lrmc_price_floor(all_zero, LRMC, "S")
    assert (out0["price_floor_lrmc"] == 0.0).all() and (
        out0["power_price_excarbon_usd_per_mwh"] == 25.0
    ).all()


def test_a_negative_price_is_left_alone_when_no_floor_applies():
    frame = pd.DataFrame(
        [_row("HydroCap", -5.0, 80.0, capex=2_400_000.0, cf=0.45, life=70.0)]
    )
    out = apply_lrmc_price_floor(frame, LRMC, "S")
    assert out["power_price_excarbon_usd_per_mwh"].iloc[0] == -5.0


def test_a_missing_price_takes_the_floor_where_one_exists():
    frame = pd.DataFrame([_row("CoalCap - w/o CCS", float("nan"), 70.0, **COAL)])
    out = apply_lrmc_price_floor(frame, LRMC, "S")
    assert out["power_price_excarbon_usd_per_mwh"].iloc[0] == pytest.approx(
        _coal_lrmc(), rel=1e-6
    )


def test_a_bare_family_name_is_never_a_candidate_even_without_children():
    frame = pd.DataFrame(
        [_row("CoalCap", 25.0, 70.0, **COAL), _row("WindCap - Onshore", 25.0, 30.0)]
    )
    out = apply_lrmc_price_floor(frame, LRMC, "S")
    assert (out["price_floor_lrmc"] == 0.0).all()
    assert (out["power_price_excarbon_usd_per_mwh"] == 25.0).all()


def test_a_row_with_a_missing_technology_name_does_not_break_selection():
    frame = pd.DataFrame(
        [_row("CoalCap - w/o CCS", 25.0, 70.0, **COAL), _row(None, 25.0, 1.0)]
    )
    out = apply_lrmc_price_floor(frame, LRMC, "S")
    assert out["power_price_excarbon_usd_per_mwh"].tolist() == pytest.approx(
        [_coal_lrmc()] * 2, rel=1e-6
    )
    assert len(out) == 2


def test_row_count_is_preserved_on_a_non_unique_index():
    frame = pd.DataFrame(
        [
            _row("CoalCap - w/o CCS", 25.0, 70.0, geo="CHN", **COAL),
            _row("CoalCap - w/o CCS", 90.0, 70.0, geo="EU", **COAL),
        ]
    )
    frame.index = [0, 0]
    out = apply_lrmc_price_floor(frame, LRMC, "S")
    assert len(out) == 2
    assert sorted(out["scenario_geography"]) == ["CHN", "EU"]


def test_tied_generation_resolves_by_technology_name_regardless_of_row_order():
    gas = dict(fuel=30.0, eff=0.55, om=32_000.0, capex=820_000.0, cf=0.5, life=35.0)
    rows = [
        _row("GasCap - w/o CCS", 25.0, 50.0, **gas),
        _row("CoalCap - w/o CCS", 25.0, 50.0, **COAL),
    ]
    for order in (rows, rows[::-1]):
        out = apply_lrmc_price_floor(pd.DataFrame(order), LRMC, "S")
        assert (out["price_setter_technology"] == "CoalCap - w/o CCS").all()


def test_params_none_and_a_null_rate_are_handled():
    frame = pd.DataFrame([_row("CoalCap - w/o CCS", 25.0, 70.0, **COAL)])
    out = apply_lrmc_price_floor(frame, None)
    assert (out["power_price_excarbon_usd_per_mwh"] == 25.0).all() and (
        out["price_floor_lrmc"] == 0.0
    ).all()
    with pytest.raises(ValueError, match="price_floor.discount_rate"):
        apply_lrmc_price_floor(frame, {"method": "lrmc", "discount_rate": None})


STAGED = (
    Path(__file__).resolve().parents[3] / "data" / "05_model_input" / "scenarios.csv"
)


@pytest.mark.skipif(
    not STAGED.exists(), reason=f"staged scenarios not present at {STAGED}"
)
def test_the_witch_china_2030_anchor_on_the_staged_extract():
    """WITCH 5.0, EN_NoPolicy, CHN, 2030: coal sets the price and its LRMC at 8% is ~40.18 vs an IAM price of 25.27."""
    sc = pd.read_csv(STAGED)
    year_col = "year" if "year" in sc.columns else "scenario_year"
    w = sc[
        (sc["scenario"] == "AR6_WITCH 5.0_EN_NoPolicy")
        & (sc["scenario_geography"] == "CHN")
        & (sc[year_col] == 2030)
    ].rename(columns={year_col: "year"})
    w = w.assign(power_price_excarbon_usd_per_mwh=w["scenario_price"])
    out = apply_lrmc_price_floor(w, LRMC, "AR6_WITCH 5.0_EN_NoPolicy")
    assert (out["price_setter_technology"] == "CoalCap - w/o CCS").all()
    assert out["price_floor_lrmc"].iloc[0] == pytest.approx(40.18, abs=0.05)
    assert out["power_price_excarbon_usd_per_mwh"].tolist() == pytest.approx(
        [40.18] * len(out), abs=0.05
    )
    assert out["scenario_price"].tolist() == pytest.approx([25.27] * len(out), abs=0.01)


# ── Santa round-2 findings ───────────────────────────────────────────────────

INF = float("inf")


@pytest.mark.parametrize(
    "broken",
    [
        {"fuel": 0.0},
        {"fuel": -1.0},
        {"fuel": INF},
        {"om": 0.0},
        {"om": -1.0},
        {"capex": 0.0},
        {"capex": -1.0},
        {"cf": INF},
        {"eff": INF},
        {"life": INF},
    ],
)
def test_a_non_positive_or_infinite_cost_input_disqualifies_the_setter(broken):
    frame = pd.DataFrame(
        [
            _row("CoalCap - w/o CCS", -5.0, 70.0, **{**COAL, **broken}),
            _row("WindCap - Onshore", -5.0, 30.0),
        ]
    )
    out = apply_lrmc_price_floor(frame, LRMC, "S")
    assert (out["price_floor_lrmc"] == 0.0).all()
    assert (out["power_price_excarbon_usd_per_mwh"] == -5.0).all()
    assert out["price_setter_technology"].isna().all()


def test_an_unusable_largest_candidate_is_skipped_for_the_next_usable_one():
    gas = dict(fuel=30.0, eff=0.55, om=32_000.0, capex=820_000.0, cf=0.5, life=35.0)
    frame = pd.DataFrame(
        [
            _row(
                "CoalCap - w/o CCS", 25.0, 70.0, **{**COAL, "fuel": 0.0}
            ),  # largest, but fuel price missing
            _row("GasCap - w/o CCS", 25.0, 20.0, **gas),
        ]
    )
    out = apply_lrmc_price_floor(frame, LRMC, "S")
    assert (out["price_setter_technology"] == "GasCap - w/o CCS").all()
    assert (out["price_floor_lrmc"] > 0).all()


@pytest.mark.parametrize("generation", [-10.0, INF])
def test_negative_or_infinite_generation_is_not_a_candidate(generation):
    frame = pd.DataFrame(
        [
            _row("CoalCap - w/o CCS", 25.0, generation, **COAL),
            _row("WindCap - Onshore", 25.0, 30.0),
        ]
    )
    out = apply_lrmc_price_floor(frame, LRMC, "S")
    assert (out["price_floor_lrmc"] == 0.0).all() and (
        out["power_price_excarbon_usd_per_mwh"] == 25.0
    ).all()


def test_a_zero_price_is_left_alone_when_no_floor_applies():
    frame = pd.DataFrame(
        [_row("HydroCap", 0.0, 80.0, capex=2_400_000.0, cf=0.45, life=70.0)]
    )
    assert (
        apply_lrmc_price_floor(frame, LRMC, "S")[
            "power_price_excarbon_usd_per_mwh"
        ].iloc[0]
        == 0.0
    )


def test_a_name_extended_by_another_name_is_a_parent_even_outside_the_bare_families():
    frame = pd.DataFrame(
        [
            _row("CoalCap - w/o CCS", 25.0, 90.0, **COAL),
            _row(
                "CoalCap - w/o CCS - Sub", 25.0, 10.0, **{**COAL, "capex": 2_000_000.0}
            ),
        ]
    )
    out = apply_lrmc_price_floor(frame, LRMC, "S")
    assert (out["price_setter_technology"] == "CoalCap - w/o CCS - Sub").all()


def test_identical_duplicate_rows_survive_the_merge_unduplicated():
    row = _row("CoalCap - w/o CCS", 25.0, 70.0, **COAL)
    frame = pd.DataFrame([row, row, row])
    out = apply_lrmc_price_floor(frame, LRMC, "S")
    assert len(out) == 3
    assert out["power_price_excarbon_usd_per_mwh"].tolist() == pytest.approx(
        [_coal_lrmc()] * 3, rel=1e-6
    )


def test_valid_and_invalid_region_years_coexist_in_one_frame():
    frame = pd.DataFrame(
        [
            _row("CoalCap - w/o CCS", 25.0, 70.0, geo="CHN", **COAL),
            _row("CoalCap - w/o CCS", 25.0, 70.0, geo="EU", **{**COAL, "cf": 0.0}),
            _row(
                "HydroCap", 25.0, 70.0, geo="IND", capex=2_400_000.0, cf=0.45, life=70.0
            ),
        ]
    )
    out = apply_lrmc_price_floor(frame, LRMC, "S").set_index("scenario_geography")
    assert len(out) == 3
    assert out.loc["CHN", "power_price_excarbon_usd_per_mwh"] == pytest.approx(
        _coal_lrmc(), rel=1e-6
    )
    assert out.loc["EU", "power_price_excarbon_usd_per_mwh"] == 25.0
    assert out.loc["IND", "power_price_excarbon_usd_per_mwh"] == 25.0


def test_numeric_like_strings_in_generation_are_compared_as_numbers():
    gas = dict(fuel=30.0, eff=0.55, om=32_000.0, capex=820_000.0, cf=0.5, life=35.0)
    frame = pd.DataFrame(
        [
            _row("CoalCap - w/o CCS", 25.0, "10", **COAL),
            _row("GasCap - w/o CCS", 25.0, "9", **gas),
        ]
    )
    out = apply_lrmc_price_floor(frame, LRMC, "S")
    assert (out["price_setter_technology"] == "CoalCap - w/o CCS").all()


def test_the_witch_china_2030_anchor_embedded():
    """The exact WITCH 5.0 / EN_NoPolicy / CHN / 2030 coal row from the 2026-09-01 extract."""
    row = _row(
        "CoalCap - w/o CCS",
        25.272907283496348,
        757911.0751219639,
        fuel=6.7605629934424325,
        eff=0.37933000848255,
        om=47693.7544005038,
        capex=1069744.518,
        cf=0.7015931438322137,
        life=40.0,
        geo="CHN",
    )
    out = apply_lrmc_price_floor(
        pd.DataFrame([row, _row("SolarCap - PV", 25.272907283496348, 1.0, geo="CHN")]),
        LRMC,
        "S",
    )
    assert out["price_floor_lrmc"].iloc[0] == pytest.approx(40.17898240, abs=1e-6)
    assert out["power_price_excarbon_usd_per_mwh"].tolist() == pytest.approx(
        [40.17898240] * 2, abs=1e-6
    )


def test_the_pipeline_wires_the_price_floor_parameter_into_prepare_scenarios():
    from altr_model.pipelines.prepare_scenario_asset_and_company_inputs.pipeline import (
        PIPELINE_PARAMETERS,
        create_pipeline,
    )

    assert "price_floor" in PIPELINE_PARAMETERS
    node = next(
        n for n in create_pipeline().nodes if n.name.endswith("prepare_scenarios")
    )
    assert "params:price_floor" in node.inputs


# ── Santa round-3 findings ───────────────────────────────────────────────────


@pytest.mark.parametrize("lifetime", [10_000.0, 1e6, 1e-6])
def test_the_annuity_factor_is_finite_for_any_finite_positive_lifetime(lifetime):
    crf = capital_recovery_factor(0.08, lifetime)
    assert 0.0 < crf < float("inf")
    if lifetime >= 1e4:
        assert crf == pytest.approx(0.08, abs=1e-9)  # tends to the interest rate


def test_an_absurdly_long_but_finite_lifetime_still_sets_a_floor():
    frame = pd.DataFrame(
        [_row("CoalCap - w/o CCS", 25.0, 70.0, **{**COAL, "life": 10_000.0})]
    )
    out = apply_lrmc_price_floor(frame, LRMC, "S")
    assert (out["price_setter_technology"] == "CoalCap - w/o CCS").all()
    assert out["price_floor_lrmc"].iloc[0] > 25.0


@pytest.mark.parametrize(
    "params",
    [
        {"method": "lrmc"},
        {"method": "lrmc", "discount_rate": "eight percent"},
        {"method": "lrmc", "discount_rate": [0.08]},
    ],
)
def test_a_missing_or_non_numeric_rate_is_a_value_error(params):
    with pytest.raises(ValueError, match="price_floor.discount_rate"):
        apply_lrmc_price_floor(
            pd.DataFrame([_row("CoalCap - w/o CCS", 25.0, 70.0, **COAL)]), params, "S"
        )


# ── the floor comes from the baseline scenario and is shared by every scenario ─


def test_the_target_scenario_takes_the_baseline_floor_even_when_its_own_setter_is_broken():
    """2026-09-01 extract: target capacity factors of ~1e-12 for phased-out coal."""
    target_coal = {**COAL, "cf": 4e-12}
    frame = pd.DataFrame(
        [
            _row("CoalCap - w/o CCS", 25.3, 70.0, **COAL),
            {**_row("CoalCap - w/o CCS", 33.8, 70.0, **target_coal), "scenario": "T"},
            {**_row("WindCap - Onshore", 33.8, 30.0), "scenario": "T"},
        ]
    )
    out = apply_lrmc_price_floor(frame, LRMC, "S").set_index("scenario")
    assert out.loc["S", "price_floor_lrmc"] == pytest.approx(_coal_lrmc(), rel=1e-6)
    assert out.loc["T", "price_floor_lrmc"].tolist() == pytest.approx(
        [_coal_lrmc()] * 2, rel=1e-6
    )
    assert out.loc["T", "power_price_excarbon_usd_per_mwh"].tolist() == pytest.approx(
        [_coal_lrmc()] * 2, rel=1e-6
    )


def test_a_target_price_above_the_baseline_floor_is_untouched():
    frame = pd.DataFrame(
        [
            _row("CoalCap - w/o CCS", 25.3, 70.0, **COAL),
            {**_row("CoalCap - w/o CCS", 90.0, 70.0, **COAL), "scenario": "T"},
        ]
    )
    out = apply_lrmc_price_floor(frame, LRMC, "S").set_index("scenario")
    assert out.loc["T", "power_price_excarbon_usd_per_mwh"] == 90.0


def test_the_baseline_scenario_must_be_named_and_present():
    frame = pd.DataFrame([_row("CoalCap - w/o CCS", 25.3, 70.0, **COAL)])
    with pytest.raises(ValueError, match="baseline_scenario"):
        apply_lrmc_price_floor(frame, LRMC, None)
    with pytest.raises(ValueError, match="not in the scenarios frame"):
        apply_lrmc_price_floor(frame, LRMC, "MISSING")


def test_a_larger_usable_target_candidate_never_sets_the_price():
    """Pins baseline-only derivation: pooling target rows would pick the gas row."""
    gas = dict(fuel=30.0, eff=0.55, om=32_000.0, capex=820_000.0, cf=0.5, life=35.0)
    frame = pd.DataFrame(
        [
            _row("CoalCap - w/o CCS", 25.3, 70.0, **COAL),
            {**_row("GasCap - w/o CCS", 25.3, 999.0, **gas), "scenario": "T"},
        ]
    )
    out = apply_lrmc_price_floor(frame, LRMC, "S")
    assert (out["price_setter_technology"] == "CoalCap - w/o CCS").all()
    assert out["price_floor_lrmc"].tolist() == pytest.approx(
        [_coal_lrmc()] * 2, rel=1e-6
    )


def test_a_target_region_year_absent_from_the_baseline_gets_no_floor():
    frame = pd.DataFrame(
        [
            _row("CoalCap - w/o CCS", 25.3, 70.0, geo="CHN", **COAL),
            {
                **_row("CoalCap - w/o CCS", 12.0, 70.0, geo="IND", **COAL),
                "scenario": "T",
            },
        ]
    )
    out = apply_lrmc_price_floor(frame, LRMC, "S").set_index("scenario_geography")
    assert out.loc["IND", "price_floor_lrmc"] == 0.0
    assert out.loc["IND", "power_price_excarbon_usd_per_mwh"] == 12.0
    assert out.loc["IND", "price_setter_technology"] is None or pd.isna(
        out.loc["IND", "price_setter_technology"]
    )


def test_a_frame_without_a_scenario_column_is_a_value_error():
    frame = pd.DataFrame([_row("CoalCap - w/o CCS", 25.3, 70.0, **COAL)]).drop(
        columns="scenario"
    )
    with pytest.raises(ValueError, match="scenario"):
        apply_lrmc_price_floor(frame, LRMC, "S")


def test_a_missing_baseline_is_a_value_error_even_with_null_scenario_names():
    frame = pd.DataFrame(
        [
            _row("CoalCap - w/o CCS", 25.3, 70.0, **COAL),
            {**_row("CoalCap - w/o CCS", 25.3, 70.0, **COAL), "scenario": None},
        ]
    )
    with pytest.raises(ValueError, match="not in the scenarios frame"):
        apply_lrmc_price_floor(frame, LRMC, "MISSING")


def test_the_price_setter_is_the_largest_generator_not_the_largest_fleet():
    """90 MW of coal at 0.5 generates less than 100 MW of gas at 0.6."""
    gas = dict(fuel=30.0, eff=0.55, om=32_000.0, capex=820_000.0, cf=0.6, life=35.0)
    frame = pd.DataFrame(
        [
            _row("CoalCap - w/o CCS", 25.0, 90.0, **{**COAL, "cf": 0.5}),
            _row("GasCap - w/o CCS", 25.0, 100.0, **gas),
        ]
    )
    out = apply_lrmc_price_floor(frame, LRMC, "S")
    assert (out["price_setter_technology"] == "GasCap - w/o CCS").all()
