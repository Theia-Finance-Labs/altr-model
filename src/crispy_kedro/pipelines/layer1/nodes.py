"""
This is a boilerplate pipeline 'layer1'
generated using Kedro 0.19.12
"""

import pandas as pd
import numpy as np
from typing import Tuple


def calculate_fair_share_perc(
    scenarios: pd.DataFrame,
) -> pd.DataFrame:

    # Sort the DataFrame by scenario_year so that the first value in each group is the earliest year
    scenarios_fair_share = scenarios.sort_values("year")

    # Compute the first scenario_pathway value for each group
    # This ensures we capture the value after sorting by scenario_year
    scenarios_fair_share["first_pathway"] = scenarios_fair_share.groupby(
        ["scenario", "sector", "scenario_geography", "technology"]
    )["scenario_pathway"].transform("first")

    # Calculate tmsr = (scenario_pathway - first_pathway) / first_pathway
    scenarios_fair_share["tmsr"] = (
        scenarios_fair_share["scenario_pathway"] - scenarios_fair_share["first_pathway"]
    ) / scenarios_fair_share["first_pathway"]

    # Drop the helper column if it's no longer needed
    scenarios_fair_share = scenarios_fair_share.drop(columns="first_pathway")

    # Set fair_share_perc equal to tmsr
    scenarios_fair_share["fair_share_perc"] = scenarios_fair_share["tmsr"]

    # Replace NaN values (which may appear if first_pathway was zero) with 0
    scenarios_fair_share["fair_share_perc"] = scenarios_fair_share[
        "fair_share_perc"
    ].fillna(0)

    scenarios_fair_share = scenarios_fair_share.loc[
        :,
        [
            "scenario",
            "scenario_type",
            "sector",
            "technology",
            "technology_type",
            "year",
            "scenario_pathway",
            "fair_share_perc",
            "scenario_price",
            "scenario_capacity_factor",
        ],
    ]

    return scenarios_fair_share


