# NOTE: this file ships in the export — no absolute internal paths anywhere.
# The full-inputs comparison only runs where ALTR_FULL_INPUTS is set (internal).
import os
from pathlib import Path

import pandas as pd
import pytest
import yaml

DATA = Path(__file__).parent / "data"
FIXTURE_CONF = Path(__file__).resolve().parents[2] / "conf" / "fixture"
FIXTURE_PARAMS = (
    FIXTURE_CONF / "parameters_prepare_scenario_asset_and_company_inputs.yml"
)
_FULL_ENV = os.environ.get("ALTR_FULL_INPUTS", "")
FULL = Path(_FULL_ENV) if _FULL_ENV else None

#: Files the fixture environment reads, under the names main's catalog uses.
LIVE_FILES = ("assets_forecasts.csv", "companies_ownerships.csv", "scenarios.csv")


def test_fixture_files_exist_and_are_small():
    # ar6_carbon_prices.csv is committed but INERT: main's catalog has no
    # `ar6_carbon_prices` dataset (the carbon-price injection it belongs to is
    # not on main), so nothing reads it. It is kept so a ruling that wires the
    # dataset in does not also need the data re-cut.
    for name in (*LIVE_FILES, "ar6_carbon_prices.csv"):
        f = DATA / name
        assert f.exists(), f"missing {name}"
        assert f.stat().st_size < 25_000_000


@pytest.mark.skipif(
    FULL is None or not FULL.is_dir(),
    reason="ALTR_FULL_INPUTS not set (external machine)",
)
def test_fixture_schemas_match_full_inputs():
    # Columns must be identical to the full inputs the pipeline consumes.
    for name in ("assets_forecasts.csv", "companies_ownerships.csv"):
        fix_cols = list(pd.read_csv(DATA / name, nrows=0).columns)
        full_cols = list(pd.read_csv(FULL / name, nrows=0).columns)
        assert fix_cols == full_cols, name


def test_fixture_scenarios_contain_both_pair_members():
    # The pair is not hardcoded here: it is whatever conf/fixture selects, so
    # the slice and the fixture environment cannot drift apart.
    params = yaml.safe_load(FIXTURE_PARAMS.read_text())
    names = set(pd.read_csv(DATA / "scenarios.csv", usecols=["scenario"])["scenario"])
    assert params["baseline_scenario"] in names
    assert params["target_scenario"] in names


def test_fixture_scenarios_use_the_year_column():
    # Main indexes the scenario frame on `year` (`filter_assets` takes
    # `groupby("scenario_type")["year"].min()`); `scenario_year` appears
    # nowhere in src/. A slice carrying the old name fails deep in the run.
    cols = set(pd.read_csv(DATA / "scenarios.csv", nrows=0).columns)
    assert "year" in cols
    assert "scenario_year" not in cols


def test_fixture_scenarios_carry_cost_columns():
    # The pipeline consumes the EXTENDED scenario file (cost columns), not the
    # bare prices/pathways extract. Missing these fails input preparation.
    # Keep this set literally identical to SCENARIOS_REQUIRED's cost block in
    # scripts/prepare_inputs.py.
    cols = set(pd.read_csv(DATA / "scenarios.csv", nrows=0).columns)
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
    comp = pd.read_csv(DATA / "companies_ownerships.csv")
    assets = pd.read_csv(DATA / "assets_forecasts.csv")
    assert set(comp["asset_id"]) <= set(assets["asset_id"])
    assert comp["company_id"].nunique() <= 8


def test_every_fixture_company_survives_consolidation():
    # Main does not select an ownership tier: `filter_companies` calls
    # `_consolidate_ownership_stakes`, which SUMS every stake a company holds
    # in an asset-year. So — unlike the pre-migration pipeline, which dropped
    # equity-only companies under `ownership_type: "direct"` — no fixture
    # company may be lost on the way in. Asserted against main's own function
    # so the fixture cannot drift from the behaviour it feeds.
    from altr_model.pipelines.prepare_scenario_asset_and_company_inputs._input_nodes import (  # noqa: E501
        _consolidate_ownership_stakes,
    )

    comp = pd.read_csv(DATA / "companies_ownerships.csv")
    consolidated = _consolidate_ownership_stakes(comp)
    assert set(consolidated["company_id"]) == set(comp["company_id"])
