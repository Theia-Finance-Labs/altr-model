"""Scenario price surfaces and the MCPR adjustment (earnings model, stage 6).

Turns validated scenario pathways into per-(geography, sector, technology,
year) surfaces, then rewrites the power price towards a market-clearing
price set by the marginal dispatchable technology. See ALTR Documentation,
MCPR section, and the references in ``apply_mcpr_adjustment``.
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


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


def apply_mcpr_adjustment(  # noqa: PLR0912, PLR0913, PLR0915, PLR0917
    scenario_surfaces: pd.DataFrame,
    enable_mcpr: bool = True,
    mcpr_method: str = "marginal_technology",
    mcpr_markup_factor: float = 1.0,
    mcpr_value_factors: dict[str, float] = None,
    mcpr_marginal_technologies: list = None,
    enable_regional_mcpr_vf: bool = False,
    mcpr_regional_value_factors: dict[str, dict[str, float]] = None,
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
        if cp_coverage > 0.5:  # noqa: PLR2004 — coverage majority threshold
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
