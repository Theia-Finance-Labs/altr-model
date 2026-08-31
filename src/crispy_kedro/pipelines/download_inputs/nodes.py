"""BigQuery ingestion (internal-only; not part of the eight ALTR stages).

Each node executes an ``ibis`` table expression bound by the catalog to a
BigQuery table and materialises it as the ``downloaded_*`` CSV inputs that
stage 1 (``inputs_processing``) consumes. External runs skip this pipeline and
produce the same three files with ``scripts/prepare_inputs.py`` instead.
"""

import ibis
import pandas as pd


def download_scenarios(scenarios: ibis.expr.types.Table) -> pd.DataFrame:
    return scenarios.execute()


def download_assets(assets_forecasts: ibis.expr.types.Table) -> pd.DataFrame:
    return assets_forecasts.execute()


def download_companies(plant_ownerships: ibis.expr.types.Table) -> pd.DataFrame:
    return plant_ownerships.execute()