def compute_target_trajectory(
    raw_trajectory: pd.DataFrame, scenarios: pd.DataFrame
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
        .rename(columns={"capacity": "initial_asset_trajectory"})
    )

    # Merge the first-year values with the target scenario to get a row for every (technology, year)
    target_trajectory = raw_trajectory_first_year.merge(
        scenarios.loc[
            scenarios["scenario_type"] == "target",
            [
                "sector",
                "technology",
                "year",
                "scenario_pathway",
                "fair_share_perc",
            ],
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
        raw_trajectory[["asset_id", "sector", "technology", "year", "capacity"]],
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
        target_trajectory_final["capacity"],
        target_trajectory_final["asset_trajectory_extended"],
    )

    target_trajectory_final = target_trajectory_final.sort_values(
        ["asset_id", "sector", "technology", "year"]
    )

    # Return only the desired columns
    return target_trajectory_final.loc[
        :, ["asset_id", "sector", "technology", "year", "asset_trajectory_target"]
    ]


def apply_capacity_factors(
    traj_scenario: pd.DataFrame,
    traj_assets_target_clean: pd.DataFrame,
    traj_assets: pd.DataFrame,
) -> pd.DataFrame:
    def merge_and_apply(df_assets: pd.DataFrame, scenario_type: str) -> pd.DataFrame:
        capfac = traj_scenario.loc[
            traj_scenario["scenario_type"] == scenario_type,
            ["year", "sector", "scenario_capacity_factor", "technology"],
        ]

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

    traj_assets_target_prod = merge_and_apply(traj_assets_target_clean, "target")

    traj_assets_baseline_prod = traj_assets.rename(
        columns=({"capacity": "asset_trajectory_baseline"})
    )
    traj_assets_baseline_prod = merge_and_apply(traj_assets_baseline_prod, "baseline")

    traj_assets_target_prod = traj_assets_target_prod[
        ["asset_id", "sector", "technology", "year", "asset_trajectory_target"]
    ]

    traj_assets_baseline_prod = traj_assets_baseline_prod[
        ["asset_id", "sector", "technology", "year", "asset_trajectory_baseline"]
    ]

    traj_assets_prod = pd.merge(
        traj_assets_target_prod,
        traj_assets_baseline_prod,
        on=["asset_id", "sector", "technology", "year"],
        how="inner",
    )

    return traj_assets_prod


def apply_compensation_shock(
    traj_assets_prod: pd.DataFrame,
    shock_year: int,
) -> pd.DataFrame:
    group_cols = ["asset_id", "sector", "technology"]
    ls_data_to_compensate = traj_assets_prod

    # Calculate asset_trajectory_shock
    ls_data_to_compensate["asset_trajectory_shock"] = np.where(
        ls_data_to_compensate["year"] <= shock_year,
        ls_data_to_compensate["asset_trajectory_baseline"],
        0,
    )

    # Pre-shock calculations
    ls_pre_shock = (
        ls_data_to_compensate[ls_data_to_compensate["year"] <= (shock_year - 1)]
        .groupby(group_cols)
        .agg(
            late_sudden_pre_shock_val=("asset_trajectory_shock", "last"),
            late_sudden_pre_shock_tot=("asset_trajectory_shock", "sum"),
        )
        .reset_index()
    )

    # Production scenario target totals
    production_totals = (
        ls_data_to_compensate.groupby(group_cols)
        .agg(
            production_scenario_target_total_sum=(
                "asset_trajectory_target",
                "sum",
            ),
            n_shocked_years=("year", lambda x: x.max() - shock_year + 1),
        )
        .reset_index()
    )

    # Calculate 'x'
    x_integral = ls_pre_shock.merge(production_totals, on=group_cols, how="left")
    x_integral["sum_1_to_n_shocked_years"] = (
        x_integral["n_shocked_years"] * (x_integral["n_shocked_years"] + 1) / 2
    )
    x_integral["x"] = (
        x_integral["production_scenario_target_total_sum"]
        - x_integral["late_sudden_pre_shock_tot"]
        - x_integral["n_shocked_years"] * x_integral["late_sudden_pre_shock_val"]
    ) / (-x_integral["sum_1_to_n_shocked_years"])

    # Merge 'x' and 'late_sudden_pre_shock_val' back to compensate data
    ls_data_to_compensate = ls_data_to_compensate.merge(
        x_integral[group_cols + ["x", "late_sudden_pre_shock_val"]],
        on=group_cols,
        how="left",
    )

    # Handle any remaining missing 'late_sudden_pre_shock_val'
    ls_data_to_compensate["late_sudden_pre_shock_val"] = ls_data_to_compensate[
        "late_sudden_pre_shock_val"
    ].fillna(0)
    ls_data_to_compensate["x"] = ls_data_to_compensate["x"].fillna(0)

    # Calculate year_diff and adjust asset_trajectory_shock
    ls_data_to_compensate["year_diff"] = ls_data_to_compensate["year"] - shock_year + 1
    ls_data_to_compensate["asset_trajectory_shock"] = np.where(
        (ls_data_to_compensate["year"] >= shock_year),
        ls_data_to_compensate["late_sudden_pre_shock_val"]
        - ls_data_to_compensate["year_diff"].clip(lower=0) * ls_data_to_compensate["x"],
        ls_data_to_compensate["asset_trajectory_shock"],
    )

    # Select relevant columns
    assets_compensated_shocked = ls_data_to_compensate.loc[
        :, ["asset_id", "sector", "technology", "year", "asset_trajectory_shock"]
    ]

    return assets_compensated_shocked


def enforce_zero_after_first(
    group: pd.DataFrame, trajectory_column: str
) -> pd.DataFrame:
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


def force_phase_out_traj_assets(traj_assets_target: pd.DataFrame) -> pd.DataFrame:

    traj_assets_target_clean = (
        traj_assets_target.groupby(["asset_id", "sector", "technology"])
        .apply(lambda group: enforce_zero_after_first(group, "asset_trajectory_target"))
        .reset_index(drop=True)
    )

    return traj_assets_target_clean


def force_phase_out_late_sudden(traj_assets_shocked: pd.DataFrame) -> pd.DataFrame:

    traj_assets_shocked = (
        traj_assets_shocked.groupby(["asset_id", "sector", "technology"])
        .apply(lambda group: enforce_zero_after_first(group, "asset_trajectory_shock"))
        .reset_index(drop=True)
    )

    return traj_assets_shocked


def allocate_production_to_companies(
    companies_ownership_tree: pd.DataFrame,
    traj_assets_baseline: pd.DataFrame,
    traj_assets_shocked: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    def allocate_trajectory(asset_df, asset_col, output_col):
        """
        Merges asset-level trajectories with company ownership info,
        allocates the asset trajectory based on normalized ownership,
        and aggregates by company, sector, technology, and year.

        Parameters:
            asset_df: DataFrame with asset trajectories.
            asset_col: The column name in asset_df to allocate (e.g.
                       "asset_trajectory_baseline" or "asset_trajectory_shock").
            output_col: The name for the resulting allocated column
                        (e.g. "company_trajectory_baseline" or
                        "company_trajectory_shock").

        Returns:
            A DataFrame aggregated to the company level.
        """
        merged = asset_df.merge(
            companies_ownership_tree[
                ["asset_id", "company_id", "normalized_ownership"]
            ],
            on="asset_id",
            how="inner",
        )
        merged[f"allocated_{asset_col}"] = (
            merged[asset_col] * merged["normalized_ownership"]
        )
        allocated = (
            merged.groupby(
                ["company_id", "sector", "technology", "year"], as_index=False
            )[f"allocated_{asset_col}"]
            .sum()
            .rename(columns={f"allocated_{asset_col}": output_col})
        )
        return allocated

    # Allocate baseline trajectories. Assumes traj_assets_baseline has a column named
    # "asset_trajectory_baseline".
    traj_companies_baseline = allocate_trajectory(
        traj_assets_baseline, "asset_trajectory_baseline", "company_trajectory_baseline"
    )

    # Allocate shock trajectories. Assumes traj_assets_shocked has a column named
    # "asset_trajectory_shock".
    traj_companies_shock = allocate_trajectory(
        traj_assets_shocked, "asset_trajectory_shock", "company_trajectory_shock"
    )

    return traj_companies_baseline, traj_companies_shock
