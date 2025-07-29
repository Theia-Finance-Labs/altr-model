"""
This is a boilerplate pipeline 'create_baseline_and_target_trajectories'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline  # noqa
from .nodes import (
    assign_scenario_geographies_to_assets,
    aggregate_assets_to_company_level,
    calculate_tmsr,
    compute_scenarios_trajectories,
    compute_assets_trajectories,
)


def create_pipeline(**kwargs) -> Pipeline:
    return Pipeline(
        [
            node(
                assign_scenario_geographies_to_assets,
                inputs=dict(assets_data="traj_assets", scenarios_data="traj_scenario"),
                outputs="assets_data_with_scenario_geographies",
            ),
            node(
                aggregate_assets_to_company_level,
                inputs=dict(assets_data="assets_data_with_scenario_geographies"),
                outputs="companies_technology_forecasts",
            ),
            node(
                func=calculate_tmsr,
                inputs=dict(scenarios_data="traj_scenario"),
                outputs="traj_scenario_tmsr",
            ),
            node(
                compute_scenarios_trajectories,
                inputs=dict(
                    scenarios_data="traj_scenario_tmsr",
                    assets_data="companies_technology_forecasts",
                ),
                outputs="scenarios_trajectories",
            ),
            node(
                compute_assets_trajectories,
                inputs=dict(
                    assets_data="companies_technology_forecasts",
                    scenarios_trajectories="scenarios_trajectories",
                ),
                outputs="assets_trajectories",
            ),
        ],
        tags="altrisk",
    )
