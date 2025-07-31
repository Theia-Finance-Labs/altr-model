"""
This is a boilerplate pipeline 'inputs_processing'
generated using Kedro 0.19.12
"""

import pandas as pd
from typing import List, Tuple


def filter_scenarios(
    scenarios_pathways: pd.DataFrame, target_scenario: str, baseline_scenario: str
) -> pd.DataFrame:
    scenarios_pathways_filtered = scenarios_pathways.loc[
        scenarios_pathways.scenario.isin([target_scenario, baseline_scenario]), :
    ].reset_index(drop=True)

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
    if company_ids:
        filtered_companies_ownership_tree = companies_ownership_tree.loc[
            companies_ownership_tree.company_id.isin(company_ids), :
        ].reset_index(drop=True)
    else:
        filtered_companies_ownership_tree = companies_ownership_tree

    return filtered_companies_ownership_tree


def filter_assets(
    assets_forecasts: pd.DataFrame,
    companies_ownership_tree: pd.DataFrame,
) -> pd.DataFrame:
    owned_assets = companies_ownership_tree["asset_id"].unique().tolist()
    filtered_assets_forecasts = assets_forecasts.loc[
        assets_forecasts["asset_id"].isin(owned_assets), :
    ].reset_index(drop=True)

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


def allocate_assets_to_companies(
    assets_data: pd.DataFrame,
    companies_ownership: pd.DataFrame,
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
    assets_prepared = assets_data.rename(columns={"production_year": "year"})

    # Prepare companies data - ensure we have the right column names
    companies_prepared = companies_ownership.copy()

    # Handle technology column naming - companies data uses 'technology_category'
    if (
        "technology_category" in companies_prepared.columns
        and "technology" in assets_prepared.columns
    ):
        companies_prepared = companies_prepared.rename(
            columns={"technology_category": "technology"}
        )

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
