import pandas as pd
import pytest
from crispy_kedro.pipelines.calculate_asset_earnings.nodes import (
    validate_asset_trajectories,
)


def _asset_trajectories(companies: tuple[str, ...], years: list[int]) -> pd.DataFrame:
    rows = []
    for company_id in companies:
        for trajectory_type in ("baseline", "latesudden"):
            for year in years:
                rows.append(
                    {
                        "asset_id": "jointly-owned-asset",
                        "company_id": company_id,
                        "scenario_geography": "EU",
                        "sector": "Power",
                        "technology": "CoalCap",
                        "year": year,
                        "trajectory_type": trajectory_type,
                        "asset_trajectory": 10.0,
                        "emission_factor": 1.0,
                        "scenario": "scenario",
                        "scenario_type": trajectory_type,
                        "capacity_factor": 0.5,
                        "power_price_excarbon_usd_per_mwh": 50.0,
                        "fuel_price_usd_per_mwh_fuel": 10.0,
                        "capex_usd_per_mw": 100.0,
                        "fom_usd_per_mw_yr": 5.0,
                        "carbon_price_usd_per_tco2": 20.0,
                        "efficiency_decimal": 0.4,
                        "scrap_usd_per_mw": 1.0,
                    }
                )
    return pd.DataFrame(rows)


def test_joint_ownership_is_validated_as_separate_asset_series():
    trajectories = _asset_trajectories(("owner-a", "owner-b"), [2025, 2026, 2027])

    result = validate_asset_trajectories(trajectories)

    assert len(result) == len(trajectories)


def test_missing_year_is_still_rejected_within_a_canonical_asset_series():
    trajectories = _asset_trajectories(("owner-a",), [2025, 2027])

    with pytest.raises(ValueError, match="Non-contiguous asset trajectory years"):
        validate_asset_trajectories(trajectories)
