"""Maintainer-only script: download the model's raw input tables from BigQuery.

End users without BigQuery access never run this — they receive the three
CSVs this script produces (``downloaded_scenarios.csv``, ``downloaded_assets.csv``,
``downloaded_companies.csv`` in ``data/05_model_input/``) through another channel
and place them there directly. Requires the ``bigquery`` dependency group
(``uv sync --group bigquery``), kept out of the default install so end users
don't need any Google Cloud packages.

Reads via the BigQuery Storage API into Arrow batches for a real per-row tqdm
progress bar — plain ``query_job.result().to_dataframe()`` gives no feedback
until the whole table has downloaded.

Credentials fall back to Application Default Credentials.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
from google.cloud import bigquery, bigquery_storage
from tqdm import tqdm

logger = logging.getLogger("crispy_kedro.bigquery_marts")

PROJECT_ID = "cloud-1in1000"

# output CSV name -> "database.table" (both under PROJECT_ID)
TABLES: dict[str, str] = {
    "downloaded_scenarios": "bertrand2_marts.altr_scenarios",
    "downloaded_assets": "bertrand2_marts.altr_assets_forecasts",
    "downloaded_companies": "bertrand2_marts.altr_companies_ownership_tree",
}

OUTPUT_DIR = Path("data/05_model_input")


def _cast_decimals_to_float(batch: pa.RecordBatch) -> pa.RecordBatch:
    """Cast Decimal128/256 columns (BigQuery NUMERIC/BIGNUMERIC) to float64."""
    columns = [
        pc.cast(column, pa.float64()) if pa.types.is_decimal(field.type) else column
        for field, column in zip(batch.schema, batch.columns)
    ]
    return pa.RecordBatch.from_arrays(columns, names=batch.schema.names)


def _download_table(
    client: bigquery.Client,
    storage_client: bigquery_storage.BigQueryReadClient,
    fully_qualified_table: str,
) -> pd.DataFrame:
    query = f"SELECT * FROM `{fully_qualified_table}`"
    (count_row,) = client.query(f"SELECT COUNT(*) AS total_rows FROM ({query})").result()

    query_job = client.query(query)
    batches = query_job.result().to_arrow_iterable(bqstorage_client=storage_client)

    frames: list[pd.DataFrame] = []
    with tqdm(
        total=count_row.total_rows, unit="rows", unit_scale=True, desc=fully_qualified_table
    ) as pbar:
        for batch in batches:
            batch = _cast_decimals_to_float(batch)
            frames.append(batch.to_pandas())
            pbar.update(batch.num_rows)

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def download_all(output_dir: Path = OUTPUT_DIR) -> dict[str, Path]:
    """Download every table in ``TABLES`` to a CSV in ``output_dir``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    client = bigquery.Client(project=PROJECT_ID)
    storage_client = bigquery_storage.BigQueryReadClient(credentials=client._credentials)

    paths: dict[str, Path] = {}
    for output_name, table in TABLES.items():
        fully_qualified_table = f"{PROJECT_ID}.{table}"
        logger.info("Downloading %s (%s)", output_name, fully_qualified_table)
        df = _download_table(client, storage_client, fully_qualified_table)

        path = output_dir / f"{output_name}.csv"
        df.to_csv(path, index=False)
        paths[output_name] = path
        logger.info("Saved %s", path)

    return paths


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    download_all()
