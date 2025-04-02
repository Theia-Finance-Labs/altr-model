import pandas as pd
import ibis
from typing import Tuple


def filter_scenarios(
    scenarios: ibis.expr.types.Table,
    baseline_scenario: str,
    target_scenario: str,
    scenario_geography: str,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    traj_scenario = scenarios.filter(
        scenarios.scenario.isin([baseline_scenario, target_scenario])
        & scenarios.scenario_geography.isin([scenario_geography])
    )
    traj_scenario = traj_scenario.execute()
    return traj_scenario


def calculate_fair_share_perc(
    scenarios: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    # Define the grouping columns
    group_cols = ["scenario", "sector", "scenario_geography", "technology"]

    # Sort the DataFrame by scenario_year so that the first value in each group is the earliest year
    scenarios = scenarios.sort_values("scenario_year")

    # Compute the first scenario_pathway value for each group
    # This ensures we capture the value after sorting by scenario_year
    scenarios["first_pathway"] = scenarios.groupby(group_cols)[
        "scenario_pathway"
    ].transform("first")

    # Calculate tmsr = (scenario_pathway - first_pathway) / first_pathway
    scenarios["tmsr"] = (
        scenarios["scenario_pathway"] - scenarios["first_pathway"]
    ) / scenarios["first_pathway"]

    # Drop the helper column if it's no longer needed
    scenarios = scenarios.drop(columns="first_pathway")

    # Set fair_share_perc equal to tmsr
    scenarios["fair_share_perc"] = scenarios["tmsr"]

    # Replace NaN values (which may appear if first_pathway was zero) with 0
    scenarios["fair_share_perc"] = scenarios["fair_share_perc"].fillna(0)

    scenarios[
        [
            "scenario",
            "scenario_type",
            "sector",
            "technology",
            "technology_type",
            "scenario_year",
            "scenario_pathway",
            "fair_share_perc",
            "scenario_price",
            "scenario_capacity_factor",
        ]
    ]

    scenario_traj_baseline = (
        scenarios.loc[scenarios["scenario_type"] == "baseline"]
        .sort_values(["technology", "scenario_year"])
        .rename(columns={"scenario_year": "year"})
    )

    scenario_traj_target = (
        scenarios.loc[scenarios["scenario_type"] == "target"]
        .sort_values(["technology", "scenario_year"])
        .rename(columns={"scenario_year": "year"})
    )

    return scenario_traj_baseline, scenario_traj_target


def apply_capacity_factors(traj_assets_baseline_clean, traj_assets_target_clean):
    return traj_assets_baseline_prod, traj_assets_target_prod
