"""Asset retirement handling for the asset-level distribution stage.

Builds the per-group retirement lookup, flags assets whose capacity is
permanently phased out by the shock, and freezes the last active capacity of a
retiring asset for downstream reference (ALTR methodology: retirement).
"""
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def flag_phased_out_assets_as_retired(
    dec_staggered: pd.DataFrame,
) -> pd.DataFrame:
    """
    (unchanged)
    """
    GROUP_COLS = ["company_id", "scenario_geography", "sector", "technology"]
    if dec_staggered is None or dec_staggered.empty:
        return dec_staggered

    need = [
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
        "asset_id",
        "year",
        "capacity_after_shock",
        "is_synthetic",
        "late_sudden_phase",
    ]
    miss = [c for c in need if c not in dec_staggered.columns]
    if miss:
        raise ValueError(
            f"dec_staggered missing columns for flagging phased-out assets: {miss}"
        )

    df = dec_staggered.copy()

    df["is_synthetic"] = df["is_synthetic"].fillna(False).astype(bool)
    df["late_sudden_phase"] = df["late_sudden_phase"].fillna("").astype(str)
    df["capacity_after_shock"] = df["capacity_after_shock"].astype(float)

    # Work on real assets only
    real = df[~df["is_synthetic"]]
    if real.empty:
        return df

    key_cols = GROUP_COLS + ["asset_id"]

    # Collect rows (by index) to set as retirement
    to_mark_idx: list[int] = []

    for _, g in real.groupby(key_cols, sort=False):
        g_sorted = g.sort_values("year")
        caps = g_sorted["capacity_after_shock"].to_numpy(dtype=float)
        years = g_sorted["year"].to_numpy(dtype=int)

        if not np.isfinite(caps).any():
            continue
        if np.nanmax(caps) <= 0.0:
            # never positive; skip
            continue

        pos = caps > 0.0
        # future_pos[i] = any(pos[j] for j>=i)
        future_pos = np.maximum.accumulate(pos[::-1])[::-1]
        # positions where no future positives and current is zero -> start of permanent zero suffix
        start_perm_zero = (~future_pos) & (~pos)

        if not start_perm_zero.any():
            continue
        i0 = int(np.argmax(start_perm_zero))  # first True
        # ensure there was a positive before i0
        if i0 == 0 or not pos[:i0].any():
            continue

        retire_year = years[i0]
        # index of the row in the original df corresponding to (asset_id, retire_year)
        row = g_sorted[g_sorted["year"] == retire_year]
        if not row.empty:
            # Get the first matching row's index from the original df
            idx = row.index[0]
            # don't override existing explicit retirement
            current_phase = df.at[idx, "late_sudden_phase"]
            if current_phase != "retirement":
                to_mark_idx.append(idx)

    if to_mark_idx:
        df.loc[to_mark_idx, "late_sudden_phase"] = "retirement"

    return df


def _build_retirement_map(
    assets_retirement_dates: pd.DataFrame,
) -> dict[tuple[str, str, str, str], dict[str, int]]:
    """
    Returns: { (cid, geo, sector, tech): {asset_id: retirement_year_int, ...}, ... }
    Full retirement: capacity must be 0 for y >= retirement_year.
    """
    if assets_retirement_dates is None or assets_retirement_dates.empty:
        return {}
    GROUP_COLS = ["company_id", "scenario_geography", "sector", "technology"]
    need_cols = GROUP_COLS + ["asset_id", "retirement_year"]
    miss = [c for c in need_cols if c not in assets_retirement_dates.columns]
    if miss:
        raise ValueError(f"assets_retirement_dates missing columns: {miss}")

    ret_map: dict[tuple[str, str, str, str], dict[str, int]] = {}
    tmp = assets_retirement_dates[need_cols].copy()

    for key, sub in tmp.groupby(GROUP_COLS, sort=False):
        r = dict(zip(sub["asset_id"].astype(str), sub["retirement_year"].astype(int)))
        ret_map[key] = r
    return ret_map


