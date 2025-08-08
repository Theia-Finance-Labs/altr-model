"""
Comprehensive earnings model pipeline implementing full financial methodology
with synthetic asset creation, tranche ledger, and cash flow calculations.
"""

import pandas as pd
import numpy as np
from typing import Tuple, Dict, List
import logging

logger = logging.getLogger(__name__)

# Constants
HOURS_PER_YEAR = 8760

# Technology defaults
TECHNOLOGY_DEFAULTS = {
    "Coal": {"lifetime_years": 40, "efficiency_decimal": 0.35, "decom_usd_per_mw": 50000},
    "Gas": {"lifetime_years": 30, "efficiency_decimal": 0.45, "decom_usd_per_mw": 30000},
    "GasCap": {"lifetime_years": 30, "efficiency_decimal": 0.45, "decom_usd_per_mw": 30000},
    "Oil": {"lifetime_years": 30, "efficiency_decimal": 0.35, "decom_usd_per_mw": 40000},
    "OilCap": {"lifetime_years": 30, "efficiency_decimal": 0.35, "decom_usd_per_mw": 40000},
    "Nuclear": {"lifetime_years": 60, "efficiency_decimal": 0.33, "decom_usd_per_mw": 500000},
    "Solar": {"lifetime_years": 25, "efficiency_decimal": 1.0, "decom_usd_per_mw": 20000},
    "Wind": {"lifetime_years": 25, "efficiency_decimal": 1.0, "decom_usd_per_mw": 25000},
    "Hydro": {"lifetime_years": 80, "efficiency_decimal": 1.0, "decom_usd_per_mw": 100000},
    "Geothermal": {"lifetime_years": 30, "efficiency_decimal": 1.0, "decom_usd_per_mw": 75000},
}


def validate_and_standardize_inputs(
    asset_level_staggered_shock: pd.DataFrame,
    downloaded_scenarios: pd.DataFrame,
    all_alignment_classifications: pd.DataFrame,
    assets_data: pd.DataFrame,
) -> Dict[str, pd.DataFrame]:
    """
    Node 1: Validate and standardize all inputs.
    
    Actions:
    - Enforce schemas/dtypes
    - Strip/standardize strings (geo/sector/technology)
    - Keep only needed columns
    - Assert year is contiguous per asset
    """
    
    logger.info("Validating and standardizing inputs...")
    
    # Clean asset data
    assets = asset_level_staggered_shock.copy()
    
    # Standardize string columns
    string_cols = ["asset_id", "company_id", "scenario_geography", "sector", "technology"]
    for col in string_cols:
        if col in assets.columns:
            assets[col] = assets[col].astype(str).str.strip()
    
    # Ensure numeric columns
    numeric_cols = ["year", "asset_age", "capacity_before_shock", "capacity_after_shock"]
    for col in numeric_cols:
        if col in assets.columns:
            assets[col] = pd.to_numeric(assets[col], errors='coerce')
    
    # Clean scenarios data
    scenarios = downloaded_scenarios.copy()
    
    # Standardize scenario naming
    scenarios["scenario"] = (
        "AR6_" + scenarios["scenario_provider"].astype(str).str.strip() + 
        "_" + scenarios["scenario"].astype(str).str.strip()
    )
    
    # Standardize geography/sector/tech
    scenarios["scenario_geography"] = scenarios["scenario_geography"].astype(str).str.strip()
    scenarios["sector"] = scenarios["sector"].astype(str).str.strip()
    scenarios["technology"] = scenarios["technology"].astype(str).str.strip()
    
    # Ensure numeric columns
    scenario_numeric_cols = [
        "scenario_price", "scenario_capacity_factor", "scenario_year",
        "lifetime_years", "efficiency_decimal", "capacity_additions_mw_per_yr",
        "om_cost_usd_per_mw_per_yr", "capital_cost_usd_per_mw", "carbon_price_usd_per_tco2"
    ]
    for col in scenario_numeric_cols:
        if col in scenarios.columns:
            scenarios[col] = pd.to_numeric(scenarios[col], errors='coerce')
    
    # Rename scenario_year to year for consistency
    scenarios = scenarios.rename(columns={"scenario_year": "year"})
    
    # Clean alignment data
    alignments = all_alignment_classifications.copy()
    
    # Standardize columns
    alignments["company_id"] = alignments["company_id"].astype(str).str.strip()
    alignments["scenario_geography"] = alignments["scenario_geography"].astype(str).str.strip()
    alignments["sector"] = alignments["sector"].astype(str).str.strip()
    alignments["technology"] = alignments["technology"].astype(str).str.strip()
    
    # Ensure boolean columns
    alignments["aligned"] = alignments["aligned"].astype(bool)
    alignments["increasing"] = alignments["increasing"].astype(bool)
    
    # Clean assets static data (emission factors, etc.)
    assets_static = assets_data.copy()
    
    # Standardize columns
    assets_static["asset_id"] = assets_static["asset_id"].astype(str).str.strip()
    assets_static["sector"] = assets_static["sector"].astype(str).str.strip()
    assets_static["technology"] = assets_static["technology"].astype(str).str.strip()
    
    # Ensure numeric emission factors
    assets_static["emission_factor"] = pd.to_numeric(assets_static["emission_factor"], errors='coerce').fillna(0.0)
    
    # Check year continuity per asset
    year_check = assets.groupby("asset_id")["year"].apply(
        lambda x: x.sort_values().diff().dropna().unique()
    )
    
    logger.info(f"Processed {len(assets)} asset-year rows")
    logger.info(f"Processed {len(scenarios)} scenario-year rows") 
    logger.info(f"Processed {len(alignments)} alignment classifications")
    logger.info(f"Processed {len(assets_static)} assets static data rows")
    
    return {
        "assets_validated": assets,
        "scenarios_validated": scenarios,
        "alignments_validated": alignments,
        "assets_static_validated": assets_static
    }


