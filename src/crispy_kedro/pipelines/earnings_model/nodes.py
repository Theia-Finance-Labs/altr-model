"""
Comprehensive earnings model pipeline implementing full financial methodology
with synthetic asset creation, tranche ledger, and cash flow calculations.
"""

import logging
from typing import Dict

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# Constants
HOURS_PER_YEAR = 8760


def validate_and_standardize_inputs(
    asset_level_staggered_shock: pd.DataFrame,
    downloaded_scenarios: pd.DataFrame,
    all_alignment_classifications: pd.DataFrame,
    assets_data: pd.DataFrame,
    frozen_capacity_at_retirement: pd.DataFrame = None,
) -> Dict[str, pd.DataFrame]:
    """
    Node 1: Validate and standardize all inputs.

    Actions:
    - Enforce schemas/dtypes
    - Strip/standardize strings (geo/sector/technology)
    - Keep only needed columns
    - Assert year is contiguous per asset
    - Optionally merge frozen capacity at retirement for fixed cost calculations
    """

    logger.info("Validating and standardizing inputs...")

    # Clean asset data (melted: includes trajectory_type, asset_trajectory)
    assets = asset_level_staggered_shock.copy()

    # Merge frozen capacity if provided
    if (
        frozen_capacity_at_retirement is not None
        and not frozen_capacity_at_retirement.empty
    ):
        logger.info("Merging frozen capacity at retirement data...")
        merge_keys = [
            "asset_id",
            "company_id",
            "scenario_geography",
            "technology",
            "year",
        ]
        assets = assets.merge(
            frozen_capacity_at_retirement[
                merge_keys + ["frozen_capacity_at_retirement"]
            ],
            on=merge_keys,
            how="left",
        )
        logger.info(
            "Frozen capacity merged. Assets with frozen capacity: %s",
            assets["frozen_capacity_at_retirement"].notna().sum(),
        )
    else:
        logger.info("No frozen capacity data provided - continuing without it")
        assets["frozen_capacity_at_retirement"] = None

    # Add emission factor to assets by merging the shorter EF series (typically 2023-2030)
    # onto the longer staggered trajectories (up to 2050). Then forward-fill per asset/technology.
    ef_source = assets_data[
        [
            "asset_id",
            "technology",
            "scenario_geography",
            "year",
            "emission_factor",
        ]
    ].drop_duplicates()
    assets = assets.merge(
        ef_source,
        on=["asset_id", "technology", "scenario_geography", "year"],
        how="left",
    )

    # Forward-fill emission_factor along each (asset_id, technology) across years
    if not assets.empty:
        assets = (
            assets.sort_values(["asset_id", "technology", "year"])
            .groupby(["asset_id", "technology"], group_keys=False)
            .apply(lambda g: g.assign(emission_factor=g["emission_factor"].ffill()))
        )

    # For newly created renewable synthetic assets, set remaining missing EF to 0
    renewable_techs = {
        "SolarCap - CSP",
        "SolarCap - PV",
        "WindCap - Offshore",
        "WindCap - Onshore",
        "HydroCap",
        "NuclearCap",
        "GeothermalCap",
    }
    renew_mask = (
        assets["technology"].isin(list(renewable_techs))
        & assets["emission_factor"].isna()
    )
    if renew_mask.any():
        assets.loc[renew_mask, "emission_factor"] = 0.0

    if "is_synthetic" in assets.columns:
        syn_renew_mask = (
            assets["is_synthetic"].astype(bool)
            & assets["technology"].isin(list(renewable_techs))
            & assets["emission_factor"].isna()
        )
        if syn_renew_mask.any():
            assets.loc[syn_renew_mask, "emission_factor"] = 0.0

    logger.info("Initial assets shape: %s", assets.shape)
    logger.info(
        "Initial assets sample: %s",
        assets.head(2).to_dict("records") if len(assets) > 0 else "EMPTY",
    )

    # Standardize string columns
    string_cols = [
        "asset_id",
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
    ]
    for col in string_cols:
        assets[col] = assets[col].astype(str).str.strip()

    # Ensure numeric columns (melted)
    numeric_cols = ["year", "asset_age", "asset_trajectory", "emission_factor"]
    for col in numeric_cols:
        before_conversion = len(assets)
        assets[col] = pd.to_numeric(assets[col], errors="coerce")
        # Check for NaN values that might cause issues
        nan_count = assets[col].isna().sum()
        if nan_count > 0:
            logger.warning(
                "Column %s: %s/%s values became NaN after conversion",
                col,
                nan_count,
                before_conversion,
            )
        logger.warning(
            "Sample non-NaN values: %s", assets[col].dropna().head(3).tolist()
        )

    # Standardize trajectory_type
    assets["trajectory_type"] = assets["trajectory_type"].astype(str)

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
        "fuel_intensity",
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
    alignments["company_id"] = alignments["company_id"].astype(str)
    alignments["scenario_geography"] = alignments["scenario_geography"].astype(str)
    alignments["sector"] = alignments["sector"].astype(str)
    alignments["technology"] = alignments["technology"].astype(str)

    # Ensure boolean columns
    alignments["aligned"] = alignments["aligned"].astype(bool)
    alignments["increasing"] = alignments["increasing"].astype(bool)

    # Standardize trajectory_type
    assets["trajectory_type"] = assets["trajectory_type"].astype(str)

    # Check year continuity per asset and trajectory (non-destructive check)
    logger.info("Assets shape before year continuity check: %s", assets.shape)
    if len(assets) > 0:
        # Remove any rows with NaN years to avoid issues
        assets_before_filter = len(assets)
        assets = assets.dropna(subset=["year"])
        assets_after_filter = len(assets)
        if assets_before_filter != assets_after_filter:
            logger.warning(
                "Dropped %s rows with NaN years",
                assets_before_filter - assets_after_filter,
            )

        year_check = assets.groupby(["asset_id", "trajectory_type"])["year"].apply(
            lambda x: x.sort_values().diff().dropna().unique()
        )
        logger.info("Year continuity check completed for %s assets", len(year_check))
    else:
        logger.error(
            "No assets to check for year continuity - assets DataFrame is empty!"
        )

    logger.info("Final assets shape before return: %s", assets.shape)
    logger.info("Processed %s asset-year rows", len(assets))
    logger.info("Processed %s scenario-year rows", len(scenarios))
    logger.info("Processed %s alignment classifications", len(alignments))

    return {
        "assets_validated": assets,
        "scenarios_validated": scenarios,
        "alignments_validated": alignments,
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
        # "scenario_provider",
        "scenario_type",
    ]
    surfaces = scenarios[surface_cols].copy()

    # Build individual surfaces with proper naming

    # Power price (ex-carbon) - assume scenario_price is already in correct units for power assets
    surfaces["power_price_excarbon_usd_per_mwh"] = scenarios["scenario_price"]

    # Fuel price - use scenario_price directly (assume already in appropriate units)
    surfaces["fuel_price_usd_per_mwh_fuel"] = scenarios["fuel_price"]

    # For non-fuel technologies, set fuel price to 0
    non_fuel_techs = [
        "SolarCap - CSP",
        "SolarCap - PV",
        "WindCap - Offshore",
        "WindCap - Onshore",
        "HydroCap",
        "NuclearCap",
        "GeothermalCap",
    ]
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
    # surfaces["fuel_intensity"] = scenarios["fuel_intensity"]

    # Lifetime
    surfaces["lifetime_years"] = scenarios["lifetime_years"]

    # Add decommissioning costs
    surfaces["scrap_usd_per_mw"] = -surfaces["capex_usd_per_mw"] / 2

    logger.info("Built scenario surfaces with %s rows", len(surfaces))

    return surfaces


