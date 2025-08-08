"""
This is a boilerplate pipeline 'inputs_processing'
generated using Kedro 0.19.12
"""

import pandas as pd
from typing import List, Tuple
import numpy as np


def check_input_parameters(
    shock_year: int,
    alignment_year: int,
) -> None:
    if alignment_year < shock_year:
        raise ValueError("Alignment year must be greater than shock year")


def filter_scenarios(
    scenarios_pathways: pd.DataFrame, target_scenario: str, baseline_scenario: str
) -> pd.DataFrame:

    scenarios_pathways_filtered = scenarios_pathways.loc[
        scenarios_pathways.scenario.isin([target_scenario, baseline_scenario]), :
    ].reset_index(drop=True)

    scenarios_pathways_filtered = scenarios_pathways_filtered.reset_index(drop=True)

    scenarios_pathways_filtered.loc[:, "scenario_pathway"] = (
        scenarios_pathways_filtered.loc[:, "scenario_pathway"].astype(float)
    )

    scenarios_pathways_filtered = scenarios_pathways_filtered.rename(
        columns={"scenario_year": "year"}
    )
    return scenarios_pathways_filtered


def filter_companies(
    companies_ownership_tree: pd.DataFrame, company_ids: List[str]
) -> pd.DataFrame:

    # TODO : remove with logic to handle multi-level ownerships,
    # and/or fix in the data when owner=parent ie 1 company id matches 2 owewrnships levels
    companies_owners = companies_ownership_tree[
        companies_ownership_tree["ownership_level"] == 1
    ]

    if company_ids:
        filtered_companies_ownership_tree = companies_owners.loc[
            companies_owners.company_id.isin(company_ids), :
        ].reset_index(drop=True)
    else:
        filtered_companies_ownership_tree = companies_owners

    return filtered_companies_ownership_tree


def filter_assets(
    assets_forecasts: pd.DataFrame,
    companies_ownership_tree: pd.DataFrame,
    scenarios_pathways: pd.DataFrame,
    max_forecast_horizon: int,
) -> pd.DataFrame:
    owned_assets = companies_ownership_tree["asset_id"].unique().tolist()
    filtered_assets_forecasts = assets_forecasts.loc[
        assets_forecasts["asset_id"].isin(owned_assets), :
    ]

    scenario_start_year = scenarios_pathways.year.min()
    forecast_end_year = scenario_start_year + max_forecast_horizon

    filtered_assets_forecasts = filtered_assets_forecasts.loc[
        (scenario_start_year <= filtered_assets_forecasts.production_year)
        & (filtered_assets_forecasts.production_year <= forecast_end_year),
        :,
    ]

    # Check if we have any assets after filtering
    if filtered_assets_forecasts.empty:
        raise ValueError("No assets remaining after filtering by year range and company ownership")

    filtered_assets_forecasts = filtered_assets_forecasts.rename(
        {"production_year": "year"}, axis=1
    )
    filtered_assets_forecasts.loc[:, "capacity"] = filtered_assets_forecasts.loc[
        :, "capacity"
    ].astype(float)

    return filtered_assets_forecasts


def assign_scenario_geographies_to_assets(
    assets_forecasts: pd.DataFrame, scenarios_pathways: pd.DataFrame
) -> pd.DataFrame:
    """Assign scenario geographies to assets based on country mapping."""
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

    # Check if there are unassigned assets and a global geography exists
    unassigned_mask = assets_forecasts_with_scenario_geographies[
        "scenario_geography"
    ].isna()

    if unassigned_mask.sum() > 0:
        # Look for a global geography (one with NaN/null country_iso2)
        global_geographies = geographies_to_countries_mapping[
            geographies_to_countries_mapping["country_iso2"].isna()
        ]["scenario_geography"].unique()

        if len(global_geographies) > 0:
            # Use the first global geography found (typically "Global")
            global_geography = global_geographies[0]
            print(
                f"Assigning {unassigned_mask.sum()} unassigned assets to global geography: {global_geography}"
            )

            # Assign unassigned assets to the global geography
            assets_forecasts_with_scenario_geographies.loc[
                unassigned_mask, "scenario_geography"
            ] = global_geography

    assert (
        assets_forecasts_with_scenario_geographies["scenario_geography"].isna().sum()
        == 0
    ), "Some assets are not assigned to a scenario geography"

    return assets_forecasts_with_scenario_geographies


