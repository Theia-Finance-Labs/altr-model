"""
Financial model pipeline for calculating asset-level net profits
and aggregating to company level using AR6 scenarios data.
"""

import pandas as pd
import numpy as np
from typing import Tuple


def calculate_asset_level_net_profits(
    asset_level_staggered_shock: pd.DataFrame,
    downloaded_scenarios_ar6: pd.DataFrame,
    target_scenario: str,
    baseline_scenario: str,
    shock_year: int,
    market_passthrough: float = 0.5,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Calculate net profits at asset level using sector-specific equations:
    - Power: Netprofits = (Capacity*CapFactor)*((Price-FuelCost/Efficiency-OpMgmtCost)-(EmissionFactor*MarketPassthrough*CarbonTax))-(dCapacity/dyears*CapitalCost)
    - Oil&Gas, Coal: Netprofits = Production*((Price-OpMgmtCost)-(EmissionFactor*MarketPassthrough*CarbonTax))-(dCapacity/dyears*CapitalCost)
    - Automotive, Steel: Netprofits = Production*((Price-FuelCost/Efficiency-OpMgmtCost)-(EmissionFactor*MarketPassthrough*CarbonTax))-(dCapacity/dyears*CapitalCost)

    Note: Uses asset_level_staggered_shock with capacity_after_shock for actual asset-level calculations.
    """
    # Rename scenario to align with scenarios data in DB
    downloaded_scenarios_ar6["scenario"] = (
        "AR6_"
        + downloaded_scenarios_ar6["scenario_provider"]
        + "_"
        + downloaded_scenarios_ar6["scenario"]
    )

    # Prepare AR6 scenario data for baseline and target scenarios
    ar6_baseline = downloaded_scenarios_ar6[
        downloaded_scenarios_ar6["scenario"] == baseline_scenario
    ].copy()

    ar6_target = downloaded_scenarios_ar6[
        downloaded_scenarios_ar6["scenario"] == target_scenario
    ].copy()

    # Rename scenario_year to year to match asset data
    ar6_baseline = ar6_baseline.rename(columns={"scenario_year": "year"})
    ar6_target = ar6_target.rename(columns={"scenario_year": "year"})

    def calculate_sector_net_profits(
        asset_data: pd.DataFrame,
        ar6_scenarios_filtered: pd.DataFrame,
        scenario_type: str,
    ) -> pd.DataFrame:
        """
        Calculate net profits for a specific scenario type using asset-level data with capacity_after_shock.
        """

        # Merge asset-level data with AR6 scenario data for prices and other parameters
        # Match on technology and year (sector comes from AR6 data)
        assets_with_ar6 = asset_data.merge(
            ar6_scenarios_filtered,
            on=["scenario_geography", "sector", "technology", "year"],
            how="inner",
        )

        # Initialize net profits column
        assets_with_ar6["net_profits"] = 0.0
        # Initialize production_volume column
        assets_with_ar6["production_volume"] = 0.0

        # Power Sector calculation - uses capacity_after_shock * capacity_factor
        power_mask = assets_with_ar6["sector"] == "Power"
        if power_mask.any():
            power_data = assets_with_ar6[power_mask].copy()

            # For power sector: Production volume = capacity_after_shock * Capacity Factor (from AR6)
            # Use capacity_after_shock for both scenarios (it already reflects the shock)
            power_data["production_volume"] = power_data[
                "capacity_after_shock"
            ] * power_data.get("scenario_capacity_factor", 1)

            # Revenue = Production * Price
            power_data["revenue"] = (
                power_data["production_volume"] * power_data["scenario_price"]
            )

            # Operating costs = FuelCost/Efficiency + OpMgmtCost
            power_data["fuel_cost_per_unit"] = power_data.get(
                "fuel_cost", 0
            ) / power_data.get("efficiency_decimal", 1)
            power_data["operating_cost"] = power_data[
                "fuel_cost_per_unit"
            ] + power_data.get("om_cost_usd_per_mw_per_yr", 0)

            # Carbon tax cost (only applies after shock year)
            power_data["carbon_cost"] = 0.0
            post_shock_mask = power_data["year"] > shock_year
            if post_shock_mask.any():
                power_data.loc[post_shock_mask, "carbon_cost"] = (
                    power_data.loc[post_shock_mask, "production_volume"]
                    * power_data.loc[post_shock_mask].get("emission_factor", 0)
                    * (1 - market_passthrough)
                    * power_data.loc[post_shock_mask].get(
                        "carbon_price_usd_per_tco2", 0
                    )
                )

            # Capital costs (dCapacity/dyears * CapitalCost)
            power_data["capital_cost"] = power_data.get(
                "capacity_additions_mw_per_yr", 0
            ) * power_data.get("capital_cost_usd_per_mw", 0)

            # Net profits
            power_data["net_profits"] = (
                power_data["revenue"]
                - power_data["operating_cost"] * power_data["production_volume"]
                - power_data["carbon_cost"]
                - power_data["capital_cost"]
            )

            # Copy back all calculated columns, not just net_profits
            assets_with_ar6.loc[power_mask, "net_profits"] = power_data["net_profits"]
            assets_with_ar6.loc[power_mask, "production_volume"] = power_data[
                "production_volume"
            ]
            assets_with_ar6.loc[power_mask, "revenue"] = power_data["revenue"]
            assets_with_ar6.loc[power_mask, "carbon_cost"] = power_data["carbon_cost"]
            assets_with_ar6.loc[power_mask, "capital_cost"] = power_data["capital_cost"]

        # Oil & Gas, Coal Sectors calculation - uses capacity_after_shock directly as production
        oil_gas_coal_mask = assets_with_ar6["sector"].isin(["Oil&Gas", "Coal"])
        if oil_gas_coal_mask.any():
            ogc_data = assets_with_ar6[oil_gas_coal_mask].copy()

            # For Oil&Gas, Coal: Production volume = capacity_after_shock (no capacity factor)
            ogc_data["production_volume"] = ogc_data["capacity_after_shock"]

            # Revenue = Production * Price
            ogc_data["revenue"] = (
                ogc_data["production_volume"] * ogc_data["scenario_price"]
            )

            # Operating costs
            ogc_data["operating_cost"] = ogc_data.get("om_cost_usd_per_mw_per_yr", 0)

            # Carbon tax cost (only applies after shock year)
            ogc_data["carbon_cost"] = 0.0
            post_shock_mask = ogc_data["year"] > shock_year
            if post_shock_mask.any():
                ogc_data.loc[post_shock_mask, "carbon_cost"] = (
                    ogc_data.loc[post_shock_mask, "production_volume"]
                    * ogc_data.loc[post_shock_mask].get("emission_factor", 0)
                    * (1 - market_passthrough)
                    * ogc_data.loc[post_shock_mask].get("carbon_price_usd_per_tco2", 0)
                )

            # Capital costs
            ogc_data["capital_cost"] = ogc_data.get(
                "capacity_additions_mw_per_yr", 0
            ) * ogc_data.get("capital_cost_usd_per_mw", 0)

            # Net profits
            ogc_data["net_profits"] = (
                ogc_data["revenue"]
                - ogc_data["operating_cost"] * ogc_data["production_volume"]
                - ogc_data["carbon_cost"]
                - ogc_data["capital_cost"]
            )

            # Copy back all calculated columns, not just net_profits
            assets_with_ar6.loc[oil_gas_coal_mask, "net_profits"] = ogc_data[
                "net_profits"
            ]
            assets_with_ar6.loc[oil_gas_coal_mask, "production_volume"] = ogc_data[
                "production_volume"
            ]
            assets_with_ar6.loc[oil_gas_coal_mask, "revenue"] = ogc_data["revenue"]
            assets_with_ar6.loc[oil_gas_coal_mask, "carbon_cost"] = ogc_data[
                "carbon_cost"
            ]
            assets_with_ar6.loc[oil_gas_coal_mask, "capital_cost"] = ogc_data[
                "capital_cost"
            ]

        # Automotive, Steel Sectors calculation - uses capacity_after_shock directly as production
        auto_steel_mask = assets_with_ar6["sector"].isin(["Automotive", "Steel"])
        if auto_steel_mask.any():
            as_data = assets_with_ar6[auto_steel_mask].copy()

            # For Automotive, Steel: Production volume = capacity_after_shock (no capacity factor)
            as_data["production_volume"] = as_data["capacity_after_shock"]

            # Revenue = Production * Price
            as_data["revenue"] = (
                as_data["production_volume"] * as_data["scenario_price"]
            )

            # Operating costs = FuelCost/Efficiency + OpMgmtCost
            as_data["fuel_cost_per_unit"] = as_data.get("fuel_cost", 0) / as_data.get(
                "efficiency_decimal", 1
            )
            as_data["operating_cost"] = as_data["fuel_cost_per_unit"] + as_data.get(
                "om_cost_usd_per_mw_per_yr", 0
            )

            # Carbon tax cost (only applies after shock year)
            as_data["carbon_cost"] = 0.0
            post_shock_mask = as_data["year"] > shock_year
            if post_shock_mask.any():
                as_data.loc[post_shock_mask, "carbon_cost"] = (
                    as_data.loc[post_shock_mask, "production_volume"]
                    * as_data.loc[post_shock_mask].get("emission_factor", 0)
                    * (1 - market_passthrough)
                    * as_data.loc[post_shock_mask].get("carbon_price_usd_per_tco2", 0)
                )

            # Capital costs
            as_data["capital_cost"] = as_data.get(
                "capacity_additions_mw_per_yr", 0
            ) * as_data.get("capital_cost_usd_per_mw", 0)

            # Net profits
            as_data["net_profits"] = (
                as_data["revenue"]
                - as_data["operating_cost"] * as_data["production_volume"]
                - as_data["carbon_cost"]
                - as_data["capital_cost"]
            )

            # Copy back all calculated columns, not just net_profits
            assets_with_ar6.loc[auto_steel_mask, "net_profits"] = as_data["net_profits"]
            assets_with_ar6.loc[auto_steel_mask, "production_volume"] = as_data[
                "production_volume"
            ]
            assets_with_ar6.loc[auto_steel_mask, "revenue"] = as_data["revenue"]
            assets_with_ar6.loc[auto_steel_mask, "carbon_cost"] = as_data["carbon_cost"]
            assets_with_ar6.loc[auto_steel_mask, "capital_cost"] = as_data[
                "capital_cost"
            ]

        return assets_with_ar6

    # Calculate net profits for baseline scenario (using capacity_before_shock)
    asset_baseline = asset_level_staggered_shock.copy()
    asset_baseline["capacity_after_shock"] = asset_baseline["capacity_before_shock"]
    assets_net_profits_baseline = calculate_sector_net_profits(
        asset_baseline, ar6_baseline, "baseline"
    )

    # Calculate net profits for target/shock scenario (using capacity_after_shock)
    assets_net_profits_shock = calculate_sector_net_profits(
        asset_level_staggered_shock, ar6_target, "target"
    )

    return assets_net_profits_baseline, assets_net_profits_shock


def aggregate_assets_to_company_technology(
    assets_net_profits_baseline: pd.DataFrame, assets_net_profits_shock: pd.DataFrame
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Aggregate asset-level net profits to company-technology level by summing across all assets of the same technology for each company."""

    def aggregate_scenario(assets_df: pd.DataFrame) -> pd.DataFrame:
        return (
            assets_df.groupby(["company_id", "technology", "year"])
            .agg({"net_profits": "sum", "production_volume": "sum"})
            .reset_index()
        )

    company_tech_profits_baseline = aggregate_scenario(assets_net_profits_baseline)
    company_tech_profits_shock = aggregate_scenario(assets_net_profits_shock)

    return company_tech_profits_baseline, company_tech_profits_shock


def aggregate_company_technology_to_company(
    company_tech_profits_baseline: pd.DataFrame,
    company_tech_profits_shock: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Aggregate company-technology level net profits to company level by summing across all technologies."""

    def aggregate_scenario(company_tech_df: pd.DataFrame) -> pd.DataFrame:
        return (
            company_tech_df.groupby(["company_id", "year"])
            .agg({"net_profits": "sum", "production_volume": "sum"})
            .reset_index()
        )

    company_profits_baseline = aggregate_scenario(company_tech_profits_baseline)
    company_profits_shock = aggregate_scenario(company_tech_profits_shock)

    return company_profits_baseline, company_profits_shock


def calculate_discounted_net_profits(
    company_profits_baseline: pd.DataFrame,
    company_profits_shock: pd.DataFrame,
    discount_rate: float,
    growth_rate: float,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Calculate discounted net profits and terminal values for baseline and shock scenarios.
    """

    def discount_dividend_model(
        data: pd.DataFrame, profit_col: str, discounted_col: str
    ) -> pd.DataFrame:
        """Apply discount model to net profits."""
        data = data.sort_values(by=["company_id", "year"]).copy()

        def apply_discount(group):
            group = group.copy()
            group["t_calc"] = range(len(group))
            group[discounted_col] = group[profit_col] / (
                (1 + discount_rate) ** group["t_calc"]
            )
            return group

        data = data.groupby(["company_id"], group_keys=False).apply(apply_discount)
        data = data.drop(columns=["t_calc"])
        return data

    def calculate_terminal_value(
        data: pd.DataFrame, profit_col: str, discounted_col: str
    ) -> pd.DataFrame:
        """Append terminal value rows."""
        end_year = data["year"].max()
        terminal_data = data[data["year"] == end_year].copy()
        terminal_data["year"] = terminal_data["year"] + 1
        terminal_data[profit_col] = terminal_data[profit_col] * (1 + growth_rate)
        terminal_data[discounted_col] = terminal_data[profit_col] / (
            discount_rate - growth_rate
        )

        data_with_terminal = pd.concat([data, terminal_data], ignore_index=True)
        data_with_terminal = data_with_terminal.sort_values(
            by=["company_id", "year"]
        ).reset_index(drop=True)
        return data_with_terminal

    # Process baseline
    baseline_processed = discount_dividend_model(
        company_profits_baseline,
        profit_col="net_profits",
        discounted_col="discounted_net_profit_baseline",
    )

    company_net_profits_baseline = calculate_terminal_value(
        baseline_processed,
        profit_col="net_profits",
        discounted_col="discounted_net_profit_baseline",
    )

    # Process shock
    shock_processed = discount_dividend_model(
        company_profits_shock,
        profit_col="net_profits",
        discounted_col="discounted_net_profit_shock",
    )

    company_net_profits_shock = calculate_terminal_value(
        shock_processed,
        profit_col="net_profits",
        discounted_col="discounted_net_profit_shock",
    )

    return company_net_profits_baseline, company_net_profits_shock
