"""Characterization tests for the MCPR price adjustment (earnings_model).

Pinned behaviors — current behavior, computed by hand in each test body:

* `enable_mcpr=False` short-circuit: prices untouched, `marginal_emission_factor`
  added as 0.0.
* Reference clearing price = max power price among marginal (dispatchable
  fossil) technologies per (scenario_geography, year, scenario_type), times
  `mcpr_markup_factor`.
* Static Hirth (2013) value factors applied to the reference price; unmapped
  technologies default to 1.0.
* `mcpr_floor_at_iam_price` floors the adjusted price at the original IAM price
  (MCPR only lifts), and switching it off lets the adjusted price fall below it.
* Dynamic capture ratios override the static factors with the Hirth empirical
  VF(vre_share) relationships.
* `merit_order_decline` mode scales the reference price by
  `clip(1 - alpha * delta_vre_pct, floor)`, where delta_vre is measured against
  the earliest year per (geography, scenario_type) — applied BEFORE value
  factors, and still subject to the IAM-price floor.
* Regional value factors override the static ones for the named geography.
* Emission factors are propagated from asset data as capacity-weighted means per
  technology, and `marginal_emission_factor` is then the EF of the price-setting
  technology per (geography, year, scenario_type); it falls back to 0.0 when
  scenario surfaces carry no `emission_factor` column.
* `mcpr_mode="auto"` resolves to `carbon_explicit` (OP9), also at full
  carbon-price coverage; an unknown `mcpr_method` raises `ValueError`.
* `compute_scenario_vre_share`: VRE share of target-scenario pathway per
  (geography, year), missing VRE filled with 0, empty target -> empty frame.
"""

import logging

import pandas as pd
import pytest

from crispy_kedro.pipelines.earnings_model.nodes import (
    apply_mcpr_adjustment,
    compute_scenario_vre_share,
)


def _surfaces(rows, scenario_type="target"):
    """rows: list of (technology, year, power_price)."""
    return pd.DataFrame(
        [
            {
                "scenario_geography": "EU",
                "sector": "Power",
                "technology": tech,
                "year": year,
                "scenario": "S1",
                "scenario_type": scenario_type,
                "power_price_usd_per_mwh": price,
            }
            for tech, year, price in rows
        ]
    )


BASE_ROWS = [
    ("GasCap", 2030, 80.0),
    ("CoalCap", 2030, 70.0),
    ("SolarCap - PV", 2030, 30.0),
    ("WindCap - Onshore", 2030, 100.0),
]


def _prices(result):
    return dict(
        zip(result["technology"], result["power_price_usd_per_mwh"].round(6))
    )


def test_disabled_mcpr_returns_prices_unchanged_with_zero_marginal_ef():
    out = apply_mcpr_adjustment(_surfaces(BASE_ROWS), enable_mcpr=False)

    assert _prices(out) == {
        "GasCap": 80.0,
        "CoalCap": 70.0,
        "SolarCap - PV": 30.0,
        "WindCap - Onshore": 100.0,
    }
    assert (out["marginal_emission_factor"] == 0.0).all()


def test_reference_price_is_max_marginal_price_and_floor_only_lifts():
    # Marginal technologies are GasCap (80) and CoalCap (70) -> reference = 80.
    # Value factors: Gas/Coal 1.0, Solar PV 0.85, Wind Onshore 0.90.
    #   Gas   80 * 1.00 = 80.0 vs IAM 80  -> 80.0
    #   Coal  80 * 1.00 = 80.0 vs IAM 70  -> 80.0 (lifted)
    #   Solar 80 * 0.85 = 68.0 vs IAM 30  -> 68.0 (lifted)
    #   Wind  80 * 0.90 = 72.0 vs IAM 100 -> 100.0 (floored at IAM price)
    out = apply_mcpr_adjustment(_surfaces(BASE_ROWS))

    assert _prices(out) == {
        "GasCap": 80.0,
        "CoalCap": 80.0,
        "SolarCap - PV": 68.0,
        "WindCap - Onshore": 100.0,
    }
    # No emission_factor on the surfaces and no assets_data -> EF falls back to 0.
    assert (out["marginal_emission_factor"] == 0.0).all()


