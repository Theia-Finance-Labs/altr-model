"""
Valuation model pipeline for converting earnings to NPV using DCF methodology.
"""

from kedro.pipeline import node, Pipeline, pipeline

from .nodes import (
    compute_yearly_npv_trajectories,
    calculate_npv_per_asset,
    aggregate_to_company_technology_npv,
    aggregate_to_company_npv,
)


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            # Node 1: Compute yearly NPV trajectories with financial components
            node(
                func=compute_yearly_npv_trajectories,
                inputs={
                    "asset_earnings": "asset_earnings",
                    "discount_rate_baseline": "params:dcf.discount_rate_baseline",
                    "discount_rate_shock": "params:dcf.discount_rate_shock",
                    "terminal_growth_rate": "params:dcf.terminal_value.g_real_default",
                    "terminal_growth_rate_brown": "params:dcf.terminal_value.g_real_brown",
                    "terminal_growth_rate_green": "params:dcf.terminal_value.g_real_green",
                    "terminal_method": "params:dcf.terminal_value.method",
                    "terminal_normalization_window": "params:dcf.terminal_value.normalization_window",
                    "brown_discount_spread": "params:dcf.brown_discount_spread",
                    "green_discount_spread": "params:dcf.green_discount_spread",
                    "stranding_aware_tv": "params:dcf.stranding_aware_tv",
                    "stranding_consecutive_years": "params:dcf.stranding_consecutive_years",
                    "brown_remaining_life_years": "params:dcf.brown_remaining_life_years",
                },
                outputs="yearly_npv_trajectories",
                name="compute_yearly_npv_trajectories_node",
            ),
            # Node 2: Aggregate yearly NPV to asset level with pivot
            node(
                func=calculate_npv_per_asset,
                inputs="yearly_npv_trajectories",
                outputs="asset_npv",
                name="calculate_npv_per_asset_node",
            ),
            # Node 3: Aggregate to company-technology level NPV
            node(
                func=aggregate_to_company_technology_npv,
                inputs="asset_npv",
                outputs="company_technology_npv",
                name="aggregate_to_company_technology_npv_node",
            ),
            # Node 4: Aggregate to company level NPV
            node(
                func=aggregate_to_company_npv,
                inputs="company_technology_npv",
                outputs="company_npv",
                name="aggregate_to_company_npv_node",
            ),
        ],
        tags="altrisk",
    )
