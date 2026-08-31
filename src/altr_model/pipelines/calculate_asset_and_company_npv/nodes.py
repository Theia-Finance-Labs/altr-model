"""
Valuation model pipeline nodes for converting earnings to NPV using DCF methodology.
"""

import logging

import numpy as np
import pandas as pd

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

    # map() over the column instead of a row-wise apply: same per-value
    # semantics (including the raise above), one Python call per row instead
    # of one Series construction per row.
    npv_data["discount_rate"] = npv_data["scenario_type"].map(get_discount_rate)

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

    # ------------------------------------------------------------------
    # Vectorised trajectory + terminal-value computation.
    #
    # This replaces a per-group Python loop measured at ~1.55 ms/group, i.e.
    # ~60 s per production run at ~40k groups. Semantics are unchanged and
    # pinned by tests/.../test_npv_vectorized_equivalence.py, which
    # re-implements the old loop and asserts frame equality.
    # ------------------------------------------------------------------

    # Group ids in the order the old groupby(sort=True) iterated, then sort rows
    # by (group, year) so every group is one contiguous, year-ordered block.
    # dropna=False keeps assets whose group keys contain NaN: the downstream
    # nodes keep them, and pandas' default silently discarded them here.
    gid = npv_data.groupby(group_keys, dropna=False, sort=True).ngroup().to_numpy()
    npv_data = npv_data.assign(_gid=gid).sort_values(
        ["_gid", "year"], kind="stable", ignore_index=True
    )
    gid = npv_data["_gid"].to_numpy()

    n_rows = len(npv_data)
    n_groups = int(gid.max()) + 1 if n_rows else 0
    sizes = np.bincount(gid, minlength=n_groups)
    starts = np.zeros(n_groups, dtype=np.int64)
    if n_groups:
        starts[1:] = np.cumsum(sizes)[:-1]
    last_idx = starts + sizes - 1

    # NaN years must fail loudly: the int casts below would silently wrap
    # NaN to INT64_MIN and produce astronomically wrong terminal values.
    n_nan_year = int(npv_data["year"].isna().sum())
    if n_nan_year:
        raise ValueError(
            f"asset_earnings contains {n_nan_year} rows with NaN year; "
            "cannot compute NPV trajectories"
        )
    years = npv_data["year"].to_numpy()
    discount_rate = npv_data["discount_rate"].to_numpy(dtype=np.float64)
    fcff = npv_data["FCFF"].to_numpy(dtype=np.float64)

    # Rows are year-sorted, so the group's first row carries its minimum year.
    base_year_per_group = years[starts].astype(np.int64)
    base_year = base_year_per_group[gid]
    years_from_base = years - base_year
    discount_factor = (1.0 + discount_rate) ** (-years_from_base)

    npv_data["base_year"] = base_year
    npv_data["terminal_method"] = terminal_method
    npv_data["terminal_growth_rate"] = terminal_growth_rate
    npv_data["years_from_base"] = years_from_base
    npv_data["discount_factor"] = discount_factor
    npv_data["pv_fcff"] = fcff * discount_factor
    npv_data["terminal_value"] = 0.0
    npv_data["yearly_npv"] = npv_data["pv_fcff"]  # Only FCFF for forecast years

    # Per-group terminal anchors, all taken from the last (highest-year) row.
    final_year = years[last_idx].astype(np.int64)
    final_fcff = fcff[last_idx]
    final_discount_rate = discount_rate[last_idx]
    years_to_terminal = (final_year + 1) - base_year_per_group

    # Gordon Growth perpetuity, only where the final FCFF is positive and the
    # discount rate exceeds the growth rate.
    terminal_value = np.zeros(n_groups, dtype=np.float64)
    if terminal_method == "perpetuity" and n_groups:
        with np.errstate(divide="ignore", invalid="ignore"):
            perpetuity_tv = (
                final_fcff
                * (1.0 + terminal_growth_rate)
                / (final_discount_rate - terminal_growth_rate)
            ) * (1.0 + final_discount_rate) ** (-years_to_terminal)
        has_terminal_value = (final_fcff > 0) & (
            final_discount_rate > terminal_growth_rate
        )
        terminal_value = np.where(has_terminal_value, perpetuity_tv, 0.0)

    # One terminal row per group with a non-zero terminal value, built as a
    # single frame (the old per-group Series.to_frame().T forced object dtype).
    add_groups = np.flatnonzero(terminal_value != 0)
    if len(add_groups):
        anchors = last_idx[add_groups]
        group_years_to_terminal = years_to_terminal[add_groups]
        terminal_rows = npv_data.iloc[anchors].copy()
        terminal_rows["year"] = final_year[add_groups] + 1
        terminal_rows["years_from_base"] = group_years_to_terminal
        terminal_rows["discount_factor"] = (
            1.0 + final_discount_rate[add_groups]
        ) ** (-group_years_to_terminal)
        terminal_rows["pv_fcff"] = 0.0  # No FCFF in terminal year
        terminal_rows["terminal_value"] = terminal_value[add_groups]
        terminal_rows["yearly_npv"] = terminal_value[add_groups]
        # Financial components are 0 in the terminal year (it's just the TV)
        for fin_col in available_financial_cols:
            terminal_rows[fin_col] = 0.0
        npv_data = pd.concat([npv_data, terminal_rows], ignore_index=True).sort_values(
            ["_gid", "year"], kind="stable", ignore_index=True
        )

    logger.info(
        "Computed %d asset-trajectory groups, %d with a terminal-value row",
        n_groups,
        len(add_groups),
    )

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
    yearly_df = npv_data[[col for col in output_cols if col in npv_data.columns]].copy()

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

    # Aggregate by asset and trajectory type. dropna=False: the trajectory
    # groupby upstream keeps NaN group keys, so dropping them here would make
    # those assets disappear between two nodes with no warning.
    aggregated = (
        data.groupby(group_keys + ["trajectory_type"], dropna=False)
        .agg(agg_dict)
        .reset_index()
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

    company_tech_npv = (
        asset_npv.groupby(groupby_cols, dropna=False).agg(agg_funcs).reset_index()
    )

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
        company_technology_npv.groupby(groupby_cols, dropna=False)
        .agg(agg_funcs)
        .reset_index()
    )

    with np.errstate(divide="ignore", invalid="ignore"):
        base_c = company_npv["baseline_npv"].to_numpy(dtype=np.float64)
        shock_c = company_npv["latesudden_npv"].to_numpy(dtype=np.float64)
        change_c = np.true_divide((shock_c - base_c), abs(base_c))
    company_npv["npv_change"] = change_c

    logger.info(f"Aggregated to {len(company_npv)} company-level records")

    return company_npv
