"""Operating block, free cash flow and the final earnings series (stage 6).

Computes production, fuel, fixed O&M and net carbon cost into EBITDA,
subtracts CapEx to obtain FCFF, and writes the asset-level earnings series
consumed by the valuation model. See ALTR Documentation, earnings and
carbon-cost sections.
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Constants
HOURS_PER_YEAR = 8760


def compute_ops_block(  # noqa: PLR0913, PLR0915, PLR0917
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
