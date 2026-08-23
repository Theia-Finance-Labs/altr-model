"""Focused tests for company-to-asset allocation and reconciliation."""

from __future__ import annotations

import pandas as pd
import pytest
from crispy_kedro.pipelines.allocate_company_trajectories_to_assets._allocation_nodes import (
    compute_asset_baseline_trajectories,
    stagger_decreasing_technologies,
    stagger_increasing_technologies,
)
from crispy_kedro.pipelines.allocate_company_trajectories_to_assets.nodes import (
    build_canonical_asset_trajectories,
    extend_asset_panel_and_attach_retirement,
    reconcile_realized_company_trajectories,
)
from crispy_kedro.pipelines.prepare_scenario_asset_and_company_inputs.nodes import (
    FINANCIAL_SURFACE_COLUMNS,
)
from pandas.testing import assert_frame_equal


def _asset_row(asset_id: str, late_sudden: float, baseline: float) -> dict:
    return {
        "asset_id": asset_id,
        "asset_name": asset_id,
        "company_id": "company",
        "company_name": "Company",
        "scenario_geography": "World",
        "sector": "Power",
        "technology": "CoalCap",
        "year": 2033,
        "asset_age": 10.0,
        "is_synthetic": False,
        "late_sudden_phase": "transition",
        "alignment_type": "misaligned_high_carbon",
        "capacity_after_shock": late_sudden,
        "asset_baseline_trajectory": baseline,
        "emission_factor": 0.9,
        "retirement_year": 2040,
        "asset_lifetime_years": 40.0,
    }


def _company_pathways() -> pd.DataFrame:
    rows = []
    for trajectory_type, value, scenario_type in [
        ("baseline", 7.0, "baseline"),
        ("target", 6.0, "target"),
        ("late_sudden_requested", 9.0, "target"),
    ]:
        row = {
            "company_id": "company",
            "company_name": "Company",
            "scenario_geography": "World",
            "sector": "Power",
            "technology": "CoalCap",
            "year": 2033,
            "trajectory_type": trajectory_type,
            "company_trajectory": value,
            "late_sudden_phase": "transition",
            "increasing": False,
            "aligned": False,
            "alignment_type": "misaligned_high_carbon",
            "scenario_type": scenario_type,
        }
        for column in FINANCIAL_SURFACE_COLUMNS:
            row[column] = scenario_type if column == "scenario" else 1.0
        rows.append(row)
    return pd.DataFrame(rows)


def _allocation_company_path(
    technology: str, alignment_type: str, values: list[float]
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "company_id": "company",
                "company_name": "Company",
                "scenario_geography": "World",
                "sector": "Power",
                "technology": technology,
                "year": year,
                "trajectory_type": "latesudden",
                "company_trajectory": value,
                "late_sudden_phase": "transition",
                "alignment_type": alignment_type,
            }
            for year, value in zip(range(2032, 2036), values)
        ]
    )


def _allocation_assets(technology: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "asset_id": asset_id,
                "asset_name": asset_id,
                "company_id": "company",
                "company_name": "Company",
                "scenario_geography": "World",
                "sector": "Power",
                "technology": technology,
                "year": year,
                "asset_activity": activity,
                "asset_age": initial_age + year - 2032,
                "asset_baseline_trajectory": activity,
            }
            for year in range(2032, 2036)
            for asset_id, activity, initial_age in [
                ("older", 6.0, 20.0),
                ("newer", 4.0, 5.0),
            ]
        ]
    )


def test_realized_company_path_is_the_sum_of_allocated_asset_capacity():
    asset_trajectories = build_canonical_asset_trajectories(
        pd.DataFrame([_asset_row("a", 4.0, 3.0), _asset_row("b", 5.0, 4.0)]),
        _company_pathways(),
    )
    company_trajectories = reconcile_realized_company_trajectories(
        asset_trajectories, _company_pathways()
    )

    assets = asset_trajectories
    companies = company_trajectories
    assert set(assets["trajectory_type"]) == {"baseline", "latesudden"}
    assert set(companies["trajectory_type"]) == {
        "baseline",
        "target",
        "late_sudden_requested",
        "late_sudden_realized",
    }

    realized = companies[companies["trajectory_type"].eq("late_sudden_realized")]
    allocated = (
        assets[assets["trajectory_type"].eq("latesudden")]
        .groupby(
            [
                "company_id",
                "scenario_geography",
                "sector",
                "technology",
                "year",
            ],
            as_index=False,
        )["asset_trajectory"]
        .sum()
        .rename(columns={"asset_trajectory": "company_trajectory"})
    )
    assert_frame_equal(
        realized[allocated.columns].reset_index(drop=True),
        allocated.reset_index(drop=True),
        check_dtype=False,
    )
    assert set(assets["emission_factor"]) == {0.9}


def test_increasing_allocation_creates_synthetic_top_up_to_company_path():
    company_path = _allocation_company_path(
        "SolarCap - PV", "misaligned_low_carbon", [10.0, 13.0, 14.0, 15.0]
    )
    allocated, _ = stagger_increasing_technologies(
        company_path,
        _allocation_assets("SolarCap - PV"),
        shock_year=2033,
    )

    totals = allocated.groupby("year")["capacity_after_shock"].sum().to_dict()
    synthetic = allocated[allocated["is_synthetic"]]
    assert totals == {2032: 10.0, 2033: 13.0, 2034: 14.0, 2035: 15.0}
    assert synthetic["asset_id"].nunique() == 1
    assert synthetic.set_index("year")["capacity_after_shock"].to_dict() == {
        2032: 0.0,
        2033: 3.0,
        2034: 4.0,
        2035: 5.0,
    }


