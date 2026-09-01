"""THE regression gate: the model pipelines on the committed fixture slice.

Run after every refactor task. Asserts the run completes and that the shape
*and* the headline numbers of the persisted outputs are unchanged.

The reporting pipeline is excluded: `plot_transition_risk_results` writes its
plots and tables to hardcoded `data/08_reporting/...` paths that config cannot
redirect, so a fixture run of it would escape the quarantine. Selecting by tag
is how the codebase itself draws that line — the five model pipelines are
tagged `altrisk` and the plotting one `reporting` — and it is the same
selection `kedro run --tags altrisk` gives a user, so this gate exercises the
documented path rather than a parallel one.

They run as ONE session because they hand off through MemoryDatasets
(`company_projection_inputs`, `company_pathways_pre_allocation`), which do not
survive a session boundary.

What is pinned here is the behavioural contract every later task must keep:

* ``company_npv``   — final valuation table: columns, row count, NPV values
  at ``rtol=1e-9``. Any numeric drift anywhere upstream lands here.
* ``asset_npv``     — valuation output surface, plus the NPV pair of one asset
  per company: the company totals alone would not notice values moving between
  two assets of the same company.
* ``asset_earnings`` — earnings output surface, plus the FCFF total of three
  assets, for the same reason one stage earlier.
* ``asset_trajectories`` — the allocation stage's canonical output surface.
  (The pre-migration gate pinned ``asset_level_staggered_shock`` here; main
  retired that dataset — it is in ``tests/test_run.py``'s ``REMOVED_DATASETS``
  — and ``asset_trajectories`` is the surface that replaced it.)

Asset-level pins are keyed on ``(asset_id, company_id)``, not ``asset_id``:
main's asset tables carry one row per owning company, so ``asset_id`` alone is
not unique (841 of 2274 ``asset_npv`` rows repeat one).

The column lists and counts below were RE-DERIVED from a run of this tree on
this fixture slice — never copied from the pre-migration branch. Re-pin them
ONLY when the fixture inputs change.

The slice itself was re-cut on 2026-09-01 onto the FIVE COMPANIES the handover
branch's committed slice holds (``make_fixture_slice.COMMITTED_COMPANY_IDS``),
so that the two branches' fixture outputs are comparable company for company —
the behaviour-equivalence bar in the owner ruling of the same date
(docs/superpowers/plans/implementation-notes-handover.md, "Owner decisions
2026-09-01", item 3).
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
    "CN_3371785431787292505": (14444851383.538136, 19770203481.453262),
    "CN_6166477550945836346": (32895227587.00516, 38653047868.446045),
    "CN_6488161088428600082": (166617808558.14053, 178362502684.41144),
    "CN_8676642915009364747": (15848006141.37615, 11041375998.798037),
    "CP_3685197042895689972": (83282487176.45253, 101583595057.26031),
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
ASSET_NPV_ROWS = 1591

# (asset_id, company_id) -> (baseline_npv, latesudden_npv), one per company.
# The company totals above survive any reshuffle *within* a company, so these
# pin the asset level itself: a value that moves from one asset to another
# lands here.
ASSET_NPV_VALUES = {
    (
        "INTERNAL_A_L100000100038_int_ast_power_gem_stage2",
        "CN_3371785431787292505",
    ): (438641600.3250352, 160814261.16432664),
    (
        "INTERNAL_A_L100000201220_int_ast_power_gem_stage2",
        "CN_6166477550945836346",
    ): (-16061995.104730489, -37950247.25718575),
    (
        "INTERNAL_A_L100000100647_int_ast_power_gem_stage2",
        "CN_6488161088428600082",
    ): (-23952871.940641385, -137750029.86188442),
    (
        "INTERNAL_A_L100000102814_int_ast_power_gem_stage2",
        "CN_8676642915009364747",
    ): (471916.3127151702, -106937.43187820396),
    (
        "INTERNAL_A_L100000100087_int_ast_power_gem_stage2_GasCap",
        "CP_3685197042895689972",
    ): (25743371.13094669, -76527953.31856209),
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
    "asset_age",
    "capacity_factor",
    "alignment_type",
    "late_sudden_phase",
    "Q",
    "revenue",
    "var_cost",
    "fixed_cost",
    "carbon_cost_net",
    "EBITDA",
    "capex_total",
    "FCFF",
]
ASSET_EARNINGS_ROWS = 82732

# (asset_id, company_id) -> FCFF summed over that pair's rows. Same purpose one
# stage earlier: the row count above cannot see two assets trading cash flows.
ASSET_EARNINGS_FCFF = {
    (
        "INTERNAL_A_L100000100038_int_ast_power_gem_stage2",
        "CN_3371785431787292505",
    ): 852382247.4900097,
    (
        "INTERNAL_A_L100000201220_int_ast_power_gem_stage2",
        "CN_6166477550945836346",
    ): -118020727.60238393,
    (
        "INTERNAL_A_L100000100647_int_ast_power_gem_stage2",
        "CN_6488161088428600082",
    ): -458316739.2883063,
}

ASSET_TRAJECTORIES_COLUMNS = [
    "asset_id",
    "asset_name",
    "company_id",
    "company_name",
    "scenario_geography",
    "sector",
    "technology",
    "year",
    "asset_age",
    "is_synthetic",
    "late_sudden_phase",
    "alignment_type",
    "trajectory_type",
    "asset_trajectory",
    "emission_factor",
    "retirement_year",
    "asset_lifetime_years",
    "scenario_type",
    "scenario",
    "power_price_excarbon_usd_per_mwh",
    "fuel_price_usd_per_mwh_fuel",
    "capacity_factor",
    "capex_usd_per_mw",
    "fom_usd_per_mw_yr",
    "carbon_price_usd_per_tco2",
    "efficiency_decimal",
    "lifetime_years",
    "scrap_usd_per_mw",
    "increasing",
    "aligned",
]
ASSET_TRAJECTORIES_ROWS = 82732


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

    for (asset_id, company_id), expected in ASSET_NPV_VALUES.items():
        rows = asset_npv.loc[
            (asset_npv["asset_id"] == asset_id)
            & (asset_npv["company_id"] == company_id)
        ]
        assert len(rows) == 1, (
            f"{asset_id}/{company_id}: expected 1 row, found {len(rows)}"
        )
        row = rows.iloc[0]
        assert row["baseline_npv"] == pytest.approx(expected[0], rel=1e-9)
        assert row["latesudden_npv"] == pytest.approx(expected[1], rel=1e-9)


def test_earnings_output_shape_stable(fixture_run):
    earnings = _read("asset_earnings")
    assert list(earnings.columns) == ASSET_EARNINGS_COLUMNS
    assert len(earnings) == ASSET_EARNINGS_ROWS
    assert np.isfinite(earnings["FCFF"]).all(), "FCFF has non-finite values"

    fcff = earnings.groupby(["asset_id", "company_id"])["FCFF"].sum()
    for key, expected in ASSET_EARNINGS_FCFF.items():
        assert key in fcff.index, f"{key} missing from earnings"
        assert fcff[key] == pytest.approx(expected, rel=1e-9)


def test_asset_allocation_output_shape_stable(fixture_run):
    trajectories = _read("asset_trajectories")
    assert list(trajectories.columns) == ASSET_TRAJECTORIES_COLUMNS
    assert len(trajectories) == ASSET_TRAJECTORIES_ROWS
