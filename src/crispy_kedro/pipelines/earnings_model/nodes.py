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
    "Coal": {
        "lifetime_years": 40,
        "efficiency_decimal": 0.35,
        "decom_usd_per_mw": 50000,
    },
    "Gas": {
        "lifetime_years": 30,
        "efficiency_decimal": 0.45,
        "decom_usd_per_mw": 30000,
    },
    "GasCap": {
        "lifetime_years": 30,
        "efficiency_decimal": 0.45,
        "decom_usd_per_mw": 30000,
    },
    "Oil": {
        "lifetime_years": 30,
        "efficiency_decimal": 0.35,
        "decom_usd_per_mw": 40000,
    },
    "OilCap": {
        "lifetime_years": 30,
        "efficiency_decimal": 0.35,
        "decom_usd_per_mw": 40000,
    },
    "Nuclear": {
        "lifetime_years": 60,
        "efficiency_decimal": 0.33,
        "decom_usd_per_mw": 500000,
    },
    "Solar": {
        "lifetime_years": 25,
        "efficiency_decimal": 1.0,
        "decom_usd_per_mw": 20000,
    },
    "Wind": {
        "lifetime_years": 25,
        "efficiency_decimal": 1.0,
        "decom_usd_per_mw": 25000,
    },
    "Hydro": {
        "lifetime_years": 80,
        "efficiency_decimal": 1.0,
        "decom_usd_per_mw": 100000,
    },
    "Geothermal": {
        "lifetime_years": 30,
        "efficiency_decimal": 1.0,
        "decom_usd_per_mw": 75000,
    },
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
    logger.info(f"Initial assets shape: {assets.shape}")
    logger.info(
        f"Initial assets sample: {assets.head(2).to_dict('records') if len(assets) > 0 else 'EMPTY'}"
    )

    # Standardize string columns
    string_cols = [
        "asset_id",
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
        "capex_indicator",
    ]
    for col in string_cols:
        if col in assets.columns:
            assets[col] = assets[col].astype(str).str.strip()

    # Ensure numeric columns
    numeric_cols = [
        "year",
        "asset_age",
        "capacity_before_shock",
        "capacity_after_shock",
        "capex_capacity",
    ]
    for col in numeric_cols:
        if col in assets.columns:
            before_conversion = len(assets)
            assets[col] = pd.to_numeric(assets[col], errors="coerce")
            # Check for NaN values that might cause issues
            nan_count = assets[col].isna().sum()
            if nan_count > 0:
                logger.warning(
                    f"Column {col}: {nan_count}/{before_conversion} values became NaN after conversion"
                )
                logger.warning(
                    f"Sample non-NaN values: {assets[col].dropna().head(3).tolist()}"
                )

    # Clean scenarios data
    scenarios = downloaded_scenarios.copy()

    # Standardize geography/sector/tech
    scenarios["scenario_geography"] = (
        scenarios["scenario_geography"].astype(str).str.strip()
    )
    scenarios["sector"] = scenarios["sector"].astype(str).str.strip()
    scenarios["technology"] = scenarios["technology"].astype(str).str.strip()

    # Ensure numeric columns
    scenario_numeric_cols = [
        "scenario_price",
        "scenario_capacity_factor",
        "scenario_year",
        "lifetime_years",
        "efficiency_decimal",
        "capacity_additions_mw_per_yr",
        "om_cost_usd_per_mw_per_yr",
        "capital_cost_usd_per_mw",
        "carbon_price_usd_per_tco2",
    ]
    for col in scenario_numeric_cols:
        if col in scenarios.columns:
            scenarios[col] = pd.to_numeric(scenarios[col], errors="coerce")

    # Rename scenario_year to year for consistency
    scenarios = scenarios.rename(columns={"scenario_year": "year"})

    # Clean alignment data
    alignments = all_alignment_classifications.copy()

    # Standardize columns
    alignments["company_id"] = alignments["company_id"].astype(str).str.strip()
    alignments["scenario_geography"] = (
        alignments["scenario_geography"].astype(str).str.strip()
    )
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
    assets_static["emission_factor"] = pd.to_numeric(
        assets_static["emission_factor"], errors="coerce"
    ).fillna(0.0)

    # Check year continuity per asset (non-destructive check)
    logger.info(f"Assets shape before year continuity check: {assets.shape}")
    if len(assets) > 0:
        # Remove any rows with NaN years to avoid issues
        assets_before_filter = len(assets)
        assets = assets.dropna(subset=["year"])
        assets_after_filter = len(assets)
        if assets_before_filter != assets_after_filter:
            logger.warning(
                f"Dropped {assets_before_filter - assets_after_filter} rows with NaN years"
            )

        year_check = assets.groupby("asset_id")["year"].apply(
            lambda x: x.sort_values().diff().dropna().unique()
        )
        logger.info(f"Year continuity check completed for {len(year_check)} assets")
    else:
        logger.error(
            "No assets to check for year continuity - assets DataFrame is empty!"
        )

    logger.info(f"Final assets shape before return: {assets.shape}")
    logger.info(f"Processed {len(assets)} asset-year rows")
    logger.info(f"Processed {len(scenarios)} scenario-year rows")
    logger.info(f"Processed {len(alignments)} alignment classifications")
    logger.info(f"Processed {len(assets_static)} assets static data rows")

    return {
        "assets_validated": assets,
        "scenarios_validated": scenarios,
        "alignments_validated": alignments,
        "assets_static_validated": assets_static,
    }