@pytest.mark.parametrize("use_staggered_mode", [False, True])
def test_both_decreasing_allocation_modes_reconcile_to_company_path(
    use_staggered_mode: bool,
):
    company_path = _allocation_company_path(
        "CoalCap", "misaligned_high_carbon", [10.0, 8.0, 6.0, 4.0]
    )
    retirement_dates = pd.DataFrame(
        columns=[
            "asset_id",
            "company_id",
            "scenario_geography",
            "sector",
            "technology",
            "retirement_year",
        ]
    )
    allocated, _ = stagger_decreasing_technologies(
        company_path,
        _allocation_assets("CoalCap"),
        retirement_dates,
        shock_year=2033,
        alignment_year=2033,
        apply_retirement_shock=False,
        apply_decreasing_staggered_shock=use_staggered_mode,
    )

    assert allocated.groupby("year")["capacity_after_shock"].sum().to_dict() == {
        2032: 10.0,
        2033: 8.0,
        2034: 6.0,
        2035: 4.0,
    }


def test_retirement_toggle_controls_post_alignment_asset_zeroing():
    company_path = _allocation_company_path(
        "CoalCap", "misaligned_high_carbon", [10.0, 8.0, 6.0, 4.0]
    )
    retirement_dates = pd.DataFrame(
        [
            {
                "asset_id": "older",
                "company_id": "company",
                "scenario_geography": "World",
                "sector": "Power",
                "technology": "CoalCap",
                "retirement_year": 2034,
            }
        ]
    )

    results = {}
    for apply_retirement in (False, True):
        allocated, _ = stagger_decreasing_technologies(
            company_path,
            _allocation_assets("CoalCap"),
            retirement_dates,
            shock_year=2033,
            alignment_year=2033,
            apply_retirement_shock=apply_retirement,
            apply_decreasing_staggered_shock=False,
        )
        results[apply_retirement] = allocated[
            allocated["asset_id"].eq("older") & allocated["year"].eq(2034)
        ].iloc[0]

    assert results[False]["capacity_after_shock"] > 0.0
    assert results[False]["late_sudden_phase"] != "retirement"
    assert results[True]["capacity_after_shock"] == 0.0
    assert results[True]["late_sudden_phase"] == "retirement"


def test_baseline_retirement_is_key_aligned_when_asset_rows_are_interleaved():
    years = [2035, 2036, 2037]
    company_path = pd.DataFrame(
        [
            {
                "company_id": "company",
                "company_name": "Company",
                "scenario_geography": "World",
                "sector": "Power",
                "technology": "CoalCap",
                "year": year,
                "trajectory_type": "baseline",
                "company_trajectory": 20.0,
            }
            for year in years
        ]
    )
    assets = pd.DataFrame(
        [
            {
                "asset_id": asset_id,
                "asset_name": asset_id,
                "company_id": "company",
                "company_name": "Company",
                "scenario_geography": "World",
                "sector": "Power",
                "technology": "CoalCap",
                "year": year,
                "asset_activity": activity,
                "asset_age": 10.0 + year - years[0],
            }
            for year in years
            for asset_id, activity in [("retiring", 12.0), ("continuing", 8.0)]
        ]
    )
    retirement_dates = pd.DataFrame(
        [
            {
                "asset_id": "retiring",
                "company_id": "company",
                "scenario_geography": "World",
                "sector": "Power",
                "technology": "CoalCap",
                "retirement_year": 2036,
            }
        ]
    )

    result = compute_asset_baseline_trajectories(
        companies_late_sudden_trajectories=company_path,
        allocated_assets_to_companies=assets,
        assets_retirement_dates=retirement_dates,
        apply_retirement_baseline=True,
        alignment_year=2035,
    )

    retiring = result[result["asset_id"].eq("retiring")].set_index("year")
    continuing = result[result["asset_id"].eq("continuing")].set_index("year")
    assert retiring["asset_baseline_trajectory"].to_dict() == {
        2035: 12.0,
        2036: 0.0,
        2037: 0.0,
    }
    assert continuing["asset_baseline_trajectory"].to_dict() == {
        2035: 8.0,
        2036: 8.0,
        2037: 8.0,
    }


def test_retirement_is_carried_on_panel_and_missing_retirement_stays_null():
    shared = {
        "company_id": "company",
        "company_name": "Company",
        "scenario_geography": "World",
        "sector": "Power",
        "technology": "CoalCap",
        "year": 2030,
        "asset_name": "Asset",
        "capacity_factor": 0.5,
        "emission_factor": 0.9,
        "latitude": 0.0,
        "longitude": 0.0,
        "country_iso2": "DE",
        "country_name": "Germany",
        "increasing": False,
        "scenario_start_year": 2030,
        "scenario_end_year": 2032,
    }
    panel = pd.DataFrame(
        [
            {
                **shared,
                "asset_id": "retiring",
                "asset_age": 4.0,
                "asset_lifetime_years": 5.0,
            },
            {
                **shared,
                "asset_id": "continuing",
                "technology": "GasCap",
                "asset_age": 1.0,
                "asset_lifetime_years": 50.0,
            },
        ]
    )

    extended = extend_asset_panel_and_attach_retirement(panel)

    assert set(extended["year"]) == {2030, 2031, 2032}
    assert set(
        extended.loc[extended["asset_id"].eq("retiring"), "retirement_year"]
    ) == {2032.0}
    assert (
        extended.loc[extended["asset_id"].eq("continuing"), "retirement_year"]
        .isna()
        .all()
    )
