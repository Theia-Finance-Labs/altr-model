"""
This is a boilerplate pipeline 'distribute_impacts_to_asset_level'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline, pipeline  # noqa
from .assembly import (
    concatenate_staggered_shock_results,
    melt_asset_staggered_trajectories,
    split_late_sudden_trajectories_by_alignment_type,
)
from .baseline import compute_asset_baseline_trajectories
from .retirement import (
    create_frozen_capacity_at_retirement,
    flag_phased_out_assets_as_retired,
)
from .staggering_decrease import stagger_decreasing_technologies
from .staggering_increase import stagger_increasing_technologies


def create_pipeline(**kwargs) -> Pipeline:
    return Pipeline(
        [
            node(
                compute_asset_baseline_trajectories,
                inputs=dict(
                    companies_late_sudden_trajectories="companies_late_sudden_trajectories",
                    allocated_assets_to_companies="extended_companies_forecasts",
                    assets_retirement_dates="assets_retirement_dates",
                    apply_retirement_baseline="params:apply_retirement_baseline",
                    alignment_year="params:alignment_year",
                ),
                outputs="assets_with_baseline_trajectory",
                name="compute_asset_baselines",
            ),
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
                    assets_with_baseline_trajectory="assets_with_baseline_trajectory",
                    assets_retirement_dates="assets_retirement_dates",
                    shock_year="params:shock_year",
                    alignment_year="params:alignment_year",
                    apply_retirement_shock="params:apply_retirement_shock",
                    apply_decreasing_staggered_shock="params:apply_decreasing_staggered_shock",
                    g_k="params:staggered_shock.g_k",
                    n_quantiles="params:staggered_shock.n_quantiles",
                ),
                outputs=[
                    "decreasing_tech_staggered_shock",
                    "decreasing_tech_late_sudden_trajectories_corrected",
                ],
            ),
            node(
                flag_phased_out_assets_as_retired,
                inputs=dict(
                    dec_staggered="decreasing_tech_staggered_shock",
                ),
                outputs="decreasing_tech_staggered_shock_flagged",
            ),
            node(
                stagger_increasing_technologies,
                inputs=dict(
                    late_sudden_trajectories="increasing_tech_late_sudden_trajectories",
                    assets_with_baseline_trajectory="assets_with_baseline_trajectory",
                    shock_year="params:shock_year",
                ),
                outputs=[
                    "increasing_tech_staggered_shock",
                    "increasing_tech_late_sudden_trajectories_with_names",
                ],
            ),
            node(
                concatenate_staggered_shock_results,
                inputs=dict(
                    dec_late_sudden_trajectories="decreasing_tech_staggered_shock_flagged",
                    inc_late_sudden_trajectories="increasing_tech_staggered_shock",
                    increasing_tech_late_sudden_trajectories="increasing_tech_late_sudden_trajectories_with_names",
                    decreasing_tech_late_sudden_trajectories_corrected="decreasing_tech_late_sudden_trajectories_corrected",
                    original_companies_late_sudden_trajectories="companies_late_sudden_trajectories",
                ),
                outputs=[
                    "asset_level_staggered_shock",
                    "companies_late_sudden_trajectories_corrected",
                ],
            ),
            # New: normalized/melted asset trajectories for downstream nodes
            node(
                melt_asset_staggered_trajectories,
                inputs=dict(
                    assets_staggered_late_sudden="asset_level_staggered_shock",
                ),
                outputs="asset_level_staggered_shock_melted",
            ),
            # Create frozen capacity at retirement for fixed cost calculations
            node(
                create_frozen_capacity_at_retirement,
                inputs=dict(
                    asset_level_staggered_shock="asset_level_staggered_shock",
                    assets_retirement_dates="assets_retirement_dates",
                ),
                outputs="frozen_capacity_at_retirement",
                name="create_frozen_capacity",
            ),
        ],
        tags="altrisk",
    )
