"""Characterization tests for capacity flows (earnings_model).

Pinned behaviors — current behavior, computed by hand in each test body:

* `compute_capacity_flows` emits exactly one flow row per input asset-year, with
  the indicator chosen by asset kind and capacity change:
  - real asset, capacity falling  -> `retired_max_cap`, capacity = |change|
  - real asset, otherwise         -> `roll_over_cap`, capacity = 2% of the
    year's `asset_trajectory` (EPRI/Lazard routine-maintenance benchmark)
  - synthetic asset, capacity rising -> `new_buildout_cap`, capacity = change
  - synthetic asset, otherwise    -> `none`, capacity = 0.0
* The first year of every group has no predecessor, so its change is 0.
* `scenario_geography` is part of the lag key: a multi-geography asset must not
  carry one geography's last capacity into the next geography's first year.
* Missing `scenario_geography` / `asset_trajectory` raise `ValueError`.
* `validate_capacity_flow_identity` raises on duplicate flow records and
  otherwise only logs: it checks K_t = K_(t-1) - retired + roll_over/0.05 +
  new_build against `asset_trajectory` with a 0.01 MW tolerance, and returns
  None either way.
"""

import logging

import pandas as pd
import pytest

from crispy_kedro.pipelines.earnings_model.nodes import (
    compute_capacity_flows,
    validate_capacity_flow_identity,
)


def _panel(rows, is_synthetic=None):
    """rows: list of (asset_id, scenario_geography, year, asset_trajectory)."""
    frame = pd.DataFrame(
        [
            {
                "trajectory_type": "baseline",
                "company_id": "C1",
                "asset_id": asset_id,
                "technology": "GasCap",
                "scenario_geography": geo,
                "year": year,
                "asset_trajectory": traj,
            }
            for asset_id, geo, year, traj in rows
        ]
    )
    if is_synthetic is not None:
        frame["is_synthetic"] = is_synthetic
    return frame


def _flows(result):
    return {
        (row.year, row.scenario_geography): (
            row.capex_indicator,
            round(row.capex_capacity, 6),
        )
        for row in result.itertuples()
    }


def test_real_asset_gets_two_percent_rollover_and_retirement_on_decline():
    panel = _panel(
        [
            ("A1", "EU", 2025, 100.0),  # first year: change 0 -> rollover 2.0
            ("A1", "EU", 2026, 120.0),  # +20 -> still rollover, 120 * 0.02 = 2.4
            ("A1", "EU", 2027, 90.0),  # -30 -> retirement of 30.0, no rollover
        ]
    )

    out = compute_capacity_flows(panel)

    assert len(out) == 3
    assert _flows(out) == {
        (2025, "EU"): ("roll_over_cap", 2.0),
        (2026, "EU"): ("roll_over_cap", 2.4),
        (2027, "EU"): ("retired_max_cap", 30.0),
    }


def test_synthetic_asset_gets_new_buildout_on_growth_and_none_otherwise():
    panel = _panel(
        [
            ("S1", "EU", 2025, 0.0),  # first year: change 0 -> no flow
            ("S1", "EU", 2026, 50.0),  # +50 -> new buildout
            ("S1", "EU", 2027, 50.0),  # flat -> no flow (never rolled over)
        ],
        is_synthetic=True,
    )

    out = compute_capacity_flows(panel)

    assert _flows(out) == {
        (2025, "EU"): ("none", 0.0),
        (2026, "EU"): ("new_buildout_cap", 50.0),
        (2027, "EU"): ("none", 0.0),
    }


def test_lag_does_not_leak_across_scenario_geographies():
    # Without geography in the lag key, US 2025 (50 MW) would be read as a
    # 50 MW retirement following EU 2026 (100 MW).
    panel = _panel(
        [
            ("A1", "EU", 2025, 100.0),
            ("A1", "EU", 2026, 100.0),
            ("A1", "US", 2025, 50.0),
            ("A1", "US", 2026, 50.0),
        ]
    )

    out = compute_capacity_flows(panel)

    assert "retired_max_cap" not in set(out["capex_indicator"])
    assert _flows(out) == {
        (2025, "EU"): ("roll_over_cap", 2.0),
        (2026, "EU"): ("roll_over_cap", 2.0),
        (2025, "US"): ("roll_over_cap", 1.0),
        (2026, "US"): ("roll_over_cap", 1.0),
    }


def test_missing_required_columns_raise():
    panel = _panel([("A1", "EU", 2025, 100.0)])

    with pytest.raises(ValueError, match="scenario_geography"):
        compute_capacity_flows(panel.drop(columns=["scenario_geography"]))

    with pytest.raises(ValueError, match="asset_trajectory"):
        compute_capacity_flows(panel.drop(columns=["asset_trajectory"]))


def _enriched(rows):
    """rows: list of (year, capex_indicator, capex_capacity, asset_trajectory)."""
    return pd.DataFrame(
        [
            {
                "trajectory_type": "baseline",
                "company_id": "C1",
                "asset_id": "A1",
                "technology": "GasCap",
                "scenario_geography": "EU",
                "year": year,
                "capex_indicator": indicator,
                "capex_capacity": capacity,
                "asset_trajectory": traj,
            }
            for year, indicator, capacity, traj in rows
        ]
    )


def test_flow_identity_reports_rows_within_tolerance(caplog):
    # 2026: K_calc = 100 - 0 + 0/0.05 + 0 = 100 == actual 100 -> within 0.01 MW.
    # The 2025 row has no predecessor and is dropped from the check.
    data = _enriched(
        [
            (2025, "roll_over_cap", 0.0, 100.0),
            (2026, "roll_over_cap", 0.0, 100.0),
        ]
    )

    with caplog.at_level(logging.INFO):
        assert validate_capacity_flow_identity(data) is None

    assert "Flow identity validation: 1/1 rows within tolerance" in caplog.text
    assert "violations" not in caplog.text


def test_flow_identity_warns_on_violation(caplog):
    # 2026: K_calc = 100 - 0 + 0 + 20 = 120 vs actual 150 -> 30 MW off.
    data = _enriched(
        [
            (2025, "roll_over_cap", 0.0, 100.0),
            (2026, "new_buildout_cap", 20.0, 150.0),
        ]
    )

    with caplog.at_level(logging.INFO):
        validate_capacity_flow_identity(data)

    assert "Flow identity validation: 0/1 rows within tolerance" in caplog.text
    assert "Flow identity violations found in 1 asset-year combinations" in caplog.text
    assert "Diff=30.00 MW" in caplog.text


def test_flow_identity_rejects_duplicate_flow_records():
    duplicated = _enriched(
        [
            (2025, "roll_over_cap", 0.0, 100.0),
            (2025, "roll_over_cap", 0.0, 100.0),
        ]
    )

    with pytest.raises(ValueError) as excinfo:
        validate_capacity_flow_identity(duplicated)

    assert "duplicate capacity flow records" in str(excinfo.value)
