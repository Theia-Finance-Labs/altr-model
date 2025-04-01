"""
This is a boilerplate pipeline 'trisk'
generated using Kedro 0.19.12
"""

import pandas as pd
from typing import Tuple
from tqdm import tqdm

import pandas as pd
from typing import Tuple
from tqdm import tqdm


def compute_base_trajectory(
    df: pd.DataFrame, units_events: pd.DataFrame
) -> pd.DataFrame:
    # Create a 'delta' column: positive for add_capacity, negative for remove_capacity.
    df = df.sample(100)
    units_events["delta"] = units_events.apply(
        lambda row: (
            row["capacity_value"]
            if row["event_type"] == "add_capacity"
            else -row["capacity_value"]
        ),
        axis=1,
    )
    units_events = units_events[units_events["asset_id"].isin(df["asset_id"])]

    # Group units_events by asset_id, technology, and event_year.
    grouped_events = units_events.groupby(
        ["asset_id", "technology_category", "event_year"], as_index=False
    )["delta"].sum()

    # Determine the latest event year across all units_events
    max_event_year = grouped_events["event_year"].max()

    # Pre-compute the groupby object
    grouped = grouped_events.groupby(["asset_id", "technology_category"])
    trajectories = []

    for (asset_id, technology_category), group in tqdm(
        grouped, total=grouped.ngroups, desc="Processing assets x tech", leave=True
    ):
        group = group.sort_values("event_year")
        group["total_capacity"] = group["delta"].cumsum()

        start_year = int(group["event_year"].min())
        years = range(start_year, int(max_event_year) + 1)

        capacity_series = group.set_index("event_year")["total_capacity"]
        capacity_series = capacity_series.reindex(years).ffill().fillna(0)

        df_years = pd.DataFrame(
            {
                "year": list(years),
                "total_capacity": capacity_series.values,
                "asset_id": asset_id,
                "technology": technology_category,
            }
        )
        trajectories.append(df_years)

    renewal_df = pd.concat(trajectories, ignore_index=True)

    renewal_df = renewal_df.merge(
        df[["asset_id", "asset_name", "country_name"]], on="asset_id", how="left"
    )

    # Rename to have a consistent trajectory column name
    renewal_df.rename(columns={"total_capacity": "asset_trajectory"}, inplace=True)
    return renewal_df[
        [
            "asset_id",
            "asset_name",
            "country_name",
            "technology",
            "year",
            "asset_trajectory",
        ]
    ]


def get_common_scenario_years(df: pd.DataFrame) -> Tuple[int, int]:
    """Get the common minimum and maximum scenario_year across technologies."""
    grouped = df.groupby("technology")["scenario_year"]
    min_years = grouped.min()
    max_years = grouped.max()

    if min_years.nunique() != 1:
        raise ValueError("Technologies have different minimum scenario_year values.")
    if max_years.nunique() != 1:
        raise ValueError("Technologies have different maximum scenario_year values.")

    return min_years.iloc[0], max_years.iloc[0]


def compute_truncated_trajectory(
    base_trajectory: pd.DataFrame, scenarios: pd.DataFrame
) -> pd.DataFrame:
    """
    Creates a truncated trajectory using a fixed timeline based on the
    baseline scenarios. The transformation reindexes the input DataFrame
    and forward-fills the 'asset_trajectory' column.
    """
    # Get the common minimum scenario year from the baseline scenarios
    min_scenario_year, _ = get_common_scenario_years(scenarios)
    # Define a fixed timeline: from min_year to min_year+5 (inclusive)
    timeline_years = list(range(min_scenario_year, min_scenario_year + 6))

    # Create a full MultiIndex of (asset_id, technology, year)
    index = pd.MultiIndex.from_product(
        [
            base_trajectory["asset_id"].unique(),
            base_trajectory["technology"].unique(),
            timeline_years,
        ],
        names=["asset_id", "technology", "year"],
    )

    # Reindex the base trajectory to the full index
    df_full = (
        base_trajectory.set_index(["asset_id", "technology", "year"])
        .reindex(index)
        .sort_index()
        .reset_index()
    )

    # Forward fill (and back fill) for 'asset_trajectory'
    df_full["asset_trajectory"] = (
        df_full.groupby(["asset_id", "technology"], sort=False)["asset_trajectory"]
        .ffill()
        .fillna(0)
    )

    return df_full


def compute_baseline_trajectory(
    base_trajectory: pd.DataFrame, scenarios: pd.DataFrame
) -> pd.DataFrame:
    """
    Computes the baseline trajectory by extending the time range if needed.
    It expects the input DataFrame to contain a column named 'asset_trajectory'
    and returns a DataFrame with the same column name.
    """
    # Get the common scenario years from the baseline scenarios
    min_scenario_year, max_scenario_year = get_common_scenario_years(scenarios)
    # Define a fixed timeline: from min_year to min_year+5 (inclusive)
    timeline_years = list(range(min_scenario_year, min_scenario_year + 6))

    # Create a full MultiIndex of (asset_id, technology, year)
    index = pd.MultiIndex.from_product(
        [
            base_trajectory["asset_id"].unique(),
            base_trajectory["technology"].unique(),
            timeline_years,
        ],
        names=["asset_id", "technology", "year"],
    )

    # Reindex the input DataFrame to the full index
    df_full = (
        base_trajectory.set_index(["asset_id", "technology", "year"])
        .reindex(index)
        .sort_index()
        .reset_index()
    )

    # Forward fill (and back fill) the 'asset_trajectory' by group
    df_full["asset_trajectory"] = (
        df_full.groupby(["asset_id", "technology"], sort=False)["asset_trajectory"]
        .ffill()
        .fillna(0)
    )

    results = []
    # Process each asset and technology combination separately
    for (asset_id, tech), group in base_trajectory.groupby(["asset_id", "technology"]):
        # Get the scenario years for the current technology
        scenario_group = scenarios[scenarios["technology"] == tech]

        if scenario_group.empty:
            results.append(group)
            continue

        # Determine the full year range based on available data and scenarios
        start_year = min(group["year"].min(), scenario_group["scenario_year"].min())
        end_year = max(group["year"].max(), scenario_group["scenario_year"].max())
        full_years = pd.DataFrame({"year": range(start_year, end_year + 1)})

        # Merge and forward fill the base_trajectory values
        merged = full_years.merge(
            group[["year", "asset_trajectory"]], on="year", how="left"
        )
        merged["asset_trajectory"] = merged["asset_trajectory"].ffill().fillna(0)
        merged["asset_id"] = asset_id
        merged["technology"] = tech
        results.append(merged)

    # Concatenate the results for all asset_id-technology combinations
    extended_df = pd.concat(results, ignore_index=True)

    return extended_df
