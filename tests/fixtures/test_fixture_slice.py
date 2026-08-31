# NOTE: this file ships in the export — no absolute internal paths anywhere.
# The full-inputs comparison only runs where ALTR_FULL_INPUTS is set (internal).
import os
from pathlib import Path

import pandas as pd
import pytest
import yaml

DATA = Path(__file__).parent / "data"
FIXTURE_CONF = Path(__file__).resolve().parents[2] / "conf" / "fixture"
_FULL_ENV = os.environ.get("ALTR_FULL_INPUTS", "")
FULL = Path(_FULL_ENV) if _FULL_ENV else None


def test_fixture_files_exist_and_are_small():
    for name in (
        "downloaded_assets.csv",
        "downloaded_companies.csv",
        "downloaded_scenarios.csv",
        "ar6_carbon_prices.csv",
    ):
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
    # The pair is not hardcoded here: it is whatever conf/fixture selects, so
    # the slice and the fixture environment cannot drift apart.
    params = yaml.safe_load(
        (FIXTURE_CONF / "parameters_inputs_processing.yml").read_text()
    )
    df = pd.read_csv(DATA / "downloaded_scenarios.csv")
    col = "scenario" if "scenario" in df.columns else "scenario_name"
    names = set(df[col].unique())
    assert params["baseline_scenario"] in names
    assert params["target_scenario"] in names


def test_fixture_scenarios_carry_cost_columns():
    # The pipeline consumes the EXTENDED scenario file (cost columns), not the
    # bare prices/pathways extract. Missing these fails inputs_processing.
    cols = set(pd.read_csv(DATA / "downloaded_scenarios.csv", nrows=0).columns)
    required = {
        "lifetime_years",
        "efficiency_decimal",
        "capacity_additions_mw_per_yr",
        "om_cost_usd_per_mw_per_yr",
        "capital_cost_usd_per_mw",
        "carbon_price_usd_per_tco2",
        "scrap_usd_per_mw",
        "fuel_price",
    }
    assert required <= cols, sorted(required - cols)


def test_fixture_companies_have_assets():
    comp = pd.read_csv(DATA / "downloaded_companies.csv")
    assets = pd.read_csv(DATA / "downloaded_assets.csv")
    assert set(comp["asset_id"]) <= set(assets["asset_id"])
    assert comp["company_id"].nunique() <= 8


def test_fixture_companies_survive_the_ownership_filter():
    # conf/base runs with ownership_type "direct"; companies with only equity
    # rows are dropped in inputs_processing and never reach the outputs.
    comp = pd.read_csv(DATA / "downloaded_companies.csv")
    direct = comp[comp["ownership_type"] == "direct"]
    assert direct["company_id"].nunique() == comp["company_id"].nunique()
