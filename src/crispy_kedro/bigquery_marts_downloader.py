"""Download BigQuery mart tables to local Parquet files.

Adapted from crispy-datamodels-viewer's ``BigQueryManager``: chunked reads
via the BigQuery Storage API into Arrow batches, decimal-to-float64 casting
for pandas compatibility, tqdm progress. Scoped to this project's catalog
tables (see ``conf/base/catalog.yml``), which live in the ``bertrand2_marts``
and ``bertrand_marts`` BigQuery datasets under project ``cloud-1in1000``.

Gives visible per-row progress for a download that, via ibis's
``Table.execute()`` (used in ``pipelines/download_inputs/nodes.py``), runs
silently until the whole table has been fetched.

``BigQueryMartsDownloader`` takes project/dataset/credentials as explicit
constructor arguments; it never reads config or the environment itself.
Credentials fall back to Application Default Credentials (the
``GOOGLE_APPLICATION_CREDENTIALS`` path already set in ``.env``) when
``credentials_path`` is not given.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from google.cloud import bigquery, bigquery_storage
from google.oauth2 import service_account
from tqdm import tqdm

logger = logging.getLogger("crispy_kedro.bigquery_marts")


class BigQueryMartsDownloader:
    """Downloads the configured marts tables to local Parquet files."""

    def __init__(
        self,
        project_id: str,
        dataset: str,
        dataset_schema: str,
        tables: list[str],
        output_dir: Path | str,
        credentials_path: Path | str | None,
    ) -> None:
        self.project_id = project_id
        self.dataset = f"{dataset}_{dataset_schema}"
        self.tables = tables
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.credentials_path = credentials_path
        self._client: bigquery.Client | None = None

    def _get_client(self) -> bigquery.Client:
        if self._client is None:
            if self.credentials_path is not None:
                credentials = service_account.Credentials.from_service_account_file(
                    self.credentials_path
                )
                self._client = bigquery.Client(
                    project=self.project_id, credentials=credentials
                )
            else:
                self._client = bigquery.Client(project=self.project_id)
        return self._client

    def output_path_for_table(self, table: str) -> Path:
        return self.output_dir / f"{table}.parquet"

    def _fully_qualified_table(self, table: str) -> str:
        return f"{self.project_id}.{self.dataset}.{table}"

    @staticmethod
    def _cast_decimals_to_float(batch: pa.RecordBatch) -> pa.RecordBatch:
        """Cast Decimal128/256 columns (BigQuery NUMERIC/BIGNUMERIC) to float64."""
        columns = []
        names = []
        for i, field in enumerate(batch.schema):
            column = batch.column(i)
            if pa.types.is_decimal(field.type):
                column = pc.cast(column, pa.float64())
            columns.append(column)
            names.append(field.name)
        return pa.RecordBatch.from_arrays(columns, names=names)

    def _row_count(self, query: str) -> int:
        client = self._get_client()
        (row,) = client.query(f"SELECT COUNT(*) AS total_rows FROM ({query})").result()
        return row.total_rows

    def download_table(self, table: str, *, refresh: bool = False) -> Path:
        """Download one mart table to Parquet, skipping if already cached locally."""
        output_path = self.output_path_for_table(table)
        if output_path.exists() and not refresh:
            logger.info("Using cached %s", output_path)
            return output_path

        client = self._get_client()
        query = f"SELECT * FROM `{self._fully_qualified_table(table)}`"
        total_rows = self._row_count(query)

        query_job = client.query(query)
        bqstorage_client = bigquery_storage.BigQueryReadClient(credentials=client._credentials)
        batches = query_job.result().to_arrow_iterable(bqstorage_client=bqstorage_client)

        writer: pq.ParquetWriter | None = None
        pbar = tqdm(total=total_rows, unit="rows", desc=f"Downloading {table}", unit_scale=True)
        try:
            for batch in batches:
                batch = self._cast_decimals_to_float(batch)
                if writer is None:
                    writer = pq.ParquetWriter(output_path, batch.schema)
                writer.write_batch(batch)
                pbar.update(batch.num_rows)
        finally:
            if writer:
                writer.close()
            pbar.close()

        logger.info("Downloaded %s to %s", table, output_path)
        return output_path

    def download_all(self, *, refresh: bool = False) -> dict[str, Path]:
        """Download every configured marts table; returns table name -> Parquet path."""
        return {table: self.download_table(table, refresh=refresh) for table in self.tables}

    def read_table(self, table: str, *, refresh: bool = False) -> pd.DataFrame:
        """Download (if needed) and load a mart table as a pandas DataFrame."""
        return pd.read_parquet(self.download_table(table, refresh=refresh))


def _default_downloaders(output_dir: Path | str = "data/01_raw") -> list[BigQueryMartsDownloader]:
    """Downloaders for the tables declared in ``conf/base/catalog.yml``."""
    project_id = "cloud-1in1000"
    return [
        BigQueryMartsDownloader(
            project_id=project_id,
            dataset="bertrand2",
            dataset_schema="marts",
            tables=["assets_forecasts", "companies_ownership_tree", "scenarios"],
            output_dir=output_dir,
            credentials_path=None,
        ),
        BigQueryMartsDownloader(
            project_id=project_id,
            dataset="bertrand",
            dataset_schema="marts",
            tables=["financial_averages"],
            output_dir=output_dir,
            credentials_path=None,
        ),
    ]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for downloader in _default_downloaders():
        downloader.download_all()
