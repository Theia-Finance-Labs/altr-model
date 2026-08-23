"""
This is a boilerplate pipeline 'inputs_processing'
generated using Kedro 0.19.12
"""

from kedro.pipeline import Pipeline, node, pipeline

from .nodes import (
    allocate_assets_to_companies,
    apply_ccs_suffix,
    assign_scenario_geographies_to_assets,
    check_input_parameters,
    determine_increasing_or_decreasing_techs,
    determine_lifetime_per_technology,
    filter_assets,
    filter_companies,
    filter_scenarios,
    scale_electricity_price,
)

NAMESPACE = "inputs_processing"
PIPELINE_INPUTS = {
    "downloaded_assets",
    "downloaded_companies",
    "downloaded_scenarios",
}
PIPELINE_OUTPUTS = {
    "allocated_assets_to_companies",
    "increasing_or_decreasing_techs",
    "lifetime_per_technology",
    "scenarios_pathways",
}
PIPELINE_PARAMETERS = {
    "alignment_year",
    "baseline_scenario",
    "ccs_on",
    "company_ids",
    "max_forecast_horizon",
    "ownership_type",
    "shock_year",
    "target_scenario",
    "theta_capex_recovery",
}


def create_pipeline(**kwargs) -> Pipeline:
    """Create the inputs processing pipeline."""
    return pipeline(
        [
            node(
                func=check_input_parameters,
                inputs=dict(
                    shock_year="params:shock_year",
                    alignment_year="params:alignment_year",
                ),
                outputs=None,
            ),
            node(
                func=filter_scenarios,
                inputs=dict(
                    scenarios_pathways="downloaded_scenarios",
                    target_scenario="params:target_scenario",
                    baseline_scenario="params:baseline_scenario",
                ),
                outputs="scenarios_pathways_filtered",
            ),
            node(
                func=scale_electricity_price,
                inputs=dict(
                    scenarios_pathways="scenarios_pathways_filtered",
                    theta="params:theta_capex_recovery",
                ),
                outputs="scenarios_pathways",
            ),
            node(
                func=filter_companies,
                inputs=dict(
                    companies_ownership_tree="downloaded_companies",
                    company_ids="params:company_ids",
                    ownership_type="params:ownership_type",
                ),
                outputs="companies_ownership_tree",
            ),
            node(
                func=apply_ccs_suffix,
                inputs=dict(
                    assets_forecasts="downloaded_assets",
                    companies_ownership_tree="companies_ownership_tree",
                    scenarios_pathways="scenarios_pathways",
                    ccs_on="params:ccs_on",
                ),
                outputs=["assets_forecasts_ccs", "companies_ownership_tree_ccs"],
            ),
            node(
                func=filter_assets,
                inputs=dict(
                    assets_forecasts="assets_forecasts_ccs",
                    companies_ownership_tree="companies_ownership_tree_ccs",
                    scenarios_pathways="scenarios_pathways",
                    max_forecast_horizon="params:max_forecast_horizon",
                ),
                outputs="assets_forecasts",
            ),
            node(
                assign_scenario_geographies_to_assets,
                inputs=dict(
                    assets_forecasts="assets_forecasts",
                    scenarios_pathways="scenarios_pathways",
                ),
                outputs="assets_forecasts_with_scenario_geographies",
            ),
            node(
                func=allocate_assets_to_companies,
                inputs=dict(
                    assets_forecasts="assets_forecasts_with_scenario_geographies",
                    companies_ownership_tree="companies_ownership_tree_ccs",
                    scenarios_pathways="scenarios_pathways",
                ),
                outputs="allocated_assets_to_companies",
            ),
            node(
                determine_increasing_or_decreasing_techs,
                inputs=dict(scenarios_pathways="scenarios_pathways"),
                outputs="increasing_or_decreasing_techs",
            ),
            node(
                determine_lifetime_per_technology,
                inputs=dict(scenarios_pathways="scenarios_pathways"),
                outputs="lifetime_per_technology",
            ),
        ],
        inputs=PIPELINE_INPUTS,
        outputs=PIPELINE_OUTPUTS,
        parameters=PIPELINE_PARAMETERS,
        namespace=NAMESPACE,
        tags=["altrisk", "trisk"],
    )
