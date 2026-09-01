"""Scenario, asset, and company input preparation nodes.

The public outputs deliberately separate the asset-grain inventory from the
company-grain projection inputs.  Scenario data is otherwise kept private to
this namespace so it does not fan out across the whole project graph.
"""

from __future__ import annotations

import pandas as pd

from altr_model.pipelines.calculate_company_trajectories._baseline_nodes import (
    aggregate_assets_to_company_level,
    calculate_tmsr,
)
from altr_model.pipelines.prepare_scenario_asset_and_company_inputs._asset_preparation import (
    apply_reduce_granularity_from_asset_to_company_level,
)
from altr_model.pipelines.prepare_scenario_asset_and_company_inputs._input_nodes import (
    allocate_assets_to_companies,
    apply_ccs_suffix,
    assign_scenario_geographies_to_assets,
    determine_increasing_or_decreasing_techs,
    determine_lifetime_per_technology,
    filter_assets,
    filter_companies,
    filter_scenarios,
)

FINANCIAL_SURFACE_COLUMNS = [
    "scenario",
    "power_price_excarbon_usd_per_mwh",
    "fuel_price_usd_per_mwh_fuel",
    "capacity_factor",
    "capex_usd_per_mw",
    "fom_usd_per_mw_yr",
    "carbon_price_usd_per_tco2",
    "efficiency_decimal",
    "lifetime_years",
    "scrap_usd_per_mw",
]


def prepare_scenario_pathways(
    downloaded_scenarios: pd.DataFrame,
    target_scenario: str,
    baseline_scenario: str,
) -> pd.DataFrame:
    """Filter scenarios once and add all downstream trajectory/model fields."""
    # Some scenarios.csv deliveries use "scenario_name" instead of "scenario"
    # for the scenario identifier column - support both.
    if (
        "scenario" not in downloaded_scenarios.columns
        and "scenario_name" in downloaded_scenarios.columns
    ):
        downloaded_scenarios = downloaded_scenarios.rename(
            columns={"scenario_name": "scenario"}
        )
    scenarios = filter_scenarios(
        downloaded_scenarios,
        target_scenario=target_scenario,
        baseline_scenario=baseline_scenario,
    )
    scenarios = calculate_tmsr(scenarios)

    trend = determine_increasing_or_decreasing_techs(scenarios)
    scenarios = scenarios.merge(
        trend,
        on=["technology", "scenario_geography"],
        how="left",
        validate="many_to_one",
    )

    scenarios["power_price_excarbon_usd_per_mwh"] = scenarios["scenario_price"]
    scenarios["fuel_price_usd_per_mwh_fuel"] = scenarios["fuel_price"]
    scenarios["capacity_factor"] = scenarios["scenario_capacity_factor"]
    scenarios["capex_usd_per_mw"] = scenarios["capital_cost_usd_per_mw"]
    scenarios["fom_usd_per_mw_yr"] = scenarios["om_cost_usd_per_mw_per_yr"]
    return scenarios


def prepare_asset_forecast_panel(
    downloaded_assets: pd.DataFrame,
    downloaded_companies: pd.DataFrame,
    scenario_pathways: pd.DataFrame,
    company_ids: list[str],
    ownership_type: str,
    ownership_aggregation: str,
    ccs_on: bool | None,
    max_forecast_horizon: int,
    reduce_granularity_from_asset_to_company_level: bool,
) -> pd.DataFrame:
    """Build the reusable asset-grain panel and carry scenario metadata on it."""
    companies = filter_companies(
        downloaded_companies, company_ids, ownership_type, ownership_aggregation
    )
    assets_ccs, companies_ccs = apply_ccs_suffix(
        downloaded_assets.copy(), companies.copy(), scenario_pathways, ccs_on
    )
    assets = filter_assets(
        assets_ccs, companies_ccs, scenario_pathways, max_forecast_horizon
    )
    assets = assign_scenario_geographies_to_assets(assets, scenario_pathways)
    assets = allocate_assets_to_companies(assets, companies_ccs, scenario_pathways)
    assets = apply_reduce_granularity_from_asset_to_company_level(
        assets, reduce_granularity_from_asset_to_company_level
    )

    lifetimes = determine_lifetime_per_technology(scenario_pathways).rename(
        columns={"lifetime_years": "asset_lifetime_years"}
    )
    assets = assets.merge(
        lifetimes,
        on=["sector", "technology"],
        how="left",
        validate="many_to_one",
    )
    trend = scenario_pathways[
        ["technology", "scenario_geography", "increasing"]
    ].drop_duplicates()
    assets = assets.merge(
        trend,
        on=["technology", "scenario_geography"],
        how="left",
        validate="many_to_one",
    )
    assets["scenario_start_year"] = int(scenario_pathways["year"].min())
    assets["scenario_end_year"] = int(scenario_pathways["year"].max())
    return assets


def prepare_company_projection_inputs(
    asset_forecast_panel: pd.DataFrame,
    scenario_pathways: pd.DataFrame,
) -> pd.DataFrame:
    """Create one company-year row with baseline/target scenario columns."""
    company_forecasts = aggregate_assets_to_company_level(asset_forecast_panel)
    first_activity = (
        company_forecasts.sort_values("year")
        .groupby(
            ["company_id", "scenario_geography", "sector", "technology"],
            as_index=False,
        )
        .first()[
            [
                "company_id",
                "scenario_geography",
                "sector",
                "technology",
                "year",
                "company_activity",
            ]
        ]
        .rename(
            columns={
                "company_activity": "initial_company_activity",
                "year": "first_year_of_activity",
            }
        )
    )
    scenarios = scenario_pathways.merge(
        first_activity,
        on=["sector", "technology", "scenario_geography"],
        how="inner",
    )
    scenarios["scenario_activity"] = scenarios["initial_company_activity"] * (
        1 + scenarios["tmsr"]
    )
    scenarios = scenarios.sort_values(
        ["scenario", "company_id", "scenario_geography", "sector", "technology", "year"]
    )
    scenarios["scenario_activity_change"] = scenarios.groupby(
        ["company_id", "scenario", "scenario_geography", "sector", "technology"]
    )["scenario_activity"].transform(lambda values: values - values.shift(1))
    scenarios["scenario_activity_change"] = scenarios[
        "scenario_activity_change"
    ].fillna(0)

    index_columns = [
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
        "year",
    ]
    value_columns = [
        "scenario_activity",
        "scenario_activity_change",
        *FINANCIAL_SURFACE_COLUMNS,
    ]
    pivoted = scenarios.pivot_table(
        index=index_columns,
        columns="scenario_type",
        values=value_columns,
        aggfunc="first",
    )
    pivoted.columns = [
        f"{value}_{scenario_type}" for value, scenario_type in pivoted.columns.values
    ]
    pivoted = pivoted.reset_index()

    trend = scenario_pathways[
        ["technology", "scenario_geography", "increasing"]
    ].drop_duplicates()
    projection_inputs = pivoted.merge(
        company_forecasts,
        on=index_columns,
        how="left",
        validate="one_to_one",
    ).merge(
        trend,
        on=["technology", "scenario_geography"],
        how="left",
        validate="many_to_one",
    )
    return projection_inputs.sort_values(index_columns).reset_index(drop=True)
