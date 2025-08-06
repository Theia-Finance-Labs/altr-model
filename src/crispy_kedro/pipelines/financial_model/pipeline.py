"""
Financial model pipeline for asset-level net profit calculations.
"""

from kedro.pipeline import node, Pipeline, pipeline

from .nodes import (
    calculate_asset_level_net_profits,
    aggregate_company_technology_to_company,
    calculate_discounted_net_profits,
)


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            # Calculate company-level net profits using AR6 scenarios
            # Note: Input is company-level trajectories, not asset-level yet
            node(
                func=calculate_asset_level_net_profits,
                inputs=[
                    "asset_level_staggered_shock",
                    "downloaded_scenarios_ar6",
                    "params:shock_year",
                    "params:market_passthrough",
                ],
                outputs=["company_net_profits_baseline", "company_net_profits_shock"],
                name="calculate_company_level_net_profits_node",
            ),
            # Aggregate to whole company level (sum across technologies)
            node(
                func=aggregate_company_technology_to_company,
                inputs=["company_net_profits_baseline", "company_net_profits_shock"],
                outputs=["company_profits_baseline", "company_profits_shock"],
                name="aggregate_to_company_level_node",
            ),
            # Calculate discounted net profits and terminal values
            node(
                func=calculate_discounted_net_profits,
                inputs=[
                    "company_profits_baseline",
                    "company_profits_shock",
                    "params:discount_rate",
                    "params:growth_rate",
                ],
                outputs=[
                    "company_discounted_net_profits_baseline",
                    "company_discounted_net_profits_shock",
                ],
                name="calculate_discounted_net_profits_node",
            ),
        ]
    )
