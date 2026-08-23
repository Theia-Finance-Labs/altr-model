"""Maintainer-only script: download the model's raw input tables from BigQuery.

End users without BigQuery access never run this — they receive the three
CSVs this script produces (``downloaded_scenarios.csv``, ``downloaded_assets.csv``,
``downloaded_companies.csv`` in ``data/05_model_input/``) through another channel
and place them there directly. Requires the ``bigquery`` dependency group
(``uv sync --group bigquery``), kept out of the default install so end users
don't need ibis/google-cloud-bigquery.

Uses ibis's ``Table.execute()`` with a live tqdm progress bar. Ibis's BigQuery
backend hardcodes ``progress_bar_type=None`` in its own ``execute()``, so a
plain ``.execute()`` would download silently until the whole table is fetched;
``_execute_with_progress`` replicates that method but passes
``progress_bar_type="tqdm"`` through.

Credentials fall back to Application Default Credentials.
"""

from __future__ import annotations

import logging
from pathlib import Path

import ibis
import pandas as pd

logger = logging.getLogger("crispy_kedro.bigquery_marts")

PROJECT_ID = "cloud-1in1000"

# output CSV name -> (BigQuery table name, database)
TABLES: dict[str, tuple[str, str]] = {
    "downloaded_scenarios": ("altr_scenarios", "bertrand2_marts"),
    "downloaded_assets": ("altr_assets_forecasts", "bertrand2_marts"),
    "downloaded_companies": ("altr_companies_ownership_tree", "bertrand2_marts"),
}

OUTPUT_DIR = Path("data/05_model_input")


def _execute_with_progress(table: ibis.expr.types.Table) -> pd.DataFrame:
    """Same as ``table.execute()``, but with a live tqdm progress bar."""
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


def download_all(output_dir: Path = OUTPUT_DIR) -> dict[str, Path]:
    """Download every table in ``TABLES`` to a CSV in ``output_dir``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    connection = ibis.bigquery.connect(project_id=PROJECT_ID)

    paths: dict[str, Path] = {}
    for output_name, (table_name, database) in TABLES.items():
        logger.info("Downloading %s (%s.%s)", output_name, database, table_name)
        table = connection.table(table_name, database=database)
        df = _execute_with_progress(table)

        path = output_dir / f"{output_name}.csv"
        df.to_csv(path, index=False)
        paths[output_name] = path
        logger.info("Saved %s", path)

    return paths


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    download_all()
