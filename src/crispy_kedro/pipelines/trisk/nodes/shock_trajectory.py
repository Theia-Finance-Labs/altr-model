import numpy as np
import pandas as pd


def compute_proximity_to_target(
    traj_assets_raw_truncated: pd.DataFrame, traj_assets_target_clean: pd.DataFrame
) -> pd.DataFrame:

    # Determine the last year with non-NA production for each group
    last_non_na = (
        traj_assets_raw_truncated.groupby(["asset_id", "sector", "technology"])
        .apply(lambda x: x.loc[x["asset_trajectory"].notna(), "year"].max())
        .reset_index(name="last_non_na_year")
    )

    # Merge and filter data
    merged = traj_assets_raw_truncated.merge(
        last_non_na, on=["asset_id", "sector", "technology"]
    ).merge(traj_assets_target_clean, on=["asset_id", "sector", "technology", "year"])
    filtered = merged[(merged["year"] <= merged["last_non_na_year"])].sort_values(
        by=["asset_id", "sector", "technology", "year"]
    )

    # Calculate initial production and changes
    filtered["initial_technology_production"] = filtered.groupby(
        ["asset_id", "sector", "technology"]
    )["asset_trajectory"].transform("first")
    filtered["required_change"] = (
        filtered["asset_trajectory_target"] - filtered["initial_technology_production"]
    )
    filtered["realised_change"] = (
        filtered["asset_trajectory"] - filtered["initial_technology_production"]
    )

    # Aggregate changes and calculate proximity
    proximity = (
        filtered.groupby(["asset_id", "sector", "technology"])
        .agg(
            sum_required_change=("required_change", "sum"),
            sum_realised_change=("realised_change", "sum"),
        )
        .reset_index()
    )
    proximity["ratio_realised_required"] = (
        proximity["sum_realised_change"] / proximity["sum_required_change"]
    )
    proximity["proximity_to_target"] = np.select(
        [
            proximity["ratio_realised_required"] < 0,
            proximity["ratio_realised_required"] > 1,
        ],
        [0, 1],
        default=proximity["ratio_realised_required"],
    )

    proximity.drop(
        ["sum_required_change", "sum_realised_change", "ratio_realised_required"],
        axis=1,
    )

    proximity_to_target = proximity[["asset_id", "technology", "proximity_to_target"]]
    # TODO : It seems the NAs in "proximity_to_target" appear when production is 0 in raw traj
    proximity_to_target = proximity_to_target.dropna()

    return proximity_to_target


