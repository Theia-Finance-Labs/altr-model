"""Pipeline for calculating company trajectories by alignment case."""

from kedro.pipeline import Pipeline, node, pipeline

from .nodes import (
    calculate_aligned_decreasing_technology_transition,
    calculate_aligned_increasing_technology_transition,
    calculate_misaligned_decreasing_technology_transition,
    calculate_misaligned_increasing_technology_transition,
    classify_company_trajectory_alignment,
    combine_company_trajectory_cases,
    compute_baseline_and_target_trajectories,
    validate_model_years,
)

NAMESPACE = "calculate_company_trajectories"
PIPELINE_INPUTS = {"company_projection_inputs"}
PIPELINE_OUTPUTS = {"company_pathways_pre_allocation"}
PIPELINE_PARAMETERS = {"alignment_year", "price_ramp", "shock_year"}


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            node(
                validate_model_years,
                inputs={
                    "shock_year": "params:shock_year",
                    "alignment_year": "params:alignment_year",
                },
                outputs=None,
                name="validate_model_years",
            ),
            node(
                compute_baseline_and_target_trajectories,
                inputs="company_projection_inputs",
                outputs="_baseline_target_trajectories",
                name="calculate_baseline_and_target_trajectories",
            ),
            node(
                classify_company_trajectory_alignment,
                inputs="_baseline_target_trajectories",
                outputs="_classified_company_trajectories",
                name="classify_company_trajectory_alignment",
            ),
            node(
                calculate_misaligned_decreasing_technology_transition,
                inputs={
                    "classified_company_trajectories": "_classified_company_trajectories",
                    "shock_year": "params:shock_year",
                    "alignment_year": "params:alignment_year",
                },
                outputs="_misaligned_decreasing_trajectories",
                name="calculate_misaligned_decreasing_technology_transition",
            ),
            node(
                calculate_misaligned_increasing_technology_transition,
                inputs={
                    "classified_company_trajectories": "_classified_company_trajectories",
                    "shock_year": "params:shock_year",
                    "alignment_year": "params:alignment_year",
                },
                outputs="_misaligned_increasing_trajectories",
                name="calculate_misaligned_increasing_technology_transition",
            ),
            node(
                calculate_aligned_decreasing_technology_transition,
                inputs={
                    "classified_company_trajectories": "_classified_company_trajectories",
                    "shock_year": "params:shock_year",
                    "alignment_year": "params:alignment_year",
                },
                outputs="_aligned_decreasing_trajectories",
                name="calculate_aligned_decreasing_technology_transition",
            ),
            node(
                calculate_aligned_increasing_technology_transition,
                inputs={
                    "classified_company_trajectories": "_classified_company_trajectories",
                    "shock_year": "params:shock_year",
                    "alignment_year": "params:alignment_year",
                },
                outputs="_aligned_increasing_trajectories",
                name="calculate_aligned_increasing_technology_transition",
            ),
            node(
                combine_company_trajectory_cases,
                inputs={
                    "misaligned_decreasing_trajectories": "_misaligned_decreasing_trajectories",
                    "misaligned_increasing_trajectories": "_misaligned_increasing_trajectories",
                    "aligned_decreasing_trajectories": "_aligned_decreasing_trajectories",
                    "aligned_increasing_trajectories": "_aligned_increasing_trajectories",
                    "shock_year": "params:shock_year",
                    "alignment_year": "params:alignment_year",
                    "price_ramp": "params:price_ramp",
                },
                outputs="company_pathways_pre_allocation",
                name="combine_company_trajectory_cases",
            ),
        ],
        inputs=PIPELINE_INPUTS,
        outputs=PIPELINE_OUTPUTS,
        parameters=PIPELINE_PARAMETERS,
        namespace=NAMESPACE,
        tags="altrisk",
    )
