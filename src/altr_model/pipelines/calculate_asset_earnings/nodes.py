"""Financial calculations over canonical, pre-allocated asset trajectories."""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Constants
HOURS_PER_YEAR = 8760

# Annual capital maintenance as a fraction of installed capacity. 1-3% of
# replacement cost per year is the standard utility benchmark (EPRI, Lazard
# LCOE methodology); 2% is the value the handover branch charged. Only a
# fallback for direct callers — the pipeline reads params:replacement_capex_rate.
REPLACEMENT_CAPEX_RATE = 0.02

# A physical asset can legitimately appear once per owner. Every time-series
# operation must therefore use the complete canonical asset-series grain, not
# ``asset_id`` alone.
ASSET_SERIES_KEYS = [
    "company_id",
    "asset_id",
    "scenario_geography",
    "sector",
    "technology",
    "trajectory_type",
]

# State of the asset at the last forecast year, which the valuation stage prices
# an exit off. These are per-series CONSTANTS, not flows, so they travel in their
# own one-row-per-series table rather than repeated down every row of
# ``asset_earnings`` — that table is one row per asset-year-flow, and widening it
# with horizon scalars invites a "first"-aggregation hack downstream.
HORIZON_ATTRIBUTE_COLUMNS = [
    "lifetime_years",
    "asset_age",
    "scrap_usd_per_mw",
    "asset_trajectory",
]


