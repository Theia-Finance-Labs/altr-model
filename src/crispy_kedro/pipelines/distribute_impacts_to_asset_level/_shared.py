"""Shared array/indexing helpers for the asset-level distribution stage.

Used by both the decreasing- and increasing-technology staggering modules:
group indexing of the asset panel and the capped reduction allocator that
spreads a company-level cut across assets without driving any below zero.
"""
# ruff: noqa: PLR2004 — 1e-12 is the float tolerance used throughout this module

import numpy as np
import pandas as pd


# ========= NEW: vectorized reduction with caps core + Series wrapper =========
def _allocate_reduction_with_caps_array(
    floors: np.ndarray,  # >= 0
    weights: np.ndarray,  # >= 0, not necessarily normalized
    target: float,  # > 0
    n_iterations: int = 32,
) -> np.ndarray:
    """
    Vectorized clamp-and-redistribute across assets (few iterations).
    Returns negative allocations summing to -target (within eps) unless saturated.
    """
    A = floors.shape[0]
    if A == 0 or target <= 1e-12:
        return np.zeros((A,), dtype=np.float64)

    cap = np.clip(floors.astype(np.float64, copy=True), 0.0, None)
    w = np.clip(weights.astype(np.float64, copy=True), 0.0, None)
    alloc = np.zeros((A,), dtype=np.float64)

    remaining = float(target)
    # Avoid runaway loops; saturations reduce active set quickly
    for _ in range(n_iterations):
        if remaining <= 1e-12:
            break
        active = cap > 1e-12
        if not np.any(active):
            break

        w_active = w[active]
        s = w_active.sum()
        if s <= 0.0:
            # equal split among actives
            take = np.full(active.sum(), remaining / active.sum(), dtype=np.float64)
        else:
            take = remaining * (w_active / s)

        cap_active = cap[active]
        taken = np.minimum(take, cap_active)
        alloc[active] += taken
        cap[active] = cap_active - taken
        remaining -= float(taken.sum())

        # Zero out weights for saturated assets next round
        sat_mask = cap[active] <= 1e-12
        if np.any(sat_mask):
            w_active[sat_mask] = 0.0
            w[active] = w_active

        # If no one saturated this round, we're done
        if np.all(taken < cap_active - 1e-12):
            break

    return -alloc  # negative reductions


# ========= NEW: fast asset indexing & fast emitter =========
def _index_assets_by_group(
    assets: pd.DataFrame,
) -> dict[tuple[str, str, str, str], pd.DataFrame]:
    GROUP_COLS = ["company_id", "scenario_geography", "sector", "technology"]
    need = GROUP_COLS + ["asset_id", "year", "asset_activity", "asset_age"]
    miss = [c for c in need if c not in assets.columns]
    if miss:
        raise ValueError(f"assets missing columns: {miss}")

    # Include optional columns if available
    cols_to_keep = ["asset_id", "year", "asset_activity", "asset_age"]
    if "asset_name" in assets.columns:
        cols_to_keep.append("asset_name")
    if "asset_baseline_trajectory" in assets.columns:
        cols_to_keep.append("asset_baseline_trajectory")

    return {
        key: g.sort_values(["year", "asset_id"]).loc[:, cols_to_keep]
        for key, g in assets.groupby(GROUP_COLS, sort=False)
    }
