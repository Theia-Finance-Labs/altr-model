"""
Valuation model pipeline nodes for converting earnings to NPV using DCF methodology.
"""

import pandas as pd
import numpy as np
from typing import Dict, List
import logging
from tqdm import tqdm

logger = logging.getLogger(__name__)


def calculate_npv_per_asset(
    asset_earnings: pd.DataFrame,
    discount_rate_baseline: float = 0.07,
    discount_rate_shock: float = 0.08,
    terminal_growth_rate: float = 0.02,
    terminal_method: str = "perpetuity",
) -> pd.DataFrame:
    """
    Node 1: Calculate NPV per asset using DCF with terminal value, per trajectory_type.

    Returns one row per asset x scenario with two columns:
      - baseline_npv
      - latesudden_npv

    The DCF methodology and discounting logic are identical for both types.
    """

    logger.info(
        "Calculating NPV per asset using DCF methodology (per trajectory_type)..."
    )

    npv_data = asset_earnings.copy()

    # Determine discount rate based on scenario type
    baseline_indicators = ["baseline", "current", "indc", "ndc", "curpol"]

    def get_discount_rate(scenario_type, scenario_name):
        scenario_lower = str(scenario_name).lower() if pd.notna(scenario_name) else ""
        type_lower = str(scenario_type).lower() if pd.notna(scenario_type) else ""
        return (
            discount_rate_baseline
            if any(
                indicator in scenario_lower or indicator in type_lower
                for indicator in baseline_indicators
            )
            else discount_rate_shock
        )

    # Guard: need trajectory_type and FCFF
    need_cols = ["asset_id", "year", "FCFF", "trajectory_type"]
    missing = [c for c in need_cols if c not in npv_data.columns]
    if missing:
        raise ValueError(f"asset_earnings missing required columns for NPV: {missing}")

    # Build group keys (keep common scenario dimensions if present)
    group_keys = [
        "asset_id",
        *(["company_id"] if "company_id" in npv_data.columns else []),
        *(["scenario_provider"] if "scenario_provider" in npv_data.columns else []),
        *(["scenario"] if "scenario" in npv_data.columns else []),
        *(["scenario_type"] if "scenario_type" in npv_data.columns else []),
        *(["scenario_geography"] if "scenario_geography" in npv_data.columns else []),
        *(["sector"] if "sector" in npv_data.columns else []),
        *(["technology"] if "technology" in npv_data.columns else []),
        *(["is_synthetic"] if "is_synthetic" in npv_data.columns else []),
        *(["aligned"] if "aligned" in npv_data.columns else []),
        *(["increasing"] if "increasing" in npv_data.columns else []),
        *(["alignment_type"] if "alignment_type" in npv_data.columns else []),
        "trajectory_type",
    ]

    per_traj_results = []

    for key, g in tqdm(
        list(npv_data.groupby(group_keys)), desc="NPV per asset/trajectory", unit="grp"
    ):
        g = g.sort_values("year").copy()
        first_row = g.iloc[0]
        discount_rate = get_discount_rate(
            first_row.get("scenario_type", ""), first_row.get("scenario", "")
        )
        base_year = int(g["year"].min())

        # DCF
        g["years_from_base"] = g["year"] - base_year
        g["discount_factor"] = (1 + discount_rate) ** (-g["years_from_base"])
        g["pv_fcff"] = g["FCFF"] * g["discount_factor"]
        dcf_sum = float(g["pv_fcff"].sum())

        # Terminal value (per trajectory)
        terminal_value = 0.0
        if (terminal_method == "perpetuity") and (len(g) > 0):
            final_fcff = float(g["FCFF"].iloc[-1])
            final_year = int(g["year"].iloc[-1])
            if final_fcff > 0:
                terminal_cf = final_fcff * (1 + terminal_growth_rate)
                if discount_rate > terminal_growth_rate:
                    terminal_value_nominal = terminal_cf / (
                        discount_rate - terminal_growth_rate
                    )
                    years_to_terminal = (final_year + 1) - base_year
                    terminal_discount_factor = (1 + discount_rate) ** (
                        -years_to_terminal
                    )
                    terminal_value = float(
                        terminal_value_nominal * terminal_discount_factor
                    )

        npv_total = dcf_sum + terminal_value

        meta = {k: first_row.get(k) for k in group_keys}
        meta.update(
            {
                "discount_rate": discount_rate,
                "base_year": base_year,
                "terminal_method": terminal_method,
                "terminal_growth_rate": terminal_growth_rate,
                "NPV": npv_total,
            }
        )
        per_traj_results.append(meta)

    per_traj_df = pd.DataFrame(per_traj_results)

    # Pivot to wide columns per asset/scenario (baseline_npv, latesudden_npv)
    wide_index = [c for c in group_keys if c != "trajectory_type"]
    wide_index = [c for c in wide_index if c in per_traj_df.columns]

    npv_wide = per_traj_df.pivot_table(
        index=wide_index,
        columns="trajectory_type",
        values="NPV",
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()

    # Rename columns to desired output names
    rename_map = {}
    if "baseline" in npv_wide.columns:
        rename_map["baseline"] = "baseline_npv"
    if "latesudden" in npv_wide.columns:
        rename_map["latesudden"] = "latesudden_npv"
    npv_wide = npv_wide.rename(columns=rename_map)

    # Ensure both columns present
    if "baseline_npv" not in npv_wide.columns:
        npv_wide["baseline_npv"] = 0.0
    if "latesudden_npv" not in npv_wide.columns:
        npv_wide["latesudden_npv"] = 0.0

    logger.info(f"Calculated NPV (wide) for {len(npv_wide)} assets")

    return npv_wide


def aggregate_to_company_technology_npv(asset_npv: pd.DataFrame) -> pd.DataFrame:
    """
    Node 2: Aggregate asset-level NPV to company-technology level.
    """

    logger.info("Aggregating NPV to company-technology level...")

    # Group by company, technology and scenario dimensions
    groupby_cols = [
        "company_id",
        "technology",
        "scenario_provider",
        "scenario",
        "scenario_type",
        "scenario_geography",
    ]

    # Define aggregation functions
    agg_funcs = {
        # Sum NPV components (already wide)
        "baseline_npv": "sum",
        "latesudden_npv": "sum",
        # Take first value for metadata (should be consistent within group)
        "sector": "first",
        # Count assets
        "asset_id": "count",
    }

    # Ensure needed columns exist
    for col in ["baseline_npv", "latesudden_npv"]:
        if col not in asset_npv.columns:
            asset_npv[col] = 0.0

    if "asset_id" not in asset_npv.columns:
        # create a surrogate count by taking number of rows per group later
        tmp = asset_npv.copy()
        tmp["asset_id"] = tmp.get("asset_id", pd.Series(dtype=object))
        asset_npv = tmp

    company_tech_npv = asset_npv.groupby(groupby_cols).agg(agg_funcs).reset_index()

    # Rename asset count column
    company_tech_npv = company_tech_npv.rename(columns={"asset_id": "asset_count"})

    logger.info(
        f"Aggregated to {len(company_tech_npv)} company-technology combinations"
    )

    return company_tech_npv


def aggregate_to_company_npv(company_technology_npv: pd.DataFrame) -> pd.DataFrame:
    """
    Node 3: Aggregate company-technology NPV to company level.
    """

    logger.info("Aggregating NPV to company level...")

    # Group by company and scenario dimensions only
    groupby_cols = [
        "company_id",
        "scenario_provider",
        "scenario",
        "scenario_type",
        "scenario_geography",
    ]

    # Define aggregation functions
    agg_funcs = {
        # Sum NPV components across all technologies
        "baseline_npv": "sum",
        "latesudden_npv": "sum",
        # Sum asset counts
        "asset_count": "sum",
    }

    for col in ["baseline_npv", "latesudden_npv"]:
        if col not in company_technology_npv.columns:
            company_technology_npv[col] = 0.0

    company_npv = (
        company_technology_npv.groupby(groupby_cols).agg(agg_funcs).reset_index()
    )

    logger.info(f"Aggregated to {len(company_npv)} company-level records")

    return company_npv