def assemble_asset_panel(
    assets_adjusted: pd.DataFrame,
    scenario_surfaces: pd.DataFrame,
    shock_year: int,
) -> pd.DataFrame:
    """
    Node 4: Build full asset-year panel including synthetic assets.
    """

    logger.info("Assembling full asset panel...")

    # Start with adjusted original assets
    panel = assets_adjusted.copy()

    mixed_scenario_surfaces = (
        pd.concat(
            [
                scenario_surfaces.loc[
                    (scenario_surfaces["year"] < shock_year)
                    & (scenario_surfaces["scenario_type"] == "baseline"),
                    :,
                ],
                scenario_surfaces.loc[
                    (scenario_surfaces["year"] >= shock_year)
                    & (scenario_surfaces["scenario_type"] == "target"),
                    :,
                ],
            ],
            axis=0,
        )
        .reset_index(drop=True)
        .sort_values(["scenario_geography", "sector", "technology", "year"])
        .assign(trajectory_type="latesudden")
    )
    baseline_scenario_surfaces = scenario_surfaces.loc[
        scenario_surfaces["scenario_type"] == "baseline",
        :,
    ].assign(trajectory_type="baseline")
    all_scenario_surfaces = pd.concat(
        [baseline_scenario_surfaces, mixed_scenario_surfaces], axis=0
    ).reset_index(drop=True)

    # Join scenario surfaces
    panel_enriched = panel.merge(
        all_scenario_surfaces,
        on=["trajectory_type", "scenario_geography", "sector", "technology", "year"],
        how="left",
    )

    logger.info("Assembled panel with %s asset-year rows", len(panel_enriched))

    return panel_enriched


