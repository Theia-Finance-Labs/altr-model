"""Pipeline for preparing scenario, asset, and company projection data."""

from kedro.pipeline import Pipeline, node, pipeline

from .nodes import (
    prepare_asset_forecast_panel,
    prepare_company_projection_inputs,
    prepare_scenario_pathways,
)

NAMESPACE = "prepare_scenario_asset_and_company_inputs"
PIPELINE_INPUTS = {"assets_forecasts", "companies_ownerships", "scenarios"}
PIPELINE_OUTPUTS = {"asset_forecast_panel", "company_projection_inputs"}
PIPELINE_PARAMETERS = {
    "baseline_scenario",
    "ccs_on",
    "company_ids",
    "max_forecast_horizon",
    "reduce_granularity_from_asset_to_company_level",
    "target_scenario",
}


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            node(
                prepare_scenario_pathways,
                inputs={
                    "downloaded_scenarios": "scenarios",
                    "target_scenario": "params:target_scenario",
                    "baseline_scenario": "params:baseline_scenario",
                },
                outputs="_scenario_pathways",
                name="prepare_scenarios",
            ),
            node(
                prepare_asset_forecast_panel,
                inputs={
                    "downloaded_assets": "assets_forecasts",
                    "downloaded_companies": "companies_ownerships",
                    "scenario_pathways": "_scenario_pathways",
                    "company_ids": "params:company_ids",
                    "ccs_on": "params:ccs_on",
                    "max_forecast_horizon": "params:max_forecast_horizon",
                    "reduce_granularity_from_asset_to_company_level": "params:reduce_granularity_from_asset_to_company_level",
                },
                outputs="asset_forecast_panel",
                name="prepare_asset_forecast_panel",
            ),
            node(
                prepare_company_projection_inputs,
                inputs={
                    "asset_forecast_panel": "asset_forecast_panel",
                    "scenario_pathways": "_scenario_pathways",
                },
                outputs="company_projection_inputs",
                name="prepare_company_projection_inputs",
            ),
        ],
        inputs=PIPELINE_INPUTS,
        outputs=PIPELINE_OUTPUTS,
        parameters=PIPELINE_PARAMETERS,
        namespace=NAMESPACE,
        tags="altrisk",
    )
