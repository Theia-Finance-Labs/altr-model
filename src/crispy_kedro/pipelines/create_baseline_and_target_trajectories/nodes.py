"""
This is a boilerplate pipeline 'create_baseline_and_target_trajectories'
generated using Kedro 0.19.12
"""

import pandas as pd
import numpy as np


def assign_scenario_geographies_to_assets(
    assets_forecasts: pd.DataFrame, scenarios_pathways: pd.DataFrame
) -> pd.DataFrame:
    geographies_to_countries_mapping = (
        scenarios_pathways[["scenario_geography", "country_iso2_list"]]
        .drop_duplicates()
        .assign(country_iso2_list=lambda x: x.country_iso2_list.str.split(","))
        .explode("country_iso2_list")
        .rename(columns={"country_iso2_list": "country_iso2"})
    )

    assets_forecasts_with_scenario_geographies = assets_forecasts.merge(
        geographies_to_countries_mapping,
        on="country_iso2",
        how="left",
    )

    assert (
        assets_forecasts_with_scenario_geographies["scenario_geography"].isna().sum()
        == 0
    ), "Some assets are not assigned to a scenario geography"

    return assets_forecasts_with_scenario_geographies


def aggregate_assets_to_company_level(assets_forecasts: pd.DataFrame) -> pd.DataFrame:

    assets_forecasts["asset_activity"] = (
        assets_forecasts["capacity"] * assets_forecasts["capacity_factor"]
    )

    companies_forecasts = (
        assets_forecasts.groupby(
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
        .rename({"asset_activity": "company_activity"}, axis=1)
        .reset_index()
    )

    return companies_forecasts


def calculate_tmsr(
    scenarios_pathways: pd.DataFrame,
) -> pd.DataFrame:

    # Sort the DataFrame by scenario_year so that the first value in each group is the earliest year
    scenarios_fair_share = scenarios_pathways.sort_values("scenario_year").rename(
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
    scenarios_pathways: pd.DataFrame, companies_forecasts: pd.DataFrame
):

    companies_activity_first_year = (
        companies_forecasts.sort_values("year")
        .groupby(
            ["company_id", "scenario_geography", "sector", "technology"], as_index=False
        )
        .first()[
            [
                "company_id",
                "scenario_geography",
                "sector",
                "technology",
                "year",
                "company_activity",
            ]
        ]
        .rename(
            {
                "company_activity": "initial_company_activity",
                "year": "first_year_of_activity",
            },
            axis=1,
        )
    )

    scenarios_trajectories = scenarios_pathways.merge(
        companies_activity_first_year, on=["sector", "technology", "scenario_geography"]
    )

    # Apply TMSR/SMSP scenario targets
    scenarios_trajectories["scenario_activity"] = scenarios_trajectories[
        "initial_company_activity"
    ] * (1 + scenarios_trajectories["tmsr"])

    scenarios_trajectories = scenarios_trajectories.sort_values(
        by=["scenario", "company_id", "sector", "technology", "year"]
    )

    # Compute the lagged production scenario
    scenarios_trajectories["activity_change_scenario"] = scenarios_trajectories.groupby(
        ["scenario", "scenario_geography", "sector", "technology"]
    )["scenario_activity"].transform(lambda x: x - x.shift(1))

    scenarios_trajectories["scenario_activity_change"] = scenarios_trajectories[
        "activity_change_scenario"
    ].fillna(0)

    scenarios_trajectories = scenarios_trajectories[
        [
            "company_id",
            "scenario",
            "scenario_type",
            "scenario_geography",
            "sector",
            "technology",
            "year",
            "scenario_price",
            "scenario_capacity_factor",
            "scenario_activity",
            "scenario_activity_change",
        ]
    ]

    # First pivot the scenarios trajectories
    pivoted_scenarios = pivot_scenarios_trajectories(scenarios_trajectories)

    return pivoted_scenarios


def pivot_scenarios_trajectories(scenarios_trajectories):
    """
    Pivot scenarios trajectories from long to wide format in a single elegant operation.
    Converts baseline and target scenario types into separate columns.
    """

    # Define index columns and values to pivot
    index_cols = [
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
        "year",
    ]

    values_to_pivot = [
        "scenario_price",
        "scenario_capacity_factor",
        "scenario_activity",
        "scenario_activity_change",
    ]

    # Single pivot operation for both baseline and target
    pivoted_scenarios = scenarios_trajectories.pivot_table(
        index=index_cols,
        columns="scenario_type",
        values=values_to_pivot,
        aggfunc="first",
    )

    # Flatten MultiIndex columns elegantly
    pivoted_scenarios.columns = [
        f"{value}_{scenario_type}"
        for value, scenario_type in pivoted_scenarios.columns.values
    ]

    # Reset index to get regular DataFrame
    pivoted_scenarios = pivoted_scenarios.reset_index()

    return pivoted_scenarios


def compute_companies_trajectories(
    companies_forecasts: pd.DataFrame, scenarios_trajectories: pd.DataFrame
) -> pd.DataFrame:
    """
    Compute asset trajectories by merging with pivoted scenarios trajectories.
    Uses clean year-based logic for baseline projection starting point.
    """

    # Merge with assets forecasts
    companies_trajectories = scenarios_trajectories.merge(
        companies_forecasts.drop(columns=["company_name"]),
        on=["company_id", "scenario_geography", "sector", "technology", "year"],
        how="left",
    )

    # Define groupby columns
    group_cols = ["company_id", "scenario_geography", "sector", "technology"]

    # Sort to ensure proper ordering
    companies_trajectories = companies_trajectories.sort_values(group_cols + ["year"])

    # TARGET TRAJECTORY: straightforward approach
    # Forward fill company_activity and apply cumsum
    companies_trajectories["_company_activity_filled"] = companies_trajectories.groupby(
        group_cols
    )["company_activity"].transform("ffill")
    companies_trajectories["_target_cumsum"] = companies_trajectories.groupby(
        group_cols
    )["scenario_activity_change_target"].transform("cumsum")
    companies_trajectories["company_trajectory_target"] = (
        companies_trajectories["_company_activity_filled"]
        + companies_trajectories["_target_cumsum"]
    )

    # BASELINE TRAJECTORY: preserve original data, project only after it ends
    # Find last year with valid company_activity for each group
    companies_trajectories["_last_valid_year"] = (
        companies_trajectories.groupby(group_cols)
        .apply(
            lambda group: (
                group.loc[group["company_activity"].notna(), "year"].max()
                if group["company_activity"].notna().any()
                else None
            )
        )
        .reindex(companies_trajectories.set_index(group_cols).index)
        .values
    )

    # Create mask for years after the last valid data year
    companies_trajectories["_is_projection_period"] = (
        companies_trajectories["year"] > companies_trajectories["_last_valid_year"]
    ).fillna(False)

    # Compute cumsum only for projection period, starting fresh for each group
    companies_trajectories["_baseline_changes_masked"] = companies_trajectories[
        "scenario_activity_change_baseline"
    ].where(companies_trajectories["_is_projection_period"], 0)
    companies_trajectories["_baseline_cumsum"] = companies_trajectories.groupby(
        group_cols
    )["_baseline_changes_masked"].transform("cumsum")

    # Get last valid value for projection
    companies_trajectories["_last_valid_value"] = companies_trajectories.groupby(
        group_cols
    )["company_activity"].transform(
        lambda x: x.dropna().iloc[-1] if x.notna().any() else np.nan
    )

    # Build baseline trajectory: original where available, projected where not
    companies_trajectories["company_trajectory_baseline"] = np.where(
        companies_trajectories["_is_projection_period"],
        companies_trajectories["_last_valid_value"]
        + companies_trajectories["_baseline_cumsum"],
        companies_trajectories["company_activity"],
    )

    # Clean up temporary columns
    temp_cols = [
        "_company_activity_filled",
        "_target_cumsum",
        "_last_valid_year",
        "_is_projection_period",
        "_baseline_changes_masked",
        "_baseline_cumsum",
        "_last_valid_value",
    ]
    companies_trajectories = companies_trajectories.drop(columns=temp_cols)

    return companies_trajectories
