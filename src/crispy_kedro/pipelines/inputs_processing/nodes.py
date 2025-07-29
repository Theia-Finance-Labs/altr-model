"""
This is a boilerplate pipeline 'inputs_processing'
generated using Kedro 0.19.12
"""

import pandas as pd
from typing import List, Tuple


def filter_assets(
    assets_forecasts: pd.DataFrame,
    asset_ids: List[str],
) -> pd.DataFrame:
    if asset_ids:
        filtered_assets = assets_forecasts[assets_forecasts.asset_id.isin(asset_ids)]
    else:
        filtered_assets = assets_forecasts

    filtered_assets.rename(columns={"production_year": "year"}, inplace=True)
    filtered_assets["capacity"] = filtered_assets["capacity"].astype(float)

    return filtered_assets


def filter_scenarios(
    scenarios: pd.DataFrame,
    target_scenario: str,
    baseline_scenario: str,
    scenario_geography: str,
) -> pd.DataFrame:
    traj_scenario = scenarios[
        scenarios.scenario.isin([target_scenario, baseline_scenario])
        & scenarios.scenario_geography.isin([scenario_geography])
    ]

    traj_scenario["scenario_pathway"] = traj_scenario["scenario_pathway"].astype(float)
    return traj_scenario


def filter_companies(
    plant_ownerships: pd.DataFrame, filtered_plant_detail: pd.DataFrame
) -> pd.DataFrame:
    filtered_assets = filtered_plant_detail["asset_id"].unique()
    plant_ownership_df = plant_ownerships.loc[
        plant_ownerships["asset_id"].isin(filtered_assets)
    ]

    # TODO : APPLY OWNERSHIP TREE ACCORDING TO EVENTS // ownership of events is ignored quick&dirty
    # Step 1: aggregate ownership by asset and company
    # companies_ownership_tree = plant_ownership_df.groupby(
    #     ["asset_id", "owner_name", "company_id"], as_index=False
    # ).agg({"ownership_percentage": "sum"})
    # companies_ownership_tree["ownership_percentage"] = companies_ownership_tree[
    #     "ownership_percentage"
    # ].astype(float)

    # # Step 2: normalize ownership per asset
    # companies_ownership_tree["normalized_ownership"] = companies_ownership_tree[
    #     "ownership_percentage"
    # ] / companies_ownership_tree.groupby("asset_id")["ownership_percentage"].transform(
    #     "sum"
    # )

    return plant_ownership_df[
        ["asset_id", "owner_name", "company_id", "normalized_ownership"]
    ]
