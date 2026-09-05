"""Focused tests for explicit company trajectory methodology nodes."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from altr_model.pipelines.calculate_company_trajectories.nodes import (
    calculate_aligned_decreasing_technology_transition,
    calculate_aligned_increasing_technology_transition,
    calculate_misaligned_decreasing_technology_transition,
    calculate_misaligned_increasing_technology_transition,
    classify_company_trajectory_alignment,
    combine_company_trajectory_cases,
)
from altr_model.pipelines.prepare_scenario_asset_and_company_inputs.nodes import (
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


def _combined(price_ramp: bool, alignment_year: int = 2035):
    classified = classify_company_trajectory_alignment(_four_alignment_case_input())
    return combine_company_trajectory_cases(
        misaligned_decreasing_trajectories=calculate_misaligned_decreasing_technology_transition(
            classified, shock_year=2033, alignment_year=alignment_year
        ),
        misaligned_increasing_trajectories=calculate_misaligned_increasing_technology_transition(
            classified, shock_year=2033, alignment_year=alignment_year
        ),
        aligned_decreasing_trajectories=calculate_aligned_decreasing_technology_transition(
            classified, shock_year=2033, alignment_year=alignment_year
        ),
        aligned_increasing_trajectories=calculate_aligned_increasing_technology_transition(
            classified, shock_year=2033, alignment_year=alignment_year
        ),
        shock_year=2033,
        alignment_year=alignment_year,
        price_ramp=price_ramp,
    )


def test_price_ramp_blends_the_financial_surface_across_the_transition_window():
    """With the ramp on, the late & sudden surface interpolates instead of jumping.

    Ported from the handover branch (2026-09-01 owner ruling, Q2). The hard
    switch hands the shock pathway a near-term price windfall at the shock year;
    the ramp spreads the move across [shock_year, alignment_year]. A ramped
    pathway keeps carrying the BASELINE scenario name and scenario_type, since
    its surface is a mixture of the two rather than either one.
    """
    output = _combined(price_ramp=True, alignment_year=2037)
    requested = output[output["trajectory_type"].eq("late_sudden_requested")]
    by_year = requested.groupby("year")["capacity_factor"].apply(set)

    # baseline 1.0 -> target 2.0 over four years: 0, 1/4, 2/4, 3/4, 1.
    assert by_year[2032] == {1.0}
    assert by_year[2033] == {1.0}
    assert by_year[2034] == {1.25}
    assert by_year[2035] == {1.5}
    assert by_year[2036] == {1.75}
    assert by_year[2037] == {2.0}

    assert set(requested["scenario_type"]) == {"baseline"}
    assert set(requested["scenario"]) == {"Baseline"}

    # The pure target pathway is untouched by the ramp.
    target = output[output["trajectory_type"].eq("target")]
    assert set(target["capacity_factor"]) == {2.0}
    assert set(target["scenario_type"]) == {"target"}


def test_explicit_alignment_case_nodes_switch_financial_surface_at_shock():
    output = _combined(price_ramp=False)

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


def test_price_ramp_nullified_by_equal_years_warns():
    """price_ramp=True with alignment_year == shock_year silently disables the ramp.

    `ramping = price_ramp and alignment_year > shock_year` is False when the two
    years are equal, so the surfaces hard-switch at the shock year and reinstate
    the near-term price windfall the ramp exists to remove. The operator asked
    for a ramp and got the hard switch; that has to be said out loud.
    """
    with pytest.warns(UserWarning, match="price_ramp"):
        _combined(price_ramp=True, alignment_year=2033)  # shock_year is 2033


def test_price_ramp_hard_switches_structural_columns_but_blends_the_market():
    """The plant's physics switch at the shock year even under the ramp.

    Owner ruling 2026-09-05: `price_ramp` blends the market environment (prices,
    costs, capacity factor, capture) linearly across [shock, alignment], but the
    structural constants -- `lifetime_years` and `scrap_usd_per_mw` (which feeds
    `decom_cost`) -- take no fractional interim value; they hard-switch
    baseline->target at the shock year, exactly as they do with the ramp off.
    """
    output = _combined(price_ramp=True, alignment_year=2037)
    requested = output[output["trajectory_type"].eq("late_sudden_requested")]

    for column in ("scrap_usd_per_mw", "lifetime_years"):
        by_year = requested.groupby("year")[column].apply(set)
        assert by_year[2032] == {1.0}, f"{column} baseline before shock"
        assert by_year[2033] == {2.0}, f"{column} target from shock (no blend)"
        assert by_year[2035] == {2.0}, f"{column} still target mid-window (would be 1.5 if blended)"

    # the market surface still blends: capacity_factor moves 1.0 -> 2.0 over the window
    cf = requested.groupby("year")["capacity_factor"].apply(set)
    assert cf[2035] == {1.5}
