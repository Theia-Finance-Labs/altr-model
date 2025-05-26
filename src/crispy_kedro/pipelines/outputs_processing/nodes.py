"""
This is a boilerplate pipeline 'outputs_processing'
generated using Kedro 0.19.12
"""

import pandas as pd


def compute_npvs(
    traj_companies_net_profits_baseline: pd.DataFrame,
    traj_companies_net_profits_shock: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compute total NPV without terminal value

    Parameters:
      traj_companies_net_profits_baseline: DataFrame with discounted baseline profits
      traj_companies_net_profits_shock: DataFrame with discounted shock profits

    Returns:
      DataFrame with NPV calculations including baseline, shock, difference and change
    """

    companies_net_profits_baseline = (
        traj_companies_net_profits_baseline[
            traj_companies_net_profits_baseline["year"]
            < traj_companies_net_profits_baseline["year"].max()
        ]
        .groupby(["company_id", "sector", "technology"])
        .agg({"discounted_net_profit_baseline": "sum"})
        .rename(
            columns={"discounted_net_profit_baseline": "net_present_value_baseline"}
        )
        .reset_index()
    )

    companies_net_profits_shock = (
        traj_companies_net_profits_shock[
            traj_companies_net_profits_shock["year"]
            < traj_companies_net_profits_shock["year"].max()
        ]
        .groupby(["company_id", "sector", "technology"])
        .agg({"discounted_net_profit_shock": "sum"})
        .rename(columns={"discounted_net_profit_shock": "net_present_value_shock"})
        .reset_index()
    )

    companies_net_profits = pd.merge(
        companies_net_profits_baseline,
        companies_net_profits_shock,
        on=["company_id", "sector", "technology"],
    )

    companies_npvs = companies_net_profits.assign(
        net_present_value_difference=lambda x: x["net_present_value_shock"]
        - x["net_present_value_baseline"],
        net_present_value_change=lambda x: x["net_present_value_difference"]
        / x["net_present_value_baseline"],
    )

    return companies_npvs