# Tranche ledger functions removed - now using flow-based CapEx from upstream pipeline


def validate_capacity_flow_identity(
    asset_panel_enriched: pd.DataFrame,
):
    """
    Validate the capacity flow identity: K_t = K_{t-1} - retired + replaced + new_build

    This function checks that the upstream pipeline correctly calculated capacity flows
    and logs any discrepancies for debugging.
    """

    logger.info("Validating capacity flow identity...")

    data = asset_panel_enriched.copy()

    # Sort by asset and year
    data = data.sort_values(
        ["trajectory_type", "company_id", "asset_id", "technology", "year"]
    ).reset_index(drop=True)

    # Check for and remove duplicates before pivoting
    # Each (company_id, asset_id, technology, year, capex_indicator) combination should be unique
    duplicate_check_cols = [
        "trajectory_type",
        "company_id",
        "asset_id",
        "technology",
        "scenario_geography",
        "year",
        "capex_indicator",
    ]

    duplicates_count = data.duplicated(subset=duplicate_check_cols).sum()
    if duplicates_count > 0:
        raise ValueError(
            "Found %s duplicate capacity flow records. Removing duplicates...",
            duplicates_count,
        )

    # Get capacity flows by indicator type per asset-year
    # Use pivot_table with aggfunc='sum' to aggregate flows by type
    flows_pivot = data.pivot_table(
        index=[
            "trajectory_type",
            "company_id",
            "asset_id",
            "technology",
            "year",
        ],
        columns="capex_indicator",
        values="capex_capacity",
        fill_value=0.0,
        aggfunc="sum",  # Sum values for each flow type (should be identical after deduplication)
    ).reset_index()

    # Ensure all flow columns exist
    for col in ["new_buildout_cap", "roll_over_cap", "retired_max_cap"]:
        if col not in flows_pivot.columns:
            flows_pivot[col] = 0.0

    # Get unique asset-year combinations from original data
    base_cols = [
        "company_id",
        "asset_id",
        "technology",
        "year",
        "trajectory_type",
    ]
    capacity_data = data[base_cols + ["asset_trajectory"]].drop_duplicates()

    validation_data = flows_pivot.merge(capacity_data, on=base_cols, how="left")

    # Calculate previous year capacity
    validation_data = validation_data.sort_values(
        ["trajectory_type", "company_id", "asset_id", "technology", "year"]
    )
    group_keys = ["trajectory_type", "company_id", "asset_id", "technology"]
    validation_data["K_prev"] = validation_data.groupby(group_keys)[
        "asset_trajectory"
    ].shift(1)

    # Apply flow identity: K_t = K_{t-1} - retired + replaced + new_build
    # TODO the 0.05 is hardcoded like it is in the compute_capacity_flows() function.
    # Should be a parameter or this validation function droped entirely
    validation_data["K_calculated"] = (
        validation_data["K_prev"]
        - validation_data["retired_max_cap"]
        + (validation_data["roll_over_cap"] / 0.05)
        + validation_data["new_buildout_cap"]
    )

    # Compare with actual capacity (skip first year per asset where K_prev is NaN)
    validation_data = validation_data.dropna(subset=["K_prev"])

    if len(validation_data) > 0:
        validation_data["capacity_diff"] = abs(
            validation_data["asset_trajectory"] - validation_data["K_calculated"]
        )

        # Log validation results
        total_rows = len(validation_data)
        tolerance = 0.01  # MW tolerance
        valid_rows = len(validation_data[validation_data["capacity_diff"] <= tolerance])

        logger.info(
            "Flow identity validation: %s/%s rows within tolerance (%s MW)",
            valid_rows,
            total_rows,
            tolerance,
        )

        if valid_rows < total_rows:
            problem_assets = validation_data[
                validation_data["capacity_diff"] > tolerance
            ]
            logger.warning(
                "Flow identity violations found in %s asset-year combinations:",
                len(problem_assets),
            )
            for _, row in problem_assets.head(
                10
            ).iterrows():  # Show first 10 violations
                logger.warning(
                    "  Asset %s Year %s: Actual=%.2f MW, Calculated=%.2f MW, Diff=%.2f MW",
                    row["asset_id"],
                    row["year"],
                    row["asset_trajectory"],
                    row["K_calculated"],
                    row["capacity_diff"],
                )


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
    data = data.sort_values(
        ["trajectory_type", "company_id", "asset_id", "technology", "year"]
    ).reset_index(drop=True)

    # Use asset_trajectory (melted capacity)
    if "asset_trajectory" not in data.columns:
        raise ValueError("compute_capacity_flows expects 'asset_trajectory' column")

    # Calculate capacity changes vectorized, per trajectory_type when present
    group_keys = ["trajectory_type", "company_id", "asset_id", "technology"]
    data["K_prev"] = data.groupby(group_keys)["asset_trajectory"].shift(1)
    data["capacity_change"] = (data["asset_trajectory"] - data["K_prev"]).fillna(0)

    # Create flow records vectorized - this creates multiple rows per asset-year
    flow_records = []

    # 1. New buildout flows (positive capacity changes on synthetic assets)
    new_buildout_mask = data.get("is_synthetic", pd.Series(False, index=data.index)) & (
        data["capacity_change"] > 0
    )
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
    replacement_mask = (
        ~data.get("is_synthetic", pd.Series(False, index=data.index))
    ) & (data["capacity_change"] > 0)
    if replacement_mask.any():
        replacement_data = data[replacement_mask].copy()
        replacement_data["capex_indicator"] = "roll_over_cap"
        replacement_data["capex_capacity"] = replacement_data["capacity_change"] * 0.05
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
    result = result.sort_values(
        [
            "company_id",
            "asset_id",
            "technology",
            "year",
            "trajectory_type",
            "capex_indicator",
        ]
    ).reset_index(drop=True)

    logger.info(
        "Computed capacity flows for %s asset-year-flow combinations", len(result)
    )

    return result


