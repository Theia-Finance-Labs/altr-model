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
    - Optionally merge frozen capacity at retirement (lookup table; fixed costs use first-year capacity)
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
    #
    # Asset ID formats differ between data sources:
    #   Staggered shock: "L100000405573" (short GEM plant ID)
    #   Companies/forecasts: "INTERNAL_A_L100000405573_int_ast_power_gem_stage2_GasCap" (long internal ID)
    # We extract the GEM ID (L followed by digits) from both for matching.
    import re

    def extract_gem_id(asset_id_series):
        """Extract GEM plant ID (L followed by digits) from asset_id strings."""
        return asset_id_series.astype(str).str.extract(r"(L\d+)", expand=False)

    ef_source = assets_data[
        [
            "asset_id",
            "technology",
            "scenario_geography",
            "year",
            "emission_factor",
        ]
    ].drop_duplicates()

    # Create gem_id for matching
    ef_source["_gem_id"] = extract_gem_id(ef_source["asset_id"])
    assets["_gem_id"] = extract_gem_id(assets["asset_id"])

    # Try direct asset_id merge first (for matching formats)
    assets = assets.merge(
        ef_source[["asset_id", "technology", "scenario_geography", "year", "emission_factor"]],
        on=["asset_id", "technology", "scenario_geography", "year"],
        how="left",
    )

    # For rows still missing EF, fall back to gem_id + technology merge
    missing_ef = assets["emission_factor"].isna()
    if missing_ef.any():
        ef_by_gem = (
            ef_source.dropna(subset=["_gem_id", "emission_factor"])
            .groupby(["_gem_id", "technology", "scenario_geography", "year"])["emission_factor"]
            .mean()
            .reset_index()
            .rename(columns={"emission_factor": "_ef_gem"})
        )
        assets = assets.merge(
            ef_by_gem,
            on=["_gem_id", "technology", "scenario_geography", "year"],
            how="left",
        )
        # Fill missing EF from gem_id match
        filled = missing_ef & assets["_ef_gem"].notna()
        assets.loc[filled, "emission_factor"] = assets.loc[filled, "_ef_gem"]
        assets = assets.drop(columns=["_ef_gem"])

        logger.info(
            "Emission factor: %d/%d filled by direct merge, %d by GEM ID fallback, %d still missing",
            (~missing_ef).sum(),
            len(assets),
            filled.sum(),
            assets["emission_factor"].isna().sum(),
        )

    assets = assets.drop(columns=["_gem_id"])

    # Forward-fill emission_factor along each (asset_id, technology) across years
    if not assets.empty:
        assets = assets.sort_values(["asset_id", "technology", "year"])
        assets["emission_factor"] = assets.groupby(["asset_id", "technology"])[
            "emission_factor"
        ].ffill()

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


def compute_scenario_vre_share(scenarios_validated: pd.DataFrame) -> pd.DataFrame:
    """
    Compute VRE capacity share per (scenario_geography, year) from scenario
    pathway data. Used by dynamic_marginal_ef to model merit order evolution.

    VRE share is computed from the target scenario's capacity additions
    (cumulative from scenario_pathway, which represents installed capacity).
    """
    logger.info("Computing scenario VRE share...")

    df = scenarios_validated.copy()

    vre_techs = [
        "SolarCap - PV", "SolarCap - CSP",
        "WindCap - Onshore", "WindCap - Offshore",
    ]

    # Use scenario_pathway as the capacity/production proxy per technology
    # Group by geography and year across all scenario_types
    # Use target scenario for forward-looking VRE share
    target = df[df["scenario_type"] == "target"].copy()

    if target.empty:
        logger.warning("No target scenario data — VRE share set to 0")
        return pd.DataFrame(columns=["scenario_geography", "year", "vre_share"])

    target["is_vre"] = target["technology"].isin(vre_techs)

    group_cols = ["scenario_geography", "year"]
    total_cap = (
        target.groupby(group_cols)["scenario_pathway"]
        .sum()
        .reset_index()
        .rename(columns={"scenario_pathway": "total_pathway"})
    )
    vre_cap = (
        target[target["is_vre"]]
        .groupby(group_cols)["scenario_pathway"]
        .sum()
        .reset_index()
        .rename(columns={"scenario_pathway": "vre_pathway"})
    )

    merged = total_cap.merge(vre_cap, on=group_cols, how="left")
    merged["vre_pathway"] = merged["vre_pathway"].fillna(0.0)
    merged["vre_share"] = (
        merged["vre_pathway"] / merged["total_pathway"].clip(lower=1e-6)
    ).clip(0, 1)

    logger.info(
        "VRE share computed: %d geo-year combinations, "
        "range [%.1f%%, %.1f%%], mean %.1f%%",
        len(merged),
        merged["vre_share"].min() * 100,
        merged["vre_share"].max() * 100,
        merged["vre_share"].mean() * 100,
    )

    return merged[group_cols + ["vre_share"]]


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

    # Power price (AR6 Price|Secondary Energy|Electricity — inclusive of carbon effects)
    # Per IAMC variable template: "Prices should include the effect of carbon prices."
    # This is a general equilibrium market clearing price, not an LCOE.
    surfaces["power_price_usd_per_mwh"] = scenarios["scenario_price"]

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

    # Decommissioning cost per MW (negative sign = cost, not salvage value)
    # Estimated at 50% of original CapEx per MW. The abs() is taken downstream
    # in compute_flow_based_capex to ensure it enters capex_total as a positive outflow.
    surfaces["scrap_usd_per_mw"] = -surfaces["capex_usd_per_mw"] / 2

    logger.info("Built scenario surfaces with %s rows", len(surfaces))

    return surfaces


