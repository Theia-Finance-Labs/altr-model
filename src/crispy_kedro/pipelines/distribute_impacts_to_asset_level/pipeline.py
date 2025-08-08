"""
This is a boilerplate pipeline 'distribute_impacts_to_asset_level'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline, pipeline  # noqa
from .nodes import apply_staggered_shock_split


def create_pipeline(**kwargs) -> Pipeline:
    return Pipeline(
        [
            node(
                apply_staggered_shock_split,
                inputs=dict(
                    late_sudden_trajectories="all_late_sudden_trajectories",
                    allocated_assets_to_companies="allocated_assets_to_companies",
                    assets_retirement_dates="assets_retirement_dates",
                    shock_year="params:shock_year",
                ),
                outputs="asset_level_staggered_shock",
            ),
        ],
        tags="altrisk",
    )
