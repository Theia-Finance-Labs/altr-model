"""
This is a boilerplate pipeline 'download_inputs'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline, pipeline  # noqa
from .nodes import download_scenarios, download_assets, download_companies


def create_pipeline(**kwargs) -> Pipeline:

    return Pipeline(
        [
            node(
                download_scenarios,
                inputs=["db_scenarios_pathways"],
                outputs="downloaded_scenarios",
            ),
            node(
                download_assets,
                inputs=["db_assets_forecasts"],
                outputs="downloaded_assets",
            ),
            node(
                download_companies,
                inputs=["plant_ownerships"],
                outputs="downloaded_companies",
            ),
        ],
        tags="download_inputs",
    )
