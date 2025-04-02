"""
This is a boilerplate pipeline 'trisk'
generated using Kedro 0.19.12
"""

import pandas as pd
from typing import Tuple
from tqdm import tqdm

import pandas as pd
from typing import Tuple, List
from tqdm import tqdm
import ibis


def filter_assets(
    assets_detail: ibis.expr.types.Table,
    units_events: ibis.expr.types.Table,
    asset_ids: List[str],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    filtered_assets = assets_detail.filter(assets_detail.asset_id.isin(asset_ids))
    filtered_assets = filtered_assets.execute()

    filtered_events = units_events.filter(units_events.asset_id.isin(asset_ids))
    filtered_events = filtered_events.execute()
    return filtered_assets, filtered_events


def compute_raw_trajectory(
    df: pd.DataFrame, units_events: pd.DataFrame
) -> pd.DataFrame:
    # Create a 'delta' column: positive for add_capacity, negative for remove_capacity.
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
    renewal_df["asset_trajectory"] = renewal_df["asset_trajectory"].astype(float)
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


def truncate_traj_asset(
    raw_trajectory: pd.DataFrame, scenarios: pd.DataFrame
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

    # Get unique combinations of asset_id and technology
    asset_tech = raw_trajectory[["asset_id", "technology"]].drop_duplicates()

    # Build a list of tuples: (asset_id, technology, year)
    index_tuples = [
        (asset, tech, year)
        for asset, tech in asset_tech.itertuples(index=False, name=None)
        for year in timeline_years
    ]

    # Create the MultiIndex from the tuples
    multi_index = pd.MultiIndex.from_tuples(
        index_tuples, names=["asset_id", "technology", "year"]
    )
    # Reindex the base trajectory to the full index
    df_full = (
        raw_trajectory.set_index(["asset_id", "technology", "year"])
        .reindex(multi_index)
        .sort_index()
        .reset_index()
    )

    # Forward fill (and back fill) for 'asset_trajectory'
    df_full["asset_trajectory"] = (
        df_full.groupby(["asset_id", "technology"], sort=False)["asset_trajectory"]
        .ffill()
        .fillna(0)
    )

    return df_full[["asset_id", "technology", "year", "asset_trajectory"]]
