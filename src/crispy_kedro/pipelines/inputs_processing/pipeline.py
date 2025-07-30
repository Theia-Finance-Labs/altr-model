"""
This is a boilerplate pipeline 'inputs_processing'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline  # noqa
from .nodes import (
    filter_scenarios,
    filter_assets,
    filter_companies,
    allocate_assets_to_companies,
)


def create_pipeline(**kwargs) -> Pipeline:
    return Pipeline(
        [
            node(
                func=filter_scenarios,
                inputs=[
                    "downloaded_scenarios",
                    "params:target_scenario",
                    "params:baseline_scenario",
                ],
                outputs="scenarios_pathways",
            ),
            node(
                func=filter_assets,
                inputs=["downloaded_assets", "companies_ownership_tree"],
                outputs="assets_forecasts",
            ),
            node(
                func=filter_companies,
                inputs=["downloaded_companies", "params:company_ids"],
                outputs="companies_ownership_tree",
            ),
            node(
                func=allocate_assets_to_companies,
                inputs=[
                    "assets_forecasts",
                    "companies_ownership_tree",
                ],
                outputs="allocated_assets_to_companies",
            ),
        ],
        tags=["altrisk", "trisk"],
    )
