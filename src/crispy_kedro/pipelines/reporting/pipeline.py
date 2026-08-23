"""
Reporting pipeline: plots derived from altrisk pipeline outputs.
"""

from kedro.pipeline import Pipeline, node, pipeline

from .nodes import (
    plot_asset_financial_trajectories,
    plot_late_sudden_trajectories,
    plot_staggered_shock,
)


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            # Node A : plot late sudden trajectories
            node(
                plot_late_sudden_trajectories,
                inputs=dict(
                    late_sudden_trajectories="companies_late_sudden_trajectories",
                ),
                outputs=None,
                name="plot_late_sudden_trajectories",
            ),
            # Node B : plot staggered shock
            node(
                plot_staggered_shock,
                inputs=dict(
                    late_sudden_trajectories="companies_late_sudden_trajectories_corrected",
                    asset_level_df="asset_level_staggered_shock_melted",
                    use_log_scale="params:plot_staggered_shock_use_log_scale",
                    show_shock_absorption="params:plot_staggered_shock_show_shock_absorption",
                ),
                outputs=None,
                name="plot_staggered_shock",
            ),
            # Node C : plot asset financial trajectories by trajectory type
            node(
                func=plot_asset_financial_trajectories,
                inputs=dict(
                    yearly_npv_trajectories="yearly_npv_trajectories",
                    asset_level_staggered_shock_melted="asset_level_staggered_shock_melted",
                    reporting_params="params:reporting",
                ),
                outputs="asset_financial_trajectories_plots_dir",
                name="plot_asset_financial_trajectories_node",
            ),
        ],
        tags="reporting",
    )
