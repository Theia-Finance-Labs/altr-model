"""Explicit company trajectory methodology nodes."""

from __future__ import annotations

import numpy as np
import pandas as pd

from altr_model.pipelines.calculate_company_trajectories._baseline_nodes import (
    create_companies_trajectories,
)
from altr_model.pipelines.calculate_company_trajectories._late_sudden_nodes import (
    determine_companies_technologies_alignment,
    late_sudden_aligned_high_carbon_companies,
    late_sudden_aligned_low_carbon_companies,
    late_sudden_misaligned_high_carbon_companies,
    late_sudden_misaligned_low_carbon_companies,
)
from altr_model.pipelines.prepare_scenario_asset_and_company_inputs._input_nodes import (
    check_input_parameters,
)
from altr_model.pipelines.prepare_scenario_asset_and_company_inputs.nodes import (
    FINANCIAL_SURFACE_COLUMNS,
)

COMPANY_YEAR_KEYS = [
    "company_id",
    "scenario_geography",
    "sector",
    "technology",
    "year",
]
CLASSIFICATION_KEYS = COMPANY_YEAR_KEYS[:-1]


def validate_model_years(shock_year: int, alignment_year: int) -> None:
    """Validate transition timing next to the nodes that consume it."""
    check_input_parameters(shock_year, alignment_year)


def compute_baseline_and_target_trajectories(
    company_projection_inputs: pd.DataFrame,
) -> pd.DataFrame:
    """Apply the existing baseline/target calculation to the prepared wide input."""
    company_forecasts = company_projection_inputs[
        COMPANY_YEAR_KEYS + ["company_name", "company_activity"]
    ].copy()
    scenario_trajectories = company_projection_inputs.drop(
        columns=["company_name", "company_activity", "increasing"], errors="ignore"
    )
    trajectories = create_companies_trajectories(
        companies_forecasts=company_forecasts,
        scenarios_trajectories=scenario_trajectories,
    )
    trend = company_projection_inputs[
        ["technology", "scenario_geography", "increasing"]
    ].drop_duplicates()
    return trajectories.merge(
        trend,
        on=["technology", "scenario_geography"],
        how="left",
        validate="many_to_one",
    )


def classify_company_trajectory_alignment(
    company_trajectories: pd.DataFrame,
) -> pd.DataFrame:
    """Annotate every company trajectory with its explicit alignment case."""
    trend = company_trajectories[
        ["technology", "scenario_geography", "increasing"]
    ].drop_duplicates()
    classified = determine_companies_technologies_alignment(
        company_trajectories.drop(columns="increasing"), trend
    )["all_alignment_classifications"]
    classified["alignment_type"] = np.select(
        [
            classified["aligned"] & ~classified["increasing"],
            classified["aligned"] & classified["increasing"],
            ~classified["aligned"] & ~classified["increasing"],
            ~classified["aligned"] & classified["increasing"],
        ],
        [
            "aligned_high_carbon",
            "aligned_low_carbon",
            "misaligned_high_carbon",
            "misaligned_low_carbon",
        ],
        default="unclassified",
    )
    annotations = classified[
        CLASSIFICATION_KEYS + ["increasing", "aligned", "alignment_type"]
    ]
    return company_trajectories.merge(
        annotations,
        on=CLASSIFICATION_KEYS + ["increasing"],
        how="left",
        validate="many_to_one",
    )


def calculate_misaligned_decreasing_technology_transition(
    classified_company_trajectories: pd.DataFrame,
    shock_year: int,
    alignment_year: int,
) -> pd.DataFrame:
    """Calculate the requested path for misaligned decreasing technologies."""
    case_rows = classified_company_trajectories[
        classified_company_trajectories["alignment_type"].eq("misaligned_high_carbon")
    ].copy()
    return late_sudden_misaligned_high_carbon_companies(
        case_rows, shock_year, alignment_year
    )


def calculate_misaligned_increasing_technology_transition(
    classified_company_trajectories: pd.DataFrame,
    shock_year: int,
    alignment_year: int,
) -> pd.DataFrame:
    """Calculate the requested path for misaligned increasing technologies."""
    case_rows = classified_company_trajectories[
        classified_company_trajectories["alignment_type"].eq("misaligned_low_carbon")
    ].copy()
    return late_sudden_misaligned_low_carbon_companies(
        case_rows, shock_year, alignment_year
    )


def calculate_aligned_decreasing_technology_transition(
    classified_company_trajectories: pd.DataFrame,
    shock_year: int,
    alignment_year: int,
) -> pd.DataFrame:
    """Calculate the requested path for aligned decreasing technologies."""
    case_rows = classified_company_trajectories[
        classified_company_trajectories["alignment_type"].eq("aligned_high_carbon")
    ].copy()
    return late_sudden_aligned_high_carbon_companies(
        case_rows, shock_year, alignment_year
    )


