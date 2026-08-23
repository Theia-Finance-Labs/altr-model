"""
This is a boilerplate pipeline 'create_late_sudden_trajectories'
generated using Kedro 0.19.12
"""

from kedro.pipeline import Pipeline, node, pipeline

from .nodes import (
    concatenate_late_sudden_results,
    determine_companies_technologies_alignment,
    late_sudden_aligned_high_carbon_companies,
    late_sudden_aligned_low_carbon_companies,
    late_sudden_misaligned_high_carbon_companies,
    late_sudden_misaligned_low_carbon_companies,
)

NAMESPACE = "create_late_sudden_trajectories"
PIPELINE_INPUTS = {
    "companies_trajectories",
    "increasing_or_decreasing_techs",
}
PIPELINE_OUTPUTS = {
    "all_alignment_classifications",
    "companies_late_sudden_trajectories",
}
PIPELINE_PARAMETERS = {"alignment_year", "shock_year"}


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            node(
                determine_companies_technologies_alignment,
                inputs=dict(
                    companies_trajectories="companies_trajectories",
                    increasing_or_decreasing_techs="increasing_or_decreasing_techs",
                ),
                outputs=dict(
                    all_alignment_classifications="all_alignment_classifications",
                    misaligned_high_carbon_companies_trajectories="misaligned_high_carbon_companies_trajectories",
                    misaligned_low_carbon_companies_trajectories="misaligned_low_carbon_companies_trajectories",
                    aligned_high_carbon_companies_trajectories="aligned_high_carbon_companies_trajectories",
                    aligned_low_carbon_companies_trajectories="aligned_low_carbon_companies_trajectories",
                ),
            ),
            node(
                late_sudden_misaligned_high_carbon_companies,
                inputs=dict(
                    misaligned_high_carbon_companies_trajectories="misaligned_high_carbon_companies_trajectories",
                    shock_year="params:shock_year",
                    alignment_year="params:alignment_year",
                ),
                outputs="late_sudden_misaligned_high_carbon_companies",
            ),
            node(
                late_sudden_misaligned_low_carbon_companies,
                inputs=dict(
                    misaligned_low_carbon_companies_trajectories="misaligned_low_carbon_companies_trajectories",
                    shock_year="params:shock_year",
                    alignment_year="params:alignment_year",
                ),
                outputs="late_sudden_misaligned_low_carbon_companies",
            ),
            node(
                late_sudden_aligned_high_carbon_companies,
                inputs=dict(
                    aligned_high_carbon_companies_trajectories="aligned_high_carbon_companies_trajectories",
                    shock_year="params:shock_year",
                    alignment_year="params:alignment_year",
                ),
                outputs="late_sudden_aligned_high_carbon_companies",
            ),
            node(
                late_sudden_aligned_low_carbon_companies,
                inputs=dict(
                    aligned_low_carbon_companies_trajectories="aligned_low_carbon_companies_trajectories",
                    shock_year="params:shock_year",
                    alignment_year="params:alignment_year",
                ),
                outputs="late_sudden_aligned_low_carbon_companies",
            ),
            node(
                concatenate_late_sudden_results,
                inputs=dict(
                    late_sudden_misaligned_high_carbon="late_sudden_misaligned_high_carbon_companies",
                    late_sudden_misaligned_low_carbon="late_sudden_misaligned_low_carbon_companies",
                    late_sudden_aligned_high_carbon="late_sudden_aligned_high_carbon_companies",
                    late_sudden_aligned_low_carbon="late_sudden_aligned_low_carbon_companies",
                ),
                outputs="companies_late_sudden_trajectories",
            ),
        ],
        inputs=PIPELINE_INPUTS,
        outputs=PIPELINE_OUTPUTS,
        parameters=PIPELINE_PARAMETERS,
        namespace=NAMESPACE,
        tags="altrisk",
    )
