"""
This is a boilerplate pipeline 'download_inputs'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline, pipeline  # noqa
from .nodes import download_scenarios, download_assets, download_companies
from .legacy_nodes import make_assets_data, make_scenarios_data, make_financial_data


def create_pipeline(**kwargs) -> Pipeline:

    return pipeline(
        [
            node(
                download_scenarios,
                inputs=["scenarios"],
                outputs="downloaded_scenarios",
            ),
            node(
                download_assets,
                inputs=["assets_forecasts"],
                outputs="downloaded_assets",
            ),
            node(
                download_companies,
                inputs=["plant_ownerships"],
                outputs="downloaded_companies",
            ),
            node(
                func=make_assets_data,
                inputs=[
                    "downloaded_assets",
                ],
                outputs="assets_data",
                name="make_assets_data",
            ),
            node(
                func=make_scenarios_data,
                inputs="downloaded_scenarios",
                outputs="scenarios_data",
                name="make_scenarios_data",
            ),
            node(
                func=make_financial_data,
                inputs=[
                    "assets_data",
                    "downloaded_companies",
                    "financial_averages",
                ],
                outputs="financial_data",
                name="make_financial_data",
            ),
        ],
        tags="download_inputs",
    )
