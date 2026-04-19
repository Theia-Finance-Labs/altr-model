"""
Comprehensive reporting pipeline for financial model outputs and NPV analysis.
"""

from kedro.pipeline import node, Pipeline, pipeline

from .nodes import (
    plot_late_sudden_trajectories,
    plot_staggered_shock,
    reporting_validate_inputs,
    build_reporting_views,
    plot_earnings_inner_workings,
    plot_valuation_authority_pack,
    export_reporting_tables,
    plot_asset_financial_trajectories,
    reporting_qc_summary,
)


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            # Node A : plot late sudden trajectories
            node(
                plot_late_sudden_trajectories,
                inputs=dict(
                    late_sudden_trajectories="companies_late_sudden_trajectories",
                ),
                outputs=None,
                name="plot_late_sudden_trajectories",
            ),
            # Node B : plot staggered shock
            node(
                plot_staggered_shock,
                inputs=dict(
                    late_sudden_trajectories="companies_late_sudden_trajectories_corrected",
                    asset_level_df="asset_level_staggered_shock_melted",
                    use_log_scale="params:plot_staggered_shock_use_log_scale",
                    show_shock_absorption="params:plot_staggered_shock_show_shock_absorption",
                ),
                outputs=None,
                name="plot_staggered_shock",
            ),
            # Node 1: Validate inputs and check basis alignment
            node(
                func=reporting_validate_inputs,
                inputs=dict(
                    asset_earnings="asset_earnings",
                    asset_npv="asset_npv",
                    company_npv="company_npv",
                    reporting_params="params:reporting",
                ),
                outputs={
                    "asset_earnings_validated": "asset_earnings_validated",
                    "asset_npv_validated": "asset_npv_validated",
                    "company_npv_validated": "company_npv_validated",
                    "validation_summary": "validation_summary",
                },
                name="reporting_validate_inputs_node",
            ),
            # Node 2: Build reporting views
            node(
                func=build_reporting_views,
                inputs=dict(
                    asset_earnings_validated="asset_earnings_validated",
                    asset_npv_validated="asset_npv_validated",
                    company_npv_validated="company_npv_validated",
                    reporting_params="params:reporting",
                ),
                outputs={
                    "view_asset_explain": "view_asset_explain",
                    "view_asset_npv_decomp": "view_asset_npv_decomp",
                    "view_company_tech": "view_company_tech",
                    "view_deltas": "view_deltas",
                },
                name="build_reporting_views_node",
            ),
            # Node 3: Plot earnings inner workings (engineering/explainability pack)
            node(
                func=plot_earnings_inner_workings,
                inputs=dict(
                    view_asset_explain="view_asset_explain",
                    view_asset_npv_decomp="view_asset_npv_decomp",
                    reporting_params="params:reporting",
                ),
                outputs="earnings_inner_plots_dir",
                name="plot_earnings_inner_workings_node",
            ),
            # Node 4: Plot valuation authority pack (regulator-friendly visuals)
            node(
                func=plot_valuation_authority_pack,
                inputs=dict(
                    asset_npv_validated="asset_npv_validated",
                    company_npv_validated="company_npv_validated",
                    view_company_tech="view_company_tech",
                    view_deltas="view_deltas",
                    reporting_params="params:reporting",
                ),
                outputs="authority_pack_plots_dir",
                name="plot_valuation_authority_pack_node",
            ),
            # Node 5: Export compliance-ready tables
            node(
                func=export_reporting_tables,
                inputs=dict(
                    company_npv_validated="company_npv_validated",
                    view_company_tech="view_company_tech",
                    view_asset_npv_decomp="view_asset_npv_decomp",
                    reporting_params="params:reporting",
                ),
                outputs={
                    "report_company_summary": "report_company_summary",
                    "report_technology_summary": "report_technology_summary",
                    "report_top_assets": "report_top_assets",
                    "report_methodology": "report_methodology",
                },
                name="export_reporting_tables_node",
            ),
            # Node 6: Plot asset financial trajectories by trajectory type
            node(
                func=plot_asset_financial_trajectories,
                inputs=dict(
                    yearly_npv_trajectories="yearly_npv_trajectories",
                    asset_level_staggered_shock_melted="asset_level_staggered_shock_melted",
                    reporting_params="params:reporting",
                ),
                outputs="asset_financial_trajectories_plots_dir",
                name="plot_asset_financial_trajectories_node",
            ),
            # Node 7: Quality control summary
            node(
                func=reporting_qc_summary,
                inputs=dict(
                    view_asset_npv_decomp="view_asset_npv_decomp",
                    view_asset_explain="view_asset_explain",
                    reporting_params="params:reporting",
                ),
                outputs="reporting_qc_summary",
                name="reporting_qc_summary_node",
            ),
        ],
        tags="reporting",
    )
