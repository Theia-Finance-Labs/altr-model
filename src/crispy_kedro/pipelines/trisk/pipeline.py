"""
This is a boilerplate pipeline 'trisk'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline, pipeline
from .nodes.assets_trajectories import (
    filter_assets,
    compute_raw_trajectory,
    truncate_traj_asset,
)
from .nodes.trisk_input_trajectories import (
    compute_baseline_trajectory,
    compute_target_trajectory,
    force_phase_out,
    apply_capacity_factors,
)
from .nodes.scenario_trajectories import (
    filter_scenarios,
    calculate_fair_share_perc,
)

from .nodes.shock_trajectory import (
    compute_proximity_to_target,
    split_assets_per_shock_type,
    apply_compensation_shock,
    apply_simple_shock,
    gather_shock_trajectories,
)
from .nodes.revenue_trajectories import (
    apply_scenario_prices,
    calculate_net_profits,
    calculate_annual_profits,
)
from .nodes.risk_metrics import (
    calculate_asset_value_at_risk,
    calculate_pd_change_overall,
)


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
                outputs=["traj_scenario_baseline", "traj_scenario_target"],
            ),
            node(
                func=filter_assets,
                inputs=["plant_detail", "plant_events", "params:asset_ids"],
                outputs=["filtered_plant_detail", "filtered_events"],
            ),
            node(
                func=compute_raw_trajectory,
                inputs=["filtered_plant_detail", "filtered_events"],
                outputs="traj_assets_raw",
            ),
            node(
                func=truncate_traj_asset,
                inputs=["traj_assets_raw", "traj_scenario"],
                outputs="truncated_traj_assets_raw",
            ),
            node(
                func=compute_baseline_trajectory,
                inputs=["truncated_traj_assets_raw", "traj_scenario_baseline"],
                outputs="traj_assets_baseline",
            ),
            node(
                func=compute_target_trajectory,
                inputs=["truncated_traj_assets_raw", "traj_scenario_target"],
                outputs="traj_assets_target",
            ),
            node(
                func=force_phase_out,
                inputs=["traj_assets_baseline", "traj_assets_target"],
                outputs=["traj_assets_baseline_clean", "traj_assets_target_clean"],
            ),
            node(
                func=apply_capacity_factors,
                inputs=[
                    "traj_scenario",
                    "traj_assets_baseline_clean",
                    "traj_assets_target_clean",
                ],
                outputs=["traj_assets_baseline_prod", "traj_assets_target_prod"],
            ),
            node(
                func=compute_proximity_to_target,
                inputs=["truncated_traj_assets_raw", "traj_assets_target_clean"],
                outputs="proximity_to_target",
            ),
            node(
                func=split_assets_per_shock_type,
                inputs=[
                    "truncated_traj_assets_raw",
                    "traj_assets_target_prod",
                ],
                outputs=["assets_to_compensate", "assets_to_simple_shock"],
            ),
            node(
                func=apply_compensation_shock,
                inputs=[
                    "assets_to_compensate",
                    "traj_assets_baseline_prod",
                    "traj_assets_target_prod",
                ],
                outputs=["assets_compensated_shocked"],
            ),
            node(
                func=apply_simple_shock,
                inputs=[
                    "assets_to_simple_shock",
                    "traj_assets_baseline_prod",
                    "traj_assets_target_prod",
                ],
                outputs=["assets_simply_shocked"],
            ),
            node(
                gather_shock_trajectories,
                inputs=["assets_compensated_shocked", "assets_simply_shocked"],
                outputs=["traj_assets_shocked"],
            ),
            node(
                func=apply_scenario_prices,
                inputs=[
                    "traj_scenario",
                    "traj_assets_baseline_prod",
                    "traj_assets_shocked",
                ],
                outputs=["traj_assets_revenue"],
            ),
            node(
                func=calculate_net_profits,
                inputs=["traj_assets_revenue"],
                outputs=["traj_assets_net_profits"],
            ),
            node(
                func=calculate_annual_profits,
                inputs=["traj_assets_net_profits"],
                outputs=["traj_assets_annual_profits"],
            ),
            node(
                func=calculate_asset_value_at_risk,
                inputs=["traj_assets_annual_profits"],
                outputs=["asset_value_at_risk"],
            ),
            node(
                func=calculate_pd_change_overall,
                inputs=["asset_value_at_risk"],
                outputs=["pd_change_overall"],
            ),
        ]
    )
