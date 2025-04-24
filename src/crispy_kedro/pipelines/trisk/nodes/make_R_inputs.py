import ibis
import numpy as np
import pandas as pd


def make_assets_data(
    traj_assets_raw,
    forecast_horizon,
):
    traj_assets_raw_truncated = traj_assets_raw.loc[
        (traj_assets_raw.year <= 2025 + forecast_horizon)
        & (traj_assets_raw.year >= 2025),
    ]

    return traj_assets_raw_truncated


# def compute_plant_age_years(
#     traj_assets_raw_truncated: pd.DataFrame, units_events: ibis.expr.types.Table
# ) -> pd.DataFrame:
#     """
#     Computes the average (capacity-weighted) age of energy production plants (assets)
#     based on past capacity addition events.

#     Parameters
#     ----------
#     traj_assets_raw_truncated : pandas.DataFrame
#         A DataFrame containing asset-year trajectories, with at least the columns:
#         - 'asset_id': unique identifier for the asset
#         - 'year': the scenario year the asset appears in

#     units_events : ibis.expr.types.Table
#         An Ibis table representing historical unit-level events, expected to include:
#         - 'asset_id': identifier matching assets in traj_assets_raw_truncated
#         - 'event_year': the year an event occurred
#         - 'event_type': type of event (e.g. 'add_capacity')
#         - 'capacity_value': the capacity added in the event

#     Returns
#     -------
#     pandas.DataFrame
#         A DataFrame with columns:
#         - 'asset_id': the asset identifier
#         - 'asset_age': the capacity-weighted average age of capacity additions as of 2025

#     Notes
#     -----
#     - Filters events to only include 'add_capacity' before the latest year in the scenario data.
#     - Age is computed as (2025 - event_year).
#     - The result reflects the age of the plant at the reference year 2025.
#     """

#     asset_ids = traj_assets_raw_truncated["asset_id"].unique().tolist()
#     max_year = traj_assets_raw_truncated["year"].max()
#     filtered_events = units_events.filter(
#         units_events.asset_id.isin(asset_ids)
#         & (units_events.event_year < max_year)
#         & (units_events.event_type == "add_capacity")
#     ).execute()

#     filtered_events["event_age"] = 2025 - filtered_events["event_year"]

#     assets_age = (
#         filtered_events.groupby("asset_id")
#         .apply(
#             lambda group: pd.Series(
#                 {
#                     "asset_age": np.ceil(
#                         np.average(group["event_age"], weights=group["capacity_value"])
#                     )
#                 }
#             )
#         )
#         .reset_index()
#     )

#     return assets_age


def make_scenarios_data(scenarios: ibis.expr.types.Table):
    # scenarios_data = scenarios.filter(
    #     scenarios.scenario_provider.contains("GCAM")
    # ).execute()
    scenarios_data = scenarios.execute()
    return scenarios_data


def make_financial_data(
    traj_assets_raw_truncated,
    companies_ownership_tree,
    financial_averages: ibis.expr.types.Table,
):
    financial_averages_df = financial_averages.execute()

    financial_data = (
        companies_ownership_tree[["company_id", "asset_id"]]
        .merge(
            traj_assets_raw_truncated[
                ["asset_id", "technology", "sector"]
            ].drop_duplicates(),
            on=["asset_id"],
        )
        .merge(financial_averages_df, on=["sector", "technology"])
        .groupby(["company_id"])
        .agg(
            {
                "pd": "mean",
                "debt_equity_ratio": "mean",
                "net_profit_margin": "mean",
                "volatility": "mean",
            }
        )
        .reset_index()
    )

    return financial_data
