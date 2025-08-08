"""
This is a boilerplate pipeline 'inputs_processing'
generated using Kedro 0.19.12
"""

from kedro.pipeline import node, Pipeline, pipeline  # noqa
from .nodes import (
    check_input_parameters,
    filter_scenarios,
    filter_assets,
    filter_companies,
    assign_scenario_geographies_to_assets,
    allocate_assets_to_companies,
    determine_increasing_or_decreasing_techs,
    determine_lifetime_per_technology,
    determine_assets_retirement_dates,
)


def create_pipeline(**kwargs) -> Pipeline:
    return pipeline(
        [
            node(
                func=check_input_parameters,
                inputs=dict(
                    shock_year="params:shock_year",
                    alignment_year="params:alignment_year",
                ),
                outputs=None,
            ),
            node(
                func=filter_scenarios,
                inputs=dict(
                    scenarios_pathways="downloaded_scenarios",
                    target_scenario="params:target_scenario",
                    baseline_scenario="params:baseline_scenario",
                ),
                outputs="scenarios_pathways",
            ),
            node(
                func=filter_companies,
                inputs=dict(
                    companies_ownership_tree="downloaded_companies",
                    company_ids="params:company_ids",
                ),
                outputs="companies_ownership_tree",
            ),
            node(
                func=filter_assets,
                inputs=dict(
                    assets_forecasts="downloaded_assets",
                    companies_ownership_tree="companies_ownership_tree",
                    scenarios_pathways="scenarios_pathways",
                    max_forecast_horizon="params:max_forecast_horizon",
                ),
                outputs="assets_forecasts",
            ),
            node(
                assign_scenario_geographies_to_assets,
                inputs=dict(
                    assets_forecasts="assets_forecasts",
                    scenarios_pathways="scenarios_pathways",
                ),
                outputs="assets_forecasts_with_scenario_geographies",
            ),
            node(
                func=allocate_assets_to_companies,
                inputs=dict(
                    assets_forecasts="assets_forecasts_with_scenario_geographies",
                    companies_ownership_tree="companies_ownership_tree",
                ),
                outputs="allocated_assets_to_companies",
            ),
            node(
                determine_increasing_or_decreasing_techs,
                inputs=dict(scenarios_pathways="scenarios_pathways"),
                outputs="increasing_or_decreasing_techs",
            ),
            node(
                determine_lifetime_per_technology,
                inputs=dict(scenarios_pathways="scenarios_pathways"),
                outputs="lifetime_per_technology",
            ),
            node(
                determine_assets_retirement_dates,
                inputs=dict(
                    assets_forecasts="allocated_assets_to_companies",
                    lifetime_per_technology="lifetime_per_technology",
                    scenarios_pathways="scenarios_pathways",
                ),
                outputs="assets_retirement_dates",
            ),
        ],
        tags=["altrisk", "trisk"],
    )
