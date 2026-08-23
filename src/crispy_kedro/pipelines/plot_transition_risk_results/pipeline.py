"""
Reporting pipeline: plots derived from altrisk pipeline outputs.
"""

from kedro.pipeline import Pipeline, node, pipeline

from .nodes import (
    plot_asset_financial_trajectories,
    plot_late_sudden_trajectories,
    plot_staggered_shock,
)

NAMESPACE = "plot_transition_risk_results"
PIPELINE_INPUTS = {
    "asset_earnings",
    "company_trajectories",
    "yearly_npv_trajectories",
}
PIPELINE_OUTPUTS = {"asset_financial_trajectories_plots_dir"}
PIPELINE_PARAMETERS = {
    "plot_staggered_shock_show_shock_absorption",
    "plot_staggered_shock_use_log_scale",
    "reporting",
}


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            node(
                plot_late_sudden_trajectories,
                inputs=dict(
                    late_sudden_trajectories="company_trajectories",
                ),
                outputs=None,
                name="plot_late_sudden_trajectories",
            ),
            node(
                plot_staggered_shock,
                inputs=dict(
                    late_sudden_trajectories="company_trajectories",
                    asset_level_df="asset_earnings",
                    use_log_scale="params:plot_staggered_shock_use_log_scale",
                    show_shock_absorption="params:plot_staggered_shock_show_shock_absorption",
                ),
                outputs=None,
                name="plot_staggered_shock",
            ),
            node(
                func=plot_asset_financial_trajectories,
                inputs=dict(
                    yearly_npv_trajectories="yearly_npv_trajectories",
                    asset_earnings="asset_earnings",
                    reporting_params="params:reporting",
                ),
                outputs="asset_financial_trajectories_plots_dir",
                name="plot_asset_financial_trajectories",
            ),
        ],
        inputs=PIPELINE_INPUTS,
        outputs=PIPELINE_OUTPUTS,
        parameters=PIPELINE_PARAMETERS,
        namespace=NAMESPACE,
        tags="reporting",
    )