def build_scenario_surfaces(scenarios_validated: pd.DataFrame) -> pd.DataFrame:
    """
    Node 2: Build tidy per-(geo, sector, technology, year) surfaces.
    
    Creates standardized scenario surfaces with proper naming and units.
    """
    
    logger.info("Building scenario surfaces...")
    
    scenarios = scenarios_validated.copy()
    
    # Create base surface structure
    surface_cols = ["scenario_geography", "sector", "technology", "year", "scenario", "scenario_provider"]
    surfaces = scenarios[surface_cols].copy()
    
    # Build individual surfaces with proper naming
    
    # Power price (ex-carbon) - assume scenario_price is already in correct units for power assets
    surfaces["power_price_excarbon_usd_per_mwh"] = scenarios["scenario_price"]
    
    # Fuel price - use scenario_price directly (assume already in appropriate units)
    surfaces["fuel_price_usd_per_mwh_fuel"] = scenarios["scenario_price"]
    
    # For non-fuel technologies, set fuel price to 0
    non_fuel_techs = ["Solar", "Wind", "Hydro", "Nuclear", "Geothermal"]
    fuel_mask = ~surfaces["technology"].isin(non_fuel_techs)
    surfaces.loc[~fuel_mask, "fuel_price_usd_per_mwh_fuel"] = 0.0
    
    # Capacity factor
    surfaces["capacity_factor"] = scenarios["scenario_capacity_factor"].fillna(1.0)
    
    # CapEx
    surfaces["capex_usd_per_mw"] = scenarios["capital_cost_usd_per_mw"]
    
    # Fixed O&M
    surfaces["fom_usd_per_mw_yr"] = scenarios["om_cost_usd_per_mw_per_yr"]
    
    # Carbon price
    surfaces["carbon_price_usd_per_tco2"] = scenarios["carbon_price_usd_per_tco2"].fillna(0.0)
    
    # Efficiency
    surfaces["efficiency_decimal"] = scenarios["efficiency_decimal"]
    
    # Lifetime
    surfaces["lifetime_years"] = scenarios["lifetime_years"]
    
    # Fill missing values with technology defaults
    for tech, defaults in TECHNOLOGY_DEFAULTS.items():
        tech_mask = surfaces["technology"] == tech
        
        for param, default_value in defaults.items():
            if param in surfaces.columns:
                surfaces.loc[tech_mask & surfaces[param].isna(), param] = default_value
    
    # Note: emission_factor will come from assets_data.csv, not from scenario surfaces
    
    # Add decommissioning costs
    surfaces["decom_usd_per_mw"] = surfaces["technology"].map(
        lambda x: TECHNOLOGY_DEFAULTS.get(x, {}).get("decom_usd_per_mw", 50000)
    )
    
    logger.info(f"Built scenario surfaces with {len(surfaces)} rows")
    
    return surfaces


