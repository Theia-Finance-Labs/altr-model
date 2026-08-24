"""Focused tests for scenario, asset, and company input preparation."""

import pandas as pd
from altr_model.pipelines.prepare_scenario_asset_and_company_inputs._asset_preparation import (
    apply_reduce_granularity_from_asset_to_company_level,
)


def test_reduced_granularity_creates_one_synthetic_company_asset():
    shared = {
        "company_id": "company",
        "company_name": "Company",
        "scenario_geography": "World",
        "sector": "Power",
        "technology": "CoalCap",
        "year": 2030,
        "capacity_unit": "MW",
        "asset_age": 10.0,
        "age_is_inferred": False,
        "ownership_percentage": 1.0,
        "capacity_factor": 0.5,
        "emission_factor": 0.9,
    }
    assets = pd.DataFrame(
        [
            {**shared, "asset_id": "a", "asset_activity": 3.0},
            {**shared, "asset_id": "b", "asset_activity": 4.0},
        ]
    )

    reduced = apply_reduce_granularity_from_asset_to_company_level(assets, True)

    assert len(reduced) == 1
    assert reduced.loc[0, "asset_activity"] == 7.0
    assert reduced.loc[0, "asset_id"].startswith("unique_company_asset_")
