"""
This is a boilerplate pipeline 'distribute_impacts_to_asset_level'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline, pipeline  # noqa
from .nodes import staggered_shock, plot_staggered_shock


def create_pipeline(**kwargs) -> Pipeline:
    return Pipeline(
        [
            node(
                staggered_shock,
                inputs=dict(
                    late_sudden_trajectories="all_late_sudden_trajectories",
                    companies_ownership_tree="companies_ownership_tree",
                    assets_forecasts="allocated_assets_to_companies",
                    increasing_or_decreasing_techs="increasing_or_decreasing_techs",
                    shock_year="params:shock_year",
                ),
                outputs="companies_staggered_lated_sudden",
            ),
            node(
                plot_staggered_shock,
                inputs=dict(
                    late_sudden_trajectories="all_late_sudden_trajectories",
                    asset_level_df="companies_staggered_lated_sudden",
                ),
                outputs=None,
            ),
        ],
        tags="altrisk",
    )