def split_assets_per_shock_type(
    traj_assets_raw_truncated: pd.DataFrame, traj_assets_target_prod: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:

    late_sudden_data = pd.merge(
        traj_assets_raw_truncated,
        traj_assets_target_prod,
        how="inner",
        on=["asset_id", "sector", "technology", "year"],
    )

    group_cols = ["asset_id", "sector", "technology"]
    late_sudden_data = late_sudden_data.sort_values(group_cols + ["year"])

    # Compute overshoot_direction
    def determine_overshoot(asset_trajectory_target):
        first_val = asset_trajectory_target.iloc[0]
        last_val = asset_trajectory_target.iloc[-1]
        return "Decreasing" if (first_val - last_val) > 0 else "Increasing"

    late_sudden_data["overshoot_direction"] = late_sudden_data.groupby(group_cols)[
        "asset_trajectory_target"
    ].transform(determine_overshoot)

    # Fill missing asset_trajectory_filled
    late_sudden_data["asset_trajectory_filled"] = late_sudden_data[
        "asset_trajectory"
    ].ffill()

    # Identify last_non_na_year per group
    last_non_na = (
        late_sudden_data[late_sudden_data["asset_trajectory"].notna()]
        .groupby(group_cols)["year"]
        .max()
        .reset_index()
    )
    last_non_na = last_non_na.rename(columns={"year": "last_non_na_year"})

    # Merge to get last_non_na_year
    merged = late_sudden_data.merge(last_non_na, on=group_cols, how="inner")

    # Filter data where year > min(year) and <= last_non_na_year
    min_year = merged.groupby(group_cols)["year"].transform("min")
    condition = (merged["year"] > min_year) & (
        merged["year"] <= merged["last_non_na_year"]
    )
    filtered = merged[condition].copy()

    # Calculate sum_required_change and sum_realised_change
    flagged_overshoot = (
        filtered.groupby(group_cols)
        .agg(
            prod_to_follow=("asset_trajectory_target", "sum"),
            real_prod=("asset_trajectory", "sum"),
            overshoot_direction=("overshoot_direction", "first"),
            last_non_na_year=("last_non_na_year", "first"),  # Included here
        )
        .reset_index()
    )

    # Determine if overshoot correction is required
    flagged_overshoot["requires_overshoot_correction"] = np.where(
        (
            (flagged_overshoot["overshoot_direction"] == "Decreasing")
            & (flagged_overshoot["prod_to_follow"] < flagged_overshoot["real_prod"])
        )
        | (
            (flagged_overshoot["overshoot_direction"] == "Increasing")
            & (flagged_overshoot["prod_to_follow"] > flagged_overshoot["real_prod"])
        ),
        True,
        False,
    )

    # Separate groups needing compensation
    # TODO INVESTIGATE NEED FOR DROP_DUPLICATES
    assets_to_compensate = flagged_overshoot.loc[
        flagged_overshoot["requires_overshoot_correction"],
        ["asset_id", "last_non_na_year"],
    ].drop_duplicates()
    assets_to_not_compensate = flagged_overshoot.loc[
        ~flagged_overshoot["requires_overshoot_correction"],
        ["asset_id", "last_non_na_year"],
    ].drop_duplicates()

    return assets_to_compensate, assets_to_not_compensate, flagged_overshoot


def apply_compensation_shock(
    assets_to_compensate: pd.DataFrame,
    traj_assets_baseline_prod: pd.DataFrame,
    traj_assets_target_prod: pd.DataFrame,
    shock_year: int,
) -> pd.DataFrame:
    group_cols = ["asset_id", "sector", "technology"]
    late_sudden_data = pd.merge(
        traj_assets_baseline_prod, traj_assets_target_prod, on=group_cols + ["year"]
    )

    ls_data_to_compensate = late_sudden_data.merge(
        assets_to_compensate, on=["asset_id"], how="inner"
    )

    # Calculate late_sudden
    ls_data_to_compensate["late_sudden"] = np.where(
        ls_data_to_compensate["year"] <= shock_year,
        ls_data_to_compensate["asset_trajectory_baseline"],
        0,
    )

    # Pre-shock calculations
    ls_pre_shock = (
        ls_data_to_compensate[ls_data_to_compensate["year"] <= (shock_year - 1)]
        .groupby(group_cols)
        .agg(
            late_sudden_pre_shock_val=("late_sudden", "last"),
            late_sudden_pre_shock_tot=("late_sudden", "sum"),
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

    # Calculate year_diff and adjust late_sudden
    ls_data_to_compensate["year_diff"] = ls_data_to_compensate["year"] - shock_year + 1
    ls_data_to_compensate["late_sudden"] = np.where(
        (ls_data_to_compensate["year"] >= shock_year)
        & (ls_data_to_compensate["year"] > ls_data_to_compensate["last_non_na_year"]),
        ls_data_to_compensate["late_sudden_pre_shock_val"]
        - ls_data_to_compensate["year_diff"].clip(lower=0) * ls_data_to_compensate["x"],
        ls_data_to_compensate["late_sudden"],
    )

    # Select relevant columns
    assets_compensated_shocked = ls_data_to_compensate[
        ["asset_id", "sector", "technology", "year", "late_sudden"]
    ]

    return assets_compensated_shocked


def apply_simple_shock(
    assets_to_not_compensate: pd.DataFrame,
    truncated_traj_assets_prod: pd.DataFrame,
    traj_assets_target_prod: pd.DataFrame,
) -> pd.DataFrame:
    group_cols = ["asset_id", "sector", "technology"]

    # Merge production and target trajectories on group and year
    late_sudden_data = pd.merge(
        truncated_traj_assets_prod,
        traj_assets_target_prod,
        on=group_cols + ["year"],
        how="right",
    )

    # Filter to assets that are in the assets_to_not_compensate list
    ls_data_to_not_compensate = late_sudden_data.merge(
        assets_to_not_compensate, on=["asset_id"], how="inner"
    )

    # Fill forward asset_trajectory within each group
    ls_data_to_not_compensate["asset_trajectory_filled"] = (
        ls_data_to_not_compensate.groupby(group_cols)["asset_trajectory"].ffill()
    )

    # Compute the yearly change of asset_trajectory_target per group using diff (which uses shift)
    ls_data_to_not_compensate["asset_trajectory_target_change"] = (
        ls_data_to_not_compensate.groupby(group_cols)["asset_trajectory_target"].diff()
    )

    # Set the change to 0 where the original asset_trajectory is not NA
    ls_data_to_not_compensate.loc[
        ls_data_to_not_compensate["asset_trajectory"].notna(),
        "asset_trajectory_target_change",
    ] = 0

    # Compute the cumulative sum of the change per group
    ls_data_to_not_compensate["asset_trajectory_target_change_cumsum"] = (
        ls_data_to_not_compensate.groupby(group_cols)[
            "asset_trajectory_target_change"
        ].cumsum()
    )

    # Final calculation: add the filled trajectory and cumulative change
    ls_data_to_not_compensate["late_sudden"] = (
        ls_data_to_not_compensate["asset_trajectory_filled"]
        + ls_data_to_not_compensate["asset_trajectory_target_change_cumsum"]
    )

    # Select final output columns
    assets_simply_shocked = ls_data_to_not_compensate[
        ["asset_id", "sector", "technology", "year", "late_sudden"]
    ]

    return assets_simply_shocked


def gather_shock_trajectories(
    assets_compensated_shocked: pd.DataFrame,
    assets_simply_shocked: pd.DataFrame,
    flagged_overshoot: pd.DataFrame,
) -> pd.DataFrame:
    group_cols = ["asset_id", "sector", "technology"]
    # Combine compensated and not compensated
    late_sudden_df = pd.concat(
        [assets_compensated_shocked, assets_simply_shocked], ignore_index=True
    )

    # Merge overshoot_direction
    overshoot_direction = flagged_overshoot[
        ["asset_id", "sector", "technology", "overshoot_direction"]
    ].drop_duplicates()
    late_sudden_df = late_sudden_df.merge(
        overshoot_direction, on=group_cols, how="left"
    )

    traj_assets_shocked = late_sudden_df.rename(
        columns={"late_sudden": "asset_trajectory_shock"}
    )
    return traj_assets_shocked
