"""
Valuation model pipeline nodes for converting earnings to NPV using DCF methodology.
"""

import pandas as pd
import numpy as np
import logging
from tqdm import tqdm

logger = logging.getLogger(__name__)


def compute_yearly_npv_trajectories(
    asset_earnings: pd.DataFrame,
    discount_rate_baseline: float = 0.07,
    discount_rate_shock: float = 0.08,
    terminal_growth_rate: float = 0.02,
    terminal_growth_rate_brown: float = None,
    terminal_growth_rate_green: float = None,
    terminal_method: str = "perpetuity",
    terminal_normalization_window: int = 1,
    brown_discount_spread: float = 0.0,
    green_discount_spread: float = 0.0,
    stranding_aware_tv: bool = False,
    stranding_consecutive_years: int = 3,
    brown_remaining_life_years: int = 10,
) -> pd.DataFrame:
    """
    Node 1: Compute yearly NPV trajectories with all financial components.

    Returns yearly trajectories for each asset-trajectory_type combination with:
    - Present value calculations for each year
    - All financial components (FCFF, EBITDA, revenue, costs)
    - Terminal value calculation in final year

    Args:
        terminal_normalization_window: Number of final years to average for terminal
            FCFF. Default 1 (last year only). Set to 3-5 for normalized terminal value
            per Damodaran/McKinsey/CFA best practice. Prevents single-year CapEx spikes
            from eliminating terminal value.
        brown_discount_spread: Additional discount rate for carbontech (default 0).
            Reflects the carbon risk premium per Bolton & Kacperczyk (2021, 2023).
            Shell 2024 uses +150bps for O&G vs renewables.
        green_discount_spread: Discount rate reduction for greentech (default 0).
            Reflects lower cost of capital for zero-emission assets.
        stranding_aware_tv: If True, apply three-tier terminal value logic (D2 fix):
            - Stranded assets (loss-making for N consecutive years at terminal): TV = 0
              Based on Gourdel (2024) real options / abandonment logic: max(profit - carbon_cost, 0).
            - Declining carbontech (still profitable): TV = finite annuity (N years)
              instead of perpetuity. Reflects finite remaining economic life.
            - Greentech / growing: TV = Gordon Growth perpetuity (standard).
        stranding_consecutive_years: Number of consecutive loss-making years at
            the end of the horizon to trigger stranding (TV=0). Default 3.
            A company can weather 1-2 bad years but not sustained losses.
        brown_remaining_life_years: For non-stranded carbontech, compute TV as a
            finite annuity over this many years instead of perpetuity. Default 10.
            Reflects that declining fossil assets have finite remaining economic life
            beyond the model horizon.
        terminal_growth_rate_brown: Terminal growth rate for carbontech (high_carbon
            alignment types). If None, uses terminal_growth_rate. Set to 0 or negative
            to reflect declining fossil asset cash flows beyond the model horizon.
        terminal_growth_rate_green: Terminal growth rate for greentech (low_carbon
            alignment types). If None, uses terminal_growth_rate. Typically >= terminal_growth_rate
            to reflect growing clean energy cash flows.
    """

    logger.info("Computing yearly NPV trajectories...")

    if stranding_aware_tv:
        logger.info(
            "Stranding-aware TV ENABLED (Gourdel 2024): "
            "stranded (>=%d consecutive loss years) → TV=0; "
            "declining carbontech (profitable) → %d-year finite annuity; "
            "greentech → standard Gordon Growth perpetuity",
            stranding_consecutive_years,
            brown_remaining_life_years,
        )

    # Technology-differentiated terminal growth rates
    g_brown = terminal_growth_rate_brown if terminal_growth_rate_brown is not None else terminal_growth_rate
    g_green = terminal_growth_rate_green if terminal_growth_rate_green is not None else terminal_growth_rate
    if g_brown != terminal_growth_rate or g_green != terminal_growth_rate:
        logger.info(
            "Technology-differentiated terminal growth: brown=%.1f%%, green=%.1f%%, default=%.1f%%",
            g_brown * 100, g_green * 100, terminal_growth_rate * 100,
        )

    if terminal_normalization_window > 1:
        logger.info(
            "Terminal FCFF normalization: averaging last %s years (Damodaran/McKinsey practice)",
            terminal_normalization_window,
        )

    if brown_discount_spread > 0 or green_discount_spread > 0:
        logger.info(
            "Technology-differentiated discount rates: brown +%.1f bps, green -%.1f bps "
            "(Bolton & Kacperczyk 2021/2023; Shell 2024 precedent)",
            brown_discount_spread * 10000,
            green_discount_spread * 10000,
        )

    npv_data = asset_earnings.copy()

    # TODO: for some reason some assets have no scenario associated; MUST FIX THIS
    npv_data = npv_data.dropna(subset=["scenario_type"]).reset_index(drop=True)

    # Determine technology type for discount rate differentiation
    carbontech_alignments = {"misaligned_high_carbon", "aligned_high_carbon"}

    def get_discount_rate(row):
        if row.get("scenario_type") == "baseline":
            base = discount_rate_baseline
        else:
            base = discount_rate_shock

        # Apply technology-specific spread if enabled
        alignment = row.get("alignment_type", "")
        if alignment in carbontech_alignments:
            return base + brown_discount_spread
        elif green_discount_spread > 0:
            return base - green_discount_spread
        return base

    npv_data["discount_rate"] = npv_data.apply(get_discount_rate, axis=1)

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

        # Initialize g_effective before conditional block to prevent stale values
        g_effective = terminal_growth_rate

        # Add terminal value as separate row for year+1
        if (terminal_method == "perpetuity") and (len(g) > 0):
            # Normalize terminal FCFF by averaging last N years (Damodaran/McKinsey
            # best practice). Prevents single-year CapEx spikes from distorting
            # the perpetuity. At N=1, uses last year only (original behavior).
            n_window = min(terminal_normalization_window, len(g))
            final_fcff = float(g["FCFF"].iloc[-n_window:].mean())
            final_year = int(g["year"].iloc[-1])
            final_discount_rate = g.iloc[-1]["discount_rate"]

            # Select technology-appropriate terminal growth rate
            alignment = first_row.get("alignment_type", "")
            is_carbontech = alignment in carbontech_alignments
            if is_carbontech:
                g_effective = g_brown
            else:
                g_effective = g_green

            # Determine terminal value tier (if stranding-aware TV enabled)
            tv_tier = "perpetuity"  # default
            terminal_value = 0.0

            if stranding_aware_tv and final_fcff != 0:

                # Check stranding: N consecutive loss-making years at end of horizon
                # Gourdel (2024): asset is stranded when carbon costs exceed profits.
                # We generalize: if the asset has been losing money for N consecutive
                # years at the terminal, a rational owner would shut down.
                n_check = min(stranding_consecutive_years, len(g))
                last_n_fcff = g["FCFF"].iloc[-n_check:]
                is_stranded = (last_n_fcff <= 0).all()

                if is_stranded:
                    tv_tier = "stranded"
                    terminal_value = 0.0
                elif is_carbontech and final_fcff > 0:
                    # Declining carbontech still profitable: finite annuity
                    # instead of perpetuity. Reflects finite remaining economic
                    # life — the asset won't operate forever in a transition.
                    tv_tier = "finite_annuity"
                    # PV of annuity: FCFF * sum(1/(1+r)^t for t=1..N)
                    # The annuity factor discounts t=1..N back to final_year,
                    # so we discount from final_year (not final_year+1) to base_year.
                    annuity_factor = sum(
                        1 / (1 + final_discount_rate) ** t
                        for t in range(1, brown_remaining_life_years + 1)
                    )
                    terminal_cf = final_fcff * (1 + g_effective)
                    terminal_value_nominal = terminal_cf * annuity_factor
                    years_from_base_to_final = final_year - base_year
                    terminal_discount_factor = (1 + final_discount_rate) ** (
                        -years_from_base_to_final
                    )
                    terminal_value = float(
                        terminal_value_nominal * terminal_discount_factor
                    )
                else:
                    # Greentech or non-carbontech: standard Gordon Growth perpetuity
                    tv_tier = "perpetuity"
            elif not stranding_aware_tv:
                tv_tier = "perpetuity"

            # Compute perpetuity terminal value (for perpetuity tier or non-stranding mode)
            if tv_tier == "perpetuity" and final_fcff != 0:
                if final_discount_rate > g_effective:
                    terminal_cf = final_fcff * (1 + g_effective)
                    terminal_value_nominal = terminal_cf / (
                        final_discount_rate - g_effective
                    )
                    years_to_terminal = (final_year + 1) - base_year
                    terminal_discount_factor = (1 + final_discount_rate) ** (
                        -years_to_terminal
                    )
                    terminal_value = float(
                        terminal_value_nominal * terminal_discount_factor
                    )

            # Add terminal value row if non-zero
            if terminal_value != 0:
                years_to_terminal = (final_year + 1) - base_year
                terminal_discount_factor = (1 + final_discount_rate) ** (
                    -years_to_terminal
                )
                terminal_row = g.iloc[-1].copy()
                terminal_row["year"] = final_year + 1
                terminal_row["years_from_base"] = years_to_terminal
                terminal_row["discount_factor"] = terminal_discount_factor
                terminal_row["pv_fcff"] = 0.0
                terminal_row["terminal_value"] = terminal_value
                terminal_row["yearly_npv"] = terminal_value

                for fin_col in available_financial_cols:
                    if fin_col in terminal_row.index:
                        terminal_row[fin_col] = 0.0

                g = pd.concat([g, terminal_row.to_frame().T], ignore_index=True)

        # Add metadata to each row (including terminal row if added)
        for col in group_keys:
            if col not in g.columns:
                g[col] = first_row.get(col)

        g["base_year"] = base_year
        g["terminal_method"] = terminal_method
        g["terminal_growth_rate"] = g_effective

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
        # Replace inf/nan from zero baselines with NaN
        change_arr = np.where(np.isfinite(change_arr), change_arr, np.nan)
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
    change_ct = np.where(np.isfinite(change_ct), change_ct, np.nan)
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
    change_c = np.where(np.isfinite(change_c), change_c, np.nan)
    company_npv["npv_change"] = change_c

    logger.info(f"Aggregated to {len(company_npv)} company-level records")

    return company_npv
