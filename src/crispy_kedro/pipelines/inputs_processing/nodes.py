"""
This is a boilerplate pipeline 'inputs_processing'
generated using Kedro 0.19.12
"""

import pandas as pd
from typing import List, Tuple
import numpy as np


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

    filtered_assets_forecasts = filtered_assets_forecasts.reset_index(drop=True)

    assert (
        len(
            filtered_assets_forecasts.groupby(["asset_id", "technology"])[
                "production_year"
            ]
            .transform("min")
            .unique()
        )
        == 1
    ), "First production_year should be the same for all assets and technologies"

    filtered_assets_forecasts = filtered_assets_forecasts.rename(
        {"production_year": "year"}, axis=1
    )
    filtered_assets_forecasts.loc[:, "capacity"] = filtered_assets_forecasts.loc[
        :, "capacity"
    ].astype(float)

    return filtered_assets_forecasts


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
    tech_first_last = sorted_by_year.groupby("technology")["scenario_pathway"].agg(
        first="first", last="last"
    )
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
        10, 20, size=len(unique_combinations)
    )

    return unique_combinations


def determine_assets_retirement_dates(
    assets_forecasts: pd.DataFrame,
    lifetime_per_technology: pd.DataFrame,
) -> pd.DataFrame:

    assets_retirement_dates = pd.merge(
        assets_forecasts,
        lifetime_per_technology,
        on=["sector", "technology"],
        how="left",
    )

    assets_retirement_dates = assets_retirement_dates[
        (
            assets_retirement_dates["asset_age"]
            <= assets_retirement_dates["lifetime_years"]
        )
        & (
            assets_retirement_dates["asset_age"]
            >= assets_retirement_dates["lifetime_years"]
        )
    ]

    assert assets_retirement_dates.shape[0] == len(
        assets_retirement_dates[
            ["asset_id", "company_id", "technology"]
        ].drop_duplicates()
    )

    assets_retirement_dates = assets_retirement_dates.loc[
        :, ["asset_id", "company_id", "sector", "technology", "year", "capacity"]
    ].rename(columns={"year": "retirement_year"})

    return assets_retirement_dates
