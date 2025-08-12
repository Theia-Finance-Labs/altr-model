"""
This is a boilerplate pipeline 'distribute_impacts_to_asset_level'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline, pipeline  # noqa
from .nodes import (
    aggregate_late_sudden_trajectories_to_company_level,
    compute_company_level_compensation,
    stagger_decreasing_tech,
    stagger_increasing_tech,
    concatenate_staggered_shock_results,
)


def create_pipeline(**kwargs) -> Pipeline:
    return Pipeline(
        [
            node(
                aggregate_late_sudden_trajectories_to_company_level,
                inputs=dict(
                    all_assets_late_sudden_trajectories="assets_late_sudden_trajectories",
                ),
                outputs="companies_late_sudden_trajectories",
            ),
            node(
                compute_company_level_compensation,
                inputs=dict(
                    companies_late_sudden_trajectories="companies_late_sudden_trajectories",
                    shock_year="params:shock_year",
                    alignment_year="params:alignment_year",
                ),
                outputs="compensation_required_per_company",
            ),
            node(
                stagger_decreasing_tech,
                inputs=dict(
                    assets_late_sudden_trajectories="assets_late_sudden_trajectories",
                    companies_late_sudden_trajectories="companies_late_sudden_trajectories",
                    assets_retirement_dates="assets_retirement_dates",
                    compensation_required_per_company="compensation_required_per_company",
                    shock_year="params:shock_year",
                    alignment_year="params:alignment_year",
                ),
                outputs="increasing_tech_staggered_shock",
            ),
            node(
                stagger_increasing_tech,
                inputs=dict(
                    assets_late_sudden_trajectories="assets_late_sudden_trajectories",
                    companies_late_sudden_trajectories="companies_late_sudden_trajectories",
                    shock_year="params:shock_year",
                ),
                outputs="decreasing_tech_staggered_shock",
            ),
            node(
                concatenate_staggered_shock_results,
                inputs=dict(
                    dec_late_sudden_trajectories="decreasing_tech_staggered_shock",
                    inc_late_sudden_trajectories="increasing_tech_staggered_shock",
                ),
                outputs="asset_level_staggered_shock",
            ),
        ],
        tags="altrisk",
    )
