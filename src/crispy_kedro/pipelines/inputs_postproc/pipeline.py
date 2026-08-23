"""
This is a boilerplate pipeline 'inputs_postproc'
generated using Kedro 0.19.12
"""

from kedro.pipeline import Pipeline, node, pipeline

from .nodes import (
    apply_reduce_granularity_from_asset_to_company_level,
    determine_assets_retirement_dates,
    extend_allocated_assets_to_companies,
)

NAMESPACE = "inputs_postproc"
PIPELINE_INPUTS = {
    "allocated_assets_to_companies",
    "lifetime_per_technology",
    "scenarios_pathways",
}
PIPELINE_OUTPUTS = {
    "assets_retirement_dates",
    "companies_forecasts",
    "extended_companies_forecasts",
}
PIPELINE_PARAMETERS = {"reduce_granularity_from_asset_to_company_level"}


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            node(
                func=apply_reduce_granularity_from_asset_to_company_level,
                inputs=dict(
                    assets_forecasts="allocated_assets_to_companies",
                    reduce_granularity_from_asset_to_company_level="params:reduce_granularity_from_asset_to_company_level",
                ),
                outputs="companies_forecasts",
            ),
            node(
                extend_allocated_assets_to_companies,
                inputs=dict(
                    allocated_assets_to_companies="companies_forecasts",
                    scenarios_pathways="scenarios_pathways",
                ),
                outputs="extended_companies_forecasts",
            ),
            node(
                determine_assets_retirement_dates,
                inputs=dict(
                    allocated_assets_to_companies="extended_companies_forecasts",
                    lifetime_per_technology="lifetime_per_technology",
                ),
                outputs="assets_retirement_dates",
            ),
        ],
        inputs=PIPELINE_INPUTS,
        outputs=PIPELINE_OUTPUTS,
        parameters=PIPELINE_PARAMETERS,
        namespace=NAMESPACE,
        tags="altrisk",
    )
