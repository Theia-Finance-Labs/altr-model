"""
Valuation model pipeline for converting earnings to NPV using DCF methodology.
"""

from kedro.pipeline import node, Pipeline, pipeline

from .nodes import (
    calculate_npv_per_asset,
    aggregate_to_company_technology_npv,
    aggregate_to_company_npv,
)


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            # Node 1: Calculate NPV per asset with DCF and terminal value
            node(
                func=calculate_npv_per_asset,
                inputs={
                    "asset_earnings": "asset_earnings",
                    "discount_rate_baseline": "params:dcf.discount_rate_baseline",
                    "discount_rate_shock": "params:dcf.discount_rate_shock",
                    "terminal_growth_rate": "params:dcf.terminal_value.g_real_default",
                    "terminal_method": "params:dcf.terminal_value.method",
                },
                outputs="asset_npv",
                name="calculate_npv_per_asset_node",
            ),
            # Node 2: Aggregate to company-technology level NPV
            node(
                func=aggregate_to_company_technology_npv,
                inputs="asset_npv",
                outputs="company_technology_npv",
                name="aggregate_to_company_technology_npv_node",
            ),
            # Node 3: Aggregate to company level NPV
            node(
                func=aggregate_to_company_npv,
                inputs="company_technology_npv",
                outputs="company_npv",
                name="aggregate_to_company_npv_node",
            ),
        ],
        tags="altrisk",
    )