def test_without_floor_adjusted_price_can_fall_below_iam_price():
    out = apply_mcpr_adjustment(_surfaces(BASE_ROWS), mcpr_floor_at_iam_price=False)

    # Wind now takes 80 * 0.90 = 72.0 instead of keeping its IAM price of 100.
    assert _prices(out) == {
        "GasCap": 80.0,
        "CoalCap": 80.0,
        "SolarCap - PV": 68.0,
        "WindCap - Onshore": 72.0,
    }


def test_markup_factor_scales_the_reference_price():
    # reference = 80 * 1.10 = 88 -> Solar 88 * 0.85 = 74.8, Wind 88 * 0.90 = 79.2
    out = apply_mcpr_adjustment(
        _surfaces(BASE_ROWS),
        mcpr_markup_factor=1.10,
        mcpr_floor_at_iam_price=False,
    )

    assert _prices(out) == {
        "GasCap": 88.0,
        "CoalCap": 88.0,
        "SolarCap - PV": 74.8,
        "WindCap - Onshore": 79.2,
    }


def test_dynamic_capture_ratios_replace_static_value_factors():
    # Hirth VFs at vre_share = 0.30:
    #   Solar PV      max(1.10 - 1.5 * 0.30, 0.40) = 0.65 -> 80 * 0.65 = 52.0
    #   Wind Onshore  max(1.05 - 0.8 * 0.30, 0.50) = 0.81 -> 80 * 0.81 = 64.8
    #   dispatchable  1.0                                 -> 80.0
    vre = pd.DataFrame(
        {"scenario_geography": ["EU"], "year": [2030], "vre_share": [0.30]}
    )
    out = apply_mcpr_adjustment(
        _surfaces(BASE_ROWS),
        enable_dynamic_capture_ratios=True,
        scenario_vre_share=vre,
        mcpr_floor_at_iam_price=False,
    )

    assert _prices(out) == {
        "GasCap": 80.0,
        "CoalCap": 80.0,
        "SolarCap - PV": 52.0,
        "WindCap - Onshore": 64.8,
    }


def test_merit_order_decline_scales_reference_price_by_vre_growth():
    # Two years, one geography: VRE share 0.10 (2025, the baseline year) -> 0.30.
    # delta_vre(2030) = 0.20 -> decline = 1 - 0.006 * 20 pp = 0.88.
    # Reference price 100 both years -> 100.0 (2025) and 88.0 (2030).
    #   Solar 2025: 100 * 0.85 = 85.0 ; Solar 2030: 88 * 0.85 = 74.8
    surfaces = _surfaces(
        [
            ("GasCap", 2025, 100.0),
            ("SolarCap - PV", 2025, 20.0),
            ("GasCap", 2030, 100.0),
            ("SolarCap - PV", 2030, 20.0),
        ]
    )
    vre = pd.DataFrame(
        {
            "scenario_geography": ["EU", "EU"],
            "year": [2025, 2030],
            "vre_share": [0.10, 0.30],
        }
    )

    out = apply_mcpr_adjustment(
        surfaces.copy(),
        mcpr_mode="merit_order_decline",
        scenario_vre_share=vre,
        mcpr_floor_at_iam_price=False,
    )
    got = dict(
        zip(
            zip(out["technology"], out["year"]),
            out["power_price_usd_per_mwh"].round(6),
        )
    )
    assert got == {
        ("GasCap", 2025): 100.0,
        ("SolarCap - PV", 2025): 85.0,
        ("GasCap", 2030): 88.0,
        ("SolarCap - PV", 2030): 74.8,
    }

    # With the IAM floor on, the decline is negated for the marginal technology
    # itself (88 < its IAM price of 100) but still reaches solar.
    floored = apply_mcpr_adjustment(
        surfaces.copy(),
        mcpr_mode="merit_order_decline",
        scenario_vre_share=vre,
    )
    got_floored = dict(
        zip(
            zip(floored["technology"], floored["year"]),
            floored["power_price_usd_per_mwh"].round(6),
        )
    )
    assert got_floored[("GasCap", 2030)] == 100.0
    assert got_floored[("SolarCap - PV", 2030)] == 74.8


