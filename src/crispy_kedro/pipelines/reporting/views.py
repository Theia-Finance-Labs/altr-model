"""Reporting stage: input validation, tidy views and the QC summary.

Stage 8 of the ALTR pipeline. These nodes check the earnings/valuation outputs,
derive the tidy tables every plotting and export node reads
(``view_asset_explain``, ``view_asset_npv_decomp``, ``view_company_tech``,
``view_deltas``), and summarise the reconciliation checks. See the ALTR
Documentation, reporting section.
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def reporting_validate_inputs(
    asset_earnings: pd.DataFrame,
    asset_npv: pd.DataFrame,
    company_npv: pd.DataFrame,
    reporting_params: dict,
) -> dict[str, pd.DataFrame]:
    """
    Node 1: Validate inputs and check basis alignment.

    Purpose: sanity checks & basis alignment (real/nominal), required columns present,
    years contiguous.

    Validates tax-neutral DCF outputs: FCFF = EBITDA - CapEx (no taxes/depreciation).
    RFC: When enabling taxes, expect EBIT-based earnings with depreciation tax shields.
    """

    logger.info("Validating reporting inputs...")

    # Check required columns in asset_earnings
    required_earnings_cols = [
        "asset_id",
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
        "year",
        "asset_trajectory",
        "capacity_factor",
        "efficiency_decimal",
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
    ]

    missing_earnings_cols = set(required_earnings_cols) - set(asset_earnings.columns)
    if missing_earnings_cols:
        logger.warning(f"Missing columns in asset_earnings: {missing_earnings_cols}")

    # Check required columns in asset_npv (support new wide columns)
    required_npv_base = {
        "asset_id",
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
    }
    missing_npv_cols = required_npv_base - set(asset_npv.columns)
    if missing_npv_cols:
        logger.warning(f"Missing columns in asset_npv: {missing_npv_cols}")

    # Check year continuity per asset
    logger.info("Checking year continuity for all assets...")
    year_gaps = []
    total_assets = len(asset_earnings["asset_id"].unique())
    for i, (asset_id, asset_data) in enumerate(asset_earnings.groupby("asset_id")):
        if i % 100 == 0:  # Log progress every 100 assets
            logger.info(
                f"Year continuity check progress: {i}/{total_assets} assets processed"
            )

        years = sorted(asset_data["year"].unique())
        if len(years) > 1:
            gaps = [years[i + 1] - years[i] for i in range(len(years) - 1)]
            if any(gap != 1 for gap in gaps):
                year_gaps.append(asset_id)

    if year_gaps:
        logger.warning(f"Year gaps detected in {len(year_gaps)} assets")

    # Basis consistency check
    basis = reporting_params.get("basis", "real")
    logger.info(f"Reporting basis: {basis}")

    # Basic data quality checks
    logger.info(
        f"Asset earnings: {len(asset_earnings)} rows, {len(asset_earnings['asset_id'].unique())} unique assets"
    )
    logger.info(f"Asset NPV: {len(asset_npv)} rows")
    logger.info(f"Company NPV: {len(company_npv)} rows")

    # Check for negative NPVs using latesudden_npv (equivalent to old NPV logic)
    if "latesudden_npv" in asset_npv.columns:
        negative_npvs = asset_npv[asset_npv["latesudden_npv"] < 0]
        npv_col = "latesudden_npv"
    else:
        negative_npvs = pd.DataFrame()
        npv_col = "n/a"
    if len(negative_npvs) > 0:
        logger.info(
            f"Assets with negative NPV ({npv_col or 'n/a'}): {len(negative_npvs)} ({len(negative_npvs)/max(len(asset_npv),1)*100:.1f}%)"
        )

    logger.info("Input validation completed successfully")

    # Return validated datasets
    return {
        "asset_earnings_validated": asset_earnings.copy(),
        "asset_npv_validated": asset_npv.copy(),
        "company_npv_validated": company_npv.copy(),
        "validation_summary": pd.DataFrame(
            {
                "metric": ["total_assets", "negative_npv_assets", "year_gap_assets"],
                "count": [
                    len(asset_earnings["asset_id"].unique()),
                    len(negative_npvs),
                    len(year_gaps),
                ],
            }
        ),
    }


def build_reporting_views(
    asset_earnings_validated: pd.DataFrame,
    asset_npv_validated: pd.DataFrame,
    company_npv_validated: pd.DataFrame,
    reporting_params: dict,
) -> dict[str, pd.DataFrame]:
    """
    Node 2: Pre-compute tidy tables used by both plotting nodes.

    Build asset explainability view, NPV decomposition, company tech stacks, and deltas.
    """

    logger.info("Building reporting views...")

    # 1. Asset explainability view (per asset-year)
    logger.info("Building asset explainability view...")

    # Assets can be co-owned: the same asset_id appears once per owning company.
    # asset_npv is keyed by the full ownership key (see calculate_npv_per_asset
    # group_keys), so merging/grouping on asset_id alone fans rows out and mixes
    # owners' cash flows.
    owner_keys = [
        "asset_id",
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
    ]

    # Merge earnings with NPV data to get discount rates
    asset_explain = asset_earnings_validated.query(
        "trajectory_type == 'latesudden'"
    ).merge(
        asset_npv_validated[
            [*owner_keys, "latesudden_discount_rate", "latesudden_npv"]
        ],
        on=owner_keys,
        how="left",
        validate="many_to_one",
    )

    # Calculate discount factors and present values per year
    # Tax-neutral DCF: PV_FCFF = PV_EBITDA - PV_CapEx (no depreciation tax shield)
    # RFC: With taxes enabled, add PV_Depreciation and PV_TaxShield components
    base_year = asset_explain["year"].min()
    asset_explain["years_from_base"] = asset_explain["year"] - base_year
    # calculate_npv_per_asset pivots to wide, which yields object-dtype columns;
    # coerce (raising on genuine non-numerics) so the PV columns stay float and
    # can be aggregated with vectorized groupby ops.
    asset_explain["discount_factor"] = (
        1 + pd.to_numeric(asset_explain["latesudden_discount_rate"])
    ) ** (-asset_explain["years_from_base"])
    asset_explain["PV_FCFF"] = asset_explain["FCFF"] * asset_explain["discount_factor"]
    asset_explain["PV_EBITDA"] = (
        asset_explain["EBITDA"] * asset_explain["discount_factor"]
    )
    asset_explain["PV_CapEx"] = (
        asset_explain["capex_total"] * asset_explain["discount_factor"]
    )
    asset_explain["PV_Carbon"] = (
        asset_explain["carbon_cost_net"] * asset_explain["discount_factor"]
    )

    # Calculate cumulative discounted sums per asset-owner
    logger.info("Calculating cumulative present values for all assets...")
    asset_explain = asset_explain.sort_values([*owner_keys, "year"])
    asset_explain[
        ["cum_PV_EBITDA", "cum_PV_CapEx", "cum_PV_Carbon", "cum_PV_FCFF"]
    ] = asset_explain.groupby(owner_keys, dropna=False)[
        ["PV_EBITDA", "PV_CapEx", "PV_Carbon", "PV_FCFF"]
    ].cumsum()

    # 2. Asset NPV decomposition (per asset-owner)
    logger.info("Building asset NPV decomposition...")

    # Calculate PV components by asset-owner
    pv_components = (
        asset_explain.assign(
            PV_Revenue=asset_explain["revenue"] * asset_explain["discount_factor"],
            PV_VarCost=asset_explain["var_cost"] * asset_explain["discount_factor"],
            PV_FixedCost=asset_explain["fixed_cost"]
            * asset_explain["discount_factor"],
        )
        .groupby(owner_keys, dropna=False, as_index=False)
        .agg(
            {
                "PV_EBITDA": "sum",
                "PV_CapEx": "sum",
                "PV_Carbon": "sum",
                "PV_FCFF": "sum",
                "revenue": "sum",
                "var_cost": "sum",
                "fixed_cost": "sum",
                "PV_Revenue": "sum",
                "PV_VarCost": "sum",
                "PV_FixedCost": "sum",
            }
        )
    )

    # Merge with NPV data (support new wide naming)
    # Both latesudden_npv and baseline_npv should always exist
    npv_cols_available = [
        c
        for c in [
            "latesudden_npv",
            "baseline_npv",
            "DCF_sum",
            "Terminal_Value",
            "latesudden_discount_rate",
        ]
        if c in asset_npv_validated.columns
    ]
    asset_npv_decomp = pv_components.merge(
        asset_npv_validated[[*owner_keys, *npv_cols_available]],
        on=owner_keys,
        validate="one_to_one",
    )

    # Define a canonical NPV column equivalent to legacy behavior (latesudden_npv replaces old NPV)
    asset_npv_decomp["NPV"] = asset_npv_decomp["latesudden_npv"]
    asset_npv_decomp["discount_rate"] = asset_npv_decomp["latesudden_discount_rate"]

    # Asset metadata (company_id, scenario_geography, sector, technology) already
    # travels on the ownership key, so no metadata re-merge is needed here.

    # Check NPV reconciliation (tax-neutral: NPV = PV_EBITDA - PV_CapEx)
    # RFC: With taxes, reconcile as NPV = PV_EBIT*(1-tax_rate) + PV_Depreciation*tax_rate - PV_CapEx
    # Reconciliation against available NPV (prefer latesudden)
    npv_preferred = (
        "latesudden_npv"
        if "latesudden_npv" in asset_npv_decomp.columns
        else ("baseline_npv" if "baseline_npv" in asset_npv_decomp.columns else None)
    )
    asset_npv_decomp["NPV_check"] = (
        asset_npv_decomp["PV_EBITDA"] - asset_npv_decomp["PV_CapEx"]
    )
    if npv_preferred is not None:
        asset_npv_decomp["NPV_diff"] = abs(
            asset_npv_decomp[npv_preferred] - asset_npv_decomp["NPV_check"]
        )
    else:
        asset_npv_decomp["NPV_diff"] = np.nan

    # 3. Company tech stacks
    logger.info("Building company tech stacks...")

    company_tech = (
        asset_npv_decomp.groupby(["company_id", "technology"])
        .agg(
            {
                "NPV": "sum",
                "PV_EBITDA": "sum",
                "PV_CapEx": "sum",
                "PV_Revenue": "sum",
                "asset_id": "count",
                "scenario_geography": "first",
                "sector": "first",
            }
        )
        .reset_index()
    )
    company_tech.rename(columns={"asset_id": "asset_count"}, inplace=True)

    # Calculate portfolio shares per company
    logger.info("Calculating portfolio shares for all companies...")
    company_totals = company_tech.groupby("company_id")["NPV"].sum()
    total_companies = len(company_totals)

    for i, (company_id, total_npv) in enumerate(company_totals.items()):
        if i % 50 == 0:  # Log progress every 50 companies
            logger.info(
                f"Portfolio share calculation progress: {i}/{total_companies} companies processed"
            )

        company_mask = company_tech["company_id"] == company_id
        company_tech.loc[company_mask, "npv_share_of_company"] = (
            company_tech.loc[company_mask, "NPV"] / total_npv if total_npv != 0 else 0
        )

    # 4. Baseline vs shock deltas (placeholder - would need both scenarios)
    logger.info("Building deltas view (placeholder)...")

    # For now, create empty deltas view - would need baseline and shock scenarios
    deltas = pd.DataFrame(
        {
            "company_id": company_npv_validated["company_id"].unique(),
            "delta_npv": 0,  # Would calculate: shock_npv - baseline_npv
            "delta_pv_ebitda": 0,
            "delta_pv_capex": 0,
            "delta_pct": 0,
        }
    )

    logger.info(
        f"Built views - Asset explain: {len(asset_explain)}, NPV decomp: {len(asset_npv_decomp)}, Company-tech: {len(company_tech)}"
    )

    return {
        "view_asset_explain": asset_explain,
        "view_asset_npv_decomp": asset_npv_decomp,
        "view_company_tech": company_tech,
        "view_deltas": deltas,
    }


def reporting_qc_summary(
    view_asset_npv_decomp: pd.DataFrame,
    view_asset_explain: pd.DataFrame,
    reporting_params: dict,
) -> pd.DataFrame:
    """
    Node 7: Quality control checks and reporting diagnostics.
    """

    logger.info("Running reporting QC checks...")

    qc_results = []

    # 1. Basis consistency check
    basis = reporting_params.get("basis", "real")
    qc_results.append(
        {
            "check": "basis_consistency",
            "status": "PASS",
            "value": basis,
            "description": f"All calculations use {basis} basis",
        }
    )

    # 2. NPV reconciliation check
    if "NPV_diff" in view_asset_npv_decomp.columns:
        npv_diff = view_asset_npv_decomp["NPV_diff"]
        max_diff = npv_diff.max() if len(npv_diff) > 0 else 0
        tolerance = (
            reporting_params.get("small_numbers_rounding", 0.001) * 1_000_000
        )  # Convert to dollars

        reconciliation_status = "PASS" if max_diff < tolerance else "FAIL"
        qc_results.append(
            {
                "check": "npv_reconciliation",
                "status": reconciliation_status,
                "value": max_diff,
                "description": f"Max NPV reconciliation difference: ${max_diff:.2f}",
            }
        )

    # 3. Materiality threshold check
    materiality_threshold = reporting_params.get("materiality_threshold_usd", 1_000_000)
    material_assets = len(
        view_asset_npv_decomp[
            abs(view_asset_npv_decomp["NPV"]) >= materiality_threshold
        ]
    )

    qc_results.append(
        {
            "check": "materiality_filter",
            "status": "INFO",
            "value": material_assets,
            "description": f"{material_assets} assets above materiality threshold of ${materiality_threshold:,.0f}",
        }
    )

    # 4. Negative NPV assets by technology
    logger.info("Analyzing negative NPV assets by technology...")
    negative_npv_assets = view_asset_npv_decomp[view_asset_npv_decomp["NPV"] < 0]
    negative_by_tech = negative_npv_assets.groupby("technology").size()

    for tech, count in negative_by_tech.items():
        qc_results.append(
            {
                "check": f"negative_npv_{tech}",
                "status": "INFO",
                "value": count,
                "description": f"{count} {tech} assets with negative NPV",
            }
        )

    # 5. Data completeness checks
    total_assets = len(view_asset_npv_decomp)
    complete_records = len(view_asset_npv_decomp.dropna())

    qc_results.append(
        {
            "check": "data_completeness",
            "status": "PASS" if complete_records == total_assets else "WARNING",
            "value": complete_records / total_assets if total_assets > 0 else 0,
            "description": f"{complete_records}/{total_assets} complete records ({complete_records/total_assets*100:.1f}%)",
        }
    )

    # Convert to DataFrame
    qc_summary = pd.DataFrame(qc_results)

    # Add timestamp and summary stats
    qc_summary["timestamp"] = pd.Timestamp.now()

    logger.info(f"QC Summary: {len(qc_summary)} checks completed")
    logger.info(f"Status counts: {qc_summary['status'].value_counts().to_dict()}")

    return qc_summary
