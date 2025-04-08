"""
This is a boilerplate pipeline 'trisk'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline, pipeline

from .nodes.force_phase_out import (
    force_phase_out_target_baseline,
    force_phase_out_late_sudden,
)
from .nodes.assets_trajectories import (
    filter_assets,
    compute_raw_trajectory,
    truncate_traj_asset,
)
from .nodes.trisk_input_trajectories import (
    compute_baseline_trajectory,
    compute_target_trajectory,
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
    build_price_trajectory,
    filter_companies,
    allocate_production_to_companies,
    calculate_net_profits,
    calculate_discounted_net_profits,
    compute_npvs,
)


from .nodes.reporting_outputs import (
    plot_assets_baseline_target,
    plot_assets_shocks,
    merge_companies_net_profits,
    plot_companies_net_profits,
    plot_companies_npvs_kde,
)

from .nodes.make_R_inputs import (
    make_financial_data,
    make_assets_data,
    make_scenarios_data,
    compute_plant_age_years,
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
                func=filter_companies,
                inputs=["plant_ownerships", "filtered_plant_detail"],
                outputs="companies_ownership_tree",
            ),
            node(
                func=compute_raw_trajectory,
                inputs=["filtered_plant_detail", "filtered_events"],
                outputs="traj_assets_raw",
            ),
            node(
                func=truncate_traj_asset,
                inputs=["traj_assets_raw", "traj_scenario", "params:forecast_horizon"],
                outputs="traj_assets_raw_truncated",
            ),
            node(
                func=compute_baseline_trajectory,
                inputs=["traj_assets_raw_truncated", "traj_scenario_baseline"],
                outputs="traj_assets_baseline",
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
                func=compute_proximity_to_target,
                inputs=["traj_assets_raw_truncated", "traj_assets_target_clean"],
                outputs="proximity_to_target",
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
                func=split_assets_per_shock_type,
                inputs=[
                    "traj_assets_raw_truncated",
                    "traj_assets_target_prod",
                ],
                outputs=[
                    "assets_to_compensate",
                    "assets_to_not_compensate",
                    "flagged_overshoot",
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
                func=apply_simple_shock,
                inputs=[
                    "assets_to_not_compensate",
                    "truncated_traj_assets_prod",
                    "traj_assets_target_prod",
                ],
                outputs="assets_simply_shocked",
            ),
            node(
                gather_shock_trajectories,
                inputs=[
                    "assets_compensated_shocked",
                    "assets_simply_shocked",
                    "flagged_overshoot",
                ],
                outputs="traj_assets_shocked",
            ),
            node(
                func=force_phase_out_late_sudden,
                inputs=["traj_assets_shocked"],
                outputs="traj_assets_shocked_phased_out",
            ),
            node(
                func=build_price_trajectory,
                inputs=[
                    "traj_scenario",
                    "params:shock_year",
                ],
                outputs="traj_technology_prices",
            ),
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
            node(
                func=compute_npvs,
                inputs=[
                    "traj_companies_net_profits_baseline",
                    "traj_companies_net_profits_shock",
                ],
                outputs="companies_npvs",
            ),
            node(
                func=plot_assets_baseline_target,
                inputs=["traj_assets_baseline_clean", "traj_assets_target_clean"],
                outputs=None,
                tags=["reporting"],
            ),
            node(
                func=plot_assets_shocks,
                inputs=["assets_compensated_shocked", "assets_simply_shocked"],
                outputs=None,
                tags=["reporting"],
            ),
            node(
                func=merge_companies_net_profits,
                inputs=[
                    "traj_companies_net_profits_baseline",
                    "traj_companies_net_profits_shock",
                ],
                outputs="merged_companies_net_profits_excel",
                tags=["reporting"],
            ),
            node(
                func=plot_companies_net_profits,
                inputs="merged_companies_net_profits_excel",
                outputs=None,
                tags=["reporting"],
            ),
            node(
                func=plot_companies_npvs_kde,
                inputs="companies_npvs",
                outputs="npvs_kde_plot",
                tags=["reporting"],
            ),
            node(
                func=compute_plant_age_years,
                inputs=["traj_assets_raw_truncated", "plant_events"],
                outputs="assets_age",
            ),
            node(
                func=make_assets_data,
                inputs=[
                    "traj_assets_raw_truncated",
                    "filtered_plant_detail",
                    "companies_ownership_tree",
                    "assets_age",
                ],
                outputs="assets_data",
                tags=["reporting"],
            ),
            node(
                func=make_scenarios_data,
                inputs="scenarios",
                outputs="scenarios_data",
                tags=["reporting"],
            ),
            node(
                func=make_financial_data,
                inputs=[
                    "traj_assets_raw_truncated",
                    "companies_ownership_tree",
                    "financial_averages",
                ],
                outputs="financial_data",
                tags=["reporting"],
            ),
        ]
    )
