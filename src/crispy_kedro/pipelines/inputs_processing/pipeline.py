"""
This is a boilerplate pipeline 'inputs_processing'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline  # noqa
from .nodes import (
    filter_scenarios,
    filter_assets,
    filter_companies,
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
                inputs=["downloaded_assets", "params:asset_ids"],
                outputs="assets_forecasts",
            ),
            node(
                func=filter_companies,
                inputs=["downloaded_companies", "assets_forecasts"],
                outputs="companies_ownership_tree",
            ),
        ],
        tags=["altrisk", "trisk"],
    )
