"""Baseline and target company trajectory calculations."""

import logging
from typing import cast

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def aggregate_assets_to_company_level(assets_forecasts: pd.DataFrame) -> pd.DataFrame:
    """Aggregate asset-level data to company level by calculating total activity."""

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
    scenarios_pathways: pd.DataFrame, companies_forecasts: pd.DataFrame
) -> pd.DataFrame:
    """Compute scenario trajectories by merging pathways with company forecasts."""

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

    logger.info(f"After merge with companies data: {scenarios_trajectories.shape} rows")

    # Apply TMSR/SMSP scenario targets
    scenarios_trajectories["scenario_activity"] = scenarios_trajectories[
        "initial_company_activity"
    ] * (1 + scenarios_trajectories["tmsr"])

    scenarios_trajectories = scenarios_trajectories.sort_values(
        by=["scenario", "company_id", "sector", "technology", "year"]
    )

    # Compute the lagged production scenario
    scenarios_trajectories["activity_change_scenario"] = scenarios_trajectories.groupby(
        ["company_id", "scenario", "scenario_geography", "sector", "technology"]
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

    logger.info(f"Pivoted scenarios shape: {pivoted_scenarios.shape}")
    activity_change_cols = [
        col for col in pivoted_scenarios.columns if "scenario_activity_change" in col
    ]
    logger.info(f"Activity change columns created: {activity_change_cols}")

    return pivoted_scenarios


def create_companies_trajectories(
    companies_forecasts: pd.DataFrame, scenarios_trajectories: pd.DataFrame
) -> pd.DataFrame:
    """
    Compute asset trajectories by merging with pivoted scenarios trajectories.
    Uses clean year-based logic for baseline projection starting point.
    """

    logger.info(
        f"Creating companies trajectories from {scenarios_trajectories.shape[0]} scenario rows"
    )

    # Merge with assets forecasts
    companies_trajectories = scenarios_trajectories.merge(
        companies_forecasts,
        on=["company_id", "scenario_geography", "sector", "technology", "year"],
        how="left",
    )

    # Define groupby columns
    group_cols = [
        "company_id",
        "company_name",
        "scenario_geography",
        "sector",
        "technology",
    ]
    # Sort to ensure proper ordering and forward fill only company name
    companies_trajectories = companies_trajectories.sort_values(group_cols + ["year"])
    companies_trajectories["company_name"] = companies_trajectories[
        "company_name"
    ].ffill()

    # TARGET TRAJECTORY: constrained cumsum approach (no extra raw columns)
    companies_trajectories["_company_activity_filled"] = companies_trajectories.groupby(
        group_cols
    )["company_activity"].transform("ffill")

    # Debug: Check what columns are available
    logger.info(
        f"Available columns in companies_trajectories: {list(companies_trajectories.columns)}"
    )

    # Check for target scenario column with different possible names
    target_col = None
    possible_target_cols = [
        "scenario_activity_change_target",
        "scenario_activity_change_baseline",  # Check if baseline exists too
    ]

    # Also look for any columns containing scenario_activity_change to see what's actually there
    activity_change_cols = [
        col
        for col in companies_trajectories.columns
        if "scenario_activity_change" in col
    ]
    logger.info(f"Found activity change columns: {activity_change_cols}")

    # Try to find target column
    for col_name in activity_change_cols:
        if "target" in col_name.lower():
            possible_target_cols.append(col_name)
        elif col_name not in possible_target_cols:
            possible_target_cols.append(col_name)

    for col in possible_target_cols:
        if col in companies_trajectories.columns:
            target_col = col
            break

    if target_col is None:
        # List all scenario_activity_change columns
        activity_change_cols = [
            col
            for col in companies_trajectories.columns
            if "scenario_activity_change" in col
        ]
        raise ValueError(
            f"No suitable target activity change column found. Available activity change columns: {activity_change_cols}"
        )

    logger.info(f"Using target activity change column: {target_col}")

    # Compute initial cumsum of target changes
    companies_trajectories["_target_cumsum"] = companies_trajectories.groupby(
        group_cols
    )[target_col].transform("cumsum")

    # Determine where trajectory would drop to or below zero
    _target_traj_unconstrained = (
        companies_trajectories["_company_activity_filled"]
        + companies_trajectories["_target_cumsum"]
    )
    companies_trajectories["_temp_target_zero"] = (
        _target_traj_unconstrained <= 0
    ).astype(int)
    companies_trajectories["_target_zero_reached"] = (
        companies_trajectories.groupby(group_cols)["_temp_target_zero"]
        .transform("cummax")
        .astype(bool)
    )

    # Apply zero‐floor constraint directly on the cumsum values
    companies_trajectories["_target_cumsum"] = np.where(
        companies_trajectories["_target_zero_reached"],
        -companies_trajectories[
            "_company_activity_filled"
        ],  # ensures trajectory hits 0 exactly
        companies_trajectories["_target_cumsum"],
    )

    # Final target trajectory
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

    # Prepare masked baseline changes (only during projection period)
    companies_trajectories["_baseline_changes_masked"] = companies_trajectories[
        "scenario_activity_change_baseline"
    ].where(companies_trajectories["_is_projection_period"], 0)

    # Get last valid value for projection
    companies_trajectories["_last_valid_value"] = companies_trajectories.groupby(
        group_cols
    )["company_activity"].transform(
        lambda x: x.dropna().iloc[-1] if x.notna().any() else np.nan
    )

    # Compute baseline constrained cumsum (no extra raw column)
    companies_trajectories["_baseline_cumsum"] = companies_trajectories.groupby(
        group_cols
    )["_baseline_changes_masked"].transform("cumsum")

    _baseline_traj_unconstrained = (
        companies_trajectories["_last_valid_value"]
        + companies_trajectories["_baseline_cumsum"]
    )
    companies_trajectories["_temp_baseline_zero"] = (
        _baseline_traj_unconstrained <= 0
    ).astype(int)
    companies_trajectories["_baseline_zero_reached"] = (
        companies_trajectories.groupby(group_cols)["_temp_baseline_zero"]
        .transform("cummax")
        .astype(bool)
    )

    companies_trajectories["_baseline_cumsum"] = np.where(
        companies_trajectories["_baseline_zero_reached"],
        -companies_trajectories["_last_valid_value"],  # clamp so trajectory exactly 0
        companies_trajectories["_baseline_cumsum"],
    )

    # Combine original data with constrained projections
    companies_trajectories["company_trajectory_baseline"] = np.where(
        companies_trajectories["_is_projection_period"],
        companies_trajectories["_last_valid_value"]
        + companies_trajectories["_baseline_cumsum"],
        companies_trajectories["company_activity"],
    )

    # Clean up temporary columns
    temp_cols = [
        "_company_activity_filled",
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
    companies_trajectories = companies_trajectories.drop(columns=temp_cols)

    return companies_trajectories
