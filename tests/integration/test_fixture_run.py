"""THE regression gate: full pipeline on the committed fixture slice.

Run after every refactor task. Asserts the ``altrisk`` run completes and that
the shape *and* the headline numbers of the persisted outputs are unchanged.

What is pinned here is the behavioural contract every later task must keep:

* ``company_npv``   — final valuation table: columns, row count, NPV values
  at ``rtol=1e-9``. Any numeric drift anywhere upstream lands here.
* ``asset_npv``     — valuation_model output surface (Task 8 gate), plus the
  NPV pair of one asset per company: the company totals alone would not notice
  values moving between two assets of the same company.
* ``asset_earnings`` — earnings_model output surface (Task 6 gate), plus the
  FCFF total of three assets, for the same reason one stage earlier.
* ``asset_level_staggered_shock`` — distribute_impacts output surface
  (Task 7 gate).

The column lists and counts below were captured verbatim from the first
successful fixture run. Re-pin them ONLY when the fixture inputs change.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from kedro.framework.session import KedroSession
from kedro.framework.startup import bootstrap_project

PROJECT = Path(__file__).resolve().parents[2]
FIXTURE_OUT = PROJECT / "data" / "fixture_run"
MODEL_OUT = FIXTURE_OUT / "07_model_output"

COMPANY_NPV_COLUMNS = [
    "company_id",
    "company_name",
    "baseline_npv",
    "latesudden_npv",
    "baseline_discount_rate",
    "latesudden_discount_rate",
    "asset_count",
    "npv_change",
]

# company_id -> (baseline_npv, latesudden_npv), sorted by company_id.
COMPANY_NPV_VALUES = {
    "CN_3371785431787292505": (-4993101829.613025, -7097823755.342254),
    "CN_6166477550945836346": (7561824575.349691, 12858758761.724388),
    "CN_6488161088428600082": (-18280161120.13081, -71108467857.10239),
    "CN_8676642915009364747": (5642084833.022628, -6357381430.212816),
    "CP_3685197042895689972": (14241241560.29177, 43511299210.83598),
}

ASSET_NPV_COLUMNS = [
    "asset_id",
    "asset_name",
    "company_id",
    "company_name",
    "scenario_geography",
    "sector",
    "technology",
    "is_synthetic",
    "alignment_type",
    "baseline_npv",
    "latesudden_npv",
    "baseline_discount_rate",
    "latesudden_discount_rate",
    "baseline_FCFF",
    "latesudden_FCFF",
    "baseline_EBITDA",
    "latesudden_EBITDA",
    "baseline_revenue",
    "latesudden_revenue",
    "baseline_var_cost",
    "latesudden_var_cost",
    "baseline_fixed_cost",
    "latesudden_fixed_cost",
    "baseline_carbon_cost_net",
    "latesudden_carbon_cost_net",
    "baseline_capex_total",
    "latesudden_capex_total",
    "npv_change",
]
ASSET_NPV_ROWS = 721

# asset_id -> (baseline_npv, latesudden_npv), one asset per fixture company.
# The company totals above survive any reshuffle *within* a company, so these
# pin the asset level itself: a value that moves from one asset to another
# lands here. Captured verbatim from the fixture run, like everything else in
# this file — re-pin ONLY when the fixture inputs change.
ASSET_NPV_VALUES = {
    "INTERNAL_A_L100000100038_int_ast_power_gem_stage2": (
        254043761.0520262,
        -243341054.52987105,
    ),
    "INTERNAL_A_L100000101856_int_ast_power_gem_stage2": (
        -958591367.5157268,
        -1831803226.303148,
    ),
    "INTERNAL_A_L100000102910_int_ast_power_gem_stage2": (
        2079762157.3295617,
        -1893563716.853532,
    ),
    "INTERNAL_A_L100000103087_int_ast_power_gem_stage2_GasCap": (
        -96965768.51927318,
        -137950223.50345284,
    ),
    "INTERNAL_A_L100000201220_int_ast_power_gem_stage2": (
        -33179888.457690075,
        -53702645.06381515,
    ),
}

ASSET_EARNINGS_COLUMNS = [
    "asset_id",
    "asset_name",
    "company_id",
    "company_name",
    "scenario",
    "scenario_type",
    "scenario_geography",
    "sector",
    "technology",
    "year",
    "is_synthetic",
    "trajectory_type",
    "asset_trajectory",
    "capacity_factor",
    "alignment_type",
    "Q",
    "revenue",
    "var_cost",
    "fixed_cost",
    "carbon_cost_net",
    "EBITDA",
    "capex_total",
    "FCFF",
]
ASSET_EARNINGS_ROWS = 37492

# asset_id -> FCFF summed over that asset's rows. Same purpose one stage
# earlier: the row count above cannot see two assets trading cash flows.
# Re-pin ONLY when the fixture inputs change.
ASSET_EARNINGS_FCFF = {
    "INTERNAL_A_L100000100038_int_ast_power_gem_stage2": -375313785.80580044,
    "INTERNAL_A_L100000101856_int_ast_power_gem_stage2": -4364579162.536558,
    "INTERNAL_A_L100000102910_int_ast_power_gem_stage2": -3898950156.932099,
}

STAGGERED_SHOCK_COLUMNS = [
    "asset_id",
    "asset_name",
    "company_id",
    "company_name",
    "scenario_geography",
    "sector",
    "technology",
    "year",
    "asset_age",
    "capacity_before_shock",
    "allocated_shock",
    "capacity_after_shock",
    "is_synthetic",
    "late_sudden_phase",
    "alignment_type",
    "asset_baseline_trajectory",
]
STAGGERED_SHOCK_ROWS = 18746


@pytest.fixture(scope="module")
def fixture_run():
    bootstrap_project(PROJECT)
    with KedroSession.create(project_path=PROJECT, env="fixture") as session:
        return session.run(tags=["altrisk"])


def _read(name: str) -> pd.DataFrame:
    path = MODEL_OUT / f"{name}.csv"
    assert path.exists(), f"fixture run did not produce {path}"
    return pd.read_csv(path, low_memory=False)


def test_full_pipeline_on_fixture(fixture_run):
    assert fixture_run is not None
    assert list(FIXTURE_OUT.rglob("*.csv")), "fixture run produced no CSV outputs"


def test_valuation_output_shape_stable(fixture_run):
    company_npv = _read("company_npv").sort_values("company_id").reset_index(drop=True)
    assert list(company_npv.columns) == COMPANY_NPV_COLUMNS
    assert list(company_npv["company_id"]) == sorted(COMPANY_NPV_VALUES)

    for _, row in company_npv.iterrows():
        expected_baseline, expected_shock = COMPANY_NPV_VALUES[row["company_id"]]
        assert row["baseline_npv"] == pytest.approx(expected_baseline, rel=1e-9)
        assert row["latesudden_npv"] == pytest.approx(expected_shock, rel=1e-9)

    asset_npv = _read("asset_npv")
    assert list(asset_npv.columns) == ASSET_NPV_COLUMNS
    assert len(asset_npv) == ASSET_NPV_ROWS
    for col in ("baseline_npv", "latesudden_npv"):
        assert np.isfinite(asset_npv[col]).all(), f"{col} has non-finite values"

    for asset_id, (expected_baseline, expected_shock) in ASSET_NPV_VALUES.items():
        rows = asset_npv.loc[asset_npv["asset_id"] == asset_id]
        assert len(rows) == 1, f"{asset_id}: expected 1 row, found {len(rows)}"
        row = rows.iloc[0]
        assert row["baseline_npv"] == pytest.approx(expected_baseline, rel=1e-9)
        assert row["latesudden_npv"] == pytest.approx(expected_shock, rel=1e-9)


def test_earnings_output_shape_stable(fixture_run):
    earnings = _read("asset_earnings")
    assert list(earnings.columns) == ASSET_EARNINGS_COLUMNS
    assert len(earnings) == ASSET_EARNINGS_ROWS
    assert np.isfinite(earnings["FCFF"]).all(), "FCFF has non-finite values"

    fcff_by_asset = earnings.groupby("asset_id")["FCFF"].sum()
    for asset_id, expected in ASSET_EARNINGS_FCFF.items():
        assert asset_id in fcff_by_asset.index, f"{asset_id} missing from earnings"
        assert fcff_by_asset[asset_id] == pytest.approx(expected, rel=1e-9)


def test_asset_distribution_output_shape_stable(fixture_run):
    shock = _read("asset_level_staggered_shock")
    assert list(shock.columns) == STAGGERED_SHOCK_COLUMNS
    assert len(shock) == STAGGERED_SHOCK_ROWS