def build_scenario_surfaces(scenarios_validated: pd.DataFrame) -> pd.DataFrame:
    """
    Node 2: Build tidy per-(geo, sector, technology, year) surfaces.

    Creates standardized scenario surfaces with proper naming and units.
    """

    logger.info("Building scenario surfaces...")

    scenarios = scenarios_validated.copy()

    # Create base surface structure
    surface_cols = [
        "scenario_geography",
        "sector",
        "technology",
        "year",
        "scenario",
        "scenario_provider",
    ]
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
    surfaces["carbon_price_usd_per_tco2"] = scenarios[
        "carbon_price_usd_per_tco2"
    ].fillna(0.0)

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

    # Debug: Check input data
    logger.info(f"Input assets shape: {assets.shape}")
    logger.info(f"Assets columns: {list(assets.columns)}")
    logger.info(f"Input alignments shape: {alignments.shape}")
    logger.info(f"Alignments columns: {list(alignments.columns)}")

    if len(assets) == 0:
        logger.error("No assets data provided - cannot proceed")
        raise ValueError("Assets data is empty")

    if len(alignments) == 0:
        logger.warning("No alignments data provided - will use defaults")

    # Join alignment flags to assets
    assets_with_alignment = assets.merge(
        alignments[
            [
                "company_id",
                "scenario_geography",
                "sector",
                "technology",
                "aligned",
                "increasing",
                "alignment_type",
            ]
        ],
        on=["company_id", "scenario_geography", "sector", "technology"],
        how="left",
    )

    logger.info(f"After alignment merge: {assets_with_alignment.shape} rows")

    # Fill missing alignment flags (default to aligned=True, increasing=False)
    assets_with_alignment["aligned"] = assets_with_alignment["aligned"].fillna(True)
    assets_with_alignment["increasing"] = assets_with_alignment["increasing"].fillna(
        False
    )
    assets_with_alignment["alignment_type"] = assets_with_alignment[
        "alignment_type"
    ].fillna("aligned")

    # Initialize outputs
    assets_adjusted = []
    synthetic_tranches = []
    synthetic_registry = []

    # Group by company-geo-sector-tech and process
    groups = assets_with_alignment.groupby(
        ["company_id", "scenario_geography", "sector", "technology"]
    )

    logger.info(f"Number of groups to process: {len(groups)}")

    if len(groups) == 0:
        logger.error("No groups found after groupby operation")
        raise ValueError("No asset groups to process")

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

        group_data["capacity_after_shock_adj"] = group_data[
            "capacity_after_shock"
        ].copy()

        for year in sorted(group_data["year"].unique()):
            year_data = group_data[group_data["year"] == year].copy()

            # Calculate totals for this year
            K_total_t = year_data["capacity_after_shock"].sum()
            base_total_t = (
                year_data[["capacity_after_shock", "capacity_before_shock"]]
                .min(axis=1)
                .sum()
            )

            required_synthetic_t = max(0, K_total_t - base_total_t)

            # Adjust original assets (cap at base capacity)
            year_data["capacity_after_shock_adj"] = np.minimum(
                year_data["capacity_after_shock"], year_data["capacity_before_shock"]
            )

            # Update group data
            group_data.loc[group_data["year"] == year, "capacity_after_shock_adj"] = (
                year_data["capacity_after_shock_adj"]
            )

            # Handle synthetic capacity requirements
            if required_synthetic_t > synthetic_stock:
                # Need to add synthetic capacity
                add_mw = required_synthetic_t - synthetic_stock
                seq_counter += 1

                # Create synthetic asset registry entry
                synthetic_asset_id = f"SYN_{company_id}_{tech}_{year}_{seq_counter}"
                synthetic_registry.append(
                    {
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
                        "alignment_type": "aligned",
                    }
                )

                # Add to tranche list
                synthetic_tranches.append(
                    {
                        "company_id": company_id,
                        "scenario_geography": geo,
                        "sector": sector,
                        "technology": tech,
                        "start_year": year,
                        "mw": add_mw,
                        "is_synthetic": True,
                        "eligible": True,
                    }
                )

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
                    retire_from_tranche = min(
                        remaining_to_retire, tranche["mw_remaining"]
                    )

                    tranche["mw_remaining"] -= retire_from_tranche
                    remaining_to_retire -= retire_from_tranche

                    if tranche["mw_remaining"] <= 0:
                        synthetic_fifo.pop(0)

                synthetic_stock = required_synthetic_t

        assets_adjusted.append(group_data)

    # Combine all adjusted assets
    logger.info(f"Number of asset groups processed: {len(assets_adjusted)}")

    if len(assets_adjusted) == 0:
        logger.error(
            "No asset groups were processed - this will cause concatenation to fail"
        )
        logger.info("This usually means all groups were skipped during processing")
        raise ValueError("No asset groups were processed successfully")

    assets_adjusted_df = pd.concat(assets_adjusted, ignore_index=True)

    # Create synthetic dataframes
    synthetic_tranche_log = pd.DataFrame(synthetic_tranches)
    synthetic_asset_registry_df = pd.DataFrame(synthetic_registry)

    logger.info(f"Created {len(synthetic_asset_registry_df)} synthetic assets")
    logger.info(f"Adjusted {len(assets_adjusted_df)} original asset-year rows")

    return {
        "assets_adjusted": assets_adjusted_df,
        "synthetic_tranche_log": synthetic_tranche_log,
        "synthetic_asset_registry": synthetic_asset_registry_df,
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
                    "capacity_before_shock": (
                        0.0 if year == start_year else synthetic_asset["initial_mw"]
                    ),
                    "capacity_after_shock": synthetic_asset["initial_mw"],
                    "capacity_after_shock_adj": synthetic_asset["initial_mw"],
                    "is_synthetic": True,
                    "aligned": True,
                    "increasing": True,
                    "alignment_type": "aligned",
                }
                synthetic_rows.append(synthetic_row)

        if synthetic_rows:
            synthetic_df = pd.DataFrame(synthetic_rows)
            panel = pd.concat([panel, synthetic_df], ignore_index=True)

    # Join scenario surfaces
    panel_enriched = panel.merge(
        scenario_surfaces,
        on=["scenario_geography", "sector", "technology", "year"],
        how="left",
    )

    # Join assets static data to get emission factors
    panel_enriched = panel_enriched.merge(
        assets_static_validated[["asset_id", "emission_factor"]],
        on="asset_id",
        how="left",
    )

    # Fill missing emission factors with 0 (for synthetic assets or missing data)
    panel_enriched["emission_factor"] = panel_enriched["emission_factor"].fillna(0.0)

    logger.info(f"Assembled panel with {len(panel_enriched)} asset-year rows")

    return panel_enriched


