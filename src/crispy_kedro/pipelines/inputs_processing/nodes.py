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
    # Standardize scenario naming
    # TODO: remove after integration of scenario data in DBT
    scenarios_pathways["scenario"] = (
        "AR6_"
        + scenarios_pathways["scenario_provider"].astype(str).str.strip()
        + "_"
        + scenarios_pathways["scenario"].astype(str).str.strip()
    )

    assert (
        target_scenario
        in scenarios_pathways[
            scenarios_pathways["scenario_type"] == "target"
        ].scenario.unique()
    ), "Target scenario not found in scenarios pathways"
    assert (
        baseline_scenario
        in scenarios_pathways[
            scenarios_pathways["scenario_type"] == "baseline"
        ].scenario.unique()
    ), "Baseline scenario not found in scenarios pathways"

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
        raise ValueError(
            "No assets remaining after filtering by year range and company ownership"
        )

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
    """Assign scenario geographies to assets based on country mapping.

    If a country maps to multiple scenario geographies, pick the geography with the
    smallest number of countries (most granular). If there is a tie for smallest,
    raise an error listing the conflicting geographies and the asset+country pair(s).
    """
    # Build mapping of scenario geographies to individual countries
    geographies_to_countries_mapping = (
        scenarios_pathways[["scenario_geography", "country_iso2_list"]]
        .drop_duplicates()
        .assign(country_iso2_list=lambda x: x.country_iso2_list.str.split(","))
        .explode("country_iso2_list")
        .rename(columns={"country_iso2_list": "country_iso2"})
    )

    # Count how many countries each geography contains (NaNs are excluded from the count)
    geography_sizes = (
        geographies_to_countries_mapping.groupby("scenario_geography", as_index=False)[
            "country_iso2"
        ]
        .count()
        .rename(columns={"country_iso2": "geography_country_count"})
    )

    # Determine best (most granular) geography per asset+country pair
    asset_country_pairs = assets_forecasts[
        ["asset_id", "country_iso2"]
    ].drop_duplicates()

    asset_country_candidates = asset_country_pairs.merge(
        geographies_to_countries_mapping, on="country_iso2", how="left"
    ).merge(geography_sizes, on="scenario_geography", how="left")

    # For each asset+country, find the minimum country count among candidate geographies
    min_counts = asset_country_candidates.groupby(["asset_id", "country_iso2"])[
        "geography_country_count"
    ].transform("min")

    is_min = asset_country_candidates["geography_country_count"].eq(min_counts)

    # Detect ties: more than one candidate with the same minimum count for a given asset+country
    tie_counts = (
        asset_country_candidates[is_min]
        .groupby(["asset_id", "country_iso2"], as_index=False)
        .size()
        .rename(columns={"size": "num_min_candidates"})
    )

    ambiguous_pairs = tie_counts.query("num_min_candidates > 1")
    if not ambiguous_pairs.empty:
        conflict_messages = []
        for _, row in ambiguous_pairs.iterrows():
            aid = row["asset_id"]
            ctry = row["country_iso2"]
            candidates = asset_country_candidates[
                (asset_country_candidates["asset_id"] == aid)
                & (asset_country_candidates["country_iso2"] == ctry)
                & is_min
            ][["scenario_geography", "geography_country_count"]]
            candidates_list = candidates.apply(
                lambda r: f"{r['scenario_geography']} (n={int(r['geography_country_count'])})",
                axis=1,
            ).tolist()
            conflict_messages.append(
                f"asset_id={aid}, country={ctry}: conflicting geographies {candidates_list}"
            )
        conflict_text = "\n".join(conflict_messages)
        raise ValueError(
            "Ambiguous scenario geography assignment detected. "
            "Multiple geographies tie for most granular: \n" + conflict_text
        )

    # Select the unique most granular geography per asset+country
    selected_geographies = (
        asset_country_candidates[is_min]
        .drop_duplicates(["asset_id", "country_iso2"])  # ensure one per pair
        .loc[:, ["asset_id", "country_iso2", "scenario_geography"]]
    )

    # Merge the chosen geography back to all asset rows
    assets_with_geography = assets_forecasts.merge(
        selected_geographies, on=["asset_id", "country_iso2"], how="left"
    )

    # Fallback: Assign unassigned assets to a global geography (if defined with NaN country list)
    unassigned_mask = assets_with_geography["scenario_geography"].isna()

    if unassigned_mask.sum() > 0:
        global_geographies = geographies_to_countries_mapping[
            geographies_to_countries_mapping["country_iso2"].isna()
        ]["scenario_geography"].unique()

        if len(global_geographies) > 0:
            global_geography = global_geographies[0]
            print(
                f"Assigning {unassigned_mask.sum()} unassigned assets to global geography: {global_geography}"
            )
            assets_with_geography.loc[unassigned_mask, "scenario_geography"] = (
                global_geography
            )

    assert (
        assets_with_geography["scenario_geography"].isna().sum() == 0
    ), "Some assets are not assigned to a scenario geography"

    return assets_with_geography


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

    merged_data = merged_data.rename(columns={"capacity": "asset_activity"})

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

    unique_combinations = (
        scenarios_pathways.loc[
            scenarios_pathways["scenario_type"] == "target",
            ["sector", "technology", "lifetime_years"],
        ]
        .dropna(subset=["lifetime_years"])
        .groupby(["sector", "technology"])
        .agg({"lifetime_years": lambda x: np.ceil(x.mean()).astype(int)})
        .reset_index()
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
                "asset_activity",
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
            "asset_activity",
        ],
    ]

    return assets_retirement_dates


