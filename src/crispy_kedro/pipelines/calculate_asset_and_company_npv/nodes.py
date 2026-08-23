"""
Valuation model pipeline nodes for converting earnings to NPV using DCF methodology.
"""

import logging

import numpy as np
import pandas as pd
from tqdm import tqdm

logger = logging.getLogger(__name__)


def compute_yearly_npv_trajectories(
    asset_earnings: pd.DataFrame,
    discount_rate_baseline: float = 0.07,
    discount_rate_shock: float = 0.08,
    terminal_growth_rate: float = 0.02,
    terminal_method: str = "perpetuity",
) -> pd.DataFrame:
    """
    Node 1: Compute yearly NPV trajectories with all financial components.

    Returns yearly trajectories for each asset-trajectory_type combination with:
    - Present value calculations for each year
    - All financial components (FCFF, EBITDA, revenue, costs)
    - Terminal value calculation in final year
    """

    logger.info("Computing yearly NPV trajectories...")

    npv_data = asset_earnings.copy()

    unresolved_mask = npv_data["scenario_type"].isna()
    if unresolved_mask.any():
        unresolved_asset_ids = sorted(npv_data.loc[unresolved_mask, "asset_id"].unique())
        raise ValueError(
            f"{len(unresolved_asset_ids)} asset(s) have no scenario_type resolved "
            f"and cannot be included in NPV: {unresolved_asset_ids}"
        )

    def get_discount_rate(scenario_type):
        if scenario_type == "baseline":
            return discount_rate_baseline
        elif scenario_type == "target":
            return discount_rate_shock
        else:
            raise ValueError(f"Invalid scenario type: {scenario_type}")

    npv_data["discount_rate"] = npv_data.apply(
        lambda row: get_discount_rate(row["scenario_type"]), axis=1
    )

    # Guard: need trajectory_type and FCFF
    need_cols = ["asset_id", "year", "FCFF", "trajectory_type"]
    missing = [c for c in need_cols if c not in npv_data.columns]
    if missing:
        raise ValueError(f"asset_earnings missing required columns for NPV: {missing}")

    # Ensure we have the financial components we want to include
    financial_cols = [
        "FCFF",
        "EBITDA",
        "revenue",
        "var_cost",
        "fixed_cost",
        "carbon_cost_net",
        "capex_total",
    ]
    available_financial_cols = [
        col for col in financial_cols if col in npv_data.columns
    ]
    if not available_financial_cols:
        logger.warning("No financial component columns found in asset_earnings")

    group_keys = [
        "asset_name",
        "asset_id",
        "company_id",
        "company_name",
        "scenario_geography",
        "sector",
        "technology",
        "is_synthetic",
        "alignment_type",
        "trajectory_type",
    ]

    yearly_results = []

    for key, g in tqdm(
        list(npv_data.groupby(group_keys)),
        desc="Computing yearly NPV trajectories",
        unit="grp",
    ):
        g = g.sort_values("year").copy()
        first_row = g.iloc[0]
        base_year = int(g["year"].min())

        # Calculate discount factors for each year
        g["years_from_base"] = g["year"] - base_year
        g["discount_factor"] = (1 + g["discount_rate"]) ** (-g["years_from_base"])
        g["pv_fcff"] = g["FCFF"] * g["discount_factor"]

        # Calculate yearly NPV contribution (PV of FCFF only for forecast years)
        g["terminal_value"] = 0.0
        g["yearly_npv"] = g["pv_fcff"]  # Only FCFF for forecast years

        # Add terminal value as separate row for year+1
        if (terminal_method == "perpetuity") and (len(g) > 0):
            final_fcff = float(g["FCFF"].iloc[-1])
            final_year = int(g["year"].iloc[-1])

            if final_fcff > 0:
                terminal_cf = final_fcff * (1 + terminal_growth_rate)
                final_discount_rate = g.iloc[-1]["discount_rate"]
                if final_discount_rate > terminal_growth_rate:
                    terminal_value_nominal = terminal_cf / (
                        final_discount_rate - terminal_growth_rate
                    )
                    years_to_terminal = (final_year + 1) - base_year
                    terminal_discount_factor = (1 + final_discount_rate) ** (
                        -years_to_terminal
                    )
                    terminal_value = float(
                        terminal_value_nominal * terminal_discount_factor
                    )

                    # Create terminal value row for year+1
                    terminal_row = g.iloc[-1].copy()  # Copy last row as template
                    terminal_row["year"] = final_year + 1
                    terminal_row["years_from_base"] = years_to_terminal
                    terminal_row["discount_factor"] = terminal_discount_factor
                    terminal_row["pv_fcff"] = 0.0  # No FCFF in terminal year
                    terminal_row["terminal_value"] = terminal_value
                    terminal_row["yearly_npv"] = terminal_value

                    # Set financial components to 0 for terminal year (it's just the terminal value)
                    for fin_col in available_financial_cols:
                        if fin_col in terminal_row.index:
                            terminal_row[fin_col] = 0.0

                    # Add terminal row to the group
                    g = pd.concat([g, terminal_row.to_frame().T], ignore_index=True)

        # Add metadata to each row (including terminal row if added)
        for col in group_keys:
            if col not in g.columns:
                g[col] = first_row.get(col)

        g["base_year"] = base_year
        g["terminal_method"] = terminal_method
        g["terminal_growth_rate"] = terminal_growth_rate

        # Select columns for output - ensure all financial components are included
        output_cols = (
            group_keys
            + [
                "year",
                "discount_rate",
                "base_year",
                "terminal_method",
                "terminal_growth_rate",
                "years_from_base",
                "discount_factor",
                "pv_fcff",
                "terminal_value",
                "yearly_npv",
            ]
            + available_financial_cols
        )
        output_cols = [col for col in output_cols if col in g.columns]

        yearly_results.append(g[output_cols])

    yearly_df = pd.concat(yearly_results, ignore_index=True)

    logger.info(
        f"Computed yearly NPV trajectories for {len(yearly_df)} asset-year-trajectory combinations"
    )

    return yearly_df


