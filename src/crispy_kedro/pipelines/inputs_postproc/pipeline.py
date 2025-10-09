"""
This is a boilerplate pipeline 'inputs_postproc'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline, pipeline  # noqa

from .nodes import (
    align_scenarios_at_first_year,
    apply_reduce_granularity_from_asset_to_company_level,
    determine_assets_retirement_dates,
    extend_allocated_assets_to_companies,
)


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
        tags="altrisk",
    )
