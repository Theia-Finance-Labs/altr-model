"""Input validation and standardisation for the earnings model (stage 6).

Node 1 harmonises the melted asset panel, scenario pathways and alignment
classifications (schemas, dtypes, emission factors) before any pricing or
cost computation runs. ``validate_capacity_flow_identity`` is a diagnostic
over the enriched panel; see ALTR Documentation, capacity-flow methodology.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def validate_and_standardize_inputs(  # noqa: PLR0912, PLR0915
    asset_level_staggered_shock: pd.DataFrame,
    downloaded_scenarios: pd.DataFrame,
    all_alignment_classifications: pd.DataFrame,
    assets_data: pd.DataFrame,
    frozen_capacity_at_retirement: pd.DataFrame = None,
) -> dict[str, pd.DataFrame]:
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


def validate_capacity_flow_identity(
    asset_panel_enriched: pd.DataFrame,
) -> None:
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
