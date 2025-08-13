"""
This is a boilerplate pipeline 'distribute_impacts_to_asset_level'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline
from .nodes import (
    aggregate_late_sudden_trajectories_to_company_level,
    apply_company_level_retirements,
    apply_company_level_compensation,
    split_late_sudden_trajectories_by_alignment_type,
    stagger_decreasing_tech,
    stagger_increasing_tech,
    concatenate_staggered_shock_results,
)


def create_pipeline(**kwargs) -> Pipeline:
    return Pipeline(
        [
            # 1) Aggregate asset L&S to company totals by year
            node(
                aggregate_late_sudden_trajectories_to_company_level,
                inputs=dict(
                    all_assets_late_sudden_trajectories="assets_late_sudden_trajectories",
                ),
                outputs="companies_late_sudden_trajectories",
                name="aggregate_assets_to_company_latesudden",
            ),
            # 2) Apply retirements at company level (assets do not include retirements)
            node(
                apply_company_level_retirements,
                inputs=dict(
                    companies_late_sudden_trajectories="companies_late_sudden_trajectories",
                    assets_retirement_dates="assets_retirement_dates",
                    alignment_year="params:alignment_year",
                ),
                outputs="companies_late_sudden_trajectories_retired",
                name="apply_company_retirements",
            ),
            # 3) Apply compensation (only misaligned high carbon)
            node(
                apply_company_level_compensation,
                inputs=dict(
                    companies_late_sudden_trajectories="companies_late_sudden_trajectories_retired",
                    alignment_year="params:alignment_year",
                ),
                outputs="companies_late_sudden_trajectories_compensated",
                name="apply_company_compensation",
            ),
            # 4) Split assets by alignment type once (reused below)
            node(
                split_late_sudden_trajectories_by_alignment_type,
                inputs=dict(
                    assets_late_sudden_trajectories="assets_late_sudden_trajectories",
                ),
                outputs=[
                    "decreasing_tech_late_sudden_trajectories",
                    "increasing_tech_late_sudden_trajectories",
                ],
                name="split_assets_by_alignment",
            ),
            # 5) Decreasing tech stagger, using company totals with retirements+compensation
            node(
                stagger_decreasing_tech,
                inputs=dict(
                    assets_late_sudden_trajectories="decreasing_tech_late_sudden_trajectories",
                    companies_late_sudden_trajectories="companies_late_sudden_trajectories_compensated",
                    shock_year="params:shock_year",
                    alignment_year="params:alignment_year",
                ),
                outputs="decreasing_tech_staggered_shock",
                name="stagger_decreasing",
            ),
            # 6) Increasing tech stagger (Variant A), using company totals with retirements (comp doesn’t matter here)
            node(
                stagger_increasing_tech,
                inputs=dict(
                    assets_late_sudden_trajectories="increasing_tech_late_sudden_trajectories",
                    companies_late_sudden_trajectories="companies_late_sudden_trajectories_retired",
                    shock_year="params:shock_year",
                ),
                outputs="increasing_tech_staggered_shock",
                name="stagger_increasing",
            ),
            # 7) Concatenate
            node(
                concatenate_staggered_shock_results,
                inputs=dict(
                    dec_late_sudden_trajectories="decreasing_tech_staggered_shock",
                    inc_late_sudden_trajectories="increasing_tech_staggered_shock",
                ),
                outputs="asset_level_staggered_shock",
                name="concat_staggered_outputs",
            ),
        ],
        tags="altrisk",
    )