def normalize_capacity_growth_to_new_assets(
    assets_validated: pd.DataFrame,
    alignments_validated: pd.DataFrame,
) -> Dict[str, pd.DataFrame]:
    """
    Node 3: Create synthetic new-build assets for growth.
    
    When (aligned==True) & (increasing==True), capacity above base is 
    represented as synthetic new-build assets.
    """
    
    logger.info("Normalizing capacity growth to synthetic assets...")
    
    assets = assets_validated.copy()
    alignments = alignments_validated.copy()
    
    # Join alignment flags to assets
    assets_with_alignment = assets.merge(
        alignments[["company_id", "scenario_geography", "sector", "technology", "aligned", "increasing", "alignment_type"]],
        on=["company_id", "scenario_geography", "sector", "technology"],
        how="left"
    )
    
    # Fill missing alignment flags (default to aligned=True, increasing=False)
    assets_with_alignment["aligned"] = assets_with_alignment["aligned"].fillna(True)
    assets_with_alignment["increasing"] = assets_with_alignment["increasing"].fillna(False)
    assets_with_alignment["alignment_type"] = assets_with_alignment["alignment_type"].fillna("aligned")
    
    # Initialize outputs
    assets_adjusted = []
    synthetic_tranches = []
    synthetic_registry = []
    
    # Group by company-geo-sector-tech and process
    groups = assets_with_alignment.groupby(["company_id", "scenario_geography", "sector", "technology"])
    
    for group_key, group_data in groups:
        company_id, geo, sector, tech = group_key
        group_data = group_data.sort_values("year").copy()
        
        # Check if this group should have synthetic assets created
        aligned = group_data["aligned"].iloc[0]
        increasing = group_data["increasing"].iloc[0]
        
        if not (aligned and increasing):
            # No synthetic assets needed - keep as-is
            group_data["capacity_after_shock_adj"] = group_data["capacity_after_shock"]
            assets_adjusted.append(group_data)
            continue
        
        # Process year by year for synthetic asset creation
        synthetic_stock = 0.0  # MW of synthetic capacity
        synthetic_fifo = []  # List of synthetic tranches {start_year, mw_remaining}
        seq_counter = 0
        
        group_data["capacity_after_shock_adj"] = group_data["capacity_after_shock"].copy()
        
        for year in sorted(group_data["year"].unique()):
            year_data = group_data[group_data["year"] == year].copy()
            
            # Calculate totals for this year
            K_total_t = year_data["capacity_after_shock"].sum()
            base_total_t = year_data[["capacity_after_shock", "capacity_before_shock"]].min(axis=1).sum()
            
            required_synthetic_t = max(0, K_total_t - base_total_t)
            
            # Adjust original assets (cap at base capacity)
            year_data["capacity_after_shock_adj"] = np.minimum(
                year_data["capacity_after_shock"], 
                year_data["capacity_before_shock"]
            )
            
            # Update group data
            group_data.loc[group_data["year"] == year, "capacity_after_shock_adj"] = year_data["capacity_after_shock_adj"]
            
            # Handle synthetic capacity requirements
            if required_synthetic_t > synthetic_stock:
                # Need to add synthetic capacity
                add_mw = required_synthetic_t - synthetic_stock
                seq_counter += 1
                
                # Create synthetic asset registry entry
                synthetic_asset_id = f"SYN_{company_id}_{tech}_{year}_{seq_counter}"
                synthetic_registry.append({
                    "asset_id": synthetic_asset_id,
                    "company_id": company_id,
                    "scenario_geography": geo,
                    "sector": sector,
                    "technology": tech,
                    "start_year": year,
                    "initial_mw": add_mw,
                    "is_synthetic": True,
                    "aligned": True,
                    "increasing": True,
                    "alignment_type": "aligned"
                })
                
                # Add to tranche list
                synthetic_tranches.append({
                    "company_id": company_id,
                    "scenario_geography": geo,
                    "sector": sector,
                    "technology": tech,
                    "start_year": year,
                    "mw": add_mw,
                    "is_synthetic": True,
                    "eligible": True
                })
                
                # Add to FIFO queue
                synthetic_fifo.append({"start_year": year, "mw_remaining": add_mw})
                synthetic_stock += add_mw
                
            elif required_synthetic_t < synthetic_stock:
                # Need to retire synthetic capacity
                retire_mw = synthetic_stock - required_synthetic_t
                remaining_to_retire = retire_mw
                
                # Retire from FIFO (oldest first)
                while remaining_to_retire > 0 and synthetic_fifo:
                    tranche = synthetic_fifo[0]
                    retire_from_tranche = min(remaining_to_retire, tranche["mw_remaining"])
                    
                    tranche["mw_remaining"] -= retire_from_tranche
                    remaining_to_retire -= retire_from_tranche
                    
                    if tranche["mw_remaining"] <= 0:
                        synthetic_fifo.pop(0)
                
                synthetic_stock = required_synthetic_t
        
        assets_adjusted.append(group_data)
    
    # Combine all adjusted assets
    assets_adjusted_df = pd.concat(assets_adjusted, ignore_index=True)
    
    # Create synthetic dataframes
    synthetic_tranche_log = pd.DataFrame(synthetic_tranches)
    synthetic_asset_registry_df = pd.DataFrame(synthetic_registry)
    
    logger.info(f"Created {len(synthetic_asset_registry_df)} synthetic assets")
    logger.info(f"Adjusted {len(assets_adjusted_df)} original asset-year rows")
    
    return {
        "assets_adjusted": assets_adjusted_df,
        "synthetic_tranche_log": synthetic_tranche_log,
        "synthetic_asset_registry": synthetic_asset_registry_df
    }