# Tranche ledger functions removed - now using flow-based CapEx from upstream pipeline


def validate_capacity_flow_identity(
    asset_panel_enriched: pd.DataFrame,
) -> pd.DataFrame:
    """
    Validate the capacity flow identity: K_t = K_{t-1} - retired + replaced + new_build

    This function checks that the upstream pipeline correctly calculated capacity flows
    and logs any discrepancies for debugging.
    """

    logger.info("Validating capacity flow identity...")

    data = asset_panel_enriched.copy()

    # Sort by asset and year
    data = data.sort_values(["asset_id", "year"]).reset_index(drop=True)

    # Get capacity flows by indicator type per asset-year
    flows_pivot = data.pivot_table(
        index=["asset_id", "year"],
        columns="capex_indicator",
        values="capex_capacity",
        fill_value=0.0,
        aggfunc="sum",
    ).reset_index()

    # Ensure all flow columns exist
    for col in ["new_buildout_cap", "roll_over_cap", "retired_max_cap"]:
        if col not in flows_pivot.columns:
            flows_pivot[col] = 0.0

    # Merge with capacity data
    capacity_data = data[
        ["asset_id", "year", "capacity_after_shock", "capacity_before_shock"]
    ].drop_duplicates()
    validation_data = flows_pivot.merge(
        capacity_data, on=["asset_id", "year"], how="left"
    )

    # Calculate previous year capacity
    validation_data = validation_data.sort_values(["asset_id", "year"])
    validation_data["K_prev"] = validation_data.groupby("asset_id")[
        "capacity_after_shock"
    ].shift(1)

    # Apply flow identity: K_t = K_{t-1} - retired + replaced + new_build
    validation_data["K_calculated"] = (
        validation_data["K_prev"]
        - validation_data["retired_max_cap"]
        + validation_data["roll_over_cap"]
        + validation_data["new_buildout_cap"]
    )

    # Compare with actual capacity (skip first year per asset where K_prev is NaN)
    validation_data = validation_data.dropna(subset=["K_prev"])

    if len(validation_data) > 0:
        validation_data["capacity_diff"] = abs(
            validation_data["capacity_after_shock"] - validation_data["K_calculated"]
        )

        # Log validation results
        total_rows = len(validation_data)
        tolerance = 0.01  # MW tolerance
        valid_rows = len(validation_data[validation_data["capacity_diff"] <= tolerance])

        logger.info(
            f"Flow identity validation: {valid_rows}/{total_rows} rows within tolerance ({tolerance} MW)"
        )

        if valid_rows < total_rows:
            problem_assets = validation_data[
                validation_data["capacity_diff"] > tolerance
            ]
            logger.warning(
                f"Flow identity violations found in {len(problem_assets)} asset-year combinations:"
            )
            for _, row in problem_assets.head(
                10
            ).iterrows():  # Show first 10 violations
                logger.warning(
                    f"  Asset {row['asset_id']} Year {row['year']}: "
                    f"Actual={row['capacity_after_shock']:.2f} MW, "
                    f"Calculated={row['K_calculated']:.2f} MW, "
                    f"Diff={row['capacity_diff']:.2f} MW"
                )

    return data


