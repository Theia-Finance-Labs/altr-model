"""
This is a boilerplate pipeline 'outputs_processing'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline, pipeline  # noqa
from .nodes import (
    compute_npvs,
    allocate_production_to_companies,
)


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            node(
                allocate_production_to_companies,
                inputs=[
                    "companies_ownership_tree",
                    "traj_assets_baseline_prod",
                    "traj_assets_shocked_phased_out",
                ],
                outputs=["traj_companies_baseline", "traj_companies_shock"],
            ),
            node(
                func=compute_npvs,
                inputs=[
                    "traj_companies_net_profits_baseline",
                    "traj_companies_net_profits_shock",
                ],
                outputs="companies_npvs",
            ),
        ]
    )