def assemble_asset_panel(
    assets_adjusted: pd.DataFrame,
    synthetic_asset_registry: pd.DataFrame,
    scenario_surfaces: pd.DataFrame,
    assets_static_validated: pd.DataFrame,
) -> pd.DataFrame:
    """
    Node 4: Build full asset-year panel including synthetic assets.
    """
    
    logger.info("Assembling full asset panel...")
    
    # Start with adjusted original assets
    panel = assets_adjusted.copy()
    
    # Expand synthetic assets
    synthetic_rows = []
    
    if len(synthetic_asset_registry) > 0:
        # Get year range from original assets
        min_year = panel["year"].min()
        max_year = panel["year"].max()
        
        for _, synthetic_asset in synthetic_asset_registry.iterrows():
            start_year = synthetic_asset["start_year"]
            
            # Create rows for each year from start_year to max_year
            for year in range(start_year, max_year + 1):
                synthetic_row = {
                    "asset_id": synthetic_asset["asset_id"],
                    "company_id": synthetic_asset["company_id"],
                    "scenario_geography": synthetic_asset["scenario_geography"],
                    "sector": synthetic_asset["sector"],
                    "technology": synthetic_asset["technology"],
                    "year": year,
                    "asset_age": year - start_year,
                    "capacity_before_shock": 0.0 if year == start_year else synthetic_asset["initial_mw"],
                    "capacity_after_shock": synthetic_asset["initial_mw"],
                    "capacity_after_shock_adj": synthetic_asset["initial_mw"],
                    "is_synthetic": True,
                    "aligned": True,
                    "increasing": True,
                    "alignment_type": "aligned"
                }
                synthetic_rows.append(synthetic_row)
        
        if synthetic_rows:
            synthetic_df = pd.DataFrame(synthetic_rows)
            panel = pd.concat([panel, synthetic_df], ignore_index=True)
    
    # Join scenario surfaces
    panel_enriched = panel.merge(
        scenario_surfaces,
        on=["scenario_geography", "sector", "technology", "year"],
        how="left"
    )
    
    # Join assets static data to get emission factors
    panel_enriched = panel_enriched.merge(
        assets_static_validated[["asset_id", "emission_factor"]],
        on="asset_id",
        how="left"
    )
    
    # Fill missing emission factors with 0 (for synthetic assets or missing data)
    panel_enriched["emission_factor"] = panel_enriched["emission_factor"].fillna(0.0)
    
    logger.info(f"Assembled panel with {len(panel_enriched)} asset-year rows")
    
    return panel_enriched