def compute_capacity_flows(asset_panel: pd.DataFrame) -> pd.DataFrame:
    """
    Compute capacity flows from capacity changes in the asset panel (vectorized).

    Creates flow indicators:
    - new_buildout_cap: Net new capacity (growth above baseline)
    - roll_over_cap: Capacity replacement (existing capacity renewed)
    - retired_max_cap: Capacity retired (reduction from baseline)
    """

    logger.info("Computing capacity flows from capacity changes...")

    data = asset_panel.copy()
    data = data.sort_values(["asset_id", "year"]).reset_index(drop=True)

    # Calculate capacity changes vectorized
    data["K_prev"] = data.groupby("asset_id")["capacity_after_shock"].shift(1)
    data["capacity_change"] = data["capacity_after_shock"] - data["K_prev"].fillna(0)

    # Prepare base columns for flows
    data["is_synthetic"] = data.get("is_synthetic", False).fillna(False)

    # Create flow records vectorized - this creates multiple rows per asset-year
    flow_records = []

    # 1. New buildout flows (positive capacity changes)
    new_buildout_mask = data["capacity_change"] > 0
    if new_buildout_mask.any():
        new_buildout_data = data[new_buildout_mask].copy()
        new_buildout_data["capex_indicator"] = "new_buildout_cap"
        new_buildout_data["capex_capacity"] = new_buildout_data["capacity_change"]
        flow_records.append(new_buildout_data)

    # 2. Retirement flows (negative capacity changes)
    retirement_mask = data["capacity_change"] < 0
    if retirement_mask.any():
        retirement_data = data[retirement_mask].copy()
        retirement_data["capex_indicator"] = "retired_max_cap"
        retirement_data["capex_capacity"] = retirement_data["capacity_change"].abs()
        flow_records.append(retirement_data)

    # 3. Replacement flows (5% of existing non-synthetic capacity annually)
    replacement_mask = (~data["is_synthetic"]) & (data["capacity_after_shock"] > 0)
    if replacement_mask.any():
        replacement_data = data[replacement_mask].copy()
        replacement_data["capex_indicator"] = "roll_over_cap"
        replacement_data["capex_capacity"] = (
            replacement_data["capacity_after_shock"] * 0.05
        )
        flow_records.append(replacement_data)

    # 4. No-flow records (assets with no flows need placeholder records)
    no_flow_mask = (data["capacity_change"] == 0) & (~replacement_mask)
    if no_flow_mask.any():
        no_flow_data = data[no_flow_mask].copy()
        no_flow_data["capex_indicator"] = "none"
        no_flow_data["capex_capacity"] = 0.0
        flow_records.append(no_flow_data)

    # Combine all flow records
    if flow_records:
        result = pd.concat(flow_records, ignore_index=True)
    else:
        # Fallback: no flows found, add empty columns
        data["capex_indicator"] = "none"
        data["capex_capacity"] = 0.0
        result = data

    # Sort result by asset and year for consistency
    result = result.sort_values(["asset_id", "year", "capex_indicator"]).reset_index(
        drop=True
    )

    logger.info(
        f"Computed capacity flows for {len(result)} asset-year-flow combinations"
    )

    return result


