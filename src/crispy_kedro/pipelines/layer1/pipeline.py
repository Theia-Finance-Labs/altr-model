"""
This is a boilerplate pipeline 'layer1'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline, pipeline  # noqa
from .nodes import (
    calculate_fair_share_perc,
    compute_target_trajectory,
    force_phase_out_traj_assets,
    force_phase_out_late_sudden,
    apply_capacity_factors,
    apply_compensation_shock,
    allocate_production_to_companies,
)


def create_pipeline(**kwargs) -> Pipeline:
    return Pipeline(
        [
            node(
                func=calculate_fair_share_perc,
                inputs=["scenarios_pathways"],
                outputs="traj_scenario_fair_share",
            ),
            node(
                func=compute_target_trajectory,
                inputs=["allocated_assets_to_companies", "traj_scenario_fair_share"],
                outputs="traj_assets_target",
            ),
            node(
                func=force_phase_out_traj_assets,
                inputs=["traj_assets_target"],
                outputs="traj_assets_target_clean",
            ),
            node(
                func=apply_capacity_factors,
                inputs=[
                    "traj_scenario_fair_share",
                    "traj_assets_target_clean",
                    "allocated_assets_to_companies",
                ],
                outputs="traj_assets_prod",
            ),
            node(
                func=apply_compensation_shock,
                inputs=[
                    "traj_assets_prod",
                    "params:shock_year",
                ],
                outputs="traj_assets_shocked",
            ),
            node(
                func=force_phase_out_late_sudden,
                inputs=["traj_assets_shocked"],
                outputs="traj_assets_shocked_phased_out",
            ),
            node(
                func=allocate_production_to_companies,
                inputs=[
                    "companies_ownership_tree",
                    "traj_assets_prod",
                    "traj_assets_shocked_phased_out",
                ],
                outputs=["traj_companies_baseline", "traj_companies_shock"],
            ),
        ],
        tags="trisk",
    )
