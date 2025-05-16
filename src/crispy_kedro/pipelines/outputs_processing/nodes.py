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
