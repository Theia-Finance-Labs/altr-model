"""
This is a boilerplate pipeline 'distribute_impacts_to_asset_level'
generated using Kedro 0.19.12
"""

from ctypes import alignment
from kedro.pipeline import node, Pipeline, pipeline  # noqa
from .nodes import (
    split_late_sudden_trajectories_by_alignment_type,
    stagger_decreasing_technologies,
    stagger_increasing_technologies,
    concatenate_staggered_shock_results,
    compute_capex_indicators,
    flag_phased_out_assets_as_retired,
    enforce_retirements_after_alignment,
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
                stagger_decreasing_technologies,
                inputs=dict(
                    late_sudden_trajectories="decreasing_tech_late_sudden_trajectories",
                    allocated_assets_to_companies="extended_companies_forecasts",
                    assets_retirement_dates="assets_retirement_dates",
                    shock_year="params:shock_year",
                    alignment_year="params:alignment_year",
                    apply_retirement="params:apply_retirement",
                    apply_decreasing_staggered_shock="params:apply_decreasing_staggered_shock",
                ),
                outputs="decreasing_tech_staggered_shock",
            ),
            node(
                enforce_retirements_after_alignment,
                inputs=dict(
                    dec_df="decreasing_tech_staggered_shock",
                    assets_retirement_dates="assets_retirement_dates",
                    alignment_year="params:alignment_year",
                    apply_retirement="params:apply_retirement",
                ),
                outputs="decreasing_tech_staggered_shock_retired",
            ),
            node(
                flag_phased_out_assets_as_retired,
                inputs=dict(
                    dec_staggered="decreasing_tech_staggered_shock_retired",
                ),
                outputs="decreasing_tech_staggered_shock_flagged",
            ),
            node(
                stagger_increasing_technologies,
                inputs=dict(
                    late_sudden_trajectories="increasing_tech_late_sudden_trajectories",
                    allocated_assets_to_companies="extended_companies_forecasts",
                    shock_year="params:shock_year",
                ),
                outputs="increasing_tech_staggered_shock",
            ),
            node(
                concatenate_staggered_shock_results,
                inputs=dict(
                    dec_late_sudden_trajectories="decreasing_tech_staggered_shock_flagged",
                    inc_late_sudden_trajectories="increasing_tech_staggered_shock",
                ),
                outputs="asset_level_staggered_shock",
            ),
            node(
                compute_capex_indicators,
                inputs=dict(
                    assets_staggered_late_sudden="asset_level_staggered_shock",
                ),
                outputs="asset_capex_indicators",
            ),
        ],
        tags="altrisk",
    )