def compute_flow_based_capex(
    asset_panel_enriched: pd.DataFrame,
    include_replacement_capex: bool = True,
    include_decom_costs: bool = True,
) -> pd.DataFrame:
    """
    Node 5: Compute CapEx using flow-based approach.

    Computes capacity flows from capacity changes and then calculates:
    - GrowthCapEx_t = κ_t * new_buildout_cap
    - ReplaceCapEx_t = κ_t * roll_over_cap
    - DecomCost_t = δ_decom * retired_max_cap
    """

    logger.info("Computing flow-based CapEx...")

    # Compute capacity flows from the data
    capex_data = compute_capacity_flows(asset_panel_enriched)

    # First validate the capacity flow identity
    capex_data = validate_capacity_flow_identity(capex_data)

    # Ensure capex_capacity is numeric and fill NaNs
    capex_data["capex_capacity"] = pd.to_numeric(
        capex_data["capex_capacity"], errors="coerce"
    ).fillna(0.0)
    capex_data["capex_indicator"] = capex_data["capex_indicator"].fillna("none")

    # Map flow indicators to CapEx components
    # Growth CapEx: new capacity builds
    new_build_mask = capex_data["capex_indicator"] == "new_buildout_cap"
    capex_data["growth_capex"] = np.where(
        new_build_mask,
        capex_data["capex_usd_per_mw"] * capex_data["capex_capacity"],
        0.0,
    )

    # Replacement CapEx: rolled over capacity (can be switched off)
    if include_replacement_capex:
        rollover_mask = capex_data["capex_indicator"] == "roll_over_cap"
        capex_data["replace_capex"] = np.where(
            rollover_mask,
            capex_data["capex_usd_per_mw"] * capex_data["capex_capacity"],
            0.0,
        )
    else:
        capex_data["replace_capex"] = 0.0
        logger.info("Replacement CapEx switched OFF - setting to zero")

    # Decommissioning costs: retired capacity (can be switched off)
    if include_decom_costs:
        retired_mask = capex_data["capex_indicator"] == "retired_max_cap"
        capex_data["decom_cost"] = np.where(
            retired_mask,
            capex_data["decom_usd_per_mw"] * capex_data["capex_capacity"],
            0.0,
        )
    else:
        capex_data["decom_cost"] = 0.0
        logger.info("Decommissioning costs switched OFF - setting to zero")

    # Total CapEx
    capex_data["capex_total"] = (
        capex_data["growth_capex"]
        + capex_data["replace_capex"]
        + capex_data["decom_cost"]
    )

    # Log summary by flow type
    flow_summary = (
        capex_data.groupby("capex_indicator")
        .agg(
            {
                "capex_capacity": "sum",
                "growth_capex": "sum",
                "replace_capex": "sum",
                "decom_cost": "sum",
            }
        )
        .round(0)
    )

    logger.info("CapEx summary by flow type:")
    for idx, row in flow_summary.iterrows():
        logger.info(
            f"  {idx}: {row['capex_capacity']:,.0f} MW -> Growth: ${row['growth_capex']:,.0f}, Replace: ${row['replace_capex']:,.0f}, Decom: ${row['decom_cost']:,.0f}"
        )

    logger.info(f"Computed flow-based CapEx for {len(capex_data)} asset-year rows")

    return capex_data