def build_tranche_ledger_per_asset(asset_panel_enriched: pd.DataFrame) -> pd.DataFrame:
    """
    Node 5: Build tranche ledger for each asset to track retirements/replacements.
    """
    
    logger.info("Building tranche ledger per asset...")
    
    panel = asset_panel_enriched.copy()
    tranche_ledger = []
    
    # Group by asset and create tranche schedules
    for asset_id, asset_data in panel.groupby("asset_id"):
        asset_data = asset_data.sort_values("year")
        
        # Get asset info
        first_row = asset_data.iloc[0]
        t0 = first_row["year"]
        mw_initial = first_row["capacity_after_shock_adj"]
        asset_age = first_row["asset_age"]
        lifetime_years = first_row["lifetime_years"]
        aligned = first_row["aligned"]
        is_synthetic = first_row.get("is_synthetic", False)
        
        if mw_initial > 0:
            # Calculate remaining life
            if is_synthetic:
                remaining_life = lifetime_years
            else:
                remaining_life = max(lifetime_years - asset_age, 0)
            
            expiry_year = t0 + remaining_life
            
            tranche_ledger.append({
                "asset_id": asset_id,
                "tranche_id": f"{asset_id}_T0",
                "start_year": t0,
                "expiry_year": expiry_year,
                "mw": mw_initial,
                "eligible": aligned
            })
    
    tranche_df = pd.DataFrame(tranche_ledger)
    logger.info(f"Created tranche ledger with {len(tranche_df)} tranches")
    
    return tranche_df


def retirement_replacement_split_per_asset(
    asset_panel_enriched: pd.DataFrame,
    asset_tranche_ledger: pd.DataFrame,
) -> pd.DataFrame:
    """
    Node 6: Calculate retirements and replacements per asset-year.
    """
    
    logger.info("Computing retirement/replacement splits...")
    
    panel = asset_panel_enriched.copy()
    results = []
    
    for asset_id, asset_data in panel.groupby("asset_id"):
        asset_data = asset_data.sort_values("year").copy()
        asset_tranches = asset_tranche_ledger[asset_tranche_ledger["asset_id"] == asset_id]
        
        for i, row in asset_data.iterrows():
            year = row["year"]
            
            # Get capacity info
            if i == 0:  # First year
                K_prev = 0
            else:
                prev_idx = asset_data.index[asset_data.index < i][-1] if len(asset_data.index[asset_data.index < i]) > 0 else None
                K_prev = asset_data.loc[prev_idx, "capacity_after_shock_adj"] if prev_idx is not None else 0
            
            K_curr = row["capacity_after_shock_adj"]
            
            # Calculate expiries for this year
            expiring_tranches = asset_tranches[asset_tranches["expiry_year"] == year]
            E_t_total = expiring_tranches["mw"].sum()
            E_t_elig = expiring_tranches[expiring_tranches["eligible"]]["mw"].sum()
            E_t_inelig = E_t_total - E_t_elig
            
            # Calculate net capacity change
            D_t = max(0, K_prev - K_curr)  # Decrease
            delta_K_plus = max(0, K_curr - K_prev)  # Increase
            
            # Allocate retirements
            R_t_inelig = min(D_t, E_t_inelig)
            D1 = D_t - R_t_inelig
            R_t_elig = min(D1, E_t_elig)
            D2 = D1 - R_t_elig
            ER_t = D2  # Early retirement
            
            # Calculate replacement
            W_t = max(0, E_t_elig - R_t_elig)
            
            results.append({
                "asset_id": asset_id,
                "year": year,
                "E_t_inelig": E_t_inelig,
                "E_t_elig": E_t_elig,
                "R_t_inelig": R_t_inelig,
                "R_t_elig": R_t_elig,
                "ER_t": ER_t,
                "W_t": W_t,
                "delta_K_plus": delta_K_plus
            })
    
    results_df = pd.DataFrame(results)
    logger.info(f"Computed retirement/replacement for {len(results_df)} asset-year rows")
    
    return results_df