def create_frozen_capacity_at_retirement(
    asset_level_staggered_shock: pd.DataFrame,
    assets_retirement_dates: pd.DataFrame,
) -> pd.DataFrame:
    """
    Create a dataframe tracking frozen capacity at retirement time for decreasing technologies.

    For each asset that retires:
    - Captures its capacity at the year BEFORE retirement (retirement_year - 1)
    - Extends that frozen capacity constant through all years from retirement onward

    Note: This creates a lookup table that is merged into asset data, but fixed cost
    calculations in compute_ops_block() actually use first-year capacity (initial_capacity),
    not this retirement capacity. This lookup may be used for other purposes or future features.

    Args:
        asset_level_staggered_shock: Wide asset-level dataframe with capacity_after_shock
        assets_retirement_dates: Dataframe with retirement_year for each asset

    Returns:
        DataFrame with columns: asset_id, company_id, scenario_geography, sector,
        technology, year, frozen_capacity_at_retirement
    """
    logger.info("Creating frozen capacity lookup at retirement (for reference; fixed costs use first-year capacity)...")

    # Handle empty inputs
    if assets_retirement_dates is None or assets_retirement_dates.empty:
        logger.warning(
            "No retirement dates provided - returning empty frozen capacity dataframe"
        )
        return pd.DataFrame(
            columns=[
                "asset_id",
                "company_id",
                "scenario_geography",
                "sector",
                "technology",
                "year",
                "frozen_capacity_at_retirement",
            ]
        )

    if asset_level_staggered_shock is None or asset_level_staggered_shock.empty:
        logger.warning(
            "No asset staggered shock data provided - returning empty frozen capacity dataframe"
        )
        return pd.DataFrame(
            columns=[
                "asset_id",
                "company_id",
                "scenario_geography",
                "sector",
                "technology",
                "year",
                "frozen_capacity_at_retirement",
            ]
        )

    # Get asset data with capacity
    assets = asset_level_staggered_shock.copy()

    # Ensure we have required columns
    required_cols = [
        "asset_id",
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
        "year",
    ]
    missing_cols = [col for col in required_cols if col not in assets.columns]
    if missing_cols:
        raise ValueError(
            f"Missing required columns in asset_level_staggered_shock: {missing_cols}"
        )

    # Use capacity_after_shock as the capacity measure
    if "capacity_after_shock" not in assets.columns:
        logger.warning(
            "capacity_after_shock column not found - returning empty frozen capacity dataframe"
        )
        return pd.DataFrame(
            columns=[
                "asset_id",
                "company_id",
                "scenario_geography",
                "sector",
                "technology",
                "year",
                "frozen_capacity_at_retirement",
            ]
        )

    # Merge with retirement dates
    assets_with_retirement = assets.merge(
        assets_retirement_dates[
            [
                "asset_id",
                "company_id",
                "scenario_geography",
                "sector",
                "technology",
                "retirement_year",
            ]
        ],
        on=["asset_id", "company_id", "scenario_geography", "sector", "technology"],
        how="inner",  # Only keep assets that have retirement dates
    )

    if assets_with_retirement.empty:
        logger.warning(
            "No assets found with retirement dates - returning empty frozen capacity dataframe"
        )
        return pd.DataFrame(
            columns=[
                "asset_id",
                "company_id",
                "scenario_geography",
                "sector",
                "technology",
                "year",
                "frozen_capacity_at_retirement",
            ]
        )

    # Capture capacity from the year BEFORE retirement (t-1).
    # At retirement_year (t), capacity is already zeroed by the shock/retirement logic.
    # By taking t-1, we get the last active capacity level to freeze.
    target_year_mask = assets_with_retirement["year"] == (
        assets_with_retirement["retirement_year"] - 1
    )
    retirement_capacity = assets_with_retirement[target_year_mask].copy()

    retirement_capacity["frozen_capacity_at_retirement"] = retirement_capacity[
        "capacity_after_shock"
    ]

    # Keep only the columns we need for the lookup (retirement_year is already
    # merged in above - keep it instead of re-looking it up per asset)
    retirement_capacity = retirement_capacity[
        [
            "asset_id",
            "company_id",
            "scenario_geography",
            "sector",
            "technology",
            "retirement_year",
            "frozen_capacity_at_retirement",
        ]
    ].drop_duplicates()

    # Get all unique years from the asset data to extend through
    all_years = sorted(assets["year"].unique())

    # Complete timeline per retiring asset: cross-join years, keep year >= retirement
    frozen_capacity_df = retirement_capacity.merge(
        pd.DataFrame({"year": all_years}), how="cross"
    )
    frozen_capacity_df = frozen_capacity_df[
        frozen_capacity_df["year"] >= frozen_capacity_df["retirement_year"]
    ][
        [
            "asset_id",
            "company_id",
            "scenario_geography",
            "sector",
            "technology",
            "year",
            "frozen_capacity_at_retirement",
        ]
    ]

    if frozen_capacity_df.empty:
        logger.warning("No frozen capacity records created - returning empty dataframe")
        return pd.DataFrame(
            columns=[
                "asset_id",
                "company_id",
                "scenario_geography",
                "sector",
                "technology",
                "year",
                "frozen_capacity_at_retirement",
            ]
        )

    # Sort for consistency
    frozen_capacity_df = frozen_capacity_df.sort_values(
        ["company_id", "scenario_geography", "sector", "technology", "asset_id", "year"]
    ).reset_index(drop=True)

    logger.info(
        "Created frozen capacity dataframe with %s rows for %s unique assets",
        len(frozen_capacity_df),
        frozen_capacity_df["asset_id"].nunique(),
    )

    return frozen_capacity_df
