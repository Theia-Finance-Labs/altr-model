"""
Comprehensive earnings model pipeline with 10 nodes implementing
full financial methodology including synthetic assets and tranche logic.
"""

from kedro.pipeline import node, Pipeline, pipeline

from .nodes import (
    validate_and_standardize_inputs,
    build_scenario_surfaces,
    normalize_capacity_growth_to_new_assets,
    assemble_asset_panel,
    compute_flow_based_capex,
    compute_ops_block,
    compute_fcff,
    write_asset_earnings_series,
    aggregate_to_company_technology_earnings,
    aggregate_to_company_earnings,
)


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            # Node 1: Validate and standardize inputs
            node(
                func=validate_and_standardize_inputs,
                inputs={
                    "asset_level_staggered_shock": "asset_level_staggered_shock",
                    "downloaded_scenarios": "scenarios_pathways",
                    "all_alignment_classifications": "all_alignment_classifications",
                    "assets_data": "assets_forecasts_with_scenario_geographies",
                },
                outputs={
                    "assets_validated": "_temp_assets_validated",
                    "scenarios_validated": "_temp_scenarios_validated",
                    "alignments_validated": "_temp_alignments_validated",
                    "assets_static_validated": "_temp_assets_static_validated",
                },
                name="validate_and_standardize_inputs_node",
            ),
            # Node 2: Build scenario surfaces
            node(
                func=build_scenario_surfaces,
                inputs="_temp_scenarios_validated",
                outputs="_temp_scenario_surfaces",
                name="build_scenario_surfaces_node",
            ),
            # Node 3: Normalize capacity growth to synthetic assets
            node(
                func=normalize_capacity_growth_to_new_assets,
                inputs={
                    "assets_validated": "_temp_assets_validated",
                    "alignments_validated": "_temp_alignments_validated",
                },
                outputs={
                    "assets_adjusted": "_temp_assets_adjusted",
                    "synthetic_tranche_log": "_temp_synthetic_tranche_log",
                    "synthetic_asset_registry": "_temp_synthetic_asset_registry",
                },
                name="normalize_capacity_growth_to_new_assets_node",
            ),
            # Node 4: Assemble asset panel
            node(
                func=assemble_asset_panel,
                inputs={
                    "assets_adjusted": "_temp_assets_adjusted",
                    "synthetic_asset_registry": "_temp_synthetic_asset_registry",
                    "scenario_surfaces": "_temp_scenario_surfaces",
                    "assets_static_validated": "_temp_assets_static_validated",
                },
                outputs="_temp_asset_panel_enriched",
                name="assemble_asset_panel_node",
            ),
            # Node 5: Compute flow-based CapEx using upstream capex_indicator/capex_capacity
            node(
                func=compute_flow_based_capex,
                inputs={
                    "asset_panel_enriched": "_temp_asset_panel_enriched",
                    "include_replacement_capex": "params:include_replacement_capex",
                    "include_decom_costs": "params:include_decom_costs",
                },
                outputs="_temp_asset_capex_block",
                name="compute_flow_based_capex_node",
            ),
            # Node 6: Compute operations block
            node(
                func=compute_ops_block,
                inputs={
                    "asset_capex_block": "_temp_asset_capex_block",
                    "market_passthrough": "params:market_passthrough",
                },
                outputs="_temp_asset_ops_block",
                name="compute_ops_block_node",
            ),
            # Node 7: Compute FCFF
            node(
                func=compute_fcff,
                inputs="_temp_asset_ops_block",
                outputs="_temp_asset_cashflows",
                name="compute_fcff_node",
            ),
            # Node 8: Write final asset earnings series
            node(
                func=write_asset_earnings_series,
                inputs="_temp_asset_cashflows",
                outputs="asset_earnings",
                name="write_asset_earnings_series_node",
            ),
            # Node 9: Aggregate to company-technology level
            node(
                func=aggregate_to_company_technology_earnings,
                inputs="_temp_asset_cashflows",
                outputs="company_technology_earnings",
                name="aggregate_to_company_technology_earnings_node",
            ),
            # Node 10: Aggregate to company level
            node(
                func=aggregate_to_company_earnings,
                inputs="company_technology_earnings",
                outputs="company_earnings",
                name="aggregate_to_company_earnings_node",
            ),
        ],
        tags="altrisk",
    )
