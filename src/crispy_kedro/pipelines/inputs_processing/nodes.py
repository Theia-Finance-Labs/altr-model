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
        filtered_assets = assets_forecasts.loc[
            assets_forecasts.asset_id.isin(asset_ids), :
        ]
    else:
        filtered_assets = assets_forecasts

    filtered_assets = filtered_assets.rename({"production_year": "year"}, axis=1)
    filtered_assets.loc[:, "capacity"] = filtered_assets.loc[:, "capacity"].astype(
        float
    )

    return filtered_assets


def filter_scenarios(
    scenarios: pd.DataFrame, target_scenario: str, baseline_scenario: str
) -> pd.DataFrame:
    traj_scenario = scenarios.loc[
        scenarios.scenario.isin([target_scenario, baseline_scenario]), :
    ]

    traj_scenario.loc[:, "scenario_pathway"] = traj_scenario.loc[
        :, "scenario_pathway"
    ].astype(float)
    return traj_scenario


def filter_companies(
    plant_ownerships: pd.DataFrame, filtered_plant_detail: pd.DataFrame
) -> pd.DataFrame:
    filtered_assets = filtered_plant_detail["asset_id"].unique().tolist()
    plant_ownership_df = plant_ownerships.loc[
        plant_ownerships["asset_id"].isin(filtered_assets)
    ]

    return plant_ownership_df.loc[
        :, ["asset_id", "owner_name", "company_id", "normalized_ownership"]
    ]
