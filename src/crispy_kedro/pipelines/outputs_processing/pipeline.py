"""
This is a boilerplate pipeline 'outputs_processing'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline, pipeline  # noqa
from .nodes import (
    compute_npvs,
)


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            node(
                func=compute_npvs,
                inputs=[
                    "traj_companies_net_profits_baseline",
                    "traj_companies_net_profits_shock",
                ],
                outputs="companies_npvs",
            ),
        ],
        # inputs=[
        #     "traj_companies_net_profits_baseline",
        #     "traj_companies_net_profits_shock",
        # ],
        # outputs=["companies_npvs"],
        # namespace="outputs_processing",
    )
