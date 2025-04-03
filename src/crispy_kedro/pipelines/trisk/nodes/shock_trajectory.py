import numpy as np
import pandas as pd


def compute_proximity_to_target(truncated_traj_assets_raw, traj_assets_target_clean):

    # Determine the last year with non-NA production for each group
    last_non_na = (
        truncated_traj_assets_raw.groupby(["asset_id", "sector", "technology"])
        .apply(lambda x: x.loc[x["asset_trajectory"].notna(), "year"].max())
        .reset_index(name="last_non_na_year")
    )

    # Merge and filter data
    merged = truncated_traj_assets_raw.merge(
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


def split_assets_per_shock_type(truncated_traj_assets_raw, traj_assets_target_prod):

    data = pd.merge(
        truncated_traj_assets_raw,
        traj_assets_target_prod,
        how="inner",
        on=["asset_id", "sector", "technology", "year"],
    )

    # Select relevant columns
    late_sudden_data = data[
        [
            "asset_id",
            "year",
            "sector",
            "technology",
            "asset_trajectory",  # production_plan_company_technology
            "asset_trajectory_target",  # production_scenario_target
        ]
    ]

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
    ].fillna(method="ffill")

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
    assets_to_compensate = flagged_overshoot.loc[
        flagged_overshoot["requires_overshoot_correction"], "asset_id"
    ]
    assets_to_simple_shock = flagged_overshoot.loc[
        ~flagged_overshoot["requires_overshoot_correction"], "asset_id"
    ]

    return assets_to_compensate, assets_to_simple_shock


def apply_compensation_shock(
    assets_to_compensate, traj_assets_baseline_prod, traj_assets_target_prod
):
    return assets_compensated_shocked


def apply_simple_shock(
    assets_to_simple_shock, traj_assets_baseline_prod, traj_assets_target_prod
):
    return assets_simply_shocked


def gather_shock_trajectories(assets_compensated_shocked, assets_simply_shocked):
    return traj_assets_shocked
