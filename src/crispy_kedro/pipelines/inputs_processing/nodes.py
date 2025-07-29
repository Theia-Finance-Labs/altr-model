"""
This is a boilerplate pipeline 'inputs_processing'
generated using Kedro 0.19.12
"""

import pandas as pd
from typing import List, Tuple


def filter_assets(
    assets_forecasts: pd.DataFrame,
    company_ids: List[str],
) -> pd.DataFrame:
    if company_ids:
        filtered_assets_forecasts = assets_forecasts.loc[
            assets_forecasts.company_id.isin(company_ids), :
        ]
    else:
        filtered_assets_forecasts = assets_forecasts

    assert (
        len(
            filtered_assets_forecasts.groupby(["asset_id", "technology"])[
                "production_year"
            ]
            .transform("min")
            .unique()
        )
        == 1
    ), "first production_year should be the same for all assets and technologies"

    filtered_assets_forecasts = filtered_assets_forecasts.rename(
        {"production_year": "year"}, axis=1
    )
    filtered_assets_forecasts.loc[:, "capacity"] = filtered_assets_forecasts.loc[
        :, "capacity"
    ].astype(float)

    return filtered_assets_forecasts


def filter_scenarios(
    scenarios_pathways: pd.DataFrame, target_scenario: str, baseline_scenario: str
) -> pd.DataFrame:
    scenarios_pathways_filtered = scenarios_pathways.loc[
        scenarios_pathways.scenario.isin([target_scenario, baseline_scenario]), :
    ]

    scenarios_pathways_filtered.loc[:, "scenario_pathway"] = (
        scenarios_pathways_filtered.loc[:, "scenario_pathway"].astype(float)
    )

    scenarios_pathways_filtered = scenarios_pathways_filtered.rename(
        columns={"scenario_year": "year"}
    )
    return scenarios_pathways_filtered


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