def apply_mcpr_adjustment(
    scenario_surfaces: pd.DataFrame,
    enable_mcpr: bool = True,
    mcpr_method: str = "marginal_technology",
    mcpr_markup_factor: float = 1.0,
    mcpr_value_factors: Dict[str, float] = None,
    mcpr_marginal_technologies: list = None,
    enable_regional_mcpr_vf: bool = False,
    mcpr_regional_value_factors: Dict[str, Dict[str, float]] = None,
    assets_data: pd.DataFrame = None,
    enable_dynamic_capture_ratios: bool = False,
    scenario_vre_share: pd.DataFrame = None,
    mcpr_floor_at_iam_price: bool = True,
    mcpr_mode: str = "auto",
    mcpr_merit_order_alpha: float = 0.006,
    mcpr_merit_order_floor: float = 0.5,
) -> pd.DataFrame:
    """
    Apply Marginal Cost Price Ratio (MCPR) adjustment to scenario surfaces.

    In wholesale electricity markets, all generators receive the same market
    clearing price, set by the marginal (most expensive dispatched) generator
    — typically natural gas or coal. IAM scenarios, however, often report
    technology-specific "prices" that approximate LCOE or cost-based metrics
    rather than uniform market clearing prices.

    This adjustment derives a reference market clearing price from the marginal
    dispatchable technology and applies it uniformly, with technology-specific
    value/capture factors for variable renewable energy (VRE) sources.

    The theoretical basis draws on:
    - Merit order pricing: Borenstein, Bushnell & Wolak (2000), "Measuring
      Market Power in the California Electricity Market," Journal of Industrial
      Economics, 48(2), pp. 197–223.
    - Value factor framework: Hirth, L. (2013), "The Market Value of Variable
      Renewables," Energy Economics, 38, pp. 218–236.
    - System LCOE: Ueckerdt, Hirth, Luderer & Edenhofer (2013), "System LCOE:
      What are the Costs of Variable Renewables?" Energy, 63, pp. 61–75.
    - Integration costs: Hirth, Ueckerdt & Edenhofer (2015), "Integration Costs
      Revisited," Renewable Energy, 74, pp. 925–939.

    Methods:
        "marginal_technology": Uses the maximum price among dispatchable
            technologies per (geography, year, scenario_type) as the reference
            market clearing price. All technologies then receive this price
            multiplied by their value factor.

    Args:
        scenario_surfaces: DataFrame with scenario surfaces including
            power_price_usd_per_mwh per technology.
        enable_mcpr: If False, return surfaces unchanged (default True).
        mcpr_method: Adjustment method. Currently "marginal_technology".
        mcpr_markup_factor: Additional markup over marginal cost to capture
            market power effects (Lerner index). Default 1.0 (no additional
            markup). A value of 1.10 implies a 10% markup, consistent with
            competitive electricity markets (Lerner index L ≈ 0.09).
        mcpr_value_factors: Dict mapping technology names to value/capture
            factors. VRE technologies receive less than the full market price
            due to temporal correlation effects (Hirth, 2013). Defaults are
            calibrated to moderate VRE penetration (10–20%):
            - Wind Onshore: 0.90 (Hirth 2013, Table 1, ~15% penetration)
            - Wind Offshore: 0.92 (slightly higher due to better load profile)
            - Solar PV: 0.85 (Hirth 2013, Table 1, ~10% penetration)
            - Solar CSP: 0.95 (dispatchable with storage)
            - Dispatchable technologies: 1.0
        mcpr_marginal_technologies: List of technology name prefixes used to
            determine the marginal price. Defaults to fossil fuel technologies.

    Returns:
        DataFrame with adjusted power_price_usd_per_mwh.
    """
    if not enable_mcpr:
        logger.info("MCPR adjustment DISABLED — returning original prices")
        # Still need marginal_emission_factor for differential carbon cost
        scenario_surfaces["marginal_emission_factor"] = 0.0
        return scenario_surfaces

    # ── MCPR v2: Mode selection ──────────────────────────────────────────
    if mcpr_mode == "auto":
        target_rows = scenario_surfaces[
            scenario_surfaces["scenario_type"] == "target"
        ] if "scenario_type" in scenario_surfaces.columns else scenario_surfaces
        cp_col = "carbon_price_usd_per_tco2"
        if cp_col in target_rows.columns:
            cp_coverage = (target_rows[cp_col].fillna(0) > 0).mean()
        else:
            cp_coverage = 0.0
        # OP9 (2026-08-20): auto NEVER resolves to merit_order_decline. The
        # single-vintage rebuild (30/30 runs) showed merit reverses the stress
        # test direction (carbon expected-negative 43.9% vs 72.6% for
        # carbon_explicit); the valuation suite does not rescue it (+1.0pp vs
        # MCPR v1's +19.5pp interaction). Merit remains available only as an
        # explicit, paper-track setting.
        resolved_mode = "carbon_explicit"
        if cp_coverage > 0.5:
            logger.info(
                "MCPR mode=auto: carbon price coverage=%.1f%% → resolved to 'carbon_explicit'",
                cp_coverage * 100,
            )
        else:
            logger.warning(
                "MCPR mode=auto: carbon price coverage=%.1f%% is LOW — still "
                "resolving to 'carbon_explicit' (merit_order_decline is "
                "paper-track only, OP9). Consider a shadow carbon price for "
                "this scenario.",
                cp_coverage * 100,
            )
    else:
        resolved_mode = mcpr_mode
        logger.info("MCPR mode='%s' (explicitly set)", resolved_mode)

    # carbon_explicit mode requires full_ef carbon cost method to work correctly.
    # The MCPR node cannot enforce this (carbon_cost_method lives in compute_ops_block),
    # but we can warn if the pairing is likely wrong.
    if resolved_mode == "carbon_explicit":
        logger.info(
            "MCPR carbon_explicit mode: ensure carbon_cost_method='full_ef' in "
            "earnings config for correct asymmetric fossil penalty."
        )

    logger.info(
        "Applying MCPR adjustment (method=%s, markup=%.2f, mode=%s)",
        mcpr_method,
        mcpr_markup_factor,
        resolved_mode,
    )

    surfaces = scenario_surfaces.copy()

    # Propagate technology-level emission factors from asset data if available.
    # Scenario surfaces don't carry emission_factor (it's an asset-level attribute),
    # but we need it to compute the marginal emission factor for differential
    # carbon cost. Derive capacity-weighted mean EF per technology from assets.
    if (
        "emission_factor" not in surfaces.columns
        and assets_data is not None
        and "emission_factor" in assets_data.columns
    ):
        ef_cols = ["technology", "emission_factor"]
        weight_col = "asset_activity" if "asset_activity" in assets_data.columns else None
        ef_source = assets_data[assets_data["emission_factor"].notna()].copy()
        if not ef_source.empty:
            if weight_col and weight_col in ef_source.columns:
                # Capacity-weighted mean EF per technology
                ef_source["_w"] = ef_source[weight_col].clip(lower=0)
                parts = []
                for tech, g in ef_source.groupby("technology"):
                    w = g["_w"]
                    ef_val = (
                        np.average(g["emission_factor"], weights=w)
                        if w.sum() > 0
                        else g["emission_factor"].mean()
                    )
                    parts.append({"technology": tech, "emission_factor": ef_val})
                tech_ef = pd.DataFrame(parts)
            else:
                tech_ef = (
                    ef_source.groupby("technology")["emission_factor"]
                    .mean()
                    .reset_index()
                )
            surfaces = surfaces.merge(tech_ef, on="technology", how="left")
            surfaces["emission_factor"] = surfaces["emission_factor"].fillna(0.0)
            logger.info(
                "Propagated emission_factor to scenario surfaces for %s technologies: %s",
                len(tech_ef),
                dict(zip(tech_ef["technology"], tech_ef["emission_factor"].round(4))),
            )

    # Default marginal technologies (dispatchable fossil fuels)
    if mcpr_marginal_technologies is None:
        mcpr_marginal_technologies = [
            "GasCap",
            "CoalCap",
            "OilCap",
            "BiomassCap",
        ]

    # Default value factors from Hirth (2013), Energy Economics 38:218–236
    # Table 1, "Review" column, moderate penetration levels (10-20%)
    if mcpr_value_factors is None:
        mcpr_value_factors = {
            # VRE technologies — value factors < 1.0
            "WindCap - Onshore": 0.90,   # Hirth (2013) Table 1: ~0.90 at 15% penetration
            "WindCap - Offshore": 0.92,  # Slightly higher than onshore (less correlated)
            "SolarCap - PV": 0.85,       # Hirth (2013) Table 1: ~0.85 at 10% penetration
            "SolarCap - CSP": 0.95,      # Dispatchable with thermal storage
            # Dispatchable technologies — full market price
            "GasCap": 1.0,
            "GasCap_w/o CCS": 1.0,
            "GasCap_w/ CCS": 1.0,
            "CoalCap": 1.0,
            "CoalCap_w/o CCS": 1.0,
            "CoalCap_w/ CCS": 1.0,
            "OilCap": 1.0,
            "OilCap_w/o CCS": 1.0,
            "OilCap_w/ CCS": 1.0,
            "NuclearCap": 1.0,
            "HydroCap": 1.0,
            "GeothermalCap": 1.0,
            "BiomassCap": 1.0,
            "BiomassCap_w/o CCS": 1.0,
            "BiomassCap_w/ CCS": 1.0,
        }

    # Store original prices for logging
    original_prices = surfaces["power_price_usd_per_mwh"].copy()

    if mcpr_method == "marginal_technology":
        # Identify marginal technologies
        is_marginal = surfaces["technology"].apply(
            lambda t: any(t.startswith(m) for m in mcpr_marginal_technologies)
        )

        # Compute reference market clearing price per (geography, year, scenario_type)
        # as the maximum price among dispatchable/marginal technologies
        group_cols = ["scenario_geography", "year", "scenario_type"]
        marginal_prices = (
            surfaces.loc[is_marginal]
            .groupby(group_cols)["power_price_usd_per_mwh"]
            .max()
            .reset_index()
            .rename(columns={"power_price_usd_per_mwh": "mcpr_reference_price"})
        )

        # Apply markup factor (Lerner index)
        marginal_prices["mcpr_reference_price"] *= mcpr_markup_factor

        logger.info(
            "MCPR reference prices computed: mean=%.2f, min=%.2f, max=%.2f $/MWh",
            marginal_prices["mcpr_reference_price"].mean(),
            marginal_prices["mcpr_reference_price"].min(),
            marginal_prices["mcpr_reference_price"].max(),
        )

        # Merge reference price onto all technologies
        surfaces = surfaces.merge(marginal_prices, on=group_cols, how="left")

        # Apply value factors per technology
        surfaces["mcpr_value_factor"] = surfaces["technology"].map(mcpr_value_factors)

        # Dynamic capture ratios (Hirth 2013): VRE value factors decline with
        # penetration. This is a universal market mechanism — as VRE share grows,
        # solar/wind depress prices during their production hours, reducing their
        # average capture price relative to the clearing price.
        #
        # Applied as a STANDARDIZATION LAYER across all IAMs:
        # - WITCH (uniform prices): capture ratios add missing differentiation
        # - AIM/CGE (differentiated prices): capture ratios normalize to market-consistent values
        # This ensures cross-IAM comparability.
        #
        # Empirical relationships from Hirth (2013) Table 1 and Halttunen et al. (2022):
        #   Solar PV: VF = max(1.10 - 1.5 × vre_share, 0.40)
        #   Wind Onshore: VF = max(1.05 - 0.8 × vre_share, 0.50)
        #   Wind Offshore: VF = max(1.07 - 0.7 × vre_share, 0.55)  (less correlated)
        #   Solar CSP: VF = max(1.05 - 0.3 × vre_share, 0.80)  (dispatchable with storage)
        #   Dispatchable: VF = 1.0 (sets or follows clearing price)
        if enable_dynamic_capture_ratios:
            # Use pre-computed VRE share from scenario pathways (compute_scenario_vre_share)
            if scenario_vre_share is not None and not scenario_vre_share.empty:
                merge_cols = ["scenario_geography", "year"]
                surfaces = surfaces.merge(
                    scenario_vre_share[merge_cols + ["vre_share"]],
                    on=merge_cols,
                    how="left",
                )
                surfaces["vre_share"] = surfaces["vre_share"].fillna(0.0).clip(0, 1)
                logger.info(
                    "Dynamic capture ratios: using pre-computed VRE share (range %.1f%%–%.1f%%)",
                    surfaces["vre_share"].min() * 100,
                    surfaces["vre_share"].max() * 100,
                )
            else:
                logger.warning(
                    "Dynamic capture ratios enabled but scenario_vre_share not provided. "
                    "Falling back to static VFs."
                )
                enable_dynamic_capture_ratios = False

            # Apply Hirth empirical relationships
            def hirth_vf(tech, vre_s):
                if "SolarCap - PV" in tech:
                    return max(1.10 - 1.5 * vre_s, 0.40)
                elif "WindCap - Onshore" in tech:
                    return max(1.05 - 0.8 * vre_s, 0.50)
                elif "WindCap - Offshore" in tech:
                    return max(1.07 - 0.7 * vre_s, 0.55)
                elif "SolarCap - CSP" in tech:
                    return max(1.05 - 0.3 * vre_s, 0.80)
                else:
                    return 1.0  # dispatchable: full clearing price

            surfaces["mcpr_value_factor"] = surfaces.apply(
                lambda row: hirth_vf(row["technology"], row["vre_share"]),
                axis=1,
            )

            logger.info(
                "Dynamic capture ratios (Hirth 2013) applied: VRE share range [%.1f%%, %.1f%%]",
                surfaces["vre_share"].min() * 100,
                surfaces["vre_share"].max() * 100,
            )
            # Log sample VFs at different VRE shares
            for tech in ["SolarCap - PV", "WindCap - Onshore"]:
                tech_data = surfaces[surfaces["technology"] == tech]
                if len(tech_data) > 0:
                    logger.info(
                        "  %s: VF range [%.2f, %.2f] (static was %.2f)",
                        tech,
                        tech_data["mcpr_value_factor"].min(),
                        tech_data["mcpr_value_factor"].max(),
                        mcpr_value_factors.get(tech, 1.0),
                    )

            surfaces = surfaces.drop(columns=["_is_vre_tech", "vre_share"], errors="ignore")
        else:
            surfaces = surfaces.drop(columns=["_is_vre_tech"], errors="ignore")

        # Override with region-specific value factors if enabled (only when NOT using dynamic)
        # Regional VFs reflect local VRE penetration levels and market structures
        # (Hirth 2013; Halttunen et al. 2022, Nature Energy)
        if enable_regional_mcpr_vf and mcpr_regional_value_factors and not enable_dynamic_capture_ratios:
            regional_overrides = 0
            for geo, tech_vf_map in mcpr_regional_value_factors.items():
                for tech, vf in tech_vf_map.items():
                    mask = (surfaces["scenario_geography"] == geo) & (
                        surfaces["technology"] == tech
                    )
                    if mask.any():
                        surfaces.loc[mask, "mcpr_value_factor"] = vf
                        regional_overrides += mask.sum()
            logger.info(
                "MCPR regional VF overrides applied to %s rows across %s geographies",
                regional_overrides,
                len(mcpr_regional_value_factors),
            )

        # For any unmapped technology, default to 1.0
        unmapped = surfaces["mcpr_value_factor"].isna()
        if unmapped.any():
            unmapped_techs = surfaces.loc[unmapped, "technology"].unique()
            logger.warning(
                "MCPR: No value factor for technologies: %s — defaulting to 1.0",
                list(unmapped_techs),
            )
            surfaces.loc[unmapped, "mcpr_value_factor"] = 1.0

        # ── MCPR v2: Merit order decline (Cevik & Ninomiya 2022) ─────────
        # Apply BEFORE value factors so the clearing price itself falls.
        # This ensures: (1) the floor at IAM price doesn't negate the decline,
        # (2) all techs see a lower clearing price (fossils included, correctly),
        # (3) VRE value factors compound on top of the already-declined price.
        if resolved_mode == "merit_order_decline" and scenario_vre_share is not None:
            merge_cols = ["scenario_geography", "year"]
            if "vre_share" not in surfaces.columns:
                surfaces = surfaces.merge(
                    scenario_vre_share[merge_cols + ["vre_share"]],
                    on=merge_cols,
                    how="left",
                )
                surfaces["vre_share"] = surfaces["vre_share"].fillna(0.0)

            # VRE share at the earliest year per geography × scenario_type.
            # Use actual minimum-year VRE share (robust to row ordering and
            # mixed baseline/target rows).
            group_cols_vre = ["scenario_geography", "scenario_type"] if "scenario_type" in surfaces.columns else ["scenario_geography"]
            vre_baseline = (
                surfaces
                .loc[surfaces.groupby(group_cols_vre)["year"].idxmin()]
                .set_index(group_cols_vre)["vre_share"]
                .rename("_vre_baseline")
            )
            surfaces = surfaces.join(vre_baseline, on=group_cols_vre)
            delta_vre = (surfaces["vre_share"] - surfaces["_vre_baseline"]).clip(lower=0.0)
            surfaces = surfaces.drop(columns=["_vre_baseline"])

            # Decline factor: (1 - alpha * delta_vre_pct)
            # delta_vre is fraction [0,1]; alpha is per percentage point, so * 100
            decline_factor = (1 - mcpr_merit_order_alpha * delta_vre * 100).clip(
                lower=mcpr_merit_order_floor
            )

            # Apply decline to the REFERENCE clearing price, not the adjusted price.
            surfaces["mcpr_reference_price"] = (
                surfaces["mcpr_reference_price"] * decline_factor
            )

            logger.info(
                "Merit order decline applied to clearing price: alpha=%.4f, floor=%.2f, "
                "VRE delta range [%.1f%%, %.1f%%], price decline range [%.1f%%, %.1f%%]",
                mcpr_merit_order_alpha,
                mcpr_merit_order_floor,
                delta_vre.min() * 100,
                delta_vre.max() * 100,
                (1 - decline_factor.max()) * 100,
                (1 - decline_factor.min()) * 100,
            )

            surfaces = surfaces.drop(columns=["vre_share"], errors="ignore")

        # Calculate adjusted price: (possibly declined) reference_price × value_factor
        surfaces["mcpr_adjusted_price"] = (
            surfaces["mcpr_reference_price"] * surfaces["mcpr_value_factor"]
        )

        # Replace the power price with adjusted price.
        has_reference = surfaces["mcpr_reference_price"].notna()
        if mcpr_floor_at_iam_price:
            # Floor at original IAM price — MCPR only LIFTS renewable prices
            # toward market clearing, never penalizes below IAM-reported level.
            original_price = surfaces.loc[has_reference, "power_price_usd_per_mwh"]
            surfaces.loc[has_reference, "power_price_usd_per_mwh"] = np.maximum(
                surfaces.loc[has_reference, "mcpr_adjusted_price"],
                original_price,
            )
        else:
            # Original behavior: replace with adjusted price (can lower VRE prices)
            surfaces.loc[has_reference, "power_price_usd_per_mwh"] = (
                surfaces.loc[has_reference, "mcpr_adjusted_price"]
            )

        # Log adjustment summary by technology
        adjustment_summary = surfaces.groupby("technology").agg(
            original_mean=("mcpr_reference_price", "mean"),  # reference is from marginal
            adjusted_mean=("power_price_usd_per_mwh", "mean"),
            value_factor=("mcpr_value_factor", "first"),
        )
        logger.info("MCPR price adjustment summary by technology:")
        for tech, row in adjustment_summary.iterrows():
            logger.info(
                "  %s: ref=%.2f → adjusted=%.2f (VF=%.2f)",
                tech,
                row["original_mean"],
                row["adjusted_mean"],
                row["value_factor"],
            )

        # Compute marginal emission factor per (geography, year, scenario_type)
        # This is the emission factor of the technology that sets the clearing price.
        # Needed for differential carbon cost: technologies pay carbon cost only on
        # emissions ABOVE what's already embedded in the AR6 market clearing price.
        # The AR6 Price|Secondary Energy|Electricity includes carbon cost effects
        # (IAMC variable template: "Prices should include the effect of carbon prices").
        if "emission_factor" in surfaces.columns:
            marginal_ef = (
                surfaces.loc[is_marginal]
                .sort_values(group_cols + ["power_price_usd_per_mwh", "technology"])
                .groupby(group_cols)
                .last()  # last = highest price = marginal technology
                .reset_index()[group_cols + ["emission_factor"]]
                .rename(columns={"emission_factor": "marginal_emission_factor"})
            )
            surfaces = surfaces.merge(marginal_ef, on=group_cols, how="left")
            surfaces["marginal_emission_factor"] = surfaces["marginal_emission_factor"].fillna(0.0)
        else:
            # emission_factor is not on scenario surfaces (it lives on asset data).
            # Set marginal_emission_factor to 0 — this means the differential carbon
            # cost will use the full emission factor (conservative, slight overcount
            # of ~marginal_EF worth of carbon cost for high-emission technologies).
            logger.warning(
                "emission_factor not available in scenario surfaces. "
                "marginal_emission_factor set to 0 (full carbon cost applied)."
            )
            surfaces["marginal_emission_factor"] = 0.0

        logger.info(
            "Marginal emission factor: mean=%.4f tCO2/MWh",
            surfaces["marginal_emission_factor"].mean(),
        )

        # Clean up temporary columns.
        # emission_factor was added temporarily for marginal EF computation —
        # drop it so it doesn't collide with asset-level EF in assemble_asset_panel.
        surfaces = surfaces.drop(
            columns=[
                "mcpr_value_factor",
                "mcpr_adjusted_price",
                "mcpr_reference_price",
                "emission_factor",
            ],
            errors="ignore",
        )
    else:
        raise ValueError(f"Unknown MCPR method: {mcpr_method}")

    # Log overall price change
    new_prices = surfaces["power_price_usd_per_mwh"]
    logger.info(
        "MCPR adjustment complete: original mean=%.2f → adjusted mean=%.2f $/MWh",
        original_prices.mean(),
        new_prices.mean(),
    )

    return surfaces


