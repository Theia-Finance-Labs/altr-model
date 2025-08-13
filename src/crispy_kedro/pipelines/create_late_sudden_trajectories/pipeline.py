"""
This is a boilerplate pipeline 'create_late_sudden_trajectories'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline, pipeline  # noqa

from .nodes import (
    determine_companies_technologies_alignment,
    late_sudden_misaligned_high_carbon_companies,
    late_sudden_misaligned_low_carbon_companies,
    late_sudden_aligned_high_carbon_companies,
    late_sudden_aligned_low_carbon_companies,
    concatenate_late_sudden_results,
)


def create_pipeline(**kwargs) -> Pipeline:
    return Pipeline(
        [
            node(
                determine_companies_technologies_alignment,
                inputs=dict(
                    companies_trajectories="companies_trajectories",
                    assets_trajectories="assets_trajectories",
                    increasing_or_decreasing_techs="increasing_or_decreasing_techs",
                ),
                outputs=[
                    "misaligned_high_carbon_assets_trajectories",
                    "misaligned_low_carbon_assets_trajectories",
                    "aligned_high_carbon_assets_trajectories",
                    "aligned_low_carbon_assets_trajectories",
                ],
            ),
            node(
                late_sudden_misaligned_high_carbon_companies,
                inputs=dict(
                    misaligned_high_carbon_assets_trajectories="misaligned_high_carbon_assets_trajectories",
                    shock_year="params:shock_year",
                    alignment_year="params:alignment_year",
                ),
                outputs="late_sudden_misaligned_high_carbon_companies",
            ),
            node(
                late_sudden_misaligned_low_carbon_companies,
                inputs=dict(
                    misaligned_low_carbon_assets_trajectories="misaligned_low_carbon_assets_trajectories",
                    shock_year="params:shock_year",
                    alignment_year="params:alignment_year",
                ),
                outputs="late_sudden_misaligned_low_carbon_companies",
            ),
            node(
                late_sudden_aligned_high_carbon_companies,
                inputs=dict(
                    aligned_high_carbon_assets_trajectories="aligned_high_carbon_assets_trajectories",
                    shock_year="params:shock_year",
                    alignment_year="params:alignment_year",
                ),
                outputs="late_sudden_aligned_high_carbon_companies",
            ),
            node(
                late_sudden_aligned_low_carbon_companies,
                inputs=dict(
                    aligned_low_carbon_assets_trajectories="aligned_low_carbon_assets_trajectories",
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
                outputs="assets_late_sudden_trajectories",
            ),
        ],
        tags="altrisk",
    )
