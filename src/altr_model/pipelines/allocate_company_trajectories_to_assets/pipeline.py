"""Allocate company trajectories to assets and reconcile company totals."""

from kedro.pipeline import Pipeline, node, pipeline

from .nodes import (
    allocate_decreasing_company_trajectories_to_assets,
    allocate_increasing_company_trajectories_to_assets,
    build_canonical_asset_trajectories,
    combine_asset_allocation_branches,
    compute_asset_baselines,
    create_frozen_capacity_at_retirement,
    extend_asset_panel_and_attach_retirement,
    reconcile_realized_company_trajectories,
    split_company_pathways_by_technology_direction,
)

NAMESPACE = "allocate_company_trajectories_to_assets"
PIPELINE_INPUTS = {"asset_forecast_panel", "company_pathways_pre_allocation"}
PIPELINE_OUTPUTS = {
    "asset_trajectories",
    "company_trajectories",
    "frozen_capacity_at_retirement",
}
PIPELINE_PARAMETERS = {
    "alignment_year",
    "apply_decreasing_staggered_shock",
    "apply_retirement_baseline",
    "apply_retirement_shock",
    "shock_year",
    "staggered_shock.g_k",
    "staggered_shock.n_quantiles",
}


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            node(
                extend_asset_panel_and_attach_retirement,
                inputs="asset_forecast_panel",
                outputs="_extended_asset_panel",
                name="extend_assets_and_attach_retirement",
            ),
            node(
                compute_asset_baselines,
                inputs={
                    "company_pathways_pre_allocation": "company_pathways_pre_allocation",
                    "extended_asset_panel": "_extended_asset_panel",
                    "apply_retirement_baseline": "params:apply_retirement_baseline",
                    "alignment_year": "params:alignment_year",
                },
                outputs="_assets_with_baseline",
                name="compute_asset_baselines",
            ),
            node(
                split_company_pathways_by_technology_direction,
                inputs="company_pathways_pre_allocation",
                outputs={
                    "decreasing_company_pathways": "_decreasing_company_pathways",
                    "increasing_company_pathways": "_increasing_company_pathways",
                },
                name="split_company_pathways_by_technology_direction",
            ),
            node(
                allocate_decreasing_company_trajectories_to_assets,
                inputs={
                    "decreasing_company_pathways": "_decreasing_company_pathways",
                    "assets_with_baseline": "_assets_with_baseline",
                    "shock_year": "params:shock_year",
                    "alignment_year": "params:alignment_year",
                    "apply_retirement_shock": "params:apply_retirement_shock",
                    "apply_decreasing_staggered_shock": "params:apply_decreasing_staggered_shock",
                    "g_k": "params:staggered_shock.g_k",
                    "n_quantiles": "params:staggered_shock.n_quantiles",
                },
                outputs="_decreasing_asset_allocation",
                name="allocate_decreasing_company_trajectories_to_assets",
            ),
            node(
                allocate_increasing_company_trajectories_to_assets,
                inputs={
                    "increasing_company_pathways": "_increasing_company_pathways",
                    "assets_with_baseline": "_assets_with_baseline",
                    "shock_year": "params:shock_year",
                },
                outputs="_increasing_asset_allocation",
                name="allocate_increasing_company_trajectories_to_assets",
            ),
            node(
                combine_asset_allocation_branches,
                inputs={
                    "decreasing_asset_allocation": "_decreasing_asset_allocation",
                    "increasing_asset_allocation": "_increasing_asset_allocation",
                    "assets_with_baseline": "_assets_with_baseline",
                },
                outputs="_asset_allocation_wide",
                name="combine_asset_allocation_branches",
            ),
            node(
                create_frozen_capacity_at_retirement,
                inputs="_asset_allocation_wide",
                outputs="frozen_capacity_at_retirement",
                name="create_frozen_capacity_at_retirement",
            ),
            node(
                build_canonical_asset_trajectories,
                inputs={
                    "asset_allocation_wide": "_asset_allocation_wide",
                    "company_pathways_pre_allocation": "company_pathways_pre_allocation",
                },
                outputs="asset_trajectories",
                name="build_canonical_asset_trajectories",
            ),
            node(
                reconcile_realized_company_trajectories,
                inputs={
                    "asset_trajectories": "asset_trajectories",
                    "company_pathways_pre_allocation": "company_pathways_pre_allocation",
                },
                outputs="company_trajectories",
                name="reconcile_realized_company_trajectories",
            ),
        ],
        inputs=PIPELINE_INPUTS,
        outputs=PIPELINE_OUTPUTS,
        parameters=PIPELINE_PARAMETERS,
        namespace=NAMESPACE,
        tags="altrisk",
    )
