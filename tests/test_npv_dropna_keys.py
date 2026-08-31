"""Regression: rows with a NaN group key must not silently vanish.

The CapEx flow-split collapse groups with dropna=False, so a row whose
company_name (or any other group key) is NaN survives it. The trajectory loop
and the asset-level aggregation used pandas' default dropna=True, so those
rows were dropped further downstream without a trace: present in the collapsed
frame, absent from the output. All three groupbys must agree.
"""

import logging

import numpy as np
import pandas as pd
import pytest
from crispy_kedro.pipelines.valuation_model.nodes import (
    aggregate_to_company_npv,
    aggregate_to_company_technology_npv,
    calculate_npv_per_asset,
    compute_yearly_npv_trajectories,
)


def _rows(asset_id, company_name, trajectory, scenario_type):
    return [
        {
            "asset_name": f"name_{asset_id}",
            "asset_id": asset_id,
            "company_id": f"CO_{asset_id}",
            "company_name": company_name,
            "scenario_geography": "EU",
            "sector": "Power",
            "technology": "GasCap - w/o CCS",
            "is_synthetic": False,
            "alignment_type": "misaligned_high_carbon",
            "trajectory_type": trajectory,
            "scenario_type": scenario_type,
            "year": year,
            "FCFF": fcff,
        }
        for year, fcff in [(2028, 100.0), (2029, 110.0), (2030, 120.0)]
    ]


def _frame():
    rows = []
    for traj, stype in [("baseline", "baseline"), ("latesudden", "AR6_shock")]:
        rows += _rows("NAMED", "Acme AG", traj, stype)
        rows += _rows("NAN_CO", np.nan, traj, stype)
    return pd.DataFrame(rows)


def test_nan_group_key_rows_survive_trajectory_computation():
    out = compute_yearly_npv_trajectories(_frame())
    assert "NAN_CO" in set(out["asset_id"]), (
        "asset with NaN company_name was dropped by the trajectory groupby"
    )
    named = out.loc[out["asset_id"] == "NAMED"]
    nan_co = out.loc[out["asset_id"] == "NAN_CO"]
    assert len(nan_co) == len(named)
    assert nan_co["company_name"].isna().all()


def test_nan_group_key_rows_survive_asset_aggregation():
    trajectories = compute_yearly_npv_trajectories(_frame())
    asset_npv = calculate_npv_per_asset(trajectories)
    assert "NAN_CO" in set(asset_npv["asset_id"]), (
        "asset with NaN company_name was dropped by the aggregation groupby"
    )
    row = asset_npv.loc[asset_npv["asset_id"] == "NAN_CO"].iloc[0]
    assert np.isfinite(row["baseline_npv"])
    assert np.isfinite(row["latesudden_npv"])


def test_nan_group_key_rows_survive_company_aggregations():
    """The company-level aggregators must also keep NaN-key rows (they used
    pandas' default dropna=True, so a NaN company_name that survived the
    asset stage silently vanished from company outputs)."""
    asset_npv = calculate_npv_per_asset(
        compute_yearly_npv_trajectories(_frame())
    )
    company_tech = aggregate_to_company_technology_npv(asset_npv)
    assert "CO_NAN_CO" in set(company_tech["company_id"]), (
        "NaN company_name dropped by company-technology aggregation"
    )
    company = aggregate_to_company_npv(company_tech)
    assert "CO_NAN_CO" in set(company["company_id"]), (
        "NaN company_name dropped by company aggregation"
    )


def test_missing_scenario_type_drop_is_logged_as_error(caplog):
    frame = _frame()
    frame.loc[frame.index[:2], "scenario_type"] = np.nan
    with caplog.at_level(logging.ERROR, logger="crispy_kedro.pipelines.valuation_model.nodes"):
        out = compute_yearly_npv_trajectories(frame)
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error_records, "dropping scenario_type rows must log at ERROR level"
    assert any("scenario_type" in r.getMessage() for r in error_records)
    # rows are still dropped, matching the pre-change behavior
    assert len(out.loc[out["year"] <= 2030]) < len(frame)


def test_nan_year_raises_instead_of_silent_garbage():
    """A NaN year used to crash loudly in the old loop; the vectorized int
    casts would wrap it to INT64_MIN and emit astronomically wrong terminal
    values. It must raise."""
    frame = _frame()
    frame.loc[frame.index[0], "year"] = np.nan
    with pytest.raises(ValueError, match="NaN year"):
        compute_yearly_npv_trajectories(frame)
