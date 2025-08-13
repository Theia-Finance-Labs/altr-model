"""
This is a boilerplate pipeline 'report_outputs'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline, pipeline  # noqa

from .nodes import (
    plot_companies_late_sudden_trajectories,
    plot_staggered_shock,
    plot_assets_late_sudden_trajectories,
)


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            node(
                plot_companies_late_sudden_trajectories,
                inputs=dict(
                    companies_late_sudden_trajectories="companies_late_sudden_trajectories_compensated",
                ),
                outputs=None,
                name="plot_companies_late_sudden_trajectories",
            ),
            node(
                plot_assets_late_sudden_trajectories,
                inputs=dict(
                    assets_late_sudden_trajectories="assets_late_sudden_trajectories",
                ),
                outputs=None,
                name="plot_assets_late_sudden_trajectories",
            ),
            node(
                plot_staggered_shock,
                inputs=dict(
                    late_sudden_trajectories="companies_late_sudden_trajectories_compensated",
                    assets_forecasts="allocated_assets_to_companies",
                    asset_level_df="asset_level_staggered_shock",
                ),
                outputs=None,
                name="plot_staggered_shock",
            ),
        ],
        tags=["reporting"],
    )
