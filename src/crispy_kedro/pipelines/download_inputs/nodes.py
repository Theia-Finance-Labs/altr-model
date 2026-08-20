"""
This is a boilerplate pipeline 'download_inputs'
generated using Kedro 0.19.12
"""

import pandas as pd
import ibis


def _execute_with_progress(table: ibis.expr.types.Table) -> pd.DataFrame:
    """Same as ``table.execute()``, but with a live tqdm progress bar.

    Ibis's BigQuery backend hardcodes ``progress_bar_type=None`` when it
    calls ``to_arrow()`` (see ``ibis.backends.bigquery.Backend.execute``),
    so a plain ``.execute()`` downloads silently with no feedback. This
    replicates that method but passes ``progress_bar_type="tqdm"`` through.
    """
    from ibis.backends.bigquery.converter import BigQueryPandasData

    backend = table._find_backend(use_default=True)
    table_expr = table.as_table()
    schema = table_expr.schema() - ibis.schema({"_TABLE_SUFFIX": "string"})
    query = backend._to_query(table_expr)
    df = query.to_arrow(
        progress_bar_type="tqdm", bqstorage_client=backend.storage_client
    ).to_pandas(timestamp_as_object=True)
    df = df.drop(columns="_TABLE_SUFFIX", errors="ignore")
    df.columns = schema.names
    return table_expr.__pandas_result__(df, schema=schema, data_mapper=BigQueryPandasData)


def download_scenarios(scenarios: ibis.expr.types.Table) -> pd.DataFrame:
    return _execute_with_progress(scenarios)


def download_assets(assets_forecasts: ibis.expr.types.Table) -> pd.DataFrame:
    return _execute_with_progress(assets_forecasts)


def download_companies(plant_ownerships: ibis.expr.types.Table) -> pd.DataFrame:
    return _execute_with_progress(plant_ownerships)
