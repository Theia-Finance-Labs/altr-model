"""
This is a boilerplate pipeline 'create_baseline_and_target_trajectories'
generated using Kedro 0.19.12
"""

import pandas as pd


def assign_scenario_geographies_to_assets(
    assets_data: pd.DataFrame, scenarios_data: pd.DataFrame
) -> pd.DataFrame:
    geographies_to_countries_mapping = (
        scenarios_data[["scenario_geography", "country_iso2_list"]]
        .drop_duplicates()
        .assign(country_iso2_list=lambda x: x.country_iso2_list.str.split(","))
        .explode("country_iso2_list")
        .rename(columns={"country_iso2_list": "country_iso2"})
    )

    assets_data_with_scenario_geographies = assets_data.merge(
        geographies_to_countries_mapping,
        on="country_iso2",
        how="left",
    )

    assert (
        assets_data_with_scenario_geographies["scenario_geography"].isna().sum() == 0
    ), "Some assets are not assigned to a scenario geography"

    return assets_data_with_scenario_geographies


def aggregate_assets_to_company_level(assets_data: pd.DataFrame) -> pd.DataFrame:

    assets_data["asset_activity"] = (
        assets_data["capacity"] * assets_data["capacity_factor"]
    )

    assets_data_aggregated = (
        assets_data.groupby(
            [
                "company_id",
                "company_name",
                "scenario_geography",
                "sector",
                "technology",
                "year",
            ]
        )
        .agg({"asset_activity": "sum"})
        .reset_index()
    )

    assets_data_aggregated["asset_activity"] = assets_data_aggregated[
        "asset_activity"
    ].astype(float)

    return assets_data_aggregated


def calculate_tmsr(
    scenarios_data: pd.DataFrame,
) -> pd.DataFrame:

    # Sort the DataFrame by scenario_year so that the first value in each group is the earliest year
    scenarios_fair_share = scenarios_data.sort_values("scenario_year").rename(
        columns={"scenario_year": "year"}
    )

    # Compute the first scenario_pathway value for each group
    # This ensures we capture the value after sorting by scenario_year
    scenarios_fair_share["first_pathway"] = scenarios_fair_share.groupby(
        ["scenario", "sector", "scenario_geography", "technology"]
    )["scenario_pathway"].transform("first")

    # Calculate tmsr = (scenario_pathway - first_pathway) / first_pathway
    scenarios_fair_share["tmsr"] = (
        scenarios_fair_share["scenario_pathway"] - scenarios_fair_share["first_pathway"]
    ) / scenarios_fair_share["first_pathway"]

    # Replace NaN values (which may appear if first_pathway was zero) with 0
    scenarios_fair_share["tmsr"] = scenarios_fair_share["tmsr"].fillna(0)

    # Drop the helper column if it's no longer needed
    scenarios_fair_share = scenarios_fair_share.drop(columns="first_pathway")

    return scenarios_fair_share


def compute_scenarios_trajectories(
    scenarios_data: pd.DataFrame, assets_data: pd.DataFrame
):

    asset_activity_first_year = (
        assets_data.sort_values("year")
        .groupby(
            ["company_id", "scenario_geography", "sector", "technology"], as_index=False
        )
        .first()[
            [
                "company_id",
                "scenario_geography",
                "sector",
                "technology",
                "asset_activity",
            ]
        ]
        .rename({"asset_activity": "initial_technology_production"}, axis=1)
    )

    scenarios_data = scenarios_data.merge(
        asset_activity_first_year, on=["sector", "technology", "scenario_geography"]
    )

    # Apply TMSR/SMSP scenario targets
    scenarios_data["scenario_activity"] = scenarios_data[
        "initial_technology_production"
    ] * (1 + scenarios_data["tmsr"])

    scenarios_data["production"] = (
        scenarios_data["production"] * scenarios_data["fair_share_perc"]
    )
    return


def compute_assets_trajectories(
    assets_data: pd.DataFrame, scenarios_trajectories: pd.DataFrame
):
    assets_data = assets_data.merge(
        scenarios_trajectories,
        on=["company_id", "company_name", "sector", "technology", "year"],
    )

    assets_data["production"] = (
        assets_data["production"] * assets_data["fair_share_perc"]
    )
    return
