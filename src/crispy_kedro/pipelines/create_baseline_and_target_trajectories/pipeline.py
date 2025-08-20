"""
This is a boilerplate pipeline 'create_baseline_and_target_trajectories'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline  # noqa
from .nodes import (
    aggregate_assets_to_company_level,
    calculate_tmsr,
    compute_scenarios_trajectories,
    create_companies_trajectories,
)


def create_pipeline(**kwargs) -> Pipeline:
    return Pipeline(
        [
            node(
                aggregate_assets_to_company_level,
                inputs=dict(assets_forecasts="allocated_assets_to_companies"),
                outputs="companies_technology_forecasts",
            ),
            node(
                func=calculate_tmsr,
                inputs=dict(scenarios_pathways="scenarios_pathways"),
                outputs="traj_scenario_tmsr",
            ),
            node(
                compute_scenarios_trajectories,
                inputs=dict(
                    scenarios_pathways="traj_scenario_tmsr",
                    companies_forecasts="companies_technology_forecasts",
                ),
                outputs="scenarios_trajectories",
            ),
            node(
                create_companies_trajectories,
                inputs=dict(
                    companies_forecasts="companies_technology_forecasts",
                    scenarios_trajectories="scenarios_trajectories",
                ),
                outputs="companies_trajectories",
            ),
        ],
        tags="altrisk",
    )