def test_regional_value_factors_override_the_static_ones():
    # EU solar VF forced to 0.50: 80 * 0.50 = 40.0, still floored at IAM 30.
    out = apply_mcpr_adjustment(
        _surfaces(BASE_ROWS),
        enable_regional_mcpr_vf=True,
        mcpr_regional_value_factors={"EU": {"SolarCap - PV": 0.50}},
    )

    assert _prices(out)["SolarCap - PV"] == 40.0
    # Untouched technologies keep the default-factor outcome.
    assert _prices(out)["WindCap - Onshore"] == 100.0


def test_marginal_emission_factor_comes_from_the_price_setting_technology():
    # Capacity-weighted EF per technology from asset data:
    #   GasCap  (0.4 * 100 + 0.6 * 300) / 400 = 0.55
    #   CoalCap zero weight -> unweighted mean 0.90
    #   SolarCap - PV                         -> 0.00
    # After the adjustment Gas and Coal both clear at 80; the tie breaks on
    # technology name, so GasCap is the marginal technology -> EF 0.55.
    assets = pd.DataFrame(
        {
            "technology": ["GasCap", "GasCap", "CoalCap", "SolarCap - PV"],
            "emission_factor": [0.4, 0.6, 0.9, 0.0],
            "asset_activity": [100.0, 300.0, 0.0, 50.0],
        }
    )

    out = apply_mcpr_adjustment(_surfaces(BASE_ROWS), assets_data=assets)

    assert out["marginal_emission_factor"].round(6).tolist() == [0.55] * 4
    # The temporary technology EF column does not leak into the surfaces.
    assert "emission_factor" not in out.columns


def test_auto_mode_resolves_to_carbon_explicit_at_full_carbon_price_coverage(caplog):
    surfaces = _surfaces(BASE_ROWS)
    surfaces["carbon_price_usd_per_tco2"] = 50.0

    with caplog.at_level(logging.INFO):
        apply_mcpr_adjustment(surfaces, mcpr_mode="auto")

    assert "coverage=100.0% → resolved to 'carbon_explicit'" in caplog.text
    assert "mode=merit_order_decline" not in caplog.text


def test_unknown_method_raises():
    with pytest.raises(ValueError, match="Unknown MCPR method"):
        apply_mcpr_adjustment(_surfaces(BASE_ROWS), mcpr_method="not_a_method")


def test_vre_share_is_target_scenario_pathway_share_per_geo_year():
    scenarios = pd.DataFrame(
        [
            # EU 2030 target: VRE 30 + 10 of 100 total -> 0.40
            ("target", "EU", 2030, "SolarCap - PV", 30.0),
            ("target", "EU", 2030, "WindCap - Onshore", 10.0),
            ("target", "EU", 2030, "GasCap", 60.0),
            # US 2030 target: no VRE -> 0.0
            ("target", "US", 2030, "GasCap", 50.0),
            # baseline rows are ignored entirely
            ("baseline", "EU", 2030, "SolarCap - PV", 900.0),
        ],
        columns=[
            "scenario_type",
            "scenario_geography",
            "year",
            "technology",
            "scenario_pathway",
        ],
    )

    out = compute_scenario_vre_share(scenarios)

    assert list(out.columns) == ["scenario_geography", "year", "vre_share"]
    assert dict(zip(out["scenario_geography"], out["vre_share"].round(6))) == {
        "EU": 0.4,
        "US": 0.0,
    }


def test_vre_share_empty_when_no_target_rows():
    scenarios = pd.DataFrame(
        [("baseline", "EU", 2030, "GasCap", 50.0)],
        columns=[
            "scenario_type",
            "scenario_geography",
            "year",
            "technology",
            "scenario_pathway",
        ],
    )

    out = compute_scenario_vre_share(scenarios)

    assert out.empty
    assert list(out.columns) == ["scenario_geography", "year", "vre_share"]