def calculate_npv_per_asset(
    yearly_npv_trajectories: pd.DataFrame,
) -> pd.DataFrame:
    """
    Node 2: Aggregate yearly NPV trajectories to asset level, pivoting by trajectory_type.

    Returns one row per asset x scenario with columns:
      - baseline_npv
      - latesudden_npv
      - npv_change
    """

    logger.info("Aggregating yearly NPV trajectories to asset level...")

    data = yearly_npv_trajectories.copy()

    # Group keys (everything except trajectory_type and year)
    group_keys = [
        "asset_id",
        "asset_name",
        "company_id",
        "company_name",
        "scenario_geography",
        "sector",
        "technology",
        "is_synthetic",
        "alignment_type",
    ]

    # Sum yearly NPV by trajectory type
    agg_dict = {
        "yearly_npv": "sum",
        "discount_rate": "mean",  # changes over time depending on scenario type
        "base_year": "first",
        "terminal_method": "first",
        "terminal_growth_rate": "first",
    }

    # Sum financial components across years as well
    financial_cols = [
        "FCFF",
        "EBITDA",
        "revenue",
        "var_cost",
        "fixed_cost",
        "carbon_cost_net",
        "capex_total",
    ]
    for col in financial_cols:
        if col in data.columns:
            agg_dict[col] = "sum"

    # Aggregate by asset and trajectory type
    aggregated = (
        data.groupby(group_keys + ["trajectory_type"]).agg(agg_dict).reset_index()
    )

    # Rename yearly_npv to NPV for clarity
    aggregated = aggregated.rename(columns={"yearly_npv": "NPV"})

    # Pivot to wide format by trajectory_type
    pivot_values = ["NPV", "discount_rate"] + [
        col for col in financial_cols if col in aggregated.columns
    ]

    npv_wide = aggregated.pivot(
        index=group_keys,
        columns="trajectory_type",
        values=pivot_values,
    ).reset_index()

    # Flatten multi-level columns and rename
    npv_wide.columns = npv_wide.columns.to_flat_index()
    rename_map = {}
    for col in npv_wide.columns:
        if isinstance(col, tuple) and len(col) == 2:
            value_name, trajectory_type = col
            # Handle single-level columns (they become ('column_name', ''))
            if trajectory_type == "":
                rename_map[col] = value_name
            # Handle multi-level columns
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
            else:
                # Handle financial components
                if trajectory_type == "baseline":
                    rename_map[col] = f"baseline_{value_name}"
                elif trajectory_type == "latesudden":
                    rename_map[col] = f"latesudden_{value_name}"

    npv_wide = npv_wide.rename(columns=rename_map)

    # Calculate NPV change (robust to division by zero and object dtypes)
    if "baseline_npv" in npv_wide.columns and "latesudden_npv" in npv_wide.columns:
        with np.errstate(divide="ignore", invalid="ignore"):
            baseline_arr = npv_wide["baseline_npv"].to_numpy(dtype=np.float64)
            shock_arr = npv_wide["latesudden_npv"].to_numpy(dtype=np.float64)
            change_arr = np.true_divide((shock_arr - baseline_arr), abs(baseline_arr))
        npv_wide["npv_change"] = change_arr

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
        "company_name",
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

    with np.errstate(divide="ignore", invalid="ignore"):
        base_ct = company_tech_npv["baseline_npv"].to_numpy(dtype=np.float64)
        shock_ct = company_tech_npv["latesudden_npv"].to_numpy(dtype=np.float64)
        change_ct = np.true_divide((shock_ct - base_ct), abs(base_ct))
    company_tech_npv["npv_change"] = change_ct
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
    groupby_cols = ["company_id", "company_name"]

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

    with np.errstate(divide="ignore", invalid="ignore"):
        base_c = company_npv["baseline_npv"].to_numpy(dtype=np.float64)
        shock_c = company_npv["latesudden_npv"].to_numpy(dtype=np.float64)
        change_c = np.true_divide((shock_c - base_c), abs(base_c))
    company_npv["npv_change"] = change_c

    logger.info(f"Aggregated to {len(company_npv)} company-level records")

    return company_npv
