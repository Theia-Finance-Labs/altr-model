"""
Valuation model pipeline for converting earnings to NPV using DCF methodology.
"""

from kedro.pipeline import Pipeline, node, pipeline

from .nodes import (
    aggregate_to_company_npv,
    aggregate_to_company_technology_npv,
    calculate_npv_per_asset,
    compute_yearly_npv_trajectories,
)

NAMESPACE = "calculate_asset_and_company_npv"
PIPELINE_INPUTS = {"asset_earnings"}
PIPELINE_OUTPUTS = {
    "asset_npv",
    "company_npv",
    "company_technology_npv",
    "yearly_npv_trajectories",
}
PIPELINE_PARAMETERS = {
    "dcf.discount_rate_baseline",
    "dcf.discount_rate_shock",
    "dcf.terminal_value.g_real_default",
    "dcf.terminal_value.method",
}


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            node(
                func=compute_yearly_npv_trajectories,
                inputs={
                    "asset_earnings": "asset_earnings",
                    "discount_rate_baseline": "params:dcf.discount_rate_baseline",
                    "discount_rate_shock": "params:dcf.discount_rate_shock",
                    "terminal_growth_rate": "params:dcf.terminal_value.g_real_default",
                    "terminal_method": "params:dcf.terminal_value.method",
                },
                outputs="yearly_npv_trajectories",
                name="calculate_yearly_npv_trajectories",
            ),
            node(
                func=calculate_npv_per_asset,
                inputs="yearly_npv_trajectories",
                outputs="asset_npv",
                name="aggregate_npv_by_asset",
            ),
            node(
                func=aggregate_to_company_technology_npv,
                inputs="asset_npv",
                outputs="company_technology_npv",
                name="aggregate_npv_by_company_and_technology",
            ),
            node(
                func=aggregate_to_company_npv,
                inputs="company_technology_npv",
                outputs="company_npv",
                name="aggregate_npv_by_company",
            ),
        ],
        inputs=PIPELINE_INPUTS,
        outputs=PIPELINE_OUTPUTS,
        parameters=PIPELINE_PARAMETERS,
        namespace=NAMESPACE,
        tags="altrisk",
    )
