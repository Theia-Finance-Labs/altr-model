"""Focused tests for explicit company trajectory methodology nodes."""

from __future__ import annotations

import numpy as np
import pandas as pd
from crispy_kedro.pipelines.calculate_company_trajectories.nodes import (
    calculate_aligned_decreasing_technology_transition,
    calculate_aligned_increasing_technology_transition,
    calculate_misaligned_decreasing_technology_transition,
    calculate_misaligned_increasing_technology_transition,
    classify_company_trajectory_alignment,
    combine_company_trajectory_cases,
)
from crispy_kedro.pipelines.prepare_scenario_asset_and_company_inputs.nodes import (
    FINANCIAL_SURFACE_COLUMNS,
)


def _four_alignment_case_input() -> pd.DataFrame:
    years = range(2029, 2038)
    cases = [
        ("aligned_high", False, 1.0),
        ("misaligned_high", False, 20.0),
        ("aligned_low", True, 20.0),
        ("misaligned_low", True, 1.0),
    ]
    rows = []
    for company_id, increasing, forecast_value in cases:
        for year in years:
            row = {
                "company_id": company_id,
                "company_name": company_id,
                "scenario_geography": "World",
                "sector": "Power",
                "technology": f"technology_{increasing}",
                "year": year,
                "company_activity": forecast_value if year <= 2031 else np.nan,
                "company_trajectory_baseline": 12.0,
                "company_trajectory_target": 10.0,
                "increasing": increasing,
            }
            for column in FINANCIAL_SURFACE_COLUMNS:
                if column == "scenario":
                    row[f"{column}_baseline"] = "Baseline"
                    row[f"{column}_target"] = "Target"
                else:
                    row[f"{column}_baseline"] = 1.0
                    row[f"{column}_target"] = 2.0
            rows.append(row)
    return pd.DataFrame(rows)


def test_explicit_alignment_case_nodes_switch_financial_surface_at_shock():
    classified = classify_company_trajectory_alignment(_four_alignment_case_input())
    output = combine_company_trajectory_cases(
        misaligned_decreasing_trajectories=calculate_misaligned_decreasing_technology_transition(
            classified, shock_year=2033, alignment_year=2035
        ),
        misaligned_increasing_trajectories=calculate_misaligned_increasing_technology_transition(
            classified, shock_year=2033, alignment_year=2035
        ),
        aligned_decreasing_trajectories=calculate_aligned_decreasing_technology_transition(
            classified, shock_year=2033, alignment_year=2035
        ),
        aligned_increasing_trajectories=calculate_aligned_increasing_technology_transition(
            classified, shock_year=2033, alignment_year=2035
        ),
        shock_year=2033,
    )

    classifications = (
        output[["company_id", "alignment_type"]]
        .drop_duplicates()
        .set_index("company_id")["alignment_type"]
        .to_dict()
    )
    assert classifications == {
        "aligned_high": "aligned_high_carbon",
        "misaligned_high": "misaligned_high_carbon",
        "aligned_low": "aligned_low_carbon",
        "misaligned_low": "misaligned_low_carbon",
    }
    assert set(output["trajectory_type"]) == {
        "baseline",
        "target",
        "late_sudden_requested",
    }

    requested = output[output["trajectory_type"].eq("late_sudden_requested")]
    before_shock = requested[requested["year"].eq(2032)]
    from_shock = requested[requested["year"].eq(2033)]
    assert set(before_shock["scenario_type"]) == {"baseline"}
    assert set(before_shock["scenario"]) == {"Baseline"}
    assert set(before_shock["capacity_factor"]) == {1.0}
    assert set(from_shock["scenario_type"]) == {"target"}
    assert set(from_shock["scenario"]) == {"Target"}
    assert set(from_shock["capacity_factor"]) == {2.0}