def compute_ops_block(
    asset_capex_block: pd.DataFrame,
    market_passthrough: float = 0.5,
) -> pd.DataFrame:
    """
    Node 8: Compute operations block (production, costs, revenue, EBITDA).

    EBITDA_t = Revenue_t − FuelCost_t − FixedO&M_t − CarbonCost_net_t
    Note: No depreciation is considered here. EBITDA is a cash operating measure.
    RFC: Corporate tax and depreciation tax shield are currently disabled; see compute_fcff().
    """

    logger.info("Computing operations block...")

    ops_data = asset_capex_block.copy()

    # Calculate average capacity for the year
    ops_data["K_avg"] = ops_data[
        "capacity_after_shock_adj"
    ]  # Simplified - could use half-year accuracy

    # Production
    ops_data["Q"] = ops_data["K_avg"] * ops_data["capacity_factor"] * HOURS_PER_YEAR

    # Fuel cost per MWh_e (for power generation)
    ops_data["fuel_cost_per_mwh"] = (
        ops_data["fuel_price_usd_per_mwh_fuel"] / ops_data["efficiency_decimal"]
    )
    ops_data["fuel_cost_per_mwh"] = ops_data["fuel_cost_per_mwh"].fillna(0)

    # Variable fuel cost
    ops_data["var_cost"] = ops_data["Q"] * ops_data["fuel_cost_per_mwh"]

    # Fixed O&M cost
    ops_data["fixed_cost"] = ops_data["fom_usd_per_mw_yr"] * ops_data["K_avg"]

    # Carbon cost (net of passthrough)
    ops_data["carbon_cost_net"] = (
        ops_data["Q"]
        * ops_data["carbon_price_usd_per_tco2"]
        * ops_data["emission_factor"]
        * (1 - market_passthrough)
    )

    # Revenue (ex-carbon price)
    ops_data["revenue"] = ops_data["Q"] * ops_data["power_price_excarbon_usd_per_mwh"]

    # EBITDA
    ops_data["EBITDA"] = (
        ops_data["revenue"]
        - ops_data["var_cost"]
        - ops_data["fixed_cost"]
        - ops_data["carbon_cost_net"]
    )

    logger.info(f"Computed operations for {len(ops_data)} asset-year rows")

    return ops_data


