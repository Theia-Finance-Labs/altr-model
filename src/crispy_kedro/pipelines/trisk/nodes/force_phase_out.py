import numpy as np
import pandas as pd


def enforce_zero_after_first(group, trajectory_column):
    # Sort the group by year to ensure the rows are in order
    group = group.sort_values("year").copy()
    # Convert the production column to a numpy array
    values = group[trajectory_column].to_numpy()
    # Find the indices where production is zero
    zero_indices = np.where(values == 0)[0]
    if len(zero_indices) > 0:
        # Once production reaches zero, force all subsequent values to zero
        first_zero_index = zero_indices[0]
        values[first_zero_index:] = 0
    # Assign the updated values back to the DataFrame
    group[trajectory_column] = values
    return group


def force_phase_out_target_baseline(
    traj_assets_baseline: pd.DataFrame, traj_assets_target: pd.DataFrame
):

    traj_assets_baseline = (
        traj_assets_baseline.groupby(["asset_id", "sector", "technology"])
        .apply(
            lambda group: enforce_zero_after_first(group, "asset_trajectory_baseline")
        )
        .reset_index(drop=True)
    )

    traj_assets_target = (
        traj_assets_target.groupby(["asset_id", "sector", "technology"])
        .apply(lambda group: enforce_zero_after_first(group, "asset_trajectory_target"))
        .reset_index(drop=True)
    )

    return traj_assets_baseline, traj_assets_target


def force_phase_out_late_sudden(traj_assets_shocked: pd.DataFrame):

    traj_assets_shocked = (
        traj_assets_shocked.groupby(["asset_id", "sector", "technology"])
        .apply(lambda group: enforce_zero_after_first(group, "asset_trajectory_shock"))
        .reset_index(drop=True)
    )

    return traj_assets_shocked
