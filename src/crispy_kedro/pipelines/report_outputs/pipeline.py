"""
This is a boilerplate pipeline 'report_outputs'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline, pipeline  # noqa

from .nodes import plot_late_sudden_trajectories, plot_staggered_shock


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            node(
                plot_late_sudden_trajectories,
                inputs=dict(
                    late_sudden_trajectories="all_late_sudden_trajectories",
                    assets_forecasts="allocated_assets_to_companies",
                ),
                outputs=None,
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
        tags=["reporting"],
    )