def interpolate_scenarios_annually(scenarios_pathways: pd.DataFrame) -> pd.DataFrame:
    """
    Interpolate scenario data to fill missing years with linear interpolation.

    This is a temporary fix to handle the fact that downloaded_scenarios.csv contains
    5-year interval data but the late_sudden trajectory algorithms expect annual data.

    Args:
        scenarios_pathways: DataFrame with scenario data (potentially sparse years)

    Returns:
        DataFrame with annually interpolated scenario data
    """

    # Main grouping columns for interpolation (keeping it simple)
    group_cols = [
        "scenario",
        "scenario_type",
        "scenario_geography",
        "sector",
        "technology",
    ]

    # Numeric columns that should be interpolated
    numeric_cols = [
        "scenario_price",
        "fuel_price",
        "scenario_pathway",
        "scenario_capacity_factor",
        "lifetime_years",
    ]
    existing_numeric_cols = [
        col for col in numeric_cols if col in scenarios_pathways.columns
    ]

    interpolated_scenarios = []

    # Group by main identifiers and interpolate within each group
    for group_key, group_df in scenarios_pathways.groupby(group_cols, dropna=False):
        group_df = group_df.sort_values("year").copy()

        # Get the year range for this group
        min_year = int(group_df["year"].min())
        max_year = int(group_df["year"].max())

        # Create annual year range
        annual_years = list(range(min_year, max_year + 1))

        # Create base template with first row's non-numeric values
        template_row = group_df.iloc[0].copy()

        # Create rows for each year
        annual_data = []
        for year in annual_years:
            row = template_row.copy()
            row["year"] = year
            annual_data.append(row)

        annual_df = pd.DataFrame(annual_data)

        # Merge with original data to get actual values where they exist
        merged_df = annual_df.merge(
            group_df[group_cols + ["year"] + existing_numeric_cols],
            on=group_cols + ["year"],
            how="left",
            suffixes=("", "_actual"),
        )

        # Replace interpolated numeric columns with actual values
        for col in existing_numeric_cols:
            actual_col = f"{col}_actual"
            if actual_col in merged_df.columns:
                merged_df[col] = merged_df[actual_col]
                merged_df.drop(columns=[actual_col], inplace=True)

        # Interpolate missing values
        for col in existing_numeric_cols:
            if col in merged_df.columns:
                merged_df[col] = pd.to_numeric(merged_df[col], errors="coerce")
                merged_df[col] = merged_df[col].interpolate(method="linear")

        interpolated_scenarios.append(merged_df)

    # Combine all groups
    if interpolated_scenarios:
        result = pd.concat(interpolated_scenarios, ignore_index=True)
        result["year"] = result["year"].astype(int)
        return result
    else:
        return scenarios_pathways  # Return original if no interpolation was possible