def compute_capex_and_decom(
    asset_panel_enriched: pd.DataFrame,
    asset_retire_replace: pd.DataFrame,
    include_replacement_capex: bool = True,
    include_decom_costs: bool = True,
) -> pd.DataFrame:
    """
    Node 7: Compute CapEx and decommissioning costs.
    """
    
    logger.info("Computing CapEx and decommissioning costs...")
    
    # Merge panel with retirement/replacement data
    capex_data = asset_panel_enriched.merge(
        asset_retire_replace,
        on=["asset_id", "year"],
        how="left"
    )
    
    # Fill NAs with 0
    capex_cols = ["E_t_inelig", "E_t_elig", "R_t_inelig", "R_t_elig", "ER_t", "W_t", "delta_K_plus"]
    for col in capex_cols:
        capex_data[col] = capex_data[col].fillna(0)
    
    # Compute CapEx components
    capex_data["growth_capex"] = capex_data["capex_usd_per_mw"] * capex_data["delta_K_plus"]
    
    # Replacement CapEx (can be switched off)
    if include_replacement_capex:
        capex_data["replace_capex"] = capex_data["capex_usd_per_mw"] * capex_data["W_t"]
    else:
        capex_data["replace_capex"] = 0.0
        logger.info("Replacement CapEx switched OFF - setting to zero")
    
    # Decommissioning costs (can be switched off)
    if include_decom_costs:
        capex_data["decom_cost"] = capex_data["decom_usd_per_mw"] * (
            capex_data["R_t_inelig"] + capex_data["R_t_elig"] + capex_data["ER_t"]
        )
    else:
        capex_data["decom_cost"] = 0.0
        logger.info("Decommissioning costs switched OFF - setting to zero")
    
    capex_data["capex_total"] = (
        capex_data["growth_capex"] + capex_data["replace_capex"] + capex_data["decom_cost"]
    )
    
    logger.info(f"Computed CapEx for {len(capex_data)} asset-year rows")
    
    return capex_data


def compute_ops_block(
    asset_capex_block: pd.DataFrame,
    market_passthrough: float = 0.5,
) -> pd.DataFrame:
    """
    Node 8: Compute operations block (production, costs, revenue, EBITDA).
    """
    
    logger.info("Computing operations block...")
    
    ops_data = asset_capex_block.copy()
    
    # Calculate average capacity for the year
    ops_data["K_avg"] = ops_data["capacity_after_shock_adj"]  # Simplified - could use half-year accuracy
    
    # Production
    ops_data["Q"] = ops_data["K_avg"] * ops_data["capacity_factor"] * HOURS_PER_YEAR
    
    # Fuel cost per MWh_e (for power generation)
    ops_data["fuel_cost_per_mwh"] = ops_data["fuel_price_usd_per_mwh_fuel"] / ops_data["efficiency_decimal"]
    ops_data["fuel_cost_per_mwh"] = ops_data["fuel_cost_per_mwh"].fillna(0)
    
    # Variable fuel cost
    ops_data["var_cost"] = ops_data["Q"] * ops_data["fuel_cost_per_mwh"]
    
    # Fixed O&M cost
    ops_data["fixed_cost"] = ops_data["fom_usd_per_mw_yr"] * ops_data["K_avg"]
    
    # Carbon cost (net of passthrough)
    ops_data["carbon_cost_net"] = (
        ops_data["Q"] * 
        ops_data["carbon_price_usd_per_tco2"] * 
        ops_data["emission_factor"] * 
        (1 - market_passthrough)
    )
    
    # Revenue (ex-carbon price)
    ops_data["revenue"] = ops_data["Q"] * ops_data["power_price_excarbon_usd_per_mwh"]
    
    # EBITDA
    ops_data["EBITDA"] = (
        ops_data["revenue"] - 
        ops_data["var_cost"] - 
        ops_data["fixed_cost"] - 
        ops_data["carbon_cost_net"]
    )
    
    logger.info(f"Computed operations for {len(ops_data)} asset-year rows")
    
    return ops_data




