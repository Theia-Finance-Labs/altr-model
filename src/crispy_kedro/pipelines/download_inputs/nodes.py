"""
This is a boilerplate pipeline 'download_inputs'
generated using Kedro 0.19.12
"""

import pandas as pd
import ibis


def download_scenarios(scenarios: ibis.expr.types.Table) -> pd.DataFrame:
    return scenarios.execute()


def download_assets(assets_forecasts: ibis.expr.types.Table) -> pd.DataFrame:
    return assets_forecasts.execute()


def download_companies(plant_ownerships: ibis.expr.types.Table) -> pd.DataFrame:
    return plant_ownerships.execute()


def download_ar6_prices(ar6_prices: ibis.expr.types.Table) -> pd.DataFrame:
    return ar6_prices.execute()
