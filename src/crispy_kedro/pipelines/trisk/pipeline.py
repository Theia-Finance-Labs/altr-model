"""
This is a boilerplate pipeline 'trisk'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline, pipeline
from .nodes.input_trajectories import (
    filter_assets,
    compute_base_trajectory,
    compute_truncated_trajectory,
    compute_baseline_trajectory,
)
from .nodes.scenario_trajectories import filter_scenarios, calculate_fair_share_perc


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            node(
                func=filter_scenarios,
                inputs=[
                    "scenarios",
                    "params:baseline_scenario",
                    "params:target_scenario",
                    "params:scenario_geography",
                ],
                outputs="traj_scenario",
            ),
            node(
                func=calculate_fair_share_perc,
                inputs=["traj_scenario"],
                outputs="traj_scenario_fair_share_perc",
            ),
            node(
                func=filter_assets,
                inputs=["plant_detail", "plant_events", "params:asset_ids"],
                outputs=["filtered_plant_detail", "filtered_events"],
            ),
            node(
                func=compute_base_trajectory,
                inputs=["filtered_plant_detail", "filtered_events"],
                outputs="base_trajectory",
                name="compute_base_trajectory_node",
            ),
            node(
                func=compute_truncated_trajectory,
                inputs=["base_trajectory", "traj_scenario_fair_share_perc"],
                outputs="truncated_trajectory",
                name="compute_truncated_trajectory_node",
            ),
            node(
                func=compute_baseline_trajectory,
                inputs=["truncated_trajectory", "traj_scenario_fair_share_perc"],
                outputs="baseline_trajectory",
                name="compute_baseline_trajectory_node",
            ),
        ]
    )
