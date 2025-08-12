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
    terminal_cutover_year: int = 2050,
    terminal_method: str = "perpetuity",
) -> pd.DataFrame:
    """
    Node 1: Calculate NPV per asset using DCF with terminal value.

    Applies different discount rates based on scenario type:
    - baseline scenarios: use discount_rate_baseline
    - shock/transition scenarios: use discount_rate_shock (higher due to transition risk)

    Validation enforces tax-neutral FCFF. No depreciation or tax shield included.
    RFC: When enabling taxes, change FCFF build and set use_after_tax_wacc=true.

    No depreciation component is discounted since taxes/shield are disabled.
    RFC: With taxes on, add PV_Dep and switch identity to match EBIT(1−T)+Dep.
    """

    logger.info("Calculating NPV per asset using DCF methodology...")

    npv_data = asset_earnings.copy()

    # Determine discount rate based on scenario type
    # If scenario contains baseline indicators, use baseline rate, otherwise shock rate
    baseline_indicators = ["baseline", "current", "indc", "ndc", "curpol"]

    def get_discount_rate(scenario_type, scenario_name):
        """Determine appropriate discount rate based on scenario characteristics."""
        scenario_lower = str(scenario_name).lower() if pd.notna(scenario_name) else ""
        type_lower = str(scenario_type).lower() if pd.notna(scenario_type) else ""

        # Check if this is a baseline scenario
        if any(
            indicator in scenario_lower or indicator in type_lower
            for indicator in baseline_indicators
        ):
            return discount_rate_baseline
        else:
            return discount_rate_shock

    # Apply discount rates
    npv_data["discount_rate"] = npv_data.apply(
        lambda row: get_discount_rate(
            row.get("scenario_type", ""), row.get("scenario", "")
        ),
        axis=1,
    )

    # Group by asset and calculate NPV
    npv_results = []

    # Add progress bar for asset processing
    asset_groups = list(npv_data.groupby("asset_id"))
    for asset_id, asset_data in tqdm(
        asset_groups, desc="Calculating NPV per asset", unit="asset"
    ):
        asset_data = asset_data.sort_values("year").copy()

        # Get asset metadata
        first_row = asset_data.iloc[0]
        discount_rate = first_row["discount_rate"]
        base_year = asset_data["year"].min()

        # Calculate present values
        asset_data["years_from_base"] = asset_data["year"] - base_year
        asset_data["discount_factor"] = (1 + discount_rate) ** (
            -asset_data["years_from_base"]
        )
        asset_data["pv_fcff"] = asset_data["FCFF"] * asset_data["discount_factor"]

        # Calculate DCF sum (present value of explicit forecast period)
        dcf_sum = asset_data["pv_fcff"].sum()

        # Calculate terminal value
        terminal_value = 0.0

        if terminal_method == "perpetuity" and len(asset_data) > 0:
            # Use final year FCFF for terminal value calculation
            final_fcff = asset_data["FCFF"].iloc[-1]
            final_year = asset_data["year"].iloc[-1]

            if final_fcff > 0 and final_year < terminal_cutover_year:
                # Terminal value = Final FCFF * (1 + g) / (r - g)
                terminal_cf = final_fcff * (1 + terminal_growth_rate)
                if discount_rate > terminal_growth_rate:
                    terminal_value_nominal = terminal_cf / (
                        discount_rate - terminal_growth_rate
                    )

                    # Discount terminal value back to base year
                    years_to_terminal = final_year + 1 - base_year
                    terminal_discount_factor = (1 + discount_rate) ** (
                        -years_to_terminal
                    )
                    terminal_value = terminal_value_nominal * terminal_discount_factor

        # Total NPV = DCF sum + Terminal value
        npv_total = dcf_sum + terminal_value

        # Create result record with asset metadata
        result = {
            "asset_id": asset_id,
            "company_id": first_row["company_id"],
            "scenario_provider": first_row.get("scenario_provider", ""),
            "scenario": first_row.get("scenario", ""),
            "scenario_type": first_row.get("scenario_type", ""),
            "scenario_geography": first_row["scenario_geography"],
            "sector": first_row["sector"],
            "technology": first_row["technology"],
            "is_synthetic": first_row.get("is_synthetic", False),
            "aligned": first_row.get("aligned", True),
            "increasing": first_row.get("increasing", False),
            "alignment_type": first_row.get("alignment_type", "aligned"),
            "discount_rate": discount_rate,
            "base_year": base_year,
            "terminal_method": terminal_method,
            "terminal_growth_rate": terminal_growth_rate,
            "DCF_sum": dcf_sum,
            "Terminal_Value": terminal_value,
            "NPV": npv_total,
        }

        npv_results.append(result)

    npv_df = pd.DataFrame(npv_results)

    logger.info(f"Calculated NPV for {len(npv_df)} assets")
    logger.info(f"Average NPV: ${npv_df['NPV'].mean():,.0f}")
    logger.info(
        f"Baseline rate assets: {(npv_df['discount_rate'] == discount_rate_baseline).sum()}"
    )
    logger.info(
        f"Shock rate assets: {(npv_df['discount_rate'] == discount_rate_shock).sum()}"
    )

    return npv_df


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
        # Sum NPV components
        "DCF_sum": "sum",
        "Terminal_Value": "sum",
        "NPV": "sum",
        # Take first value for metadata (should be consistent within group)
        "sector": "first",
        "discount_rate": "first",
        "base_year": "first",
        "terminal_method": "first",
        "terminal_growth_rate": "first",
        # Boolean flags - any True means True for the group
        "is_synthetic": "any",
        "aligned": "any",
        "increasing": "any",
        # Count number of assets
        "asset_id": "count",
    }

    company_tech_npv = asset_npv.groupby(groupby_cols).agg(agg_funcs).reset_index()

    # Rename asset count column
    company_tech_npv = company_tech_npv.rename(columns={"asset_id": "asset_count"})

    # Create alignment type summary
    alignment_summary = (
        asset_npv.groupby(groupby_cols)
        .apply(lambda x: ", ".join(x["alignment_type"].unique()))
        .reset_index(name="alignment_type_mix")
    )

    company_tech_npv = company_tech_npv.merge(
        alignment_summary, on=groupby_cols, how="left"
    )

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
        "DCF_sum": "sum",
        "Terminal_Value": "sum",
        "NPV": "sum",
        # Sum asset counts
        "asset_count": "sum",
        # Take first value for metadata
        "sector": "first",
        "discount_rate": "first",
        "base_year": "first",
        "terminal_method": "first",
        "terminal_growth_rate": "first",
        # Boolean flags - any True means True for the company
        "is_synthetic": "any",
        "aligned": "any",
        "increasing": "any",
    }

    company_npv = (
        company_technology_npv.groupby(groupby_cols).agg(agg_funcs).reset_index()
    )

    # Create technology mix summary
    tech_mix = (
        company_technology_npv.groupby(groupby_cols)
        .apply(lambda x: ", ".join(sorted(x["technology"].unique())))
        .reset_index(name="technology_mix")
    )

    company_npv = company_npv.merge(tech_mix, on=groupby_cols, how="left")

    # Create sector mix summary
    sector_mix = (
        company_technology_npv.groupby(groupby_cols)
        .apply(lambda x: ", ".join(sorted(x["sector"].unique())))
        .reset_index(name="sector_mix")
    )

    company_npv = company_npv.merge(sector_mix, on=groupby_cols, how="left")

    # Create alignment type summary
    alignment_mix = (
        company_technology_npv.groupby(groupby_cols)
        .apply(
            lambda x: ", ".join(
                sorted(
                    set(
                        [
                            item
                            for sublist in x["alignment_type_mix"].str.split(", ")
                            for item in sublist
                        ]
                    )
                )
            )
        )
        .reset_index(name="alignment_type_mix")
    )

    company_npv = company_npv.merge(alignment_mix, on=groupby_cols, how="left")

    logger.info(f"Aggregated to {len(company_npv)} company-level records")

    return company_npv
