"""
This is a boilerplate pipeline 'layer2'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline, pipeline  # noqa
from .nodes import (
    build_price_trajectory,
    calculate_net_profits,
    calculate_discounted_net_profits,
)


def create_pipeline(**kwargs) -> Pipeline:
    return Pipeline(
        [
            node(
                func=build_price_trajectory,
                inputs=[
                    "traj_scenario",
                    "params:shock_year",
                ],
                outputs="traj_technology_prices",
            ),
            node(
                func=calculate_net_profits,
                inputs=[
                    "financial_averages",
                    "traj_companies_baseline",
                    "traj_companies_shock",
                    "traj_technology_prices",
                ],
                outputs=[
                    "traj_companies_revenue_baseline",
                    "traj_companies_revenue_shock",
                ],
            ),
            node(
                func=calculate_discounted_net_profits,
                inputs=[
                    "traj_companies_revenue_baseline",
                    "traj_companies_revenue_shock",
                    "params:discount_rate",
                    "params:growth_rate",
                ],
                outputs=[
                    "traj_companies_net_profits_baseline",
                    "traj_companies_net_profits_shock",
                ],
            ),
        ],
        tags="trisk",
    )
