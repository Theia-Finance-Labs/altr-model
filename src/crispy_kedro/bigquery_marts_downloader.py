"""Maintainer-only script: download the model's raw input tables from BigQuery.

End users without BigQuery access never run this — they receive the three
CSVs this script produces (``scenarios.csv``, ``assets_forecasts.csv``,
``companies_ownerships.csv`` in ``data/05_model_input/``) through another channel
and place them there directly. Requires the ``bigquery`` dependency group
(``uv sync --group bigquery``), kept out of the default install so end users
don't need any Google Cloud packages.

Reads via the BigQuery Storage API into Arrow batches for a real per-row tqdm
progress bar — plain ``query_job.result().to_dataframe()`` gives no feedback
until the whole table has downloaded. Verifies the streamed row count against
the job's reported total and retries once via the plain REST API if the
Storage API stream came back short. CSVs are written atomically (temp file +
rename) so an interrupted run can't leave a corrupt file at the target path.

Credentials fall back to Application Default Credentials.

Configuration is read from environment variables (see ``BIGQUERY_PROJECT`` /
``BIGQUERY_DATASET`` in ``.env``):
- ``BIGQUERY_PROJECT``: GCP project id (required)
- ``BIGQUERY_DATASET``: dataset holding the three mart tables (required)
"""

from __future__ import annotations

import csv
import logging
import os
import tempfile
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
from dotenv import load_dotenv
from google.cloud import bigquery
from tqdm import tqdm

logger = logging.getLogger("crispy_kedro.bigquery_marts")

load_dotenv()


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


PROJECT_ID = _require_env("BIGQUERY_PROJECT")
MARTS_DATASET = _require_env("BIGQUERY_DATASET")

# output CSV name -> "database.table" (both under PROJECT_ID)
TABLES: dict[str, str] = {
    "scenarios": f"{MARTS_DATASET}.altr_scenarios",
    "assets_forecasts": f"{MARTS_DATASET}.altr_assets_forecasts",
    "companies_ownerships": f"{MARTS_DATASET}.altr_companies_ownership_tree",
}

OUTPUT_DIR = Path("data/05_model_input")


def _cast_decimals_to_float(batch: pa.RecordBatch) -> pa.RecordBatch:
    """Cast Decimal128/256 columns (BigQuery NUMERIC/BIGNUMERIC) to float64."""
    columns = [
        pc.cast(column, pa.float64()) if pa.types.is_decimal(field.type) else column
        for field, column in zip(batch.schema, batch.columns)
    ]
    return pa.RecordBatch.from_arrays(columns, names=batch.schema.names)


def _batches_to_pandas(batches: list[pa.RecordBatch]) -> pd.DataFrame:
    if not batches:
        return pd.DataFrame()
    return pa.Table.from_batches(batches).to_pandas()


def _download_table(
    client: bigquery.Client, fully_qualified_table: str
) -> pd.DataFrame:
    query_job = client.query(f"SELECT * FROM `{fully_qualified_table}`")
    result = query_job.result()
    expected_rows = int(result.total_rows or 0)

    batches: list[pa.RecordBatch] = []
    total_rows = 0
    with tqdm(
        total=expected_rows, unit="rows", unit_scale=True, desc=fully_qualified_table
    ) as pbar:
        for raw_batch in result.to_arrow_iterable():
            batch = _cast_decimals_to_float(raw_batch)
            batches.append(batch)
            total_rows += batch.num_rows
            pbar.update(batch.num_rows)

    if total_rows == expected_rows:
        return _batches_to_pandas(batches)

    logger.warning(
        "%s: Storage API stream returned %d of %d rows; retrying via REST API",
        fully_qualified_table,
        total_rows,
        expected_rows,
    )
    retry_table = result.to_arrow(create_bqstorage_client=False)
    if retry_table.num_rows != expected_rows:
        raise RuntimeError(
            f"{fully_qualified_table}: incomplete download after retry: "
            f"expected {expected_rows} rows, got {retry_table.num_rows}."
        )
    retry_batches = [_cast_decimals_to_float(b) for b in retry_table.to_batches()]
    return _batches_to_pandas(retry_batches)


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    """Write ``df`` to ``path`` atomically so an interrupted run can't leave a corrupt file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        df.to_csv(
            tmp_path,
            index=False,
            quoting=csv.QUOTE_MINIMAL,
            escapechar="\\",
            doublequote=True,
            lineterminator="\n",
        )
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def download_all(output_dir: Path = OUTPUT_DIR) -> dict[str, Path]:
    """Download every table in ``TABLES`` to a CSV in ``output_dir``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    client = bigquery.Client(project=PROJECT_ID)

    paths: dict[str, Path] = {}
    for output_name, table in TABLES.items():
        fully_qualified_table = f"{PROJECT_ID}.{table}"
        logger.info("Downloading %s (%s)", output_name, fully_qualified_table)
        df = _download_table(client, fully_qualified_table)

        path = output_dir / f"{output_name}.csv"
        _write_csv(df, path)
        paths[output_name] = path
        logger.info("Saved %s (%d rows)", path, len(df))

    return paths


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    download_all()