def allocate_assets_to_companies(
    assets_forecasts: pd.DataFrame,
    companies_ownership_tree: pd.DataFrame,
) -> pd.DataFrame:
    """
    Allocate asset capacities to companies based on ownership percentages.

    This function joins assets with company ownership data and calculates
    the owned asset capacity based on ownership percentages.

    Args:
        assets_data: DataFrame with asset information and capacities
        companies_ownership: DataFrame with company ownership information

    Returns:
        DataFrame with allocated asset capacities to companies
    """

    # Prepare assets data - rename production_year to year for joining
    assets_prepared = assets_forecasts.copy()

    # Prepare companies data - ensure we have the right column names
    companies_prepared = companies_ownership_tree.copy()

    # Merge assets with ownership data on asset_id, sector, technology, and year
    merged_data = pd.merge(
        assets_prepared,
        companies_prepared,
        on=["asset_id", "sector", "technology", "year"],
        how="inner",
    )

    # Calculate owned asset capacity (allocated capacity based on ownership percentage)
    merged_data["capacity"] = (
        merged_data["capacity"] * merged_data["ownership_percentage"]
    )

    return merged_data


def determine_increasing_or_decreasing_techs(
    scenarios_pathways: pd.DataFrame,
) -> pd.DataFrame:

    # 1) Compute which techs are “increasing” (low‑carbon) vs “decreasing”:
    target_only = scenarios_pathways.query("scenario_type == 'target'")
    sorted_by_year = target_only.sort_values("year")
    tech_first_last = sorted_by_year.groupby(["technology", "scenario_geography"])[
        "scenario_pathway"
    ].agg(first="first", last="last")
    tech_first_last.loc[:, "increasing"] = (
        tech_first_last["last"] > tech_first_last["first"]
    )

    tech_trend = tech_first_last.loc[:, ["increasing"]].reset_index()

    return tech_trend


def determine_lifetime_per_technology(
    scenarios_pathways: pd.DataFrame,
) -> pd.DataFrame:

    # TODO: remove to replace by the real scenarios data

    rng = np.random.RandomState(seed=42)

    unique_combinations = scenarios_pathways[["sector", "technology"]].drop_duplicates()
    unique_combinations["lifetime_years"] = rng.randint(
        20, 40, size=len(unique_combinations)
    )

    return unique_combinations


def determine_assets_retirement_dates(
    assets_forecasts: pd.DataFrame,
    lifetime_per_technology: pd.DataFrame,
    scenarios_pathways: pd.DataFrame,
) -> pd.DataFrame:

    scenario_end_year = scenarios_pathways.year.max().astype(int)

    # Get the maximum forecast year for each asset
    last_forecast_year = assets_forecasts.year.round(0).max().astype(int)

    # Merge with lifetime data
    assets_with_lifetime = pd.merge(
        assets_forecasts,
        lifetime_per_technology,
        on=["sector", "technology"],
        how="left",
    )

    # Get the last row for each asset (latest forecast year)
    last_forecast_rows = (
        assets_with_lifetime.sort_values("year")
        .groupby(
            ["company_id", "asset_id", "scenario_geography", "sector", "technology"],
            as_index=False,
        )
        .last()
    )

    # Create extended years for each asset from last forecast year + 1 to scenario end year
    extended_years = []
    for year in range(last_forecast_year + 1, scenario_end_year + 1):
        extended_year_data = last_forecast_rows.copy()
        extended_year_data["year"] = year
        # Increment asset age by the number of years past the last forecast
        extended_year_data["asset_age"] = extended_year_data["asset_age"] + (
            year - last_forecast_year
        )
        extended_years.append(extended_year_data)

    # Combine original forecasts with extended years
    extended_assets = pd.concat(
        [assets_with_lifetime] + extended_years, ignore_index=True
    )

    # Sort by asset and year to ensure proper ordering
    extended_assets = extended_assets.sort_values(
        ["company_id", "asset_id", "scenario_geography", "technology", "year"]
    )

    # Find retirement dates: when asset_age exceeds lifetime_years for the first time
    # and only consider years after the last forecast year
    retirement_candidates = extended_assets[
        (extended_assets["asset_age"] > extended_assets["lifetime_years"])
        & (extended_assets["year"] > last_forecast_year)
    ]

    # Get the first year each asset exceeds its lifetime (retirement year)
    assets_retirement_dates = (
        retirement_candidates.sort_values("year")
        .groupby(
            ["asset_id", "company_id", "scenario_geography", "sector", "technology"],
            as_index=False,
        )
        .first()
        .rename(columns={"year": "retirement_year"})
    )

    # Handle case where no assets retire after forecast period
    if assets_retirement_dates.empty:
        # Return empty DataFrame with expected columns
        return pd.DataFrame(
            columns=[
                "asset_id",
                "company_id",
                "scenario_geography",
                "sector",
                "technology",
                "retirement_year",
                "capacity",
            ]
        )

    # Select and rename columns - now keeping asset_id
    assets_retirement_dates = assets_retirement_dates.loc[
        :,
        [
            "asset_id",
            "company_id",
            "scenario_geography",
            "sector",
            "technology",
            "retirement_year",
            "capacity",
        ],
    ]

    return assets_retirement_dates
