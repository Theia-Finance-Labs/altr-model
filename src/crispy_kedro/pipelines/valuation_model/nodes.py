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

    group_keys = [
        "asset_id",
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
        "is_synthetic",
        "alignment_type",
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

    npv_wide = per_traj_df.pivot(
        index=wide_index,
        columns="trajectory_type",
        values=[
            "NPV",
            "discount_rate",
        ],
    ).reset_index()

    # Flatten multi-level columns and rename to desired output names
    npv_wide.columns = npv_wide.columns.to_flat_index()
    rename_map = {}
    for col in npv_wide.columns:
        if isinstance(col, tuple) and len(col) == 2:
            value_name, trajectory_type = col
            # Handle single-level columns (they become ('column_name', ''))
            if trajectory_type == "":
                rename_map[col] = value_name
            # Handle multi-level columns for NPV and discount_rate
            elif value_name == "NPV":
                if trajectory_type == "baseline":
                    rename_map[col] = "baseline_npv"
                elif trajectory_type == "latesudden":
                    rename_map[col] = "latesudden_npv"
            elif value_name == "discount_rate":
                if trajectory_type == "baseline":
                    rename_map[col] = "baseline_discount_rate"
                elif trajectory_type == "latesudden":
                    rename_map[col] = "latesudden_discount_rate"
    npv_wide = npv_wide.rename(columns=rename_map)

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
        "sector",
        "technology",
        "scenario_geography",
    ]

    # Define aggregation functions
    agg_funcs = {
        # Sum NPV components (already wide)
        "baseline_npv": "sum",
        "latesudden_npv": "sum",
        "baseline_discount_rate": "mean",
        "latesudden_discount_rate": "mean",
        # Count assets
        "asset_id": "count",
    }

    company_tech_npv = asset_npv.groupby(groupby_cols).agg(agg_funcs).reset_index()

    # Rename asset count column
    company_tech_npv = company_tech_npv.rename(columns={"asset_id": "asset_count"})

    company_tech_npv = company_tech_npv.assign(
        npv_change=(
            company_tech_npv["latesudden_npv"] - company_tech_npv["baseline_npv"]
        )
        / company_tech_npv["baseline_npv"],
    )
    logger.info(
        f"Aggregated to {len(company_tech_npv)} company-technology-scenario_geography combinations"
    )

    return company_tech_npv


def aggregate_to_company_npv(company_technology_npv: pd.DataFrame) -> pd.DataFrame:
    """
    Node 3: Aggregate company-technology NPV to company level.
    """

    logger.info("Aggregating NPV to company level...")

    # Group by company and scenario dimensions only
    groupby_cols = ["company_id"]

    # Define aggregation functions
    agg_funcs = {
        # Sum NPV components across all technologies
        "baseline_npv": "sum",
        "latesudden_npv": "sum",
        "baseline_discount_rate": "mean",
        "latesudden_discount_rate": "mean",
        # Sum asset counts
        "asset_count": "sum",
    }

    company_npv = (
        company_technology_npv.groupby(groupby_cols).agg(agg_funcs).reset_index()
    )

    company_npv = company_npv.assign(
        npv_change=(company_npv["latesudden_npv"] - company_npv["baseline_npv"])
        / company_npv["baseline_npv"],
    )

    logger.info(f"Aggregated to {len(company_npv)} company-level records")

    return company_npv