def validate_asset_trajectories(
    asset_trajectories: pd.DataFrame,
    frozen_capacity_at_retirement: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Validate the canonical, already-enriched asset trajectory contract.

    ``frozen_capacity_at_retirement`` is a lookup of the capacity each retiring
    asset last stood at, carried onto the panel from its retirement year on.
    Nothing in the earnings maths reads it — fixed costs use first-year capacity
    — so it is a carried surface, not a cost driver; see the Q4 entries in
    docs/superpowers/plans/consolidation-clash-report.md.
    """
    required_columns = {
        "asset_id",
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
        "year",
        "trajectory_type",
        "asset_trajectory",
        "emission_factor",
        "scenario",
        "scenario_type",
        "capacity_factor",
        "power_price_excarbon_usd_per_mwh",
        "fuel_price_usd_per_mwh_fuel",
        "capex_usd_per_mw",
        "fom_usd_per_mw_yr",
        "carbon_price_usd_per_tco2",
        "efficiency_decimal",
        "scrap_usd_per_mw",
    }
    missing = sorted(required_columns.difference(asset_trajectories.columns))
    if missing:
        raise ValueError(f"asset_trajectories missing required columns: {missing}")

    assets = asset_trajectories.copy()

    frozen_keys = ["asset_id", "company_id", "scenario_geography", "sector",
                   "technology", "year"]
    if (
        frozen_capacity_at_retirement is not None
        and not frozen_capacity_at_retirement.empty
    ):
        assets = assets.merge(
            frozen_capacity_at_retirement[
                frozen_keys + ["frozen_capacity_at_retirement"]
            ].drop_duplicates(frozen_keys),
            on=frozen_keys,
            how="left",
            validate="many_to_one",
        )
        logger.info(
            "Frozen capacity merged onto %s of %s asset-year rows",
            assets["frozen_capacity_at_retirement"].notna().sum(),
            len(assets),
        )
    else:
        assets["frozen_capacity_at_retirement"] = np.nan

    for column in [
        "asset_id",
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
        "trajectory_type",
    ]:
        assets[column] = assets[column].astype(str).str.strip()

    numeric_columns = [
        "year",
        "asset_age",
        "asset_trajectory",
        "emission_factor",
        "capacity_factor",
        "power_price_excarbon_usd_per_mwh",
        "fuel_price_usd_per_mwh_fuel",
        "capex_usd_per_mw",
        "fom_usd_per_mw_yr",
        "carbon_price_usd_per_tco2",
        "efficiency_decimal",
        "scrap_usd_per_mw",
    ]
    for column in numeric_columns:
        if column in assets.columns:
            assets[column] = pd.to_numeric(assets[column], errors="coerce")

    assets = assets.dropna(subset=["year"]).copy()

    # Forward-fill emission_factor along each asset series before any zero-fill.
    # The EF input is a shorter series than the trajectory horizon, so the tail
    # years arrive empty; without this they reach compute_ops_block's
    # fillna(0.0) and a coal plant is priced as emitting nothing for the back
    # half of its life. A forward fill never backfills, so a leading gap stays
    # NaN and is handled by the renewable rule below (or by that fillna).
    if not assets.empty:
        assets = assets.sort_values(ASSET_SERIES_KEYS + ["year"])
        assets["emission_factor"] = assets.groupby(ASSET_SERIES_KEYS, dropna=False)[
            "emission_factor"
        ].ffill()

    renewable_technologies = {
        "SolarCap - CSP",
        "SolarCap - PV",
        "WindCap - Offshore",
        "WindCap - Onshore",
        "HydroCap",
        "NuclearCap",
        "GeothermalCap",
    }
    renewable_missing = assets["technology"].isin(renewable_technologies) & assets[
        "emission_factor"
    ].isna()
    assets.loc[renewable_missing, "emission_factor"] = 0.0

    duplicate_years = assets.duplicated(ASSET_SERIES_KEYS + ["year"], keep=False)
    if duplicate_years.any():
        bad_rows = (
            assets.loc[duplicate_years, ASSET_SERIES_KEYS + ["year"]]
            .drop_duplicates()
            .head(10)
            .to_dict("records")
        )
        raise ValueError(f"Duplicate asset trajectory years: {bad_rows}")

    continuity = assets.groupby(ASSET_SERIES_KEYS, dropna=False)["year"].agg(
        first_year="min",
        last_year="max",
        year_count="nunique",
    )
    non_contiguous = continuity["year_count"] != (
        continuity["last_year"] - continuity["first_year"] + 1
    )
    if non_contiguous.any():
        bad_groups = list(non_contiguous[non_contiguous].index[:10])
        raise ValueError(f"Non-contiguous asset trajectory years: {bad_groups}")

    logger.info("Validated %s canonical asset trajectory rows", len(assets))
    return assets.reset_index(drop=True)


def validate_capacity_flow_identity(
    asset_panel_enriched: pd.DataFrame,
    replacement_capex_rate: float = REPLACEMENT_CAPEX_RATE,
):
    """
    Validate the capacity flow identity: K_t = K_{t-1} - retired + replaced + new_build

    This function checks that the upstream pipeline correctly calculated capacity flows
    and logs any discrepancies for debugging.
    """

    logger.info("Validating capacity flow identity...")

    data = asset_panel_enriched.copy()

    # Sort by asset and year
    data = data.sort_values(ASSET_SERIES_KEYS + ["year"]).reset_index(drop=True)

    # Check for and remove duplicates before pivoting
    # Each (company_id, asset_id, technology, year, capex_indicator) combination should be unique
    duplicate_check_cols = ASSET_SERIES_KEYS + ["year", "capex_indicator"]

    duplicates_count = data.duplicated(subset=duplicate_check_cols).sum()
    if duplicates_count > 0:
        raise ValueError(
            "Found %s duplicate capacity flow records. Removing duplicates...",
            duplicates_count,
        )

    # Get capacity flows by indicator type per asset-year
    # Use pivot_table with aggfunc='sum' to aggregate flows by type
    flows_pivot = data.pivot_table(
        index=ASSET_SERIES_KEYS + ["year"],
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
    base_cols = ASSET_SERIES_KEYS + ["year"]
    capacity_data = data[base_cols + ["asset_trajectory"]].drop_duplicates()

    validation_data = flows_pivot.merge(capacity_data, on=base_cols, how="left")

    # Calculate previous year capacity
    validation_data = validation_data.sort_values(ASSET_SERIES_KEYS + ["year"])
    validation_data["K_prev"] = validation_data.groupby(ASSET_SERIES_KEYS)[
        "asset_trajectory"
    ].shift(1)

    # Apply flow identity: K_t = K_{t-1} - retired + replaced + new_build
    validation_data["K_calculated"] = (
        validation_data["K_prev"]
        - validation_data["retired_max_cap"]
        + (validation_data["roll_over_cap"] / replacement_capex_rate)
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


def compute_capacity_flows(
    asset_panel: pd.DataFrame, replacement_capex_rate: float = REPLACEMENT_CAPEX_RATE
) -> pd.DataFrame:
    """
    Compute capacity flows from capacity changes in the asset panel (vectorized).

    Creates flow indicators, exactly one per asset-year:
    - new_buildout_cap: Net new capacity on synthetic assets (shock growth)
    - roll_over_cap: replacement_capex_rate of a real asset's installed capacity
    - retired_max_cap: Capacity retired on a real asset (reduction from baseline)
    - none: everything else (a synthetic asset with no capacity event)
    """

    logger.info("Computing capacity flows from capacity changes...")

    data = asset_panel.copy()
    data = data.sort_values(ASSET_SERIES_KEYS + ["year"]).reset_index(drop=True)

    # Use asset_trajectory (melted capacity)
    if "asset_trajectory" not in data.columns:
        raise ValueError("compute_capacity_flows expects 'asset_trajectory' column")

    # Calculate capacity changes vectorized, per trajectory_type when present
    data["K_prev"] = data.groupby(ASSET_SERIES_KEYS)["asset_trajectory"].shift(1)
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

    # 3. Replacement flows (replacement_capex_rate of existing installed capacity
    # annually for real assets). Routine capital maintenance/refurbishment is a
    # fraction of replacement cost per year (EPRI, Lazard LCOE methodology), so it
    # is charged on what is standing, not on the year's growth — a flat asset still
    # pays it. Excludes retiring assets, which are already charged decom costs.
    replacement_mask = is_real & ~retirement_mask
    if replacement_mask.any():
        replacement_data = data[replacement_mask].copy()
        replacement_data["capex_indicator"] = "roll_over_cap"
        replacement_data["capex_capacity"] = (
            replacement_data["asset_trajectory"] * replacement_capex_rate
        )
        flow_records.append(replacement_data)

    # 4. No-flow records (synthetic assets with no capacity events need placeholders)
    no_flow_mask = ~(new_buildout_mask | retirement_mask | replacement_mask)
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
    replacement_capex_rate: float = REPLACEMENT_CAPEX_RATE,
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
    capex_data = compute_capacity_flows(asset_panel_enriched, replacement_capex_rate)

    # NOTE: Flow identity validation disabled because it's based on flawed assumptions:
    # - Roll-over flows are replacement_capex_rate of INSTALLED capacity annually
    #   (EPRI/Lazard benchmark), which is not a capacity movement at all
    # - The validation expects flows to fully explain capacity trajectories, which they don't by design
    # - The flows themselves are correct and properly used in CapEx calculations
    # validate_capacity_flow_identity(capex_data, replacement_capex_rate)

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

    # Decommissioning costs: retired capacity (can be switched off).
    # scrap_usd_per_mw is negative (= -capex/2), representing the cost to
    # decommission. abs() makes decom_cost POSITIVE in capex_total — a real cash
    # outflow that reduces FCFF, covering demolition, remediation and site
    # restoration. Without it, retiring an asset PAID the owner.
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
    carbon_cost_method: str = "full_ef",
    dynamic_marginal_ef: bool = False,
) -> pd.DataFrame:
    """
    Node 8: Compute operations block (production, costs, revenue, EBITDA).

    EBITDA_t = Revenue_t − FuelCost_t − FixedO&M_t − CarbonCost_net_t
    Note: No depreciation is considered here. EBITDA is a cash operating measure.
    RFC: Corporate tax and depreciation tax shield are currently disabled; see compute_fcff().

    Args:
        asset_capex_block: Asset data with capacity and cost information
        market_passthrough: Fraction of carbon price passed through to market (default 0.5)
        apply_continued_om_baseline: Apply continued O&M at first-year capacity to baseline trajectories
        apply_continued_om_shock: Apply continued O&M at first-year capacity to shock trajectories
        carbon_cost_method: How emission factors enter the carbon cost.
            - "full_ef" (default): cost = Q × cp × EF. Each technology pays for
              everything it emits. Right for IAMs whose electricity prices barely
              move with carbon stringency (WITCH: a $9/MWh C1→C7 price spread
              against a $722/tCO2 carbon-price difference), where there is no
              embedded carbon to double-count.
            - "differential_ef": cost = Q × cp × max(EF − marginal_EF, 0), i.e.
              only the excess over the price-setting generator. Right for IAMs
              whose prices already embed the marginal generator's carbon cost
              (AIM/CGE: a $64/MWh spread).
        dynamic_marginal_ef: Let the marginal emission factor decay with the VRE
            capacity share, marginal_ef(t) = marginal_EF × (1 − vre_share(t))²,
            so that a technology loses its carbon rent as renewables push it off
            the margin. Quadratic rather than linear because the merit order
            turns over non-linearly: at low VRE only coal and oil are displaced,
            at high VRE gas itself is.

    Both knobs act on ``marginal_emission_factor``, which is produced by the
    market-clearing-price adjustment. That adjustment is retired in this tree
    (2026-09-01 owner ruling), so the column is absent, the marginal EF is 0 and
    the two methods coincide: every technology pays its full EF. They are ported
    so the differential path is available if the adjustment ever returns — see
    docs/superpowers/plans/consolidation-clash-report.md, entry Q2-5.
    """

    logger.info("Computing operations block...")

    if apply_continued_om_baseline or apply_continued_om_shock:
        logger.info(
            "Continued O&M costs (initial capacity) configuration: "
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

    # Fixed O&M cost - use first-year capacity if the toggle is enabled.
    if apply_continued_om_baseline or apply_continued_om_shock:
        logger.info(
            "Using constant initial capacity (from year 1) for fixed cost calculations "
            "based on trajectory type configuration"
        )

        # Sort by keys + year to ensure we find the first year's capacity
        # We use a stable sort to be safe, though not strictly required if keys are unique
        sort_keys = ASSET_SERIES_KEYS + ["year"]
        ops_data = ops_data.sort_values(sort_keys)

        # Define grouping keys to identify unique assets within a trajectory
        group_keys = ASSET_SERIES_KEYS

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

    # Carbon cost (net of passthrough), charged on the emission factor the
    # configured method exposes. See the docstring for when each applies.
    if carbon_cost_method == "full_ef":
        marginal_ef = pd.Series(0.0, index=ops_data.index)
    else:
        marginal_ef = pd.to_numeric(
            ops_data.get(
                "marginal_emission_factor", pd.Series(0.0, index=ops_data.index)
            ),
            errors="coerce",
        ).fillna(0.0)

    if dynamic_marginal_ef:
        marginal_ef = marginal_ef * (1 - _vre_capacity_share(ops_data)) ** 2

    excess_ef = (ops_data["emission_factor"] - marginal_ef).clip(lower=0.0)

    ops_data["carbon_cost_net"] = (
        ops_data["Q"]
        * ops_data["carbon_price_usd_per_tco2"]
        * excess_ef
        * (1 - market_passthrough)
    )
    logger.info(
        "Carbon cost (%s): %s asset-year rows with non-zero cost, mean charged "
        "EF %.4f tCO2/MWh",
        carbon_cost_method,
        (ops_data["carbon_cost_net"] > 0).sum(),
        excess_ef.mean(),
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


def _vre_capacity_share(ops_data: pd.DataFrame) -> pd.Series:
    """VRE share of installed capacity per geography-year, per trajectory."""
    vre_technologies = {
        "SolarCap - PV",
        "SolarCap - CSP",
        "WindCap - Onshore",
        "WindCap - Offshore",
    }
    group_columns = ["trajectory_type", "scenario_geography", "year"]
    capacity = ops_data["K_avg"]
    total = capacity.groupby([ops_data[c] for c in group_columns]).transform("sum")
    vre = (
        capacity.where(ops_data["technology"].isin(vre_technologies), 0.0)
        .groupby([ops_data[c] for c in group_columns])
        .transform("sum")
    )
    return (vre / total.clip(lower=1e-6)).clip(0.0, 1.0).fillna(0.0)


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
        "asset_age",  # used in reporting
        "capacity_factor",  # used in reporting
        # "efficiency_decimal",
        # "lifetime_years",  # NPV reads it from asset_horizon_attributes
        # "aligned",
        # "increasing",
        "alignment_type",
        "late_sudden_phase",  # used in reporting
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
        # "scrap_usd_per_mw",  # NPV reads it from asset_horizon_attributes
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


def write_asset_horizon_attributes(asset_panel_enriched: pd.DataFrame) -> pd.DataFrame:
    """Node 11: each asset series' state in its LAST forecast year.

    One row per asset series — ``ASSET_SERIES_KEYS``, i.e. one physical asset per
    owner per trajectory — carrying the four scalars the valuation stage needs to
    price a terminal exit: the asset's ``lifetime_years`` and ``asset_age`` (their
    difference is the remaining economic life at the horizon), its
    ``scrap_usd_per_mw`` (the same rate ``include_decom_costs`` books its charge
    at), and the ``asset_trajectory`` capacity still standing.

    Built from the panel BEFORE the CapEx flow split, where one asset-year is
    still one row: ``validate_asset_trajectories`` raises on a duplicate
    ``ASSET_SERIES_KEYS + year``, so the last row of a year-sorted group IS the
    horizon, with no aggregation choice to make. Taking the same values off
    ``asset_earnings`` would mean collapsing its flow rows with a "first"
    aggregation, which reads a per-year constant as though it were a flow.
    """

    logger.info("Writing asset horizon attributes...")

    present = [c for c in HORIZON_ATTRIBUTE_COLUMNS if c in asset_panel_enriched.columns]
    absent = [c for c in HORIZON_ATTRIBUTE_COLUMNS if c not in present]
    if absent:
        logger.warning(
            "Asset panel carries no %s; the valuation stage falls back where a "
            "horizon attribute is missing",
            ", ".join(absent),
        )

    horizon = (
        asset_panel_enriched.sort_values(ASSET_SERIES_KEYS + ["year"])
        .groupby(ASSET_SERIES_KEYS, dropna=False)
        # tail(1) is the group's LAST ROW, not its last non-null value per
        # column: a NaN at the horizon must stay NaN rather than silently
        # inherit an earlier year's number.
        .tail(1)[ASSET_SERIES_KEYS + present]
        .copy()
    )
    for column in present:
        horizon[column] = pd.to_numeric(horizon[column], errors="coerce")

    horizon = horizon.sort_values(ASSET_SERIES_KEYS).reset_index(drop=True)

    logger.info("Asset horizon attributes: %s asset series", len(horizon))

    return horizon
