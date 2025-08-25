"""
This is a boilerplate pipeline 'inputs_postproc'
generated using Kedro 0.19.12
"""

import pandas as pd
import numpy as np


def apply_reduce_granularity_from_asset_to_company_level(
    assets_forecasts: pd.DataFrame,
    reduce_granularity_from_asset_to_company_level: bool,
) -> pd.DataFrame:
    if reduce_granularity_from_asset_to_company_level:
        companies_forecasts = (
            assets_forecasts.groupby(
                [
                    "company_id",
                    "company_name",
                    "scenario_geography",
                    "sector",
                    "technology",
                    "year",
                    "ownership_level",
                    "capacity_unit",
                ],
            )
            .agg(
                asset_age=("asset_age", "mean"),
                age_is_inferred=("age_is_inferred", "first"),
                ownership_percentage=("ownership_percentage", "mean"),
                workforce_size=("workforce_size", "sum"),
                asset_activity=("asset_activity", "sum"),
                capacity_factor=("capacity_factor", "sum"),
                emission_factor=("emission_factor", "sum"),
            )
            .reset_index()
        )

        companies_forecasts["asset_id"] = "unique_asset_" + companies_forecasts[
            "company_id"
        ].astype(str)
        companies_forecasts["asset_name"] = "unique_asset_" + companies_forecasts[
            "company_name"
        ].astype(str)
        companies_forecasts[
            ["country_iso2", "country_name", "latitude", "longitude"]
        ] = np.nan

        return companies_forecasts
    else:
        return assets_forecasts


def determine_assets_retirement_dates(
    allocated_assets_to_companies: pd.DataFrame,
    lifetime_per_technology: pd.DataFrame,
) -> pd.DataFrame:
    extended_assets = allocated_assets_to_companies.copy()
    # Sort by asset and year to ensure proper ordering
    extended_assets = extended_assets.sort_values(
        ["company_id", "asset_id", "scenario_geography", "technology", "year"]
    )

    # Get the maximum forecast year for each asset
    last_forecast_year = (
        allocated_assets_to_companies.dropna(subset=["asset_activity"])
        .year.round(0)
        .max()
        .astype(int)
    )

    # Merge with lifetime data
    extended_assets = pd.merge(
        extended_assets,
        lifetime_per_technology,
        on=["sector", "technology"],
        how="left",
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
        ],
    ]

    return assets_retirement_dates


def extend_allocated_assets_to_companies(
    allocated_assets_to_companies: pd.DataFrame,
    scenarios_pathways: pd.DataFrame,
) -> pd.DataFrame:

    group_cols = [
        "company_id",
        "asset_id",
        "scenario_geography",
        "sector",
        "technology",
    ]
    scenario_end_year = scenarios_pathways.year.max().astype(int)

    # Get the last row for each asset (latest forecast year)
    last_forecast_rows = (
        allocated_assets_to_companies.sort_values("year")
        .groupby(
            group_cols,
            as_index=False,
        )
        .last()
    )

    # Create extended years for each group from its own last forecast year + 1 to scenario end year
    # Filter out rows where last year >= scenario end year
    last_forecast_rows = last_forecast_rows[
        last_forecast_rows["year"].round(0).astype(int) < scenario_end_year
    ].copy()

    if last_forecast_rows.empty:
        extended_rows = []
    else:
        # Create a list of years for each row
        last_forecast_rows["last_year"] = (
            last_forecast_rows["year"].round(0).astype(int)
        )
        last_forecast_rows["years_to_extend"] = last_forecast_rows["last_year"].apply(
            lambda x: list(range(x + 1, scenario_end_year + 1))
        )

        # Explode to create one row per extended year
        extended_data = last_forecast_rows.explode("years_to_extend").copy()
        extended_data = extended_data.dropna(subset=["years_to_extend"])

        if not extended_data.empty:
            # Calculate new year and asset_age
            extended_data["year"] = extended_data["years_to_extend"].astype(int)
            extended_data["asset_age"] = extended_data["asset_age"] + (
                extended_data["year"] - extended_data["last_year"]
            )

            # Keep only the required columns
            extended_rows = [extended_data[group_cols + ["year", "asset_age"]]]
        else:
            extended_rows = []

    if extended_rows:
        extended_years = pd.concat(extended_rows, ignore_index=True)
        # Combine original forecasts with extended years (other columns intentionally left as NaN)
        extended_assets = pd.concat(
            [allocated_assets_to_companies, extended_years], ignore_index=True
        )
    else:
        extended_assets = allocated_assets_to_companies.copy()

    # Sort to ensure proper ordering and forward fill only selected columns
    extended_assets = extended_assets.sort_values(group_cols + ["year"])
    extended_assets[
        [
            "company_name",
            "asset_name",
            "capacity_factor",
            "emission_factor",
            # "ownership_level",
            "latitude",
            "longitude",
            "country_iso2",
            "country_name",
        ]
    ] = extended_assets[
        [
            "company_name",
            "asset_name",
            "capacity_factor",
            "emission_factor",
            # "ownership_level",
            "latitude",
            "longitude",
            "country_iso2",
            "country_name",
        ]
    ].ffill()

    return extended_assets
