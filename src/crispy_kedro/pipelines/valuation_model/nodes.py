"""Discounted-cash-flow valuation (stage 7 of the ALTR pipeline).

Converts the per-asset FCFF series from the earnings model into present values:
yearly discounted trajectories plus a terminal value (perpetuity, finite
annuity or stranding-aware, per the ``dcf`` parameter block), then the asset
NPV under each trajectory type and its aggregation to company-technology and
company level. See the ALTR Documentation, valuation section; the NPV sign
conventions are spelled out in the handover user guide.
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_yearly_npv_trajectories(  # noqa: PLR0912, PLR0913, PLR0915, PLR0917
    asset_earnings: pd.DataFrame,
    discount_rate_baseline: float = 0.07,
    discount_rate_shock: float = 0.08,
    terminal_growth_rate: float = 0.02,
    terminal_growth_rate_brown: float | None = None,
    terminal_growth_rate_green: float | None = None,
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
    # Until that upstream defect is fixed the rows are dropped, but loudly: a
    # silent dropna hid ~200 rows per production run with no way to trace them
    # back to the sectors/technologies whose scenario mapping is broken.
    missing_scenario = npv_data["scenario_type"].isna()
    n_missing_scenario = int(missing_scenario.sum())
    if n_missing_scenario > 0:
        combo_cols = [
            c
            for c in ("scenario_geography", "sector", "technology")
            if c in npv_data.columns
        ]
        combos = (
            npv_data.loc[missing_scenario, combo_cols].drop_duplicates()
            if combo_cols
            else pd.DataFrame()
        )
        logger.error(
            "Dropping %d rows with missing scenario_type (see TODO above: some "
            "assets have no scenario associated; MUST FIX upstream). Affected "
            "(scenario_geography, sector, technology) combinations — %d unique, "
            "showing up to 20: %s",
            n_missing_scenario,
            len(combos),
            list(combos.head(20).itertuples(index=False, name=None)),
        )
    npv_data = npv_data.loc[~missing_scenario].reset_index(drop=True)

    # Determine technology type for discount rate differentiation
    carbontech_alignments = {"misaligned_high_carbon", "aligned_high_carbon"}

    # Discount rate: baseline vs shock base, plus the technology spread.
    # Vectorised equivalent of the former row-wise apply.
    base_rate = np.where(
        (npv_data["scenario_type"] == "baseline").to_numpy(),
        discount_rate_baseline,
        discount_rate_shock,
    )
    if "alignment_type" in npv_data.columns:
        is_carbontech_row = (
            npv_data["alignment_type"].isin(carbontech_alignments).to_numpy()
        )
    else:
        is_carbontech_row = np.zeros(len(npv_data), dtype=bool)
    green_rate = (
        base_rate - green_discount_spread if green_discount_spread > 0 else base_rate
    )
    npv_data["discount_rate"] = np.where(
        is_carbontech_row, base_rate + brown_discount_spread, green_rate
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

    # Collapse CapEx flow-split rows to ONE row per asset-year before any
    # row-indexed logic runs. Upstream, compute_capacity_flows emits separate
    # component rows per (asset, year) — operating, decommissioning, rollover —
    # and their FCFFs sum correctly for present value, but the terminal-value
    # anchor (last N ROWS), the normalization window and the stranding check
    # (N consecutive loss rows) all assume one row per year. In the 2026-08
    # WITCH audit 38% of asset-trajectories carried duplicate years in the
    # anchor zone, corrupting 3,414 nonzero terminal values.
    agg_map = {col: "sum" for col in available_financial_cols}
    agg_map["discount_rate"] = "first"
    pre_rows = len(npv_data)
    npv_data = (
        npv_data.groupby(group_keys + ["year"], dropna=False, as_index=False)
        .agg(agg_map)
    )
    if len(npv_data) != pre_rows:
        logger.info(
            "Collapsed %d flow-split rows into %d unique asset-year rows "
            "before terminal-value computation",
            pre_rows,
            len(npv_data),
        )

    # ------------------------------------------------------------------
    # Vectorised trajectory + terminal-value computation.
    #
    # This replaces a per-group Python loop measured at ~1.55 ms/group, i.e.
    # ~60 s per production run at ~40k groups. Semantics are unchanged and
    # pinned by tests/test_npv_vectorized_equivalence.py, which re-implements
    # the old loop and asserts frame equality across every terminal-value
    # branch (stranded / finite annuity / perpetuity / r <= g / no TV).
    # ------------------------------------------------------------------

    # Group ids in the order the old groupby(sort=True) iterated, then sort rows
    # by (group, year) so every group is one contiguous, year-ordered block.
    # dropna=False keeps assets whose group keys contain NaN: the collapse above
    # already keeps them, and pandas' default silently discarded them here.
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
    # Distance from the end of each group — the old code's `.iloc[-n:]` windows.
    pos_from_end = sizes[gid] - 1 - (np.arange(n_rows) - starts[gid])

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
    npv_data["years_from_base"] = years_from_base
    npv_data["discount_factor"] = discount_factor
    npv_data["pv_fcff"] = fcff * discount_factor
    npv_data["terminal_value"] = 0.0
    npv_data["yearly_npv"] = npv_data["pv_fcff"]

    # Per-group terminal anchors, all taken from the last (highest-year) row.
    final_year = years[last_idx].astype(np.int64)
    final_discount_rate = discount_rate[last_idx]
    if "alignment_type" in npv_data.columns:
        is_carbontech = (
            npv_data["alignment_type"]
            .iloc[last_idx]
            .isin(carbontech_alignments)
            .to_numpy()
        )
    else:
        is_carbontech = np.zeros(n_groups, dtype=bool)

    # Normalized terminal FCFF: mean of the last min(window, group_size) rows.
    # min() is implicit — pos_from_end never reaches group_size.
    window_mask = pos_from_end < terminal_normalization_window
    final_fcff = (
        pd.Series(fcff[window_mask])
        .groupby(gid[window_mask])
        .mean()  # NaN-skipping, matching the old Series.mean()
        .reindex(np.arange(n_groups))
        .to_numpy()
    )

    # Select the technology-appropriate terminal growth rate. Kept outside the
    # terminal-value block because the old code wrote it onto every row of the
    # group whether or not a terminal row was ultimately added.
    if terminal_method == "perpetuity":
        g_effective = np.where(is_carbontech, g_brown, g_green).astype(np.float64)
    else:
        g_effective = np.full(n_groups, float(terminal_growth_rate))
    npv_data["terminal_growth_rate"] = g_effective[gid]

    terminal_value = np.zeros(n_groups, dtype=np.float64)
    if terminal_method == "perpetuity" and n_groups:
        # NaN != 0 is True — same as the old float comparison.
        has_terminal_fcff = final_fcff != 0
        terminal_cf = final_fcff * (1.0 + g_effective)
        years_to_terminal = (final_year + 1) - base_year_per_group

        if stranding_aware_tv:
            # Stranded: loss-making for N consecutive years at the horizon end
            # (Gourdel 2024) — a rational owner shuts down, so TV = 0.
            strand_mask = pos_from_end < stranding_consecutive_years
            is_stranded = (
                pd.Series(fcff[strand_mask] <= 0)
                .groupby(gid[strand_mask])
                .all()
                .reindex(np.arange(n_groups), fill_value=False)
                .to_numpy()
                .astype(bool)
            )
            stranded = has_terminal_fcff & is_stranded
            # Declining but still profitable carbontech: finite annuity over the
            # remaining economic life instead of a perpetuity.
            annuity = (
                has_terminal_fcff & ~is_stranded & is_carbontech & (final_fcff > 0)
            )
            # Annuity factor accumulated in the same order as the old
            # sum(1 / (1 + r) ** t for t in 1..N) generator.
            annuity_factor = np.zeros(n_groups, dtype=np.float64)
            for t in range(1, brown_remaining_life_years + 1):
                annuity_factor = annuity_factor + 1.0 / (1.0 + final_discount_rate) ** t
            # The annuity factor already discounts t=1..N back to final_year, so
            # discount from final_year (not final_year + 1) to base_year.
            annuity_tv = (
                terminal_cf
                * annuity_factor
                * (1.0 + final_discount_rate) ** (-(final_year - base_year_per_group))
            )
            terminal_value = np.where(annuity, annuity_tv, terminal_value)
        else:
            stranded = np.zeros(n_groups, dtype=bool)
            annuity = np.zeros(n_groups, dtype=bool)

        # Gordon Growth perpetuity for everything else, only where r > g.
        with np.errstate(divide="ignore", invalid="ignore"):
            perpetuity_tv = (terminal_cf / (final_discount_rate - g_effective)) * (
                1.0 + final_discount_rate
            ) ** (-years_to_terminal)
        perpetuity = (
            has_terminal_fcff
            & ~stranded
            & ~annuity
            & (final_discount_rate > g_effective)
        )
        terminal_value = np.where(perpetuity, perpetuity_tv, terminal_value)

    # One terminal row per group with a non-zero terminal value, built as a
    # single frame (the old per-group Series.to_frame().T forced object dtype).
    add_groups = np.flatnonzero(terminal_value != 0)
    if len(add_groups):
        anchors = last_idx[add_groups]
        years_to_terminal = (final_year[add_groups] + 1) - base_year_per_group[
            add_groups
        ]
        terminal_rows = npv_data.iloc[anchors].copy()
        terminal_rows["year"] = final_year[add_groups] + 1
        terminal_rows["years_from_base"] = years_to_terminal
        terminal_rows["discount_factor"] = (
            1.0 + final_discount_rate[add_groups]
        ) ** (-years_to_terminal)
        terminal_rows["pv_fcff"] = 0.0
        terminal_rows["terminal_value"] = terminal_value[add_groups]
        terminal_rows["yearly_npv"] = terminal_value[add_groups]
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


def calculate_npv_per_asset(  # noqa: PLR0912
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

    # Aggregate by asset and trajectory type. dropna=False: the upstream
    # collapse and trajectory groupbys keep NaN group keys, so dropping them
    # here would make those assets disappear between two nodes with no warning.
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
        if isinstance(col, tuple) and len(col) == 2:  # noqa: PLR2004 — (value, trajectory_type) pair
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
            else:  # noqa: PLR5501 — comment documents the branch; left as-is
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

    company_tech_npv = (
        asset_npv.groupby(groupby_cols, dropna=False).agg(agg_funcs).reset_index()
    )

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
        company_technology_npv.groupby(groupby_cols, dropna=False)
        .agg(agg_funcs)
        .reset_index()
    )

    with np.errstate(divide="ignore", invalid="ignore"):
        base_c = company_npv["baseline_npv"].to_numpy(dtype=np.float64)
        shock_c = company_npv["latesudden_npv"].to_numpy(dtype=np.float64)
        change_c = np.true_divide((shock_c - base_c), abs(base_c))
    change_c = np.where(np.isfinite(change_c), change_c, np.nan)
    company_npv["npv_change"] = change_c

    logger.info(f"Aggregated to {len(company_npv)} company-level records")

    return company_npv
