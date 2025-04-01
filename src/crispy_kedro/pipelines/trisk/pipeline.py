"""
This is a boilerplate pipeline 'trisk'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline, pipeline
from .nodes import (
    compute_base_trajectory,
    compute_truncated_trajectory,
    compute_baseline_trajectory,
)


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            node(
                func=compute_base_trajectory,
                inputs=["plant_detail", "plant_events"],
                outputs="base_trajectory",
                name="compute_base_trajectory_node",
            ),
            node(
                func=compute_truncated_trajectory,
                inputs=["base_trajectory", "scenarios"],
                outputs="truncated_trajectory",
                name="compute_truncated_trajectory_node",
            ),
            node(
                func=compute_baseline_trajectory,
                inputs=["truncated_trajectory", "scenarios"],
                outputs="baseline_trajectory",
                name="compute_baseline_trajectory_node",
            ),
        ]
    )
