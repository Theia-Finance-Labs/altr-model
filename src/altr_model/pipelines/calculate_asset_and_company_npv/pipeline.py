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
PIPELINE_INPUTS = {"asset_earnings", "asset_horizon_attributes"}
PIPELINE_OUTPUTS = {
    "asset_npv",
    "company_npv",
    "company_technology_npv",
    "yearly_npv_trajectories",
}
PIPELINE_PARAMETERS = {
    "dcf.brown_discount_spread",
    "dcf.brown_remaining_life_years",
    "dcf.brown_technologies",
    "dcf.discount_rate_baseline",
    "dcf.discount_rate_shock",
    "dcf.negative_tv_method",
    "dcf.stranding_aware_tv",
    "dcf.stranding_consecutive_years",
    "dcf.terminal_value.g_real_brown",
    "dcf.terminal_value.g_real_default",
    "dcf.terminal_value.g_real_green",
    "dcf.terminal_value.method",
    "dcf.terminal_value.normalization_window",
    "dcf.tv_anchor_policy",
}


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            node(
                func=compute_yearly_npv_trajectories,
                inputs={
                    "asset_earnings": "asset_earnings",
                    "asset_horizon_attributes": "asset_horizon_attributes",
                    "discount_rate_baseline": "params:dcf.discount_rate_baseline",
                    "discount_rate_shock": "params:dcf.discount_rate_shock",
                    "terminal_growth_rate": "params:dcf.terminal_value.g_real_default",
                    "terminal_method": "params:dcf.terminal_value.method",
                    "terminal_growth_rate_brown": "params:dcf.terminal_value.g_real_brown",
                    "terminal_growth_rate_green": "params:dcf.terminal_value.g_real_green",
                    "terminal_normalization_window": "params:dcf.terminal_value.normalization_window",
                    "brown_discount_spread": "params:dcf.brown_discount_spread",
                    "brown_technologies": "params:dcf.brown_technologies",
                    "stranding_aware_tv": "params:dcf.stranding_aware_tv",
                    "stranding_consecutive_years": "params:dcf.stranding_consecutive_years",
                    "brown_remaining_life_years": "params:dcf.brown_remaining_life_years",
                    "negative_tv_method": "params:dcf.negative_tv_method",
                    "tv_anchor_policy": "params:dcf.tv_anchor_policy",
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
