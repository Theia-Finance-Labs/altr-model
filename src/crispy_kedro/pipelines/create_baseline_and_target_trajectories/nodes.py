"""
This is a boilerplate pipeline 'create_baseline_and_target_trajectories'
generated using Kedro 0.19.12
"""

import pandas as pd
import numpy as np
from typing import Tuple, cast


def calculate_tmsr(
    scenarios_pathways: pd.DataFrame,
) -> pd.DataFrame:
    """Calculate Technology Market Share Rate (TMSR) for scenarios."""
    # Sort the DataFrame by year so that the first value in each group is the earliest year
    scenarios_fair_share = scenarios_pathways.sort_values("year")

    # Compute the first scenario_pathway value for each group
    # This ensures we capture the value after sorting by year
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
    scenarios_pathways: pd.DataFrame, assets_forecasts: pd.DataFrame
) -> pd.DataFrame:
    """Compute scenario trajectories by merging pathways with company forecasts."""
    companies_activity_first_year = (
        assets_forecasts.sort_values("year")
        .groupby(
            ["company_id", "asset_id", "scenario_geography", "sector", "technology"],
            as_index=False,
        )
        .first()[
            [
                "company_id",
                "asset_id",
                "scenario_geography",
                "sector",
                "technology",
                "year",
                "asset_activity",
            ]
        ]
        .rename(
            {
                "asset_activity": "initial_asset_activity",
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
        "initial_asset_activity"
    ] * (1 + scenarios_trajectories["tmsr"])

    scenarios_trajectories = scenarios_trajectories.sort_values(
        by=["scenario", "company_id", "asset_id", "sector", "technology", "year"]
    )

    # Compute the lagged production scenario
    scenarios_trajectories["activity_change_scenario"] = scenarios_trajectories.groupby(
        [
            "company_id",
            "asset_id",
            "scenario",
            "scenario_geography",
            "sector",
            "technology",
        ]
    )["scenario_activity"].transform(lambda x: x - x.shift(1))

    scenarios_trajectories["scenario_activity_change"] = scenarios_trajectories[
        "activity_change_scenario"
    ].fillna(0)

    scenarios_trajectories = scenarios_trajectories[
        [
            "company_id",
            "asset_id",
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

    def pivot_scenarios_trajectories(
        scenarios_trajectories: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Pivot scenarios trajectories from long to wide format in a single elegant operation.
        Converts baseline and target scenario types into separate columns.
        """

        # Define index columns and values to pivot
        index_cols = [
            "company_id",
            "asset_id",
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

    # First pivot the scenarios trajectories
    pivoted_scenarios = pivot_scenarios_trajectories(
        cast(pd.DataFrame, scenarios_trajectories)
    )

    return pivoted_scenarios


def create_assets_trajectories(
    assets_forecasts: pd.DataFrame, scenarios_trajectories: pd.DataFrame
) -> pd.DataFrame:
    """
    Compute asset trajectories by merging with pivoted scenarios trajectories.
    Uses clean year-based logic for baseline projection starting point.
    """

    # Merge with assets forecasts
    assets_trajectories = scenarios_trajectories.merge(
        assets_forecasts,
        on=[
            "company_id",
            "asset_id",
            "scenario_geography",
            "sector",
            "technology",
            "year",
        ],
        how="left",
    )

    # Define groupby columns
    group_cols = [
        "company_id",
        "asset_id",
        "scenario_geography",
        "sector",
        "technology",
    ]
    # Sort to ensure proper ordering and forward fill only company name
    assets_trajectories = assets_trajectories.sort_values(group_cols + ["year"])
    assets_trajectories[
        [
            "company_name",
            "asset_name",
            "capacity_factor",
            "emission_factor",
            "ownership_level",
            "latitude",
            "longitude",
            "country_iso2",
            "country_name",
        ]
    ] = assets_trajectories[
        [
            "company_name",
            "asset_name",
            "capacity_factor",
            "emission_factor",
            "ownership_level",
            "latitude",
            "longitude",
            "country_iso2",
            "country_name",
        ]
    ].ffill()

    # TARGET TRAJECTORY: constrained cumsum approach (no extra raw columns)
    assets_trajectories["_asset_activity_filled"] = assets_trajectories.groupby(
        group_cols
    )["asset_activity"].transform("ffill")

    # Compute initial cumsum of target changes
    assets_trajectories["_target_cumsum"] = assets_trajectories.groupby(group_cols)[
        "scenario_activity_change_target"
    ].transform("cumsum")

    # Determine where trajectory would drop to or below zero
    _target_traj_unconstrained = (
        assets_trajectories["_asset_activity_filled"]
        + assets_trajectories["_target_cumsum"]
    )
    assets_trajectories["_temp_target_zero"] = (_target_traj_unconstrained <= 0).astype(
        int
    )
    assets_trajectories["_target_zero_reached"] = (
        assets_trajectories.groupby(group_cols)["_temp_target_zero"]
        .transform("cummax")
        .astype(bool)
    )

    # Apply zero‐floor constraint directly on the cumsum values
    assets_trajectories["_target_cumsum"] = np.where(
        assets_trajectories["_target_zero_reached"],
        -assets_trajectories[
            "_asset_activity_filled"
        ],  # ensures trajectory hits 0 exactly
        assets_trajectories["_target_cumsum"],
    )

    # Final target trajectory
    assets_trajectories["asset_trajectory_target"] = (
        assets_trajectories["_asset_activity_filled"]
        + assets_trajectories["_target_cumsum"]
    )

    # BASELINE TRAJECTORY: preserve original data, project only after it ends
    # Find last year with valid asset_activity for each group
    assets_trajectories["_last_valid_year"] = (
        assets_trajectories.groupby(group_cols)
        .apply(
            lambda group: (
                group.loc[group["asset_activity"].notna(), "year"].max()
                if group["asset_activity"].notna().any()
                else None
            )
        )
        .reindex(assets_trajectories.set_index(group_cols).index)
        .values
    )

    # Create mask for years after the last valid data year
    assets_trajectories["_is_projection_period"] = (
        assets_trajectories["year"] > assets_trajectories["_last_valid_year"]
    ).fillna(False)

    # Prepare masked baseline changes (only during projection period)
    assets_trajectories["_baseline_changes_masked"] = assets_trajectories[
        "scenario_activity_change_baseline"
    ].where(assets_trajectories["_is_projection_period"], 0)

    # Get last valid value for projection
    assets_trajectories["_last_valid_value"] = assets_trajectories.groupby(group_cols)[
        "asset_activity"
    ].transform(lambda x: x.dropna().iloc[-1] if x.notna().any() else np.nan)

    # Compute baseline constrained cumsum (no extra raw column)
    assets_trajectories["_baseline_cumsum"] = assets_trajectories.groupby(group_cols)[
        "_baseline_changes_masked"
    ].transform("cumsum")

    _baseline_traj_unconstrained = (
        assets_trajectories["_last_valid_value"]
        + assets_trajectories["_baseline_cumsum"]
    )
    assets_trajectories["_temp_baseline_zero"] = (
        _baseline_traj_unconstrained <= 0
    ).astype(int)
    assets_trajectories["_baseline_zero_reached"] = (
        assets_trajectories.groupby(group_cols)["_temp_baseline_zero"]
        .transform("cummax")
        .astype(bool)
    )

    assets_trajectories["_baseline_cumsum"] = np.where(
        assets_trajectories["_baseline_zero_reached"],
        -assets_trajectories["_last_valid_value"],  # clamp so trajectory exactly 0
        assets_trajectories["_baseline_cumsum"],
    )

    # Combine original data with constrained projections
    assets_trajectories["asset_trajectory_baseline"] = np.where(
        assets_trajectories["_is_projection_period"],
        assets_trajectories["_last_valid_value"]
        + assets_trajectories["_baseline_cumsum"],
        assets_trajectories["asset_activity"],
    )

    # Clean up temporary columns
    temp_cols = [
        "_asset_activity_filled",
        # "_target_cumsum",
        "_temp_target_zero",
        "_target_zero_reached",
        "_last_valid_year",
        "_is_projection_period",
        "_baseline_changes_masked",
        # "_baseline_cumsum",
        "_temp_baseline_zero",
        "_baseline_zero_reached",
        "_last_valid_value",
    ]
    assets_trajectories = assets_trajectories.drop(columns=temp_cols)

    return assets_trajectories


def fill_missing_years_incrementally(
    assets_trajectories: pd.DataFrame,
) -> pd.DataFrame:
    """Fill missing asset_age values incrementally per asset over time.

    For each asset group, starting from the last known (non-null) asset_age,
    fill forward such that age increases by the difference in years from that
    last known year. Rows before the first known age remain unchanged.
    """

    if assets_trajectories.empty or "asset_age" not in assets_trajectories.columns:
        return assets_trajectories

    df = assets_trajectories.copy()

    group_cols = [
        "company_id",
        "asset_id",
        "scenario_geography",
        "sector",
        "technology",
    ]

    # Ensure required columns exist before grouping
    missing_cols = [c for c in group_cols + ["year"] if c not in df.columns]
    if missing_cols:
        # If structure is unexpected, return unchanged
        return assets_trajectories

    # Sort for stable forward-filling
    df = df.sort_values(group_cols + ["year"])  # type: ignore[arg-type]

    # Numeric year for delta computations
    year_numeric = pd.to_numeric(df["year"], errors="coerce")

    # Track the last known year where age is present, and last known age itself
    df["_base_year"] = df["year"].where(df["asset_age"].notna())
    df["_base_year"] = df.groupby(group_cols)["_base_year"].ffill()

    df["_base_age"] = df.groupby(group_cols)["asset_age"].ffill()

    # Compute inferred ages only where original is missing AND we have a base
    inferred_age = df["_base_age"] + (
        year_numeric - pd.to_numeric(df["_base_year"], errors="coerce")
    )

    df["asset_age"] = np.where(
        df["asset_age"].notna() | df["_base_year"].isna(),
        df["asset_age"],
        inferred_age,
    )

    # Cleanup temp columns
    df = df.drop(columns=["_base_year", "_base_age"])  # type: ignore[arg-type]

    return df


def aggregate_assets_to_company_level(
    assets_trajectories: pd.DataFrame,
) -> pd.DataFrame:
    """Aggregate asset-level data to company level by calculating total activity."""

    companies_trajectories = (
        assets_trajectories.groupby(
            [
                "company_id",
                "company_name",
                "scenario_geography",
                "sector",
                "technology",
                "year",
            ]
        )
        .agg(
            {
                "asset_activity": lambda x: x.sum() if not pd.isna(x).all() else np.nan,
                "asset_trajectory_target": "sum",
                "asset_trajectory_baseline": "sum",
            }
        )
        .rename(
            {
                "asset_activity": "company_activity",
                "asset_trajectory_target": "company_trajectory_target",
                "asset_trajectory_baseline": "company_trajectory_baseline",
            },
            axis=1,
        )
        .reset_index()
    )

    return companies_trajectories
