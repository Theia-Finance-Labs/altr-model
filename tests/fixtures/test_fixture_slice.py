# NOTE: this file ships in the export — no absolute internal paths anywhere.
# The full-inputs comparison only runs where ALTR_FULL_INPUTS is set (internal).
import os
from pathlib import Path

import pandas as pd
import pytest

DATA = Path(__file__).parent / "data"
_FULL_ENV = os.environ.get("ALTR_FULL_INPUTS", "")
FULL = Path(_FULL_ENV) if _FULL_ENV else None


def test_fixture_files_exist_and_are_small():
    for name in ("downloaded_assets.csv", "downloaded_companies.csv", "downloaded_scenarios.csv"):
        f = DATA / name
        assert f.exists(), f"missing {name}"
        assert f.stat().st_size < 25_000_000


@pytest.mark.skipif(
    FULL is None or not FULL.is_dir(),
    reason="ALTR_FULL_INPUTS not set (external machine)",
)
def test_fixture_schemas_match_full_inputs():
    # Columns must be identical to the full inputs the pipeline consumes.
    for name in ("downloaded_assets.csv", "downloaded_companies.csv"):
        fix_cols = list(pd.read_csv(DATA / name, nrows=0).columns)
        full_cols = list(pd.read_csv(FULL / name, nrows=0).columns)
        assert fix_cols == full_cols, name


def test_fixture_scenarios_contain_both_pair_members():
    df = pd.read_csv(DATA / "downloaded_scenarios.csv")
    col = "scenario" if "scenario" in df.columns else "scenario_name"
    names = set(df[col].unique())
    assert any("CO_CurPol" in n or "CO_BAU" in n for n in names)
    assert any("CO_2Deg2030" in n or "CO_2Deg2020" in n for n in names)


def test_fixture_companies_have_assets():
    comp = pd.read_csv(DATA / "downloaded_companies.csv")
    assets = pd.read_csv(DATA / "downloaded_assets.csv")
    assert set(comp["asset_id"]) <= set(assets["asset_id"])
    assert comp["company_id"].nunique() <= 8
