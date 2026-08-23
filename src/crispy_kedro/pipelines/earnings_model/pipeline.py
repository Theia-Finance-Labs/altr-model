"""
Comprehensive earnings model pipeline with 10 nodes implementing
full financial methodology including synthetic assets and tranche logic.
"""

from kedro.pipeline import Pipeline, node, pipeline

from .nodes import (
    assemble_asset_panel,
    build_scenario_surfaces,
    compute_fcff,
    compute_flow_based_capex,
    compute_ops_block,
    validate_and_standardize_inputs,
    write_asset_earnings_series,
)

NAMESPACE = "earnings_model"
PIPELINE_INPUTS = {
    "all_alignment_classifications",
    "asset_level_staggered_shock_melted",
    "companies_forecasts",
    "frozen_capacity_at_retirement",
    "scenarios_pathways",
}
PIPELINE_OUTPUTS = {"asset_earnings"}
PIPELINE_PARAMETERS = {
    "apply_continued_om_baseline",
    "apply_continued_om_shock",
    "include_decom_costs",
    "include_growth_capex",
    "include_replacement_capex",
    "market_passthrough",
    "shock_year",
}


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            # Node 1: Validate and standardize inputs
            node(
                func=validate_and_standardize_inputs,
                inputs=dict(
                    asset_level_staggered_shock="asset_level_staggered_shock_melted",
                    downloaded_scenarios="scenarios_pathways",
                    all_alignment_classifications="all_alignment_classifications",
                    assets_data="companies_forecasts",
                    frozen_capacity_at_retirement="frozen_capacity_at_retirement",
                ),
                outputs=dict(
                    assets_validated="_temp_assets_validated",
                    scenarios_validated="_temp_scenarios_validated",
                    alignments_validated="_temp_alignments_validated",
                ),
            ),
            # Node 2: Build scenario surfaces
            node(
                func=build_scenario_surfaces,
                inputs="_temp_scenarios_validated",
                outputs="_temp_scenario_surfaces",
            ),
            # Node 4: Assemble asset panel
            node(
                func=assemble_asset_panel,
                inputs=dict(
                    assets_adjusted="_temp_assets_validated",
                    scenario_surfaces="_temp_scenario_surfaces",
                    shock_year="params:shock_year",
                ),
                outputs="_temp_asset_panel_enriched",
            ),
            # Node 5: Compute flow-based CapEx using upstream capex_indicator/capex_capacity
            node(
                func=compute_flow_based_capex,
                inputs=dict(
                    asset_panel_enriched="_temp_asset_panel_enriched",
                    include_growth_capex="params:include_growth_capex",
                    include_replacement_capex="params:include_replacement_capex",
                    include_decom_costs="params:include_decom_costs",
                ),
                outputs="_temp_asset_capex_block",
            ),
            # Node 6: Compute operations block
            node(
                func=compute_ops_block,
                inputs=dict(
                    asset_capex_block="_temp_asset_capex_block",
                    market_passthrough="params:market_passthrough",
                    apply_continued_om_baseline="params:apply_continued_om_baseline",
                    apply_continued_om_shock="params:apply_continued_om_shock",
                ),
                outputs="_temp_asset_ops_block",
            ),
            # Node 7: Compute FCFF
            node(
                func=compute_fcff,
                inputs=dict(
                    asset_ops_block="_temp_asset_ops_block",
                ),
                outputs="_temp_asset_cashflows",
            ),
            # Node 8: Write final asset earnings series
            node(
                func=write_asset_earnings_series,
                inputs=dict(
                    asset_cashflows="_temp_asset_cashflows",
                ),
                outputs="asset_earnings",
            ),
        ],
        inputs=PIPELINE_INPUTS,
        outputs=PIPELINE_OUTPUTS,
        parameters=PIPELINE_PARAMETERS,
        namespace=NAMESPACE,
        tags="altrisk",
    )
