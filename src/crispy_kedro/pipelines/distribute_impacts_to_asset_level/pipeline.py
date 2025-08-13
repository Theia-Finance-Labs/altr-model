"""
This is a boilerplate pipeline 'distribute_impacts_to_asset_level'
generated using Kedro 0.19.12
"""

from ctypes import alignment
from kedro.pipeline import node, Pipeline, pipeline  # noqa
from .nodes import (
    split_late_sudden_trajectories_by_alignment_type,
    stagger_decreasing_from_company,
    stagger_increasing_from_company,
    concatenate_staggered_shock_results,
)


def create_pipeline(**kwargs) -> Pipeline:
    return Pipeline(
        [
            node(
                split_late_sudden_trajectories_by_alignment_type,
                inputs=dict(
                    companies_late_sudden_trajectories="companies_late_sudden_trajectories",
                ),
                outputs=[
                    "decreasing_tech_late_sudden_trajectories",
                    "increasing_tech_late_sudden_trajectories",
                ],
                name="split_assets_by_alignment",
            ),
            node(
                stagger_decreasing_from_company,
                inputs=dict(
                    late_sudden_trajectories="decreasing_tech_late_sudden_trajectories",
                    allocated_assets_to_companies="extended_allocated_assets_to_companies",
                    assets_retirement_dates="assets_retirement_dates",
                    shock_year="params:shock_year",
                    alignment_year="params:alignment_year",
                ),
                outputs="decreasing_tech_staggered_shock",
            ),
            node(
                stagger_increasing_from_company,
                inputs=dict(
                    late_sudden_trajectories="increasing_tech_late_sudden_trajectories",
                    allocated_assets_to_companies="extended_allocated_assets_to_companies",
                    shock_year="params:shock_year",
                ),
                outputs="increasing_tech_staggered_shock",
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