def compute_flow_based_capex(
    asset_panel_enriched: pd.DataFrame,
    include_growth_capex: bool,
    include_replacement_capex: bool,
    include_decom_costs: bool,
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
    validate_capacity_flow_identity(capex_data)

    # Ensure capex_capacity is numeric and fill NaNs
    capex_data["capex_capacity"] = pd.to_numeric(
        capex_data["capex_capacity"], errors="coerce"
    ).fillna(0.0)
    capex_data["capex_indicator"] = capex_data["capex_indicator"].fillna("none")

    # Map flow indicators to CapEx components
    # Growth CapEx: new capacity builds (can now be switched off)
    if include_growth_capex:
        new_build_mask = capex_data["capex_indicator"] == "new_buildout_cap"
        capex_data["growth_capex"] = np.where(
            new_build_mask,
            capex_data["capex_usd_per_mw"] * capex_data["capex_capacity"],
            0.0,
        )
    else:
        capex_data["growth_capex"] = 0.0
        logger.info("Growth CapEx switched OFF - setting to zero")

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
            capex_data["scrap_usd_per_mw"] * capex_data["capex_capacity"],
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
            "  %s: %.0f MW -> Growth: $%.0f, Replace: $%.0f, Decom: $%.0f",
            idx,
            row["capex_capacity"],
            row["growth_capex"],
            row["replace_capex"],
            row["decom_cost"],
        )

    logger.info("Computed flow-based CapEx for %s asset-year rows", len(capex_data))

    return capex_data


