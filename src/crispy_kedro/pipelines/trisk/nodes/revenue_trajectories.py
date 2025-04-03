import pandas as pd
import numpy as np


def build_price_trajectory(traj_scenario, shock_year):

    # Part 1: years > shock_year -1 (i.e., years >= shock_year)
    after_shock_target = traj_scenario.loc[
        (traj_scenario["scenario_year"] >= shock_year)
        & (traj_scenario["scenario_type"] == "target"),
        ["sector", "technology", "scenario_year", "scenario_price"],
    ].rename(
        columns={"scenario_year": "year", "scenario_price": "scenario_price_target"}
    )

    after_shock_baseline = traj_scenario.loc[
        (traj_scenario["scenario_year"] >= shock_year)
        & (traj_scenario["scenario_type"] == "baseline"),
        ["sector", "technology", "scenario_year", "scenario_price"],
    ].rename(
        columns={"scenario_year": "year", "scenario_price": "scenario_price_baseline"}
    )
    after_shock = pd.merge(
        after_shock_target,
        after_shock_baseline,
        how="inner",
        on=["sector", "technology", "year"],
    )

    after_shock_sorted = after_shock.sort_values(["sector", "technology", "year"])

    # Group and summarize to get baseline and target prices
    summary = (
        after_shock_sorted.groupby(["sector", "technology"])
        .agg(
            baseline_price_at_shock=("scenario_price_baseline", "first"),
            target_price_end_shockperiod=("scenario_price_target", "last"),
            first_year=("year", "min"),
            last_year=("year", "max"),
        )
        .reset_index()
    )

    # Function to interpolate prices
    def interpolate_prices(row):
        first_year = row["first_year"] + 1
        last_year = row["last_year"]
        if first_year > last_year:
            return pd.DataFrame(
                columns=["asset_id", "sector", "technology"]
                + ["year", "late_sudden_price"]
            )
        years = list(range(int(first_year), int(last_year) + 1))
        baseline = row["baseline_price_at_shock"]
        target = row["target_price_end_shockperiod"]
        if first_year == last_year:
            prices = [target]
        else:
            prices = np.linspace(
                baseline, target, num=(int(last_year) - int(first_year) + 1)
            )
        df = pd.DataFrame(
            {
                "sector": row["sector"],
                "technology": row["technology"],
                "year": years,
                "late_sudden_price": prices,
            }
        )
        return df

    # Apply interpolation
    interpolated_prices = summary.apply(interpolate_prices, axis=1).tolist()
    interpolated_prices = (
        pd.concat(interpolated_prices, ignore_index=True)
        if interpolated_prices
        else pd.DataFrame()
    )
    # Part 2: years <= shock_year
    before_shock = traj_scenario.loc[
        (traj_scenario["scenario_year"] <= shock_year)
        & (traj_scenario["scenario_type"] == "baseline"),
        ["sector", "technology", "scenario_year", "scenario_price"],
    ].rename(columns={"scenario_year": "year", "scenario_price": "late_sudden_price"})

    # Combine both parts
    final_result = pd.concat([before_shock, interpolated_prices], ignore_index=True)

    # Select relevant columns
    traj_technology_prices = final_result[
        ["sector", "technology", "year", "late_sudden_price"]
    ]

    return traj_technology_prices


def filter_companies(plant_ownerships, filtered_plant_detail):
    filtered_assets = filtered_plant_detail["asset_id"].unique()
    plant_ownership_df = plant_ownerships.filter(
        plant_ownerships.asset_id.isin(filtered_assets)
    ).execute()

    # TODO : APPLY OWNERSHIP TREE ACCORDING TO EVENTS
    # Step 1: aggregate ownership by asset and company
    companies_ownership_tree = plant_ownership_df.groupby(
        ["asset_id", "owner_name", "company_id"], as_index=False
    ).agg({"ownership_percentage": "sum"})

    # Step 2: normalize ownership per asset
    companies_ownership_tree["normalized_ownership"] = (
        companies_ownership_tree["ownership_percentage"]
        / companies_ownership_tree.groupby("asset_id")[
            "ownership_percentage"
        ].transform("sum")
    ).astype(float)

    return companies_ownership_tree[
        ["asset_id", "owner_name", "company_id", "normalized_ownership"]
    ]


def allocate_production_to_companies(companies_ownership_tree, traj_assets_shocked):
    # Merge the asset shock data with company ownership info on asset_id
    traj_companies_shock = traj_assets_shocked.merge(
        companies_ownership_tree[["asset_id", "company_id", "normalized_ownership"]],
        on="asset_id",
        how="inner",
    )

    # Allocate asset shock to companies based on their normalized ownership
    traj_companies_shock["allocated_trajectory_shock"] = (
        traj_companies_shock["asset_trajectory_shock"]
        * traj_companies_shock["normalized_ownership"]
    )

    # Group by company, sector, technology, and year, summing the allocated shocks
    traj_companies_shock = (
        traj_companies_shock.groupby(
            ["company_id", "sector", "technology", "year"], as_index=False
        )["allocated_trajectory_shock"]
        .sum()
        .rename(columns={"allocated_trajectory_shock": "company_trajectory_shock"})
        .loc[
            :,
            ["company_id", "sector", "technology", "year", "company_trajectory_shock"],
        ]
    )

    return traj_companies_shock


def calculate_net_profits(
    financial_averages,
    traj_companies_shock,
    traj_technology_prices,
):
    financial_averages_df = financial_averages.execute()
    financial_averages_df["net_profit_margin"] = financial_averages_df[
        "net_profit_margin"
    ].astype(float)

    # Merge back to traj_companies_revenue
    traj_companies_revenue = traj_companies_shock.merge(
        traj_technology_prices, on=["sector", "technology", "year"], how="inner"
    ).merge(financial_averages_df, on=["sector", "technology"], how="inner")

    traj_companies_revenue["net_profits_shock"] = (
        traj_companies_revenue["company_trajectory_shock"]
        * traj_companies_revenue["late_sudden_price"]
        * traj_companies_revenue["net_profit_margin"]
    )
    return traj_companies_revenue


def calculate_annual_profits(traj_companies_net_profits):
    return traj_companies_net_profits