def assemble_asset_panel(
    assets_adjusted: pd.DataFrame,
    scenario_surfaces: pd.DataFrame,
    shock_year: int,
    alignment_year: int = None,
    price_ramp: bool = False,
) -> pd.DataFrame:
    """
    Node 4: Build full asset-year panel including synthetic assets.

    If price_ramp=True and alignment_year is provided, scenario surfaces
    are linearly blended from baseline to target over the transition window
    [shock_year, alignment_year) instead of hard-switching at shock_year.
    This eliminates the near-term price windfall (RC4) where target prices
    are 30-50% higher than baseline at the shock year.
    """

    logger.info("Assembling full asset panel...")

    # Start with adjusted original assets
    panel = assets_adjusted.copy()

    if price_ramp and alignment_year is not None and alignment_year > shock_year:
        logger.info(
            "Price ramp ENABLED: blending baseline->target over [%d, %d]",
            shock_year,
            alignment_year,
        )
        # Columns to blend (all numeric scenario surface values)
        merge_keys = [
            "scenario_geography", "sector", "technology", "year",
        ]
        baseline_surf = scenario_surfaces.loc[
            scenario_surfaces["scenario_type"] == "baseline"
        ].copy()
        target_surf = scenario_surfaces.loc[
            scenario_surfaces["scenario_type"] == "target"
        ].copy()

        # Identify numeric columns to blend
        non_blend_cols = merge_keys + ["scenario", "scenario_type"]
        blend_cols = [
            c for c in baseline_surf.columns
            if c not in non_blend_cols and baseline_surf[c].dtype in ("float64", "float32", "int64")
        ]

        # Merge baseline and target on keys
        blended = baseline_surf[merge_keys + blend_cols].merge(
            target_surf[merge_keys + blend_cols],
            on=merge_keys,
            suffixes=("_base", "_tgt"),
            how="inner",
        )

        # Compute blend weight: 0 at shock_year, 1 at alignment_year
        ramp_duration = alignment_year - shock_year
        blended["_blend"] = (
            (blended["year"] - shock_year) / ramp_duration
        ).clip(0, 1)

        # Pre-shock: use baseline (blend=0). Transition: interpolate. Post-alignment: use target (blend=1).
        blended.loc[blended["year"] < shock_year, "_blend"] = 0.0

        # Blend each column
        for col in blend_cols:
            base_col = f"{col}_base"
            tgt_col = f"{col}_tgt"
            if base_col in blended.columns and tgt_col in blended.columns:
                blended[col] = (
                    blended[base_col] * (1 - blended["_blend"])
                    + blended[tgt_col] * blended["_blend"]
                )

        # Clean up
        drop_cols = (
            [f"{c}_base" for c in blend_cols if f"{c}_base" in blended.columns]
            + [f"{c}_tgt" for c in blend_cols if f"{c}_tgt" in blended.columns]
            + ["_blend"]
        )
        blended = blended.drop(columns=drop_cols)

        # Restore non-blend columns from baseline
        for col in ["scenario", "scenario_type"]:
            if col in baseline_surf.columns:
                mapping = baseline_surf[merge_keys + [col]].drop_duplicates()
                blended = blended.merge(mapping, on=merge_keys, how="left")

        mixed_scenario_surfaces = (
            blended
            .reset_index(drop=True)
            .sort_values(["scenario_geography", "sector", "technology", "year"])
            .assign(trajectory_type="latesudden")
        )
    else:
        # Original hard-switch behavior
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
    if "scenario_geography" not in data.columns:
        raise ValueError("compute_capacity_flows expects 'scenario_geography' column")
    data = data.sort_values(
        [
            "trajectory_type",
            "company_id",
            "asset_id",
            "technology",
            "scenario_geography",
            "year",
        ]
    ).reset_index(drop=True)

    # Use asset_trajectory (melted capacity)
    if "asset_trajectory" not in data.columns:
        raise ValueError("compute_capacity_flows expects 'asset_trajectory' column")

    # Calculate capacity changes vectorized, per trajectory_type when present.
    # scenario_geography is part of the key: without it, shift(1) carries the last
    # row of one geography into the first row of the next for a multi-geography asset.
    group_keys = [
        "trajectory_type",
        "company_id",
        "asset_id",
        "technology",
        "scenario_geography",
    ]
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

    # 2. Retirement flows (negative capacity changes on REAL assets only).
    # Synthetic assets are accounting constructs for incremental shock growth —
    # their capacity decline is not a physical decommissioning event.
    is_real = ~data.get("is_synthetic", pd.Series(False, index=data.index))
    retirement_mask = (data["capacity_change"] < 0) & is_real
    if retirement_mask.any():
        retirement_data = data[retirement_mask].copy()
        retirement_data["capex_indicator"] = "retired_max_cap"
        retirement_data["capex_capacity"] = retirement_data["capacity_change"].abs()
        flow_records.append(retirement_data)

    # 3. Replacement flows (2% of existing installed capacity annually for real assets)
    # Routine capital maintenance/refurbishment (1-3% of replacement cost per year
    # is the standard utility benchmark — EPRI, Lazard LCOE methodology).
    # Excludes retiring assets (already charged decom costs).
    replacement_mask = is_real & ~retirement_mask
    if replacement_mask.any():
        replacement_data = data[replacement_mask].copy()
        replacement_data["capex_indicator"] = "roll_over_cap"
        replacement_data["capex_capacity"] = replacement_data["asset_trajectory"] * 0.02
        flow_records.append(replacement_data)

    # 4. No-flow records (synthetic assets with no capacity events need placeholder records)
    has_flow = new_buildout_mask | retirement_mask | replacement_mask
    no_flow_mask = ~has_flow
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

    # NOTE: Flow identity validation disabled because it's based on flawed assumptions:
    # - Roll-over flows are 2% of installed capacity annually (EPRI/Lazard benchmark)
    # - The validation expects flows to fully explain capacity trajectories, which they don't by design
    # - The flows themselves are correct and properly used in CapEx calculations
    # validate_capacity_flow_identity(capex_data)

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
    # scrap_usd_per_mw is negative (= -capex/2), representing the cost to decommission.
    # We take abs() so that decom_cost is POSITIVE in capex_total — a real cash outflow
    # that reduces FCFF, reflecting demolition, remediation, and site restoration costs.
    if include_decom_costs:
        retired_mask = capex_data["capex_indicator"] == "retired_max_cap"
        capex_data["decom_cost"] = np.where(
            retired_mask,
            capex_data["scrap_usd_per_mw"].abs() * capex_data["capex_capacity"],
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
    apply_continued_om_baseline: bool = False,
    apply_continued_om_shock: bool = True,
    dynamic_marginal_ef: bool = False,
    scenario_vre_share: pd.DataFrame = None,
    carbon_cost_method: str = "differential_ef",
) -> pd.DataFrame:
    """
    Node 8: Compute operations block (production, costs, revenue, EBITDA).

    EBITDA_t = Revenue_t − FuelCost_t − FixedO&M_t − CarbonCost_net_t
    Note: No depreciation is considered here. EBITDA is a cash operating measure.
    RFC: Corporate tax and depreciation tax shield are currently disabled; see compute_fcff().

    Args:
        asset_capex_block: Asset data with capacity and cost information
        market_passthrough: Fraction of carbon price passed through to market (default 0.5)
        apply_continued_om_baseline: If True, apply continued O&M costs (frozen capacity) to baseline trajectories
        apply_continued_om_shock: If True, apply continued O&M costs (frozen capacity) to shock trajectories
        dynamic_marginal_ef: If True, make marginal_emission_factor decline over
            time proportional to VRE capacity share. This models the merit order
            evolution: as renewables displace fossils from the marginal position,
            the carbon rent that gas/coal enjoy disappears, and their differential
            carbon cost rises. When False, uses the static marginal_EF from MCPR.
        carbon_cost_method: How to compute carbon cost. Options:
            - "differential_ef" (default): carbon cost = Q × cp × max(EF - marginal_EF, 0).
              Assumes IAM electricity prices embed marginal generator's carbon cost.
              Appropriate for IAMs where prices fully reflect carbon (e.g., AIM/CGE).
            - "full_ef": carbon cost = Q × cp × EF.
              Uses the technology's full emission factor. Appropriate for IAMs where
              prices minimally embed carbon cost (e.g., WITCH, where C1→C7 price
              spread is only $9/MWh despite $722/tCO2 carbon price difference).
    """

    logger.info("Computing operations block...")

    if apply_continued_om_baseline or apply_continued_om_shock:
        logger.info(
            "Continued O&M costs (frozen capacity) configuration: "
            "baseline=%s, shock=%s",
            apply_continued_om_baseline,
            apply_continued_om_shock,
        )
    else:
        logger.info(
            "Using actual asset capacity for fixed cost calculations (no frozen capacity)"
        )

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
    # Apply continued O&M costs (frozen capacity) based on baseline/shock configuration
    if apply_continued_om_baseline or apply_continued_om_shock:
        logger.info(
            "Using constant initial capacity (from year 1) for fixed cost calculations "
            "based on trajectory type configuration"
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
        # 1. If technology is decreasing, use initial_capacity (based on trajectory type flags)
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

        # Determine which trajectories should have frozen capacity based on parameters
        is_baseline = ops_data["trajectory_type"] == "baseline"
        is_shock = ops_data["trajectory_type"] != "baseline"

        # Apply frozen capacity based on trajectory type and configuration
        apply_to_trajectory = (is_baseline & apply_continued_om_baseline) | (
            is_shock & apply_continued_om_shock
        )

        # Final mask: decreasing technologies AND configured trajectory types
        decreasing_mask = is_decreasing & apply_to_trajectory

        ops_data["K_for_fixed_cost"] = np.where(
            decreasing_mask, ops_data["initial_capacity"], ops_data["K_avg"]
        )

        baseline_count = (
            is_decreasing & is_baseline & apply_continued_om_baseline
        ).sum()
        shock_count = (is_decreasing & is_shock & apply_continued_om_shock).sum()

        logger.info(
            "Applied constant initial capacity to %s asset-year rows total: "
            "%s baseline rows, %s shock rows (decreasing techs only). "
            "Increasing techs use actual capacity.",
            decreasing_mask.sum(),
            baseline_count,
            shock_count,
        )
    else:
        ops_data["K_for_fixed_cost"] = ops_data["K_avg"]

    ops_data["fixed_cost"] = (
        ops_data["fom_usd_per_mw_yr"] * ops_data["K_for_fixed_cost"]
    )

    # Differential carbon cost
    # AR6 scenario prices (Price|Secondary Energy|Electricity) INCLUDE the effect
    # of carbon pricing via general equilibrium / merit order (per IAMC template:
    # "Prices should include the effect of carbon prices").
    # Carbon cost method determines how emission factors are applied:
    #
    # "differential_ef" (default): Uses excess EF above the marginal generator.
    #   Rationale: IAM prices embed marginal generator's carbon cost, so only the
    #   EXCESS is an additional cost. Avoids double-counting for IAMs like AIM/CGE
    #   where C1→C7 price spread ($64/MWh) reflects full carbon embedding.
    #
    # "full_ef": Uses each technology's full emission factor.
    #   Rationale: For IAMs like WITCH where prices minimally embed carbon (C1→C7
    #   spread is only $9/MWh despite $722/tCO2 difference), there is effectively
    #   nothing to double-count. Using full EF correctly penalises all fossil
    #   technologies including gas (which otherwise pays ~$0 as marginal generator).
    if carbon_cost_method == "full_ef":
        marginal_ef_static = pd.Series(0.0, index=ops_data.index)
        logger.info(
            "Carbon cost method: full_ef — using full emission factor "
            "(marginal_EF set to 0). All fossil technologies pay full carbon cost."
        )
    else:
        marginal_ef_static = ops_data.get(
            "marginal_emission_factor", pd.Series(0.0, index=ops_data.index)
        )
        marginal_ef_static = pd.to_numeric(marginal_ef_static, errors="coerce").fillna(0.0)
        logger.info(
            "Carbon cost method: differential_ef — using excess EF above "
            "marginal generator (mean marginal_EF=%.4f).",
            marginal_ef_static.mean(),
        )

    if dynamic_marginal_ef:
        # NOTE (2026-08-20): this scaling is inert under carbon_cost_method=
        # 'full_ef' (marginal_ef_static is forced to 0) and when MCPR is
        # disabled (the surface carries marginal_emission_factor=0). It is
        # live only under {enable_mcpr: True, carbon_cost_method:
        # 'differential_ef'} — a combination no production or study config
        # uses. Kept for the differential-EF path; excluded from the external
        # update list for that reason.
        # Dynamic marginal_EF: as VRE capacity share grows, the marginal generator
        # shifts from fossil (high EF) toward clean tech (low EF). We model this as:
        #   marginal_ef(t) = marginal_ef_static * (1 - vre_share(t))^2
        #
        # Quadratic decay reflects non-linear merit order: at low VRE only coal/oil
        # displaced (marginal EF stays high); at high VRE gas itself displaced.
        # At 0% VRE: marginal_ef = static value (oil/gas sets the price)
        # At ~34% VRE: gas starts paying differential carbon cost
        # At 100% VRE: marginal_ef = 0 (clean tech is marginal, full carbon cost applies)
        #
        # VRE share is computed from SCENARIO data (which has all technologies)
        # rather than from the asset panel (which may only contain carbontech assets).

        if scenario_vre_share is not None and not scenario_vre_share.empty:
            # Use pre-computed VRE share from scenario pathways
            merge_cols = ["scenario_geography", "year"]
            ops_data = ops_data.merge(
                scenario_vre_share[merge_cols + ["vre_share"]],
                on=merge_cols,
                how="left",
            )
            ops_data["vre_share"] = ops_data["vre_share"].fillna(0.0)
        else:
            # Fallback: compute from asset panel (may underestimate VRE if greentech
            # assets are sparse in the staggered shock data)
            logger.warning(
                "scenario_vre_share not provided — computing VRE share from asset panel. "
                "This may underestimate VRE if greentech is sparse in the data."
            )
            vre_techs = [
                "SolarCap - PV", "SolarCap - CSP",
                "WindCap - Onshore", "WindCap - Offshore",
            ]
            group_cols = ["trajectory_type", "scenario_geography", "year"]
            ops_data["_is_vre"] = ops_data["technology"].isin(vre_techs)
            cap_by_group = (
                ops_data.groupby(group_cols)
                .agg(
                    total_cap=("K_avg", "sum"),
                    vre_cap=("K_avg", lambda x: x[ops_data.loc[x.index, "_is_vre"]].sum()),
                )
                .reset_index()
            )
            cap_by_group["vre_share"] = (
                cap_by_group["vre_cap"] / cap_by_group["total_cap"].clip(lower=1e-6)
            ).clip(0, 1)
            ops_data = ops_data.merge(
                cap_by_group[group_cols + ["vre_share"]], on=group_cols, how="left"
            )
            ops_data["vre_share"] = ops_data["vre_share"].fillna(0.0)
            ops_data = ops_data.drop(columns=["_is_vre"])

        # Dynamic marginal EF declines with VRE share (convex/quadratic decay).
        # Linear (1-x) is too gentle: gas EF=0.37 only starts paying at 56% VRE.
        # Quadratic (1-x)^2 reflects the non-linear merit order transition:
        # at low VRE, only coal/oil are displaced (marginal EF stays high);
        # at high VRE, gas itself is displaced (marginal EF drops rapidly).
        # With (1-x)^2: gas starts paying at ~34% VRE instead of 56%.
        marginal_ef = marginal_ef_static * (1 - ops_data["vre_share"]) ** 2

        logger.info(
            "Dynamic marginal EF enabled: VRE share range [%.1f%%, %.1f%%], "
            "marginal EF range [%.4f, %.4f] (static was %.4f)",
            ops_data["vre_share"].min() * 100,
            ops_data["vre_share"].max() * 100,
            marginal_ef.min(),
            marginal_ef.max(),
            marginal_ef_static.mean(),
        )

        # Clean up
        ops_data = ops_data.drop(columns=["vre_share"])
    else:
        marginal_ef = marginal_ef_static

    excess_ef = (ops_data["emission_factor"] - marginal_ef).clip(lower=0.0)

    ops_data["carbon_cost_net"] = (
        ops_data["Q"]
        * ops_data["carbon_price_usd_per_tco2"]
        * excess_ef
        * (1 - market_passthrough)
    )

    logger.info(
        "Differential carbon cost: %s asset-year rows with non-zero cost, "
        "mean excess EF=%.4f tCO2/MWh",
        (ops_data["carbon_cost_net"] > 0).sum(),
        excess_ef.mean(),
    )

    # Revenue (AR6 price inclusive of carbon effects on marginal generator)
    ops_data["revenue"] = ops_data["Q"] * ops_data["power_price_usd_per_mwh"]

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
        # "power_price_usd_per_mwh",
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