def compute_ops_block(
    asset_capex_block: pd.DataFrame,
    market_passthrough: float = 0.5,
    use_frozen_capacity_for_fixed_costs: bool = False,
) -> pd.DataFrame:
    """
    Node 8: Compute operations block (production, costs, revenue, EBITDA).

    EBITDA_t = Revenue_t − FuelCost_t − FixedO&M_t − CarbonCost_net_t
    Note: No depreciation is considered here. EBITDA is a cash operating measure.
    RFC: Corporate tax and depreciation tax shield are currently disabled; see compute_fcff().

    Args:
        asset_capex_block: Asset data with capacity and cost information
        market_passthrough: Fraction of carbon price passed through to market (default 0.5)
        use_frozen_capacity_for_fixed_costs: If True, use frozen capacity at retirement for fixed costs
                                              instead of actual capacity (default False)
    """

    logger.info("Computing operations block...")
    if use_frozen_capacity_for_fixed_costs:
        logger.info("Using frozen capacity at retirement for fixed cost calculations")
    else:
        logger.info("Using actual asset capacity for fixed cost calculations")

    ops_data = asset_capex_block.copy()
    ops_data["emission_factor"] = ops_data["emission_factor"].fillna(0.0)

    # Calculate average capacity for the year (use melted capacity)
    ops_data["K_avg"] = ops_data["asset_trajectory"]

    # Production (always use actual capacity)
    ops_data["Q"] = ops_data["K_avg"] * ops_data["capacity_factor"] * HOURS_PER_YEAR

    # Fuel cost per MWh_e (for power generation)
    ops_data["fuel_cost_per_mwh"] = (
        ops_data["fuel_price_usd_per_mwh_fuel"] / ops_data["efficiency_decimal"]
    )
    # ops_data["fuel_cost_per_mwh"] = (
    #     ops_data["fuel_price_usd_per_mwh_fuel"] * ops_data["fuel_intensity"]
    # )

    ops_data["fuel_cost_per_mwh"] = ops_data["fuel_cost_per_mwh"].fillna(0)

    # Variable fuel cost (always use actual production)
    ops_data["var_cost"] = ops_data["Q"] * ops_data["fuel_cost_per_mwh"]

    # Fixed O&M cost - use frozen capacity if toggle is enabled
    # SAFETY: Only apply frozen capacity logic to non-baseline trajectories (latesudden)
    # to prevent contaminating the baseline scenario with shock-scenario capacities.
    if use_frozen_capacity_for_fixed_costs:
        logger.info(
            "Using constant initial capacity (from year 1) for fixed cost calculations in shock scenarios"
        )

        # Sort by keys + year to ensure we find the first year's capacity
        # We use a stable sort to be safe, though not strictly required if keys are unique
        sort_keys = [
            "trajectory_type",
            "company_id",
            "asset_id",
            "technology",
            "scenario_geography",
            "year",
        ]
        ops_data = ops_data.sort_values(sort_keys)

        # Define grouping keys to identify unique assets within a trajectory
        group_keys = [
            "trajectory_type",
            "company_id",
            "asset_id",
            "technology",
            "scenario_geography",
        ]

        # Compute initial capacity: transform('first') takes the first value in the sorted group
        ops_data["initial_capacity"] = ops_data.groupby(group_keys)["K_avg"].transform(
            "first"
        )

        # Apply logic:
        # 1. If technology is decreasing (in baseline or shock), use initial_capacity
        # 2. Otherwise (increasing techs), use K_avg (actual capacity)
        # Decreasing technologies have alignment_type in ["misaligned_high_carbon", "aligned_high_carbon"]
        decreasing_alignment_types = ["misaligned_high_carbon", "aligned_high_carbon"]

        # Check if alignment_type column exists
        if "alignment_type" in ops_data.columns:
            is_decreasing = ops_data["alignment_type"].isin(decreasing_alignment_types)
        else:
            # If alignment_type not available, log warning and apply to all technologies
            logger.warning(
                "alignment_type column not found. Applying constant capacity to all technologies."
            )
            is_decreasing = pd.Series(True, index=ops_data.index)

        # Apply frozen capacity only to decreasing technologies AND only in shock scenarios
        # We do NOT apply it to baseline, allowing baseline costs to retire with capacity (orderly transition)
        is_shock_scenario = ops_data["trajectory_type"] != "baseline"
        decreasing_mask = is_decreasing & is_shock_scenario

        ops_data["K_for_fixed_cost"] = np.where(
            decreasing_mask, ops_data["initial_capacity"], ops_data["K_avg"]
        )

        logger.info(
            "Applied constant initial capacity to %s asset-year rows (decreasing techs in shock scenarios only). "
            "Baseline and increasing techs use actual capacity.",
            decreasing_mask.sum(),
        )
    else:
        ops_data["K_for_fixed_cost"] = ops_data["K_avg"]

    ops_data["fixed_cost"] = (
        ops_data["fom_usd_per_mw_yr"] * ops_data["K_for_fixed_cost"]
    )

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

    logger.info("Computed operations for %s asset-year rows", len(ops_data))

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
    # DISABLED because we don't apply a corporate tax rate and depreciation
    # thus does not affect tax base and can be ignored in EBITDA,
    # since it would be added back in in FCFF
    cashflow_data["FCFF"] = cashflow_data["EBITDA"] - cashflow_data["capex_total"]

    logger.info("Computed FCFF for %s asset-year rows", len(cashflow_data))

    return cashflow_data