def calculate_aligned_increasing_technology_transition(
    classified_company_trajectories: pd.DataFrame,
    shock_year: int,
    alignment_year: int,
) -> pd.DataFrame:
    """Calculate the requested path for aligned increasing technologies."""
    case_rows = classified_company_trajectories[
        classified_company_trajectories["alignment_type"].eq("aligned_low_carbon")
    ].copy()
    return late_sudden_aligned_low_carbon_companies(
        case_rows, shock_year, alignment_year
    )


def combine_company_trajectory_cases(
    misaligned_decreasing_trajectories: pd.DataFrame,
    misaligned_increasing_trajectories: pd.DataFrame,
    aligned_decreasing_trajectories: pd.DataFrame,
    aligned_increasing_trajectories: pd.DataFrame,
    shock_year: int,
    alignment_year: int,
    price_ramp: bool,
) -> pd.DataFrame:
    """Combine the four visible cases into the canonical pre-allocation table.

    ``price_ramp`` controls how the late & sudden pathway picks up the target
    scenario's financial surfaces. Off, the surfaces hard-switch from baseline
    to target at ``shock_year``; on, they blend linearly across the transition
    window ``[shock_year, alignment_year]``. The hard switch hands the shock
    pathway a near-term price windfall — target prices sit 30-50% above
    baseline at the shock year — which shows up as fossil assets gaining value
    under a climate shock. Blending removes it.
    """
    case_rows = pd.concat(
        [
            misaligned_decreasing_trajectories,
            misaligned_increasing_trajectories,
            aligned_decreasing_trajectories,
            aligned_increasing_trajectories,
        ],
        ignore_index=True,
    )
    assumption_columns = [
        f"{column}_{scenario_type}"
        for column in FINANCIAL_SURFACE_COLUMNS
        for scenario_type in ("baseline", "target")
    ]
    id_columns = [
        "company_id",
        "company_name",
        "scenario_geography",
        "sector",
        "technology",
        "year",
        "late_sudden_phase",
        "increasing",
        "aligned",
        "alignment_type",
        *assumption_columns,
    ]
    pathways = (
        case_rows.melt(
            id_vars=id_columns,
            value_vars=[
                "company_trajectory_latesudden",
                "company_trajectory_baseline",
                "company_trajectory_target",
            ],
            var_name="trajectory_source",
            value_name="company_trajectory",
        )
        .assign(
            trajectory_type=lambda frame: frame["trajectory_source"].replace(
                {
                    "company_trajectory_latesudden": "late_sudden_requested",
                    "company_trajectory_baseline": "baseline",
                    "company_trajectory_target": "target",
                }
            )
        )
        .drop(columns="trajectory_source")
    )

    is_baseline = pathways["trajectory_type"].eq("baseline")
    is_late_sudden = pathways["trajectory_type"].eq("late_sudden_requested")
    ramping = price_ramp and alignment_year > shock_year
    uses_target_surface = pathways["trajectory_type"].eq("target") | (
        is_late_sudden & pathways["year"].ge(shock_year) & ~ramping
    )
    if ramping:
        # 0 at (and before) the shock year, 1 from the alignment year on.
        blend = (
            (pathways["year"] - shock_year) / (alignment_year - shock_year)
        ).clip(0.0, 1.0)
    for column in FINANCIAL_SURFACE_COLUMNS:
        baseline_values = pathways[f"{column}_baseline"]
        target_values = pathways[f"{column}_target"]
        if not ramping:
            late_sudden_values = np.where(
                pathways["year"].ge(shock_year), target_values, baseline_values
            )
        elif pd.api.types.is_numeric_dtype(baseline_values):
            late_sudden_values = baseline_values * (1 - blend) + target_values * blend
        else:
            # `scenario` is the scenario NAME: it labels a surface rather than
            # being one, so a blended pathway cannot take the target's. It keeps
            # carrying the baseline name, as scenario_type does below.
            late_sudden_values = baseline_values
        pathways[column] = np.where(
            is_baseline,
            baseline_values,
            np.where(
                pathways["trajectory_type"].eq("target"),
                target_values,
                late_sudden_values,
            ),
        )
    pathways["scenario_type"] = np.where(uses_target_surface, "target", "baseline")

    output_columns = list(
        dict.fromkeys(
            [
                "company_id",
                "company_name",
                "scenario_geography",
                "sector",
                "technology",
                "year",
                "trajectory_type",
                "company_trajectory",
                "late_sudden_phase",
                "increasing",
                "aligned",
                "alignment_type",
                "scenario_type",
                *FINANCIAL_SURFACE_COLUMNS,
            ]
        )
    )
    return (
        pathways[output_columns]
        .sort_values(COMPANY_YEAR_KEYS + ["trajectory_type"])
        .reset_index(drop=True)
    )