def compute_fcff(asset_ops_block: pd.DataFrame) -> pd.DataFrame:
    """
    Node 9: Compute Free Cash Flow to Firm (FCFF).

    Free Cash Flow (tax-neutral):
    FCFF_t = EBITDA_t − CapEx_total_t − ΔNWC_t

    RFC: Corporate tax and depreciation tax shield are currently DISABLED.
    If later enabled, switch to:
      FCFF_t = EBIT_t*(1−T) + Dep_t − CapEx_t − ΔNWC_t
    and ensure dcf.use_after_tax_wacc = true.
    """

    logger.info("Computing FCFF...")

    cashflow_data = asset_ops_block.copy()

    # FCFF = EBITDA - CapEx (tax-neutral, no working capital changes)
    # DISABLED because we don't apply a corporate tax rate and depreciation thus does not affect tax base and can be ignored in EBITDA, since it would be added back in in FCFF
    cashflow_data["FCFF"] = cashflow_data["EBITDA"] - cashflow_data["capex_total"]

    logger.info(f"Computed FCFF for {len(cashflow_data)} asset-year rows")

    return cashflow_data


def aggregate_to_company_technology_earnings(
    asset_cashflows: pd.DataFrame,
) -> pd.DataFrame:
    """
    Aggregate asset-level earnings to company-technology level.
    """

    logger.info("Aggregating to company-technology level...")

    # Define aggregation functions for different metrics
    agg_funcs = {
        # Sum financial flows and physical quantities
        **{
            col: "sum"
            for col in asset_cashflows.columns
            if any(
                metric in col
                for metric in [
                    "Q",
                    "revenue",
                    "var_cost",
                    "fixed_cost",
                    "carbon_cost_net",
                    "EBITDA",
                    "growth_capex",
                    "replace_capex",
                    "decom_cost",
                    "capex_total",
                    "FCFF",
                    "capacity_after_shock_adj",
                    "capacity_before_shock",
                ]
            )
        },
        # Take first value for metadata (should be same across assets of same company-technology)
        **{
            col: "first"
            for col in asset_cashflows.columns
            if col
            in [
                "scenario_provider",
                "scenario",
                "scenario_type",
                "scenario_geography",
                "sector",
                "aligned",
                "increasing",
                "alignment_type",
                "emission_factor",
            ]
        },
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
        weighted_cf = (
            asset_cashflows.groupby(["company_id", "technology", "year"])
            .apply(
                lambda x: (
                    (x["capacity_factor"] * x["capacity_after_shock_adj"]).sum()
                    / x["capacity_after_shock_adj"].sum()
                    if x["capacity_after_shock_adj"].sum() > 0
                    else 0
                )
            )
            .reset_index(name="capacity_factor")
        )

        company_tech_agg = company_tech_agg.merge(
            weighted_cf, on=["company_id", "technology", "year"], how="left"
        )

    if "efficiency_decimal" in asset_cashflows.columns:
        # Weight efficiency by production
        weighted_eff = (
            asset_cashflows.groupby(["company_id", "technology", "year"])
            .apply(
                lambda x: (
                    (x["efficiency_decimal"] * x["Q"]).sum() / x["Q"].sum()
                    if x["Q"].sum() > 0
                    else 0
                )
            )
            .reset_index(name="efficiency_decimal")
        )

        company_tech_agg = company_tech_agg.merge(
            weighted_eff, on=["company_id", "technology", "year"], how="left"
        )

    # Add synthetic asset indicator
    company_tech_agg["has_synthetic_assets"] = (
        asset_cashflows.groupby(["company_id", "technology", "year"])["is_synthetic"]
        .any()
        .reset_index(drop=True)
    )

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
        **{
            col: "sum"
            for col in company_tech_earnings.columns
            if any(
                metric in col
                for metric in [
                    "Q",
                    "revenue",
                    "var_cost",
                    "fixed_cost",
                    "carbon_cost_net",
                    "EBITDA",
                    "growth_capex",
                    "replace_capex",
                    "decom_cost",
                    "capex_total",
                    "FCFF",
                    "capacity_after_shock_adj",
                    "capacity_before_shock",
                ]
            )
        },
        # Take first value for metadata
        **{
            col: "first"
            for col in company_tech_earnings.columns
            if col
            in ["scenario_provider", "scenario", "scenario_type", "scenario_geography"]
        },
        # Any alignment across technologies
        **{
            col: "any"
            for col in company_tech_earnings.columns
            if col in ["aligned", "increasing", "has_synthetic_assets"]
        },
    }

    # Group by company and year only
    company_agg = (
        company_tech_earnings.groupby(["company_id", "year"])
        .agg(agg_funcs)
        .reset_index()
    )

    # Calculate weighted averages for rates
    if "capacity_factor" in company_tech_earnings.columns:
        weighted_cf = (
            company_tech_earnings.groupby(["company_id", "year"])
            .apply(
                lambda x: (
                    (x["capacity_factor"] * x["capacity_after_shock_adj"]).sum()
                    / x["capacity_after_shock_adj"].sum()
                    if x["capacity_after_shock_adj"].sum() > 0
                    else 0
                )
            )
            .reset_index(name="capacity_factor")
        )

        company_agg = company_agg.merge(
            weighted_cf, on=["company_id", "year"], how="left"
        )

    if "efficiency_decimal" in company_tech_earnings.columns:
        weighted_eff = (
            company_tech_earnings.groupby(["company_id", "year"])
            .apply(
                lambda x: (
                    (x["efficiency_decimal"] * x["Q"]).sum() / x["Q"].sum()
                    if x["Q"].sum() > 0
                    else 0
                )
            )
            .reset_index(name="efficiency_decimal")
        )

        company_agg = company_agg.merge(
            weighted_eff, on=["company_id", "year"], how="left"
        )

    # Create technology mix summary
    tech_mix = (
        company_tech_earnings.groupby(["company_id", "year"])
        .apply(lambda x: ", ".join(x["technology"].unique()))
        .reset_index(name="technology_mix")
    )

    company_agg = company_agg.merge(tech_mix, on=["company_id", "year"], how="left")

    # Create sector mix summary
    if "sector" in company_tech_earnings.columns:
        sector_mix = (
            company_tech_earnings.groupby(["company_id", "year"])
            .apply(lambda x: ", ".join(x["sector"].unique()))
            .reset_index(name="sector_mix")
        )

        company_agg = company_agg.merge(
            sector_mix, on=["company_id", "year"], how="left"
        )

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
        "asset_id",
        "company_id",
        "scenario_provider",
        "scenario",
        "scenario_type",
        "scenario_geography",
        "sector",
        "technology",
        "year",
        "is_synthetic",
        # State
        "capacity_after_shock_adj",
        "capacity_before_shock",
        "capacity_factor",
        "efficiency_decimal",
        "lifetime_years",
        "aligned",
        "increasing",
        "alignment_type",
        "emission_factor",
        # Flow-based CapEx information
        "capex_indicator",
        "capex_capacity",
        # Prices/costs
        "power_price_excarbon_usd_per_mwh",
        "fuel_price_usd_per_mwh_fuel",
        "carbon_price_usd_per_tco2",
        "fom_usd_per_mw_yr",
        "capex_usd_per_mw",
        "decom_usd_per_mw",
        # Earnings series
        "Q",
        "revenue",
        "var_cost",
        "fixed_cost",
        "carbon_cost_net",
        "EBITDA",
        # CapEx & decom (flow-based)
        "growth_capex",
        "replace_capex",
        "decom_cost",
        "capex_total",
        # Cash
        "FCFF",
    ]

    # Fill missing columns with appropriate defaults
    for col in output_columns:
        if col not in asset_cashflows.columns:
            if col in ["is_synthetic", "aligned", "increasing"]:
                asset_cashflows[col] = False
            elif col in [
                "scenario_provider",
                "scenario",
                "scenario_type",
                "alignment_type",
            ]:
                asset_cashflows[col] = "unknown"
            else:
                asset_cashflows[col] = 0.0

    # Select final columns
    final_output = asset_cashflows[output_columns].copy()

    # Sort by asset and year
    final_output = final_output.sort_values(["asset_id", "year"]).reset_index(drop=True)

    logger.info(
        f"Final earnings series: {len(final_output)} rows, {len(final_output.columns)} columns"
    )

    return final_output
