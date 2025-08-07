"""
Financial model pipeline for asset-level net profit calculations.
"""

from kedro.pipeline import node, Pipeline, pipeline

from .nodes import (
    calculate_asset_level_net_profits,
    aggregate_assets_to_company_technology,
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
                inputs=dict(
                    asset_level_staggered_shock="asset_level_staggered_shock",
                    downloaded_scenarios_ar6="downloaded_scenarios_ar6",
                    target_scenario="params:target_scenario",
                    baseline_scenario="params:baseline_scenario",
                    shock_year="params:shock_year",
                    market_passthrough="params:market_passthrough",
                ),
                outputs=["company_net_profits_baseline", "company_net_profits_shock"],
                name="calculate_company_level_net_profits_node",
            ),
            # Aggregate assets to company-technology level
            node(
                func=aggregate_assets_to_company_technology,
                inputs=dict(
                    assets_net_profits_baseline="company_net_profits_baseline",
                    assets_net_profits_shock="company_net_profits_shock",
                ),
                outputs=["company_tech_profits_baseline", "company_tech_profits_shock"],
                name="aggregate_assets_to_company_technology_node",
            ),
            # Aggregate company-technology to whole company level
            node(
                func=aggregate_company_technology_to_company,
                inputs=dict(
                    company_tech_profits_baseline="company_tech_profits_baseline",
                    company_tech_profits_shock="company_tech_profits_shock",
                ),
                outputs=["company_profits_baseline", "company_profits_shock"],
                name="aggregate_company_technology_to_company_node",
            ),
            # Calculate discounted net profits and terminal values
            node(
                func=calculate_discounted_net_profits,
                inputs=dict(
                    company_profits_baseline="company_profits_baseline",
                    company_profits_shock="company_profits_shock",
                    discount_rate="params:discount_rate",
                    growth_rate="params:growth_rate",
                ),
                outputs=[
                    "company_discounted_net_profits_baseline",
                    "company_discounted_net_profits_shock",
                ],
                name="calculate_discounted_net_profits_node",
            ),
        ],
        tags="altrisk",
    )
