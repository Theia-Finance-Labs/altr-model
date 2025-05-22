import pandas as pd
import ibis


def make_assets_data(traj_assets_raw: pd.DataFrame, forecast_horizon=5):
    traj_assets_raw = traj_assets_raw.rename(columns={"production_year": "year"})
    traj_assets_raw_truncated = traj_assets_raw.loc[
        (traj_assets_raw.year <= 2025 + forecast_horizon)
        & (traj_assets_raw.year >= 2025),
    ]

    return traj_assets_raw_truncated


def make_scenarios_data(scenarios: pd.DataFrame):
    scenarios_data = scenarios
    return scenarios_data


def make_financial_data(
    traj_assets_raw_truncated: pd.DataFrame,
    companies_ownership_tree: pd.DataFrame,
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
