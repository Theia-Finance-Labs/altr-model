"""Pipeline for calculating asset earnings from canonical trajectories."""

from kedro.pipeline import Pipeline, node, pipeline

from .nodes import (
    compute_fcff,
    compute_flow_based_capex,
    compute_ops_block,
    validate_asset_trajectories,
    write_asset_earnings_series,
    write_asset_horizon_attributes,
)

NAMESPACE = "calculate_asset_earnings"
PIPELINE_INPUTS = {"asset_trajectories", "frozen_capacity_at_retirement"}
PIPELINE_OUTPUTS = {"asset_earnings", "asset_horizon_attributes"}
PIPELINE_PARAMETERS = {
    "apply_continued_om_baseline",
    "apply_continued_om_shock",
    "carbon_cost_method",
    "dynamic_marginal_ef",
    "include_decom_costs",
    "include_growth_capex",
    "include_replacement_capex",
    "replacement_capex_rate",
    "market_passthrough",
}


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            node(
                func=validate_asset_trajectories,
                inputs=dict(
                    asset_trajectories="asset_trajectories",
                    frozen_capacity_at_retirement="frozen_capacity_at_retirement",
                ),
                outputs="_temp_asset_panel_enriched",
                name="validate_asset_trajectories",
            ),
            node(
                func=compute_flow_based_capex,
                inputs=dict(
                    asset_panel_enriched="_temp_asset_panel_enriched",
                    include_growth_capex="params:include_growth_capex",
                    include_replacement_capex="params:include_replacement_capex",
                    replacement_capex_rate="params:replacement_capex_rate",
                    include_decom_costs="params:include_decom_costs",
                ),
                outputs="_temp_asset_capex_block",
                name="calculate_capacity_flows_and_capex",
            ),
            node(
                func=compute_ops_block,
                inputs=dict(
                    asset_capex_block="_temp_asset_capex_block",
                    market_passthrough="params:market_passthrough",
                    apply_continued_om_baseline="params:apply_continued_om_baseline",
                    apply_continued_om_shock="params:apply_continued_om_shock",
                    carbon_cost_method="params:carbon_cost_method",
                    dynamic_marginal_ef="params:dynamic_marginal_ef",
                ),
                outputs="_temp_asset_ops_block",
                name="calculate_operating_earnings",
            ),
            node(
                func=compute_fcff,
                inputs=dict(
                    asset_ops_block="_temp_asset_ops_block",
                ),
                outputs="_temp_asset_cashflows",
                name="calculate_free_cash_flow",
            ),
            node(
                func=write_asset_earnings_series,
                inputs=dict(
                    asset_cashflows="_temp_asset_cashflows",
                ),
                outputs="asset_earnings",
                name="write_asset_earnings",
            ),
            node(
                func=write_asset_horizon_attributes,
                inputs=dict(
                    asset_panel_enriched="_temp_asset_panel_enriched",
                ),
                outputs="asset_horizon_attributes",
                name="write_asset_horizon_attributes",
            ),
        ],
        inputs=PIPELINE_INPUTS,
        outputs=PIPELINE_OUTPUTS,
        parameters=PIPELINE_PARAMETERS,
        namespace=NAMESPACE,
        tags="altrisk",
    )
