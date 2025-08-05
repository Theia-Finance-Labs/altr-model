"""
This is a boilerplate pipeline 'layer2'
generated using Kedro 0.19.12
"""

import pandas as pd
import numpy as np
import ibis.expr.types


def build_price_trajectory(
    traj_scenario_ar6: pd.DataFrame, shock_year: int
) -> pd.DataFrame:

    # Part 1: years > shock_year -1 (i.e., years >= shock_year)
    after_shock_target = traj_scenario_ar6.loc[
        (traj_scenario_ar6["scenario_year"] >= shock_year)
        & (traj_scenario_ar6["scenario_type"] == "target"),
        ["sector", "technology", "scenario_year", "scenario_price"],
    ].rename(
        columns={"scenario_year": "year", "scenario_price": "scenario_price_target"}
    )

    after_shock_baseline = traj_scenario_ar6.loc[
        (traj_scenario_ar6["scenario_year"] >= shock_year)
        & (traj_scenario_ar6["scenario_type"] == "baseline"),
        ["sector", "technology", "scenario_year", "scenario_price"],
    ].rename(
        columns={"scenario_year": "year", "scenario_price": "scenario_price_baseline"}
    )
    after_shock = pd.merge(
        after_shock_target,
        after_shock_baseline,
        how="inner",
        on=["sector", "technology", "year"],
    )

    after_shock_sorted = after_shock.sort_values(["sector", "technology", "year"])

    # Group and summarize to get baseline and target prices
    summary = (
        after_shock_sorted.groupby(["sector", "technology"])
        .agg(
            baseline_price_at_shock=("scenario_price_baseline", "first"),
            target_price_end_shockperiod=("scenario_price_target", "last"),
            first_year=("year", "min"),
            last_year=("year", "max"),
        )
        .reset_index()
    )

    # Function to interpolate prices
    def interpolate_prices(row):
        first_year = row["first_year"] + 1
        last_year = row["last_year"]
        if first_year > last_year:
            return pd.DataFrame(
                columns=[
                    "sector",
                    "technology",
                    "year",
                    "scenario_price_late_sudden",
                ]
            )
        years = list(range(int(first_year), int(last_year) + 1))
        baseline = row["baseline_price_at_shock"]
        target = row["target_price_end_shockperiod"]
        if first_year == last_year:
            prices = [target]
        else:
            prices = np.linspace(
                baseline, target, num=(int(last_year) - int(first_year) + 1)
            )
        df = pd.DataFrame(
            {
                "sector": row["sector"],
                "technology": row["technology"],
                "year": years,
                "scenario_price_late_sudden": prices,
            }
        )
        return df

    # Apply interpolation
    interpolated_prices = summary.apply(interpolate_prices, axis=1).tolist()
    interpolated_prices = (
        pd.concat(interpolated_prices, ignore_index=True)
        if interpolated_prices
        else pd.DataFrame()
    )
    # Part 2: years <= shock_year
    before_shock = traj_scenario_ar6.loc[
        (traj_scenario_ar6["scenario_year"] <= shock_year)
        & (traj_scenario_ar6["scenario_type"] == "baseline"),
        ["sector", "technology", "scenario_year", "scenario_price"],
    ].rename(
        columns={
            "scenario_year": "year",
            "scenario_price": "scenario_price_late_sudden",
        }
    )

    # Combine both parts
    final_result = pd.concat([before_shock, interpolated_prices], ignore_index=True)

    # Select relevant columns
    traj_price_late_sudden = final_result[
        ["sector", "technology", "year", "scenario_price_late_sudden"]
    ]

    # Add baseline price
    traj_price_baseline = traj_scenario_ar6.loc[
        traj_scenario_ar6["scenario_type"] == "baseline",
        ["sector", "technology", "scenario_year", "scenario_price"],
    ].rename(
        columns={"scenario_year": "year", "scenario_price": "scenario_price_baseline"}
    )

    traj_price_late_sudden = pd.merge(
        traj_price_late_sudden,
        traj_price_baseline,
        on=["sector", "technology", "year"],
        how="inner",
    )

    return traj_price_late_sudden


