"""
This is a boilerplate pipeline 'inputs_processing'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline, pipeline  # noqa
from .nodes import filter_scenarios, filter_assets, filter_companies
from .legacy_nodes import make_assets_data, make_scenarios_data, make_financial_data


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            node(
                func=filter_scenarios,
                inputs=[
                    "scenarios",
                    "params:target_scenario",
                    "params:scenario_geography",
                ],
                outputs="traj_scenario",
            ),
            node(
                func=filter_assets,
                inputs=["assets_forecasts", "params:asset_ids"],
                outputs="traj_assets_raw",
            ),
            node(
                func=filter_companies,
                inputs=["plant_ownerships", "traj_assets_raw"],
                outputs="companies_ownership_tree",
            ),
            node(
                func=make_assets_data,
                inputs=[
                    "traj_assets_raw",
                    "params:forecast_horizon",
                ],
                outputs="assets_data",
            ),
            node(
                func=make_scenarios_data,
                inputs="scenarios",
                outputs="scenarios_data",
            ),
            node(
                func=make_financial_data,
                inputs=[
                    "traj_assets_raw_truncated",
                    "companies_ownership_tree",
                    "financial_averages",
                ],
                outputs="financial_data",
            ),
        ]
    )