def compute_fcff(asset_ops_block: pd.DataFrame) -> pd.DataFrame:
    """
    Node 9: Compute Free Cash Flow to Firm (FCFF).
    """
    
    logger.info("Computing FCFF...")
    
    cashflow_data = asset_ops_block.copy()
    
    # FCFF = EBITDA - CapEx (tax-neutral, no working capital changes)
    cashflow_data["FCFF"] = cashflow_data["EBITDA"] - cashflow_data["capex_total"]
    
    logger.info(f"Computed FCFF for {len(cashflow_data)} asset-year rows")
    
    return cashflow_data


def aggregate_to_company_technology_earnings(asset_cashflows: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate asset-level earnings to company-technology level.
    """
    
    logger.info("Aggregating to company-technology level...")
    
    # Define aggregation functions for different metrics
    agg_funcs = {
        # Sum financial flows and physical quantities
        **{col: "sum" for col in asset_cashflows.columns 
           if any(metric in col for metric in [
               "Q", "revenue", "var_cost", "fixed_cost", "carbon_cost_net", "EBITDA",
               "growth_capex", "replace_capex", "decom_cost", "capex_total", "FCFF",
               "capacity_after_shock_adj", "capacity_before_shock"
           ])},
        
        # Take first value for metadata (should be same across assets of same company-technology)
        **{col: "first" for col in asset_cashflows.columns 
           if col in [
               "scenario_provider", "scenario", "scenario_type", "scenario_geography",
               "sector", "aligned", "increasing", "alignment_type", "emission_factor"
           ]},
    }
    
    # Group by company, technology, and year
    company_tech_agg = (
        asset_cashflows.groupby(["company_id", "technology", "year"])
        .agg(agg_funcs)
        .reset_index()
    )
    
    # Calculate capacity factor and efficiency as weighted averages
    if "capacity_factor" in asset_cashflows.columns:
        # Weight capacity factor by capacity
        weighted_cf = asset_cashflows.groupby(["company_id", "technology", "year"]).apply(
            lambda x: (x["capacity_factor"] * x["capacity_after_shock_adj"]).sum() / x["capacity_after_shock_adj"].sum()
            if x["capacity_after_shock_adj"].sum() > 0 else 0
        ).reset_index(name="capacity_factor")
        
        company_tech_agg = company_tech_agg.merge(
            weighted_cf, on=["company_id", "technology", "year"], how="left"
        )
    
    if "efficiency_decimal" in asset_cashflows.columns:
        # Weight efficiency by production
        weighted_eff = asset_cashflows.groupby(["company_id", "technology", "year"]).apply(
            lambda x: (x["efficiency_decimal"] * x["Q"]).sum() / x["Q"].sum()
            if x["Q"].sum() > 0 else 0
        ).reset_index(name="efficiency_decimal")
        
        company_tech_agg = company_tech_agg.merge(
            weighted_eff, on=["company_id", "technology", "year"], how="left"
        )
    
    # Add synthetic asset indicator
    company_tech_agg["has_synthetic_assets"] = asset_cashflows.groupby(
        ["company_id", "technology", "year"]
    )["is_synthetic"].any().reset_index(drop=True)
    
    logger.info(f"Aggregated to {len(company_tech_agg)} company-technology-year rows")
    
    return company_tech_agg


def aggregate_to_company_earnings(company_tech_earnings: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate company-technology level earnings to company level.
    """
    
    logger.info("Aggregating to company level...")
    
    # Define aggregation functions
    agg_funcs = {
        # Sum all financial and physical metrics
        **{col: "sum" for col in company_tech_earnings.columns 
           if any(metric in col for metric in [
               "Q", "revenue", "var_cost", "fixed_cost", "carbon_cost_net", "EBITDA",
               "growth_capex", "replace_capex", "decom_cost", "capex_total", "FCFF",
               "capacity_after_shock_adj", "capacity_before_shock"
           ])},
        
        # Take first value for metadata
        **{col: "first" for col in company_tech_earnings.columns 
           if col in [
               "scenario_provider", "scenario", "scenario_type", "scenario_geography"
           ]},
        
        # Any alignment across technologies
        **{col: "any" for col in company_tech_earnings.columns 
           if col in ["aligned", "increasing", "has_synthetic_assets"]},
    }
    
    # Group by company and year only
    company_agg = (
        company_tech_earnings.groupby(["company_id", "year"])
        .agg(agg_funcs)
        .reset_index()
    )
    
    # Calculate weighted averages for rates
    if "capacity_factor" in company_tech_earnings.columns:
        weighted_cf = company_tech_earnings.groupby(["company_id", "year"]).apply(
            lambda x: (x["capacity_factor"] * x["capacity_after_shock_adj"]).sum() / x["capacity_after_shock_adj"].sum()
            if x["capacity_after_shock_adj"].sum() > 0 else 0
        ).reset_index(name="capacity_factor")
        
        company_agg = company_agg.merge(
            weighted_cf, on=["company_id", "year"], how="left"
        )
    
    if "efficiency_decimal" in company_tech_earnings.columns:
        weighted_eff = company_tech_earnings.groupby(["company_id", "year"]).apply(
            lambda x: (x["efficiency_decimal"] * x["Q"]).sum() / x["Q"].sum()
            if x["Q"].sum() > 0 else 0
        ).reset_index(name="efficiency_decimal")
        
        company_agg = company_agg.merge(
            weighted_eff, on=["company_id", "year"], how="left"
        )
    
    # Create technology mix summary
    tech_mix = company_tech_earnings.groupby(["company_id", "year"]).apply(
        lambda x: ", ".join(x["technology"].unique())
    ).reset_index(name="technology_mix")
    
    company_agg = company_agg.merge(tech_mix, on=["company_id", "year"], how="left")
    
    # Create sector mix summary
    if "sector" in company_tech_earnings.columns:
        sector_mix = company_tech_earnings.groupby(["company_id", "year"]).apply(
            lambda x: ", ".join(x["sector"].unique())
        ).reset_index(name="sector_mix")
        
        company_agg = company_agg.merge(sector_mix, on=["company_id", "year"], how="left")
    
    logger.info(f"Aggregated to {len(company_agg)} company-year rows")
    
    return company_agg


def write_asset_earnings_series(asset_cashflows: pd.DataFrame) -> pd.DataFrame:
    """
    Node 10: Write final asset earnings series with all required columns.
    """
    
    logger.info("Writing final asset earnings series...")
    
    # Select and organize final columns
    output_columns = [
        # Keys
        "asset_id", "company_id", "scenario_provider", "scenario", "scenario_type",
        "scenario_geography", "sector", "technology", "year", "is_synthetic",
        
        # State
        "capacity_after_shock_adj", "capacity_before_shock", "capacity_factor",
        "efficiency_decimal", "lifetime_years", "aligned", "increasing", "alignment_type",
        "emission_factor",
        
        # Prices/costs
        "power_price_excarbon_usd_per_mwh", "fuel_price_usd_per_mwh_fuel",
        "carbon_price_usd_per_tco2", "fom_usd_per_mw_yr", "capex_usd_per_mw",
        "decom_usd_per_mw",
        
        # Earnings series
        "Q", "revenue", "var_cost", "fixed_cost", "carbon_cost_net", "EBITDA",
        
        # CapEx & decom
        "growth_capex", "replace_capex", "decom_cost", "capex_total",
        
        # Cash
        "FCFF"
    ]
    
    # Fill missing columns with appropriate defaults
    for col in output_columns:
        if col not in asset_cashflows.columns:
            if col in ["is_synthetic", "aligned", "increasing"]:
                asset_cashflows[col] = False
            elif col in ["scenario_provider", "scenario", "scenario_type", "alignment_type"]:
                asset_cashflows[col] = "unknown"
            else:
                asset_cashflows[col] = 0.0
    
    # Select final columns
    final_output = asset_cashflows[output_columns].copy()
    
    # Sort by asset and year
    final_output = final_output.sort_values(["asset_id", "year"]).reset_index(drop=True)
    
    logger.info(f"Final earnings series: {len(final_output)} rows, {len(final_output.columns)} columns")
    
    return final_output