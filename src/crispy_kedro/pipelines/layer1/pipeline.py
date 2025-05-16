"""
This is a boilerplate pipeline 'layer1'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline, pipeline  # noqa
from .nodes import (
    calculate_fair_share_perc,
    compute_target_trajectory,
    force_phase_out_target_baseline,
    force_phase_out_late_sudden,
    apply_capacity_factors,
    apply_compensation_shock,
)


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            node(
                func=calculate_fair_share_perc,
                inputs=["traj_scenario"],
                outputs=["traj_scenario_baseline", "traj_scenario_target"],
            ),
            node(
                func=compute_target_trajectory,
                inputs=["traj_assets_raw_truncated", "traj_scenario_target"],
                outputs="traj_assets_target",
            ),
            node(
                func=force_phase_out_target_baseline,
                inputs=["traj_assets_baseline", "traj_assets_target"],
                outputs=["traj_assets_baseline_clean", "traj_assets_target_clean"],
            ),
            node(
                func=apply_capacity_factors,
                inputs=[
                    "traj_scenario",
                    "traj_assets_baseline_clean",
                    "traj_assets_target_clean",
                    "traj_assets_raw_truncated",
                ],
                outputs=[
                    "traj_assets_baseline_prod",
                    "traj_assets_target_prod",
                    "truncated_traj_assets_prod",
                ],
            ),
            node(
                func=apply_compensation_shock,
                inputs=[
                    "assets_to_compensate",
                    "traj_assets_baseline_prod",
                    "traj_assets_target_prod",
                    "params:shock_year",
                ],
                outputs="assets_compensated_shocked",
            ),
            node(
                func=force_phase_out_late_sudden,
                inputs=["traj_assets_shocked"],
                outputs="traj_assets_shocked_phased_out",
            ),
        ]
    )
