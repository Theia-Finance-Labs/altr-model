import numpy as np
import pandas as pd


def compute_baseline_trajectory(
    raw_trajectory: pd.DataFrame, baseline_scenario: pd.DataFrame
) -> pd.DataFrame:
    """
    Computes the baseline trajectory by extending the time range if needed.
    It expects the input DataFrame to contain a column named 'asset_trajectory'
    and returns a DataFrame with the same column name.
    """

    raw_trajectory_first_year = (
        raw_trajectory.sort_values("year")
        .groupby(["asset_id", "technology"], as_index=False)
        .first()
        .drop(columns="year")
        .rename(columns={"asset_trajectory": "initial_asset_trajectory"})
    )

    baseline_trajectory = raw_trajectory_first_year.merge(
        baseline_scenario[
            ["technology", "year", "scenario_pathway", "fair_share_perc"]
        ],
        how="right",
        on=["technology"],
    )

    baseline_trajectory["asset_trajectory_extended"] = baseline_trajectory[
        "initial_asset_trajectory"
    ] * (1 + baseline_trajectory["fair_share_perc"])

    # Ensure a proper order by sorting by asset_id, technology, and year
    baseline_trajectory = baseline_trajectory.sort_values(
        ["asset_id", "technology", "year"]
    )

    # Compute the difference per asset and technology, row by row
    baseline_trajectory["asset_trajectory_change"] = baseline_trajectory.groupby(
        ["asset_id", "technology"]
    )["asset_trajectory_extended"].diff()

    baseline_trajectory["asset_trajectory_cumsum"] = baseline_trajectory.groupby(
        ["asset_id", "technology"]
    )["asset_trajectory_change"].cumsum()

    baseline_trajectory_final = pd.merge(
        baseline_trajectory,
        raw_trajectory,
        how="left",
        on=["asset_id", "technology", "year"],
    )

    # Step 1 — Forward fill asset_trajectory down per asset_id and technology
    baseline_trajectory_final["asset_trajectory_ffill"] = (
        baseline_trajectory_final.sort_values(["asset_id", "technology", "year"])
        .groupby(["asset_id", "technology"])["asset_trajectory"]
        .ffill()
    )

    # Step 2 — Coalesce + sum: use asset_trajectory_cumsum only where asset_trajectory is NA
    mask_na = baseline_trajectory_final["asset_trajectory"].isna()

    baseline_trajectory_final.loc[mask_na, "asset_trajectory_baseline"] = (
        baseline_trajectory_final.loc[mask_na, "asset_trajectory_ffill"]
        + baseline_trajectory_final.loc[mask_na, "asset_trajectory_cumsum"]
    )
    baseline_trajectory_final.loc[~mask_na, "asset_trajectory_baseline"] = (
        baseline_trajectory_final.loc[~mask_na, "asset_trajectory"]
    )

    return baseline_trajectory_final.loc[
        :, ["asset_id", "technology", "year", "asset_trajectory_baseline"]
    ]


def compute_target_trajectory(
    raw_trajectory: pd.DataFrame, target_scenario: pd.DataFrame
) -> pd.DataFrame:
    """
    Computes the target trajectory by extending the time range using the target scenario.
    The first year target equals the original asset_trajectory.
    For subsequent years, the target is computed as the initial asset trajectory
    multiplied by (1 + fair_share_perc). Negative values are set to zero.
    """
    import numpy as np

    # Get the first-year value per asset_id and technology
    raw_trajectory_first_year = (
        raw_trajectory.sort_values("year")
        .groupby(["asset_id", "technology"], as_index=False)
        .first()
        .drop(columns="year")
        .rename(columns={"asset_trajectory": "initial_asset_trajectory"})
    )

    # Merge the first-year values with the target scenario to get a row for every (technology, year)
    target_trajectory = raw_trajectory_first_year.merge(
        target_scenario[["technology", "year", "scenario_pathway", "fair_share_perc"]],
        how="right",
        on="technology",
    )

    # Compute the extended target value using the scenario factor for each row
    target_trajectory["asset_trajectory_extended"] = target_trajectory[
        "initial_asset_trajectory"
    ] * (1 + target_trajectory["fair_share_perc"])

    # Merge with raw_trajectory to recover the original asset_trajectory values where available
    target_trajectory_final = pd.merge(
        target_trajectory,
        raw_trajectory[["asset_id", "technology", "year", "asset_trajectory"]],
        how="left",
        on=["asset_id", "technology", "year"],
    )

    # Determine the first year for each asset+technology group from the target scenario
    target_trajectory_final["first_year"] = target_trajectory_final.groupby(
        ["asset_id", "technology"]
    )["year"].transform("min")

    # For the first year, use the original asset_trajectory; for subsequent years, use the extended value.
    target_trajectory_final["asset_trajectory_target"] = np.where(
        target_trajectory_final["year"] == target_trajectory_final["first_year"],
        target_trajectory_final["asset_trajectory"],
        target_trajectory_final["asset_trajectory_extended"],
    )

    target_trajectory_final = target_trajectory_final.sort_values(
        ["asset_id", "technology", "year"]
    )

    # Return only the desired columns
    return target_trajectory_final[
        ["asset_id", "technology", "year", "asset_trajectory_target"]
    ]


def force_phase_out(traj_assets_baseline, traj_assets_target):

    def enforce_zero_after_first(group):
        # Sort the group by year to ensure the rows are in order
        group = group.sort_values("year").copy()
        # Convert the production column to a numpy array
        values = group["asset_trajectory_final"].to_numpy()
        # Find the indices where production is zero
        zero_indices = np.where(values == 0)[0]
        if len(zero_indices) > 0:
            # Once production reaches zero, force all subsequent values to zero
            first_zero_index = zero_indices[0]
            values[first_zero_index:] = 0
        # Assign the updated values back to the DataFrame
        group["asset_trajectory_final"] = values
        return group

    traj_assets_baseline = traj_assets_baseline.groupby(
        ["asset_id", "technology"]
    ).apply(enforce_zero_after_first)

    return traj_assets_baseline, traj_assets_target