def calculate_asset_level_net_profits(
    assets_baseline: pd.DataFrame,
    assets_shock: pd.DataFrame,
    ar6_scenarios: pd.DataFrame,
    shock_year: int,
    market_passthrough: float = 0.5,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Calculate net profits at asset level using sector-specific equations:
    - Power: Netprofits = (Capacity*CapFactor)*((Price-FuelCost/Efficiency-OpMgmtCost)-(EmissionFactor*MarketPassthrough*CarbonTax))-(dCapacity/dyears*CapitalCost)
    - Oil&Gas, Coal: Netprofits = Production*((Price-OpMgmtCost)-(EmissionFactor*MarketPassthrough*CarbonTax))-(dCapacity/dyears*CapitalCost)
    - Automotive, Steel: Netprofits = Production*((Price-FuelCost/Efficiency-OpMgmtCost)-(EmissionFactor*MarketPassthrough*CarbonTax))-(dCapacity/dyears*CapitalCost)
    """
    
    def calculate_sector_net_profits(assets_df: pd.DataFrame, scenario_type: str) -> pd.DataFrame:
        # Merge with AR6 scenario data for prices and other parameters
        assets_with_ar6 = assets_df.merge(
            ar6_scenarios, 
            on=["sector", "technology", "year"], 
            how="inner"
        )
        
        # Initialize net profits column
        assets_with_ar6["net_profits"] = 0.0
        
        # Power Sector calculation
        power_mask = assets_with_ar6["sector"] == "Power"
        if power_mask.any():
            power_data = assets_with_ar6[power_mask].copy()
            
            # Production volume = Capacity * Capacity Factor
            power_data["production_volume"] = (
                power_data["capacity"] * power_data["scenario_capacity_factor"]
            )
            
            # Revenue = Production * Price
            power_data["revenue"] = (
                power_data["production_volume"] * power_data["scenario_price"]
            )
            
            # Operating costs = FuelCost/Efficiency + OpMgmtCost
            power_data["fuel_cost_per_unit"] = power_data.get("fuel_cost", 0) / power_data.get("efficiency_decimal", 1)
            power_data["operating_cost"] = (
                power_data["fuel_cost_per_unit"] + power_data.get("om_cost_usd_per_mw_per_yr", 0)
            )
            
            # Carbon tax cost (only applies after shock year)
            power_data["carbon_cost"] = 0.0
            post_shock_mask = power_data["year"] > shock_year
            if post_shock_mask.any():
                power_data.loc[post_shock_mask, "carbon_cost"] = (
                    power_data.loc[post_shock_mask, "production_volume"] *
                    power_data.loc[post_shock_mask].get("emission_factor", 0) *
                    (1 - market_passthrough) *
                    power_data.loc[post_shock_mask].get("carbon_price_usd_per_tco2", 0)
                )
            
            # Capital costs (dCapacity/dyears * CapitalCost)
            power_data["capital_cost"] = (
                power_data.get("capacity_additions_mw_per_yr", 0) * 
                power_data.get("capital_cost_usd_per_mw", 0)
            )
            
            # Net profits
            power_data["net_profits"] = (
                power_data["revenue"] - 
                power_data["operating_cost"] * power_data["production_volume"] -
                power_data["carbon_cost"] -
                power_data["capital_cost"]
            )
            
            assets_with_ar6.loc[power_mask, "net_profits"] = power_data["net_profits"]
        
        # Oil & Gas, Coal Sectors calculation
        oil_gas_coal_mask = assets_with_ar6["sector"].isin(["Oil&Gas", "Coal"])
        if oil_gas_coal_mask.any():
            ogc_data = assets_with_ar6[oil_gas_coal_mask].copy()
            
            # Production volume from asset production pathways
            ogc_data["production_volume"] = ogc_data["production"]  # Assuming this column exists
            
            # Revenue = Production * Price
            ogc_data["revenue"] = ogc_data["production_volume"] * ogc_data["scenario_price"]
            
            # Operating costs
            ogc_data["operating_cost"] = ogc_data.get("om_cost_usd_per_mw_per_yr", 0)
            
            # Carbon tax cost (only applies after shock year)
            ogc_data["carbon_cost"] = 0.0
            post_shock_mask = ogc_data["year"] > shock_year
            if post_shock_mask.any():
                ogc_data.loc[post_shock_mask, "carbon_cost"] = (
                    ogc_data.loc[post_shock_mask, "production_volume"] *
                    ogc_data.loc[post_shock_mask].get("emission_factor", 0) *
                    (1 - market_passthrough) *
                    ogc_data.loc[post_shock_mask].get("carbon_price_usd_per_tco2", 0)
                )
            
            # Capital costs
            ogc_data["capital_cost"] = (
                ogc_data.get("capacity_additions_mw_per_yr", 0) * 
                ogc_data.get("capital_cost_usd_per_mw", 0)
            )
            
            # Net profits
            ogc_data["net_profits"] = (
                ogc_data["revenue"] - 
                ogc_data["operating_cost"] * ogc_data["production_volume"] -
                ogc_data["carbon_cost"] -
                ogc_data["capital_cost"]
            )
            
            assets_with_ar6.loc[oil_gas_coal_mask, "net_profits"] = ogc_data["net_profits"]
        
        # Automotive, Steel Sectors calculation
        auto_steel_mask = assets_with_ar6["sector"].isin(["Automotive", "Steel"])
        if auto_steel_mask.any():
            as_data = assets_with_ar6[auto_steel_mask].copy()
            
            # Production volume from asset production pathways
            as_data["production_volume"] = as_data["production"]  # Assuming this column exists
            
            # Revenue = Production * Price
            as_data["revenue"] = as_data["production_volume"] * as_data["scenario_price"]
            
            # Operating costs = FuelCost/Efficiency + OpMgmtCost
            as_data["fuel_cost_per_unit"] = as_data.get("fuel_cost", 0) / as_data.get("efficiency_decimal", 1)
            as_data["operating_cost"] = (
                as_data["fuel_cost_per_unit"] + as_data.get("om_cost_usd_per_mw_per_yr", 0)
            )
            
            # Carbon tax cost (only applies after shock year)
            as_data["carbon_cost"] = 0.0
            post_shock_mask = as_data["year"] > shock_year
            if post_shock_mask.any():
                as_data.loc[post_shock_mask, "carbon_cost"] = (
                    as_data.loc[post_shock_mask, "production_volume"] *
                    as_data.loc[post_shock_mask].get("emission_factor", 0) *
                    (1 - market_passthrough) *
                    as_data.loc[post_shock_mask].get("carbon_price_usd_per_tco2", 0)
                )
            
            # Capital costs
            as_data["capital_cost"] = (
                as_data.get("capacity_additions_mw_per_yr", 0) * 
                as_data.get("capital_cost_usd_per_mw", 0)
            )
            
            # Net profits
            as_data["net_profits"] = (
                as_data["revenue"] - 
                as_data["operating_cost"] * as_data["production_volume"] -
                as_data["carbon_cost"] -
                as_data["capital_cost"]
            )
            
            assets_with_ar6.loc[auto_steel_mask, "net_profits"] = as_data["net_profits"]
        
        return assets_with_ar6
    
    # Calculate net profits for baseline and shock scenarios
    assets_net_profits_baseline = calculate_sector_net_profits(assets_baseline, "baseline")
    assets_net_profits_shock = calculate_sector_net_profits(assets_shock, "shock")
    
    return assets_net_profits_baseline, assets_net_profits_shock


def aggregate_assets_to_company_technology(
    assets_net_profits: pd.DataFrame
) -> pd.DataFrame:
    """Aggregate asset-level net profits to company-technology level."""
    company_tech_profits = assets_net_profits.groupby([
        "company_id", "sector", "technology", "year"
    ]).agg({
        "net_profits": "sum",
        "production_volume": "sum",
        "capacity": "sum"
    }).reset_index()
    
    return company_tech_profits


def aggregate_company_technology_to_company(
    company_tech_profits: pd.DataFrame
) -> pd.DataFrame:
    """Aggregate company-technology level net profits to whole company level."""
    company_profits = company_tech_profits.groupby([
        "company_id", "year"
    ]).agg({
        "net_profits": "sum",
        "production_volume": "sum",
        "capacity": "sum"
    }).reset_index()
    
    return company_profits


def calculate_discounted_net_profits(
    traj_companies_revenue_baseline: pd.DataFrame,
    traj_companies_revenue_shock: pd.DataFrame,
    discount_rate: float,
    growth_rate: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Processes the baseline and shock revenue data to compute annual
    discounted net profits and append terminal value rows.

    Parameters:
      companies_revenue_baseline : DataFrame with columns including
                                   'company_id', 'sector', 'technology', 'year',
                                   'net_profits_baseline', etc.
      companies_revenue_shock    : DataFrame with columns including
                                   'company_id', 'sector', 'technology', 'year',
                                   'net_profits_shock', etc.
      discount_rate              : Annual discount rate.
      growth_rate                : Long-run growth rate for terminal value.

    Returns:
      A tuple (traj_companies_net_profits_baseline, traj_companies_net_profits_shock)
      where each is a DataFrame with annual discounted profits and a terminal row.
    """
    # Process baseline
    baseline_processed = discount_dividend_model(
        traj_companies_revenue_baseline,
        discount_rate,
        profit_col="net_profits_baseline",
        discounted_col="discounted_net_profit_baseline",
    )

    traj_companies_net_profits_baseline = calculate_terminal_value(
        baseline_processed,
        growth_rate,
        discount_rate,
        profit_col="net_profits_baseline",
        discounted_col="discounted_net_profit_baseline",
    )

    # Process shock (target)
    shock_processed = discount_dividend_model(
        traj_companies_revenue_shock,
        discount_rate,
        profit_col="net_profits_shock",
        discounted_col="discounted_net_profit_shock",
    )

    traj_companies_net_profits_shock = calculate_terminal_value(
        shock_processed,
        growth_rate,
        discount_rate,
        profit_col="net_profits_shock",
        discounted_col="discounted_net_profit_shock",
    )

    return traj_companies_net_profits_baseline, traj_companies_net_profits_shock


def discount_dividend_model(
    data: pd.DataFrame, discount_rate: float, profit_col: str, discounted_col: str
) -> pd.DataFrame:
    """
    For each company group, sort by year, assign a time index t_calc,
    and compute the discounted profit.

    Parameters:
      data         : DataFrame with company-level annual net profits.
      discount_rate: Annual discount rate (e.g. 0.05 for 5%).
      profit_col   : Name of the profit column (e.g. 'net_profits_baseline'
                     or 'net_profits_shock').
      discounted_col: Name of the new column to store discounted profits.

    Returns:
      DataFrame with a new discounted profits column.
    """
    data = data.sort_values(by=["company_id", "sector", "technology", "year"]).copy()

    def apply_discount(group):
        group = group.copy()
        group["t_calc"] = range(len(group))
        group[discounted_col] = group[profit_col] / (
            (1 + discount_rate) ** group["t_calc"]
        )
        return group

    data = data.groupby(["company_id", "sector", "technology"], group_keys=False).apply(
        apply_discount
    )
    data = data.drop(columns=["t_calc"])
    return data


def calculate_terminal_value(
    data: pd.DataFrame,
    growth_rate: float,
    discount_rate: float,
    profit_col: str,
    discounted_col: str,
) -> pd.DataFrame:
    """
    Append a terminal value row for each company group. The terminal row
    represents the next period (end_year + 1) where profit is grown by
    (1 + growth_rate) and discounted using a perpetuity formula.

    Parameters:
      data         : DataFrame that has been processed with discount_dividend_model.
      end_year     : The last year in the data.
      growth_rate  : The long-run growth rate for terminal value calculation.
      discount_rate: The discount rate.
      profit_col   : Name of the profit column (baseline or shock).
      discounted_col: Name of the discounted profit column.

    Returns:
      DataFrame with an appended terminal value row.
    """
    end_year = data["year"].max()
    # Filter for rows corresponding to the end year
    terminal_data = data[data["year"] == end_year].copy()
    # Prepare terminal rows for year end_year+1
    terminal_data["year"] = terminal_data["year"] + 1
    terminal_data[profit_col] = terminal_data[profit_col] * (1 + growth_rate)
    # Apply the perpetuity formula for terminal discounted value:
    # discounted_terminal = profit / (discount_rate - growth_rate)
    terminal_data[discounted_col] = terminal_data[profit_col] / (
        discount_rate - growth_rate
    )

    # Append the terminal rows back to the original data and sort
    data_with_terminal = pd.concat([data, terminal_data], ignore_index=True)
    data_with_terminal = data_with_terminal.sort_values(
        by=["company_id", "sector", "technology", "year"]
    ).reset_index(drop=True)
    return data_with_terminal