def write_asset_earnings_series(asset_cashflows: pd.DataFrame) -> pd.DataFrame:
    """
    Node 10: Write final asset earnings series with all required columns.
    """

    logger.info("Writing final asset earnings series...")

    # Select and organize final columns
    output_columns = [
        # Keys
        "asset_id",
        "asset_name",
        "company_id",
        "company_name",
        # "scenario_provider",
        "scenario",
        "scenario_type",
        "scenario_geography",
        "sector",
        "technology",
        "year",
        "is_synthetic",
        # State
        "trajectory_type",
        "asset_trajectory",  # used in reporting
        "capacity_factor",  # used in reporting
        # "efficiency_decimal",
        # "lifetime_years",
        # "aligned",
        # "increasing",
        "alignment_type",
        # "emission_factor",
        # Flow-based CapEx information
        # "capex_indicator",
        # "capex_capacity",
        # Prices/costs
        # "power_price_excarbon_usd_per_mwh",
        # "fuel_price_usd_per_mwh_fuel",
        # "carbon_price_usd_per_tco2",
        # "fom_usd_per_mw_yr",
        # "capex_usd_per_mw",
        # "scrap_usd_per_mw",
        # Earnings series
        "Q",  # used in reporting
        "revenue",
        "var_cost",
        "fixed_cost",
        "carbon_cost_net",
        "EBITDA",
        # CapEx & decom (flow-based)
        # "growth_capex",
        # "replace_capex",
        # "decom_cost",
        "capex_total",
        # Cash
        "FCFF",
    ]

    # Select final columns
    final_output = asset_cashflows[output_columns].copy()

    # Sort by asset and year
    final_output = final_output.sort_values(
        ["company_id", "asset_id", "technology", "year"]
    ).reset_index(drop=True)

    logger.info(
        "Final earnings series: %s rows, %s columns",
        len(final_output),
        len(final_output.columns),
    )

    return final_output
