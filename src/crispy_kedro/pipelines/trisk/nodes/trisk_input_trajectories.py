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
        .groupby(["asset_id", "sector", "technology"], as_index=False)
        .first()
        .drop(columns="year")
        .rename(columns={"asset_trajectory": "initial_asset_trajectory"})
    )

    baseline_trajectory = raw_trajectory_first_year.merge(
        baseline_scenario[
            ["sector", "technology", "year", "scenario_pathway", "fair_share_perc"]
        ],
        how="right",
        on=["sector", "technology"],
    )

    baseline_trajectory["asset_trajectory_extended"] = baseline_trajectory[
        "initial_asset_trajectory"
    ] * (1 + baseline_trajectory["fair_share_perc"])

    # Ensure a proper order by sorting by asset_id, technology, and year
    baseline_trajectory = baseline_trajectory.sort_values(
        ["asset_id", "sector", "technology", "year"]
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
        on=["asset_id", "sector", "technology", "year"],
    )

    # Step 1 — Forward fill asset_trajectory down per asset_id and technology
    baseline_trajectory_final["asset_trajectory_ffill"] = (
        baseline_trajectory_final.sort_values(["asset_id", "technology", "year"])
        .groupby(["asset_id", "sector", "technology"])["asset_trajectory"]
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
        :, ["asset_id", "sector", "technology", "year", "asset_trajectory_baseline"]
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

    # Get the first-year value per asset_id and technology
    raw_trajectory_first_year = (
        raw_trajectory.sort_values("year")
        .groupby(["asset_id", "sector", "technology"], as_index=False)
        .first()
        .drop(columns="year")
        .rename(columns={"asset_trajectory": "initial_asset_trajectory"})
    )

    # Merge the first-year values with the target scenario to get a row for every (technology, year)
    target_trajectory = raw_trajectory_first_year.merge(
        target_scenario[
            ["sector", "technology", "year", "scenario_pathway", "fair_share_perc"]
        ],
        how="right",
        on=["sector", "technology"],
    )

    # Compute the extended target value using the scenario factor for each row
    target_trajectory["asset_trajectory_extended"] = target_trajectory[
        "initial_asset_trajectory"
    ] * (1 + target_trajectory["fair_share_perc"])

    # Merge with raw_trajectory to recover the original asset_trajectory values where available
    target_trajectory_final = pd.merge(
        target_trajectory,
        raw_trajectory[
            ["asset_id", "sector", "technology", "year", "asset_trajectory"]
        ],
        how="left",
        on=["asset_id", "sector", "technology", "year"],
    )

    # Determine the first year for each asset+technology group from the target scenario
    target_trajectory_final["first_year"] = target_trajectory_final.groupby(
        ["asset_id", "sector", "technology"]
    )["year"].transform("min")

    # For the first year, use the original asset_trajectory; for subsequent years, use the extended value.
    target_trajectory_final["asset_trajectory_target"] = np.where(
        target_trajectory_final["year"] == target_trajectory_final["first_year"],
        target_trajectory_final["asset_trajectory"],
        target_trajectory_final["asset_trajectory_extended"],
    )

    target_trajectory_final = target_trajectory_final.sort_values(
        ["asset_id", "sector", "technology", "year"]
    )

    # Return only the desired columns
    return target_trajectory_final[
        ["asset_id", "sector", "technology", "year", "asset_trajectory_target"]
    ]


def apply_capacity_factors(
    traj_scenario,
    traj_assets_baseline_clean,
    traj_assets_target_clean,
    traj_assets_raw_truncated,
):
    def merge_and_apply(df_assets, scenario_type):
        capfac = traj_scenario.loc[
            traj_scenario["scenario_type"] == scenario_type,
            ["scenario_year", "sector", "scenario_capacity_factor", "technology"],
        ].rename(columns={"scenario_year": "year"})

        df = pd.merge(
            df_assets,
            capfac,
            how="inner",
            on=["technology", "sector", "year"],
        )

        HOURS_PER_YEAR = 24 * 365
        is_power = df["sector"] == "Power"

        df[f"asset_trajectory_{scenario_type}"] = (
            df[f"asset_trajectory_{scenario_type}"] * df["scenario_capacity_factor"]
        )
        df.loc[is_power, f"asset_trajectory_{scenario_type}"] *= HOURS_PER_YEAR

        return df

    traj_assets_baseline_prod = merge_and_apply(traj_assets_baseline_clean, "baseline")
    traj_assets_target_prod = merge_and_apply(traj_assets_target_clean, "target")

    truncated_traj_assets_prod = traj_assets_raw_truncated.rename(
        columns=({"asset_trajectory": "asset_trajectory_baseline"})
    )
    truncated_traj_assets_prod = merge_and_apply(truncated_traj_assets_prod, "baseline")
    truncated_traj_assets_prod = truncated_traj_assets_prod.rename(
        columns=({"asset_trajectory_baseline": "asset_trajectory"})
    )

    traj_assets_baseline_prod = traj_assets_baseline_prod[
        ["asset_id", "sector", "technology", "year", "asset_trajectory_baseline"]
    ]
    traj_assets_target_prod = traj_assets_target_prod[
        ["asset_id", "sector", "technology", "year", "asset_trajectory_target"]
    ]

    truncated_traj_assets_prod = truncated_traj_assets_prod[
        ["asset_id", "sector", "technology", "year", "asset_trajectory"]
    ]

    return (
        traj_assets_baseline_prod,
        traj_assets_target_prod,
        truncated_traj_assets_prod,
    )
