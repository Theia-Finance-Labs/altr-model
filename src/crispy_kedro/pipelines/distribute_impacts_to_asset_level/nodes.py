import logging
import numpy as np
import pandas as pd
from typing import Dict, Tuple, List
from tqdm import tqdm

logger = logging.getLogger(__name__)


RESULT_COLS = [
    "asset_id",
    "company_id",
    "scenario_geography",
    "sector",
    "technology",
    "year",
    "asset_age",
    "capacity_before_shock",
    "allocated_shock",
    "capacity_after_shock",
    "is_synthetic",
    "late_sudden_phase",
    "alignment_type",
    "asset_baseline_trajectory",
]


# =========================================================
# ==================== Common helpers =====================
# =========================================================


# ========= NEW: vectorized g-weights core (logistic-sum like your original) =========
def _compute_g_weights_array(
    ages_array: np.ndarray,
    k: float,
    n_quantiles: int,
    for_decreasing: bool,
    min_active_share: float = 1e-12,
) -> np.ndarray:
    """
    Vectorized version of your logistic-sum g(a).
    raw(a) = 1 - sum_q 1/(1+exp(-k*(a - cut_q)))
    If for_decreasing: negate raw so that older => higher after shifting/normalizing.

    Returns a length-A float64 array that sums to 1 (unless A==0).
    """
    A = int(ages_array.shape[0])
    if A == 0:
        return np.zeros((0,), dtype=np.float64)

    ages = ages_array.astype(np.float64, copy=False)
    if n_quantiles <= 1:
        raw = np.ones(A, dtype=np.float64)
    else:
        qs = np.linspace(0.0, 1.0, n_quantiles + 1)[1:-1]  # exclude 0 and 1
        if qs.size == 0:
            raw = np.ones(A, dtype=np.float64)
        else:
            cuts = np.quantile(ages, qs)
            # matrix: [A x Q]
            X = ages[:, None] - cuts[None, :]
            sig = 1.0 / (1.0 + np.exp(-k * X))
            raw = 1.0 - sig.sum(axis=1)

    if for_decreasing:
        raw = -raw

    # shift to positive & normalize
    raw -= np.nanmin(raw)
    raw += float(min_active_share)

    s = np.nansum(raw)
    if not np.isfinite(s) or s <= 0.0:
        return np.full(A, 1.0 / A, dtype=np.float64)
    return raw / s


def _index_company_by_year(
    df_company: pd.DataFrame,
) -> Dict[Tuple[str, str, str, str], pd.DataFrame]:
    GROUP_COLS = ["company_id", "scenario_geography", "sector", "technology"]
    return {
        k: g.sort_values("year").set_index("year")
        for k, g in df_company.groupby(GROUP_COLS, sort=False)
    }


def _build_retirement_map(
    assets_retirement_dates: pd.DataFrame,
) -> Dict[Tuple[str, str, str, str], Dict[str, int]]:
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

    ret_map: Dict[Tuple[str, str, str, str], Dict[str, int]] = {}
    tmp = assets_retirement_dates[need_cols].copy()

    for key, sub in tmp.groupby(GROUP_COLS, sort=False):
        r = dict(zip(sub["asset_id"].astype(str), sub["retirement_year"].astype(int)))
        ret_map[key] = r
    return ret_map


def compute_asset_baseline_trajectories(
    companies_late_sudden_trajectories: pd.DataFrame,
    allocated_assets_to_companies: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compute asset-level baseline trajectories over the full time horizon.

    This replaces the old _bau_fill_assets_until_shock logic but extends it
    to compute BAU trajectories for the entire time horizon, not just until shock year.

    The baseline trajectory represents the BAU (Business-as-Usual) path that assets
    would follow based on company baseline trajectories, with proper scaling and
    forward-filling for missing data.

    Additionally, this function fills missing asset_activity values using the same
    logic, ensuring that the staggered shock functions have complete data.

    Parameters
    ----------
    companies_late_sudden_trajectories : pd.DataFrame
        Company trajectories with columns including:
        - company_id, scenario_geography, sector, technology, year
        - company_trajectory_baseline
        - late_sudden_phase, alignment_type
    allocated_assets_to_companies : pd.DataFrame
        Asset data with columns including:
        - company_id, scenario_geography, sector, technology, asset_id, year
        - asset_activity, asset_age

    Returns
    -------
    pd.DataFrame
        Asset data with added column 'asset_baseline_trajectory' representing
        the full-horizon BAU trajectory for each asset, and filled asset_activity values.
    """
    if allocated_assets_to_companies.empty:
        result = allocated_assets_to_companies.copy()
        result["asset_baseline_trajectory"] = pd.Series(dtype=float)
        return result

    GROUP_COLS = ["company_id", "scenario_geography", "sector", "technology"]

    # Need baseline per (key, year)
    base_cols = GROUP_COLS + ["year", "company_trajectory_baseline"]
    missing = [
        c for c in base_cols if c not in companies_late_sudden_trajectories.columns
    ]
    if missing:
        raise ValueError(
            f"companies_late_sudden_trajectories missing columns for BAU fill: {missing}"
        )

    comp_base = (
        companies_late_sudden_trajectories[base_cols]
        .drop_duplicates(GROUP_COLS + ["year"])
        .rename(columns={"company_trajectory_baseline": "_company_baseline"})
    )

    out = allocated_assets_to_companies.copy()
    out = out.merge(comp_base, on=GROUP_COLS + ["year"], how="left")

    # Group by key + asset
    gcols = GROUP_COLS + ["asset_id"]
    out.sort_values(gcols + ["year"], inplace=True)

    def _compute_baseline_trajectory_and_fill_activity(
        group: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Compute baseline trajectory for a single asset across all years and fill missing asset_activity.

        This replicates the logic from the old _bau_fill_assets_until_shock function:
        1. Use available asset_activity data as anchor points
        2. Scale forward/backward using company baseline trajectory ratios
        3. For post-shock years, fill with constant value from shock year
        4. Forward-fill any remaining missing values
        """
        group = group.copy()

        # Initialize with existing activity
        activity = group["asset_activity"].copy()

        # Find anchor points (years with valid asset_activity data)
        valid_mask = ~activity.isna()
        if not valid_mask.any():
            # No valid data - use zeros
            group["asset_baseline_trajectory"] = 0.0
            group["asset_activity"] = group["asset_activity"].fillna(0.0)
            return group

        # Get company baseline values
        company_baseline = group["_company_baseline"].copy()

        # Fill missing values using baseline scaling where possible
        for idx in group.index[~valid_mask]:
            current_year = group.at[idx, "year"]
            current_baseline = group.at[idx, "_company_baseline"]

            if pd.isna(current_baseline) or current_baseline == 0:
                continue

            # Find nearest valid asset value (prefer earlier years, then later)
            valid_indices = group.index[valid_mask]
            if len(valid_indices) == 0:
                continue

            # Find closest year with valid data
            valid_years = group.loc[valid_indices, "year"]
            year_diffs = abs(valid_years - current_year)
            closest_idx = valid_indices[year_diffs.argmin()]

            anchor_value = group.at[closest_idx, "asset_activity"]
            anchor_baseline = group.at[closest_idx, "_company_baseline"]

            if pd.notna(anchor_baseline) and anchor_baseline != 0:
                # Scale using baseline ratio
                ratio = current_baseline / anchor_baseline
                activity.at[idx] = anchor_value * ratio
            else:
                # Fallback to flat carry
                activity.at[idx] = anchor_value

        # Apply post-shock constant filling logic (like old _bau_fill_assets_until_shock)
        # This ensures years after forecast period get constant values
        activity_filled = activity.copy()

        # Forward fill and then backward fill to handle any remaining gaps
        activity_filled = activity_filled.ffill()

        # If there are still NaN values at the beginning, backward fill
        activity_filled = activity_filled.bfill()

        # Fill any remaining NaN with 0
        activity_filled = activity_filled.fillna(0.0)

        # Set both baseline trajectory and filled asset_activity
        group["asset_baseline_trajectory"] = activity_filled
        group["asset_activity"] = activity_filled

        return group

    # Add progress bar for baseline computation
    grouped = out.groupby(gcols, sort=False, group_keys=False)
    tqdm.pandas(desc="Computing asset baselines and filling activity", unit="asset")
    out = grouped.progress_apply(_compute_baseline_trajectory_and_fill_activity)

    # Clean up helper column
    out.drop(columns=["_company_baseline"], inplace=True)
    return out


def _bau_fill_assets_until_shock(
    lsc: pd.DataFrame,
    assets: pd.DataFrame,
    shock_year: int,
) -> pd.DataFrame:
    """
    (unchanged logic)
    """
    if assets.empty:
        return assets.copy()
    GROUP_COLS = ["company_id", "scenario_geography", "sector", "technology"]
    # Need baseline per (key, year)
    base_cols = GROUP_COLS + ["year", "company_trajectory_baseline"]
    missing = [c for c in base_cols if c not in lsc.columns]
    if missing:
        raise ValueError(
            f"late_sudden_trajectories missing columns for BAU fill: {missing}"
        )

    comp_base = (
        lsc[base_cols]
        .drop_duplicates(GROUP_COLS + ["year"])
        .rename(columns={"company_trajectory_baseline": "_company_baseline"})
    )

    out = assets.copy()
    out = out.merge(comp_base, on=GROUP_COLS + ["year"], how="left")

    # Group by key + asset
    gcols = GROUP_COLS + ["asset_id"]
    out.sort_values(gcols + ["year"], inplace=True)

    def _fill_one(group: pd.DataFrame) -> pd.DataFrame:
        mask_pre = group["year"] <= int(shock_year)
        mask_post = group["year"] > int(shock_year)
        if not (mask_pre.any() or mask_post.any()):
            return group

        # PRE-SHOCK: BAU scaling from last known <= shock_year
        gpre = group.loc[mask_pre].copy()
        if not gpre.empty:
            notna_pre = ~gpre["asset_activity"].isna()
            if notna_pre.any():
                idx0 = gpre.index[notna_pre][-1]  # last non-NA row index <= shock
                y0 = int(group.at[idx0, "year"])
                v0 = float(group.at[idx0, "asset_activity"])  # anchor level
                B0 = (
                    float(group.at[idx0, "_company_baseline"])
                    if pd.notna(group.at[idx0, "_company_baseline"])
                    else np.nan
                )
                if not np.isfinite(B0) or B0 == 0.0:
                    B0 = np.nan  # triggers flat carry if baseline missing/zero

                tgt_pre = (
                    mask_pre & group["asset_activity"].isna() & (group["year"] > y0)
                )
                if tgt_pre.any():
                    if np.isnan(B0).all():
                        group.loc[tgt_pre, "asset_activity"] = v0
                    else:
                        By = group.loc[tgt_pre, "_company_baseline"].astype(float)
                        ratio = (By / B0).fillna(1.0)
                        group.loc[tgt_pre, "asset_activity"] = v0 * ratio.values

        # Determine the shock-year constant level
        v_const = np.nan
        if mask_pre.any():
            # prefer exact shock-year value if present
            at_shock = group["year"] == int(shock_year)
            if at_shock.any():
                v_at_shock = group.loc[at_shock, "asset_activity"].iloc[0]
                if pd.notna(v_at_shock):
                    v_const = float(v_at_shock)
            if not np.isfinite(v_const):
                # fallback to last available <= shock_year
                gpre_filled = group.loc[mask_pre]
                notna_pre_after = ~gpre_filled["asset_activity"].isna()
                if notna_pre_after.any():
                    idx_last = gpre_filled.index[notna_pre_after][-1]
                    v_const = float(group.at[idx_last, "asset_activity"])

        # POST-SHOCK: fill NAs with constant v_const if available
        if mask_post.any() and np.isfinite(v_const):
            tgt_post = mask_post & group["asset_activity"].isna()
            if tgt_post.any():
                group.loc[tgt_post, "asset_activity"] = v_const

        return group

    # Add progress bar for BAU fill operation
    grouped = out.groupby(gcols, sort=False, group_keys=False)
    tqdm.pandas(desc="BAU fill", unit="grp")
    out = grouped.progress_apply(_fill_one)

    # Clean up helper column
    out.drop(columns=["_company_baseline"], inplace=True)
    return out


# ========= NEW: vectorized reduction with caps core + Series wrapper =========
def _allocate_reduction_with_caps_array(
    floors: np.ndarray,  # >= 0
    weights: np.ndarray,  # >= 0, not necessarily normalized
    target: float,  # > 0
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
    for _ in range(32):
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


def _reduce_weighted_with_caps(
    floors: pd.Series,
    g_weights: pd.Series,
    R: float,
) -> pd.Series:
    if R <= 1e-12 or floors.empty:
        return pd.Series(0.0, index=floors.index, dtype=float)
    idx = floors.index
    arr = _allocate_reduction_with_caps_array(
        floors=floors.to_numpy(dtype=float, copy=False),
        weights=g_weights.reindex(idx).fillna(0.0).to_numpy(dtype=float, copy=False),
        target=float(R),
    )
    return pd.Series(arr, index=idx, dtype=float)


# ========= NEW: fast asset indexing & fast emitter =========
def _index_assets_by_group(
    assets: pd.DataFrame,
) -> Dict[Tuple[str, str, str, str], pd.DataFrame]:
    GROUP_COLS = ["company_id", "scenario_geography", "sector", "technology"]
    need = GROUP_COLS + ["asset_id", "year", "asset_activity", "asset_age"]
    miss = [c for c in need if c not in assets.columns]
    if miss:
        raise ValueError(f"assets missing columns: {miss}")

    # Include baseline trajectory if available
    cols_to_keep = ["asset_id", "year", "asset_activity", "asset_age"]
    if "asset_baseline_trajectory" in assets.columns:
        cols_to_keep.append("asset_baseline_trajectory")

    return {
        key: g.sort_values(["year", "asset_id"]).loc[:, cols_to_keep]
        for key, g in assets.groupby(GROUP_COLS, sort=False)
    }


# =========================================================
# ============== DECREASING technologies node =============
# =========================================================


def split_late_sudden_trajectories_by_alignment_type(
    companies_late_sudden_trajectories: pd.DataFrame,
):
    """Return (decreasing_df, increasing_df)."""
    dec_mask = companies_late_sudden_trajectories["alignment_type"].isin(
        ["misaligned_high_carbon", "aligned_high_carbon"]
    )
    inc_mask = companies_late_sudden_trajectories["alignment_type"].isin(
        ["misaligned_low_carbon", "aligned_low_carbon"]
    )
    return (
        companies_late_sudden_trajectories[dec_mask].copy(),
        companies_late_sudden_trajectories[inc_mask].copy(),
    )


def _stagger_decreasing_fast(
    lsc: pd.DataFrame,
    assets_bau: pd.DataFrame,
    assets_retirement_dates: pd.DataFrame,
    shock_year: int,
    alignment_year: int,
    apply_retirement: bool,
    g_k: float,
    n_quantiles: int,
    logger=None,
) -> pd.DataFrame:
    if logger:
        logger.info("Indexing company by year (fast)")
    comp_by_key = _index_company_by_year(lsc)

    if logger:
        logger.info("Building retirement map (fast)")
    ret_map_by_key = _build_retirement_map(assets_retirement_dates)

    if logger:
        logger.info("Indexing assets by group (fast)")
    assets_by_key = _index_assets_by_group(assets_bau)

    out_parts: List[pd.DataFrame] = []

    if logger:
        logger.info("Applying staggered shock (fast)")

    for key, comp_years in tqdm(
        comp_by_key.items(), desc="Stagger decreasing", unit="company"
    ):
        years = comp_years.index.to_numpy(dtype=np.int32)
        if years.size == 0:
            continue

        C = comp_years["company_trajectory_latesudden"].to_numpy(dtype=np.float64)
        comp_phase_by_year = comp_years["late_sudden_phase"].astype(object).to_numpy()
        align_type_by_year = comp_years["alignment_type"].astype(object).to_numpy()

        aset = assets_by_key.get(key)
        if aset is None or aset.empty:
            continue

        asset_ids = aset["asset_id"].astype(str).unique()
        A = asset_ids.shape[0]

        # Build T×A matrices
        act_pvt = aset.pivot(
            index="year", columns="asset_id", values="asset_activity"
        ).reindex(index=years, columns=asset_ids, fill_value=0.0)
        age_pvt = (
            aset.pivot(index="year", columns="asset_id", values="asset_age")
            .reindex(index=years, columns=asset_ids)
            .fillna(0.0)
        )

        # Extract baseline trajectory if available
        baseline_mat = None
        if "asset_baseline_trajectory" in aset.columns:
            baseline_pvt = aset.pivot(
                index="year", columns="asset_id", values="asset_baseline_trajectory"
            ).reindex(index=years, columns=asset_ids, fill_value=0.0)
            baseline_mat = baseline_pvt.to_numpy(dtype=np.float64)  # (T, A)

        base_activity = act_pvt.to_numpy(dtype=np.float64)  # (T, A)
        ages_mat = age_pvt.to_numpy(dtype=np.float64)  # (T, A)

        raw_ret = ret_map_by_key.get(key, {})
        eff_ret_year = np.full(A, np.iinfo(np.int32).max, dtype=np.int32)
        if raw_ret:
            for j, aid in enumerate(asset_ids):
                y_r = raw_ret.get(str(aid))
                if y_r is not None and pd.notna(y_r):
                    eff_ret_year[j] = max(int(y_r), int(alignment_year) + 1)

        dC = np.diff(C, prepend=C[0])
        shock_neg = np.where(years >= int(shock_year), np.minimum(dC, 0.0), 0.0)

        T = years.shape[0]
        before_mat = np.zeros((T, A), dtype=np.float64)
        alloc_mat = np.zeros((T, A), dtype=np.float64)
        after_mat = np.zeros((T, A), dtype=np.float64)
        phase_mat = np.empty((T, A), dtype=object)

        after_prev = None

        for t in range(T):
            y = int(years[t])
            before = (
                base_activity[t, :].copy()
                if (y < int(shock_year) or after_prev is None)
                else after_prev.copy()
            )

            phase_t = np.full(A, comp_phase_by_year[t], dtype=object)

            forced = np.zeros(A, dtype=np.float64)
            if (
                apply_retirement
                and align_type_by_year[t] == "misaligned_high_carbon"
                and y > int(alignment_year)
            ):
                retire_mask = y >= eff_ret_year
                if retire_mask.any():
                    forced[retire_mask] = -before[retire_mask]
                    tag_now = y == eff_ret_year
                    if tag_now.any():
                        phase_t[tag_now] = "retirement"

            remaining = shock_neg[t] - forced.sum()
            extra = np.zeros(A, dtype=np.float64)
            if remaining < -1e-12:
                active = forced >= 0.0
                if np.any(active):
                    floors = np.clip(before[active], 0.0, None)
                    g = _compute_g_weights_array(
                        ages_mat[t, active],
                        k=g_k,
                        n_quantiles=n_quantiles,
                        for_decreasing=True,
                    )
                    extra_active = _allocate_reduction_with_caps_array(
                        floors=floors, weights=g, target=-remaining
                    )
                    extra[active] = extra_active  # negative

            alloc = forced + extra
            after = np.clip(before + alloc, a_min=0.0, a_max=None)

            before_mat[t, :] = before
            alloc_mat[t, :] = alloc
            after_mat[t, :] = after
            phase_mat[t, :] = phase_t

            after_prev = after

        # Simple, uniform output frame
        T, A = after_mat.shape
        output_dict = {
            "asset_id": np.tile(asset_ids.astype(str), T),
            "company_id": key[0],
            "scenario_geography": key[1],
            "sector": key[2],
            "technology": key[3],
            "year": np.repeat(years.astype(int), A),
            "asset_age": ages_mat.ravel(),
            "capacity_before_shock": before_mat.ravel(),
            "allocated_shock": alloc_mat.ravel(),
            "capacity_after_shock": np.maximum(after_mat, 0.0).ravel(),
            "is_synthetic": False,
            "late_sudden_phase": phase_mat.ravel(),
            "alignment_type": np.repeat(align_type_by_year, A),
        }

        # Add baseline trajectory if available
        if baseline_mat is not None:
            output_dict["asset_baseline_trajectory"] = baseline_mat.ravel()
        else:
            output_dict["asset_baseline_trajectory"] = np.nan

        out_parts.append(pd.DataFrame(output_dict))

    if not out_parts:
        return pd.DataFrame(columns=RESULT_COLS)
    return pd.concat(out_parts, ignore_index=True)


def _prop_scale_decreasing_fast(
    lsc: pd.DataFrame,
    assets_bau: pd.DataFrame,
    shock_year: int,
    assets_retirement_dates: pd.DataFrame = None,
    alignment_year: int = None,
    apply_retirement: bool = False,
    logger=None,
) -> pd.DataFrame:
    """
    Proportional-scaling for decreasing techs (fast), with optional retirement integration:
      - From shock_year onward, asset shares are fixed to shock-year shares.
      - If apply_retirement: zero capacity from effective retirement year onward per asset,
        where effective_ret_year = max(retirement_year, alignment_year+1) if alignment_year is provided.
      - After zeroing, chaining is preserved (before[t] = after[t-1]), and allocated = after - before.
      - No redistribution of retired capacity to survivors (sum can fall below company trajectory).
    """
    if logger:
        logger.info("Indexing company by year (prop fast)")
    comp_by_key = _index_company_by_year(lsc)

    if logger:
        logger.info("Indexing assets by group (prop fast)")
    assets_by_key = _index_assets_by_group(assets_bau)

    # Build retirement map once
    ret_map_by_key = (
        _build_retirement_map(assets_retirement_dates)
        if apply_retirement
        and assets_retirement_dates is not None
        and not assets_retirement_dates.empty
        else {}
    )

    out_parts: List[pd.DataFrame] = []

    for key, comp_years in tqdm(
        comp_by_key.items(), desc="Prop-scale decreasing", unit="company"
    ):
        years = comp_years.index.to_numpy(dtype=np.int32)
        if years.size == 0:
            continue

        C = comp_years["company_trajectory_latesudden"].to_numpy(dtype=np.float64)

        comp_phase_by_year = (
            comp_years["late_sudden_phase"].astype(object).to_numpy()
            if "late_sudden_phase" in comp_years.columns
            else np.full(years.shape[0], "", dtype=object)
        )
        align_type_by_year = (
            comp_years["alignment_type"].astype(object).to_numpy()
            if "alignment_type" in comp_years.columns
            else np.full(years.shape[0], "", dtype=object)
        )

        aset = assets_by_key.get(key)
        if aset is None or aset.empty:
            continue

        asset_ids = aset["asset_id"].astype(str).unique()
        A = asset_ids.shape[0]

        act_pvt = aset.pivot(
            index="year", columns="asset_id", values="asset_activity"
        ).reindex(index=years, columns=asset_ids, fill_value=0.0)
        age_pvt = (
            aset.pivot(index="year", columns="asset_id", values="asset_age")
            .reindex(index=years, columns=asset_ids)
            .fillna(0.0)
        )

        # Extract baseline trajectory if available
        baseline_mat = None
        if "asset_baseline_trajectory" in aset.columns:
            baseline_pvt = aset.pivot(
                index="year", columns="asset_id", values="asset_baseline_trajectory"
            ).reindex(index=years, columns=asset_ids, fill_value=0.0)
            baseline_mat = baseline_pvt.to_numpy(dtype=np.float64)  # (T, A)

        base_activity = act_pvt.to_numpy(dtype=np.float64)  # (T, A)
        ages_mat = age_pvt.to_numpy(dtype=np.float64)  # (T, A)

        T = years.shape[0]
        before_mat = np.zeros((T, A), dtype=np.float64)
        after_mat = np.zeros((T, A), dtype=np.float64)
        phase_mat = np.empty((T, A), dtype=object)

        # Shock-year share vector w
        post_mask = years >= int(shock_year)
        t0 = int(np.argmax(post_mask)) if post_mask.any() else None

        pre_mask = years <= int(shock_year)
        if pre_mask.any():
            shock_ref = np.where(pre_mask)[0][-1]
            numer = np.clip(base_activity[shock_ref, :], 0.0, None)
        else:
            numer = np.zeros(A, dtype=np.float64)

        S = float(numer.sum())
        w = (numer / S) if S > 0.0 else np.zeros(A, dtype=np.float64)

        # Build initial before/after/phase (no retirement yet)
        if t0 is None:
            before_mat[:] = base_activity
            after_mat[:] = base_activity
            phase_mat[:] = comp_phase_by_year[:, None]
        else:
            if t0 > 0:
                before_mat[:t0, :] = base_activity[:t0, :]
                after_mat[:t0, :] = base_activity[:t0, :]
                phase_mat[:t0, :] = comp_phase_by_year[:t0, None]

            before_mat[t0, :] = base_activity[t0, :]
            after_mat[t0, :] = w[None, :] * C[t0]
            phase_mat[t0, :] = comp_phase_by_year[t0]

            if t0 + 1 < T:
                # chain: before[t] = after[t-1]
                before_mat[t0 + 1 :, :] = after_mat[t0 : T - 1, :]
                after_mat[t0 + 1 :, :] = C[t0 + 1 :, None] * w[None, :]
                phase_mat[t0 + 1 :, :] = comp_phase_by_year[t0 + 1 :, None]

        # ---------- Integrated retirement (optional) ----------
        if apply_retirement and ret_map_by_key:
            raw_ret = ret_map_by_key.get(key, {})
            if raw_ret:
                # Effective retirement per asset
                eff_ret_year = np.full(A, np.iinfo(np.int32).max, dtype=np.int32)
                for j, aid in enumerate(asset_ids):
                    yr = raw_ret.get(str(aid))
                    if yr is not None and pd.notna(yr):
                        eff_ret_year[j] = int(yr)
                        if alignment_year is not None:
                            eff_ret_year[j] = max(
                                eff_ret_year[j], int(alignment_year) + 1
                            )

                # Zero AFTER from effective retirement onward; tag phase at exact eff year if present
                for j in range(A):
                    eff = eff_ret_year[j]
                    if eff <= years[-1]:
                        mask = years >= eff
                        after_mat[mask, j] = 0.0
                        # tag phase at eff year only if that exact year exists
                        hit = np.where(years == eff)[0]
                        if hit.size > 0:
                            phase_mat[hit[0], j] = "retirement"

                # Recompute BEFORE to preserve chaining rules (pre-shock BAU, post-shock chain)
                if t0 is None:
                    before_mat[:] = base_activity  # all BAU years
                else:
                    if t0 > 0:
                        before_mat[:t0, :] = base_activity[:t0, :]
                    before_mat[t0, :] = base_activity[t0, :]
                    if t0 + 1 < T:
                        before_mat[t0 + 1 :, :] = after_mat[t0 : T - 1, :]

        alloc_mat = after_mat - before_mat

        # Emit
        output_dict = {
            "asset_id": np.tile(asset_ids.astype(str), T),
            "company_id": key[0],
            "scenario_geography": key[1],
            "sector": key[2],
            "technology": key[3],
            "year": np.repeat(years.astype(int), A),
            "asset_age": ages_mat.ravel(),
            "capacity_before_shock": before_mat.ravel(),
            "allocated_shock": alloc_mat.ravel(),
            "capacity_after_shock": np.maximum(after_mat, 0.0).ravel(),
            "is_synthetic": False,
            "late_sudden_phase": phase_mat.ravel(),
            "alignment_type": np.repeat(align_type_by_year, A),
        }

        # Add baseline trajectory if available
        if baseline_mat is not None:
            output_dict["asset_baseline_trajectory"] = baseline_mat.ravel()
        else:
            output_dict["asset_baseline_trajectory"] = np.nan

        out_parts.append(pd.DataFrame(output_dict))

    if not out_parts:
        return pd.DataFrame(columns=RESULT_COLS)
    return pd.concat(out_parts, ignore_index=True)


def stagger_decreasing_technologies(
    late_sudden_trajectories: pd.DataFrame,
    assets_with_baseline_trajectory: pd.DataFrame,
    assets_retirement_dates: pd.DataFrame,
    shock_year: int,
    alignment_year: int,
    apply_retirement: bool,
    apply_decreasing_staggered_shock: bool,
    g_k: float = 6.0,
    n_quantiles: int = 3,
) -> pd.DataFrame:
    """
    Decreasing techs.

    If apply_decreasing_staggered_shock is False: proportional scaling (your original).
    If True: uses the fast, vectorized stagger core above.
    """
    GROUP_COLS = ["company_id", "scenario_geography", "sector", "technology"]
    if not apply_decreasing_staggered_shock:
        need_c = [
            "company_id",
            "scenario_geography",
            "sector",
            "technology",
            "year",
            "company_trajectory_latesudden",
        ]
        miss_c = [c for c in need_c if c not in late_sudden_trajectories.columns]
        if miss_c:
            raise ValueError(f"late_sudden_trajectories missing columns: {miss_c}")

        lsc = late_sudden_trajectories.copy()
        # (Optional but useful) if these columns are absent, we’ll emit empty strings
        if "late_sudden_phase" not in lsc.columns:
            lsc["late_sudden_phase"] = ""
        if "alignment_type" not in lsc.columns:
            lsc["alignment_type"] = ""

        # Use pre-computed BAU trajectory instead of calling _bau_fill_assets_until_shock
        assets = assets_with_baseline_trajectory.copy()
        assets["asset_id"] = assets["asset_id"].astype(str)

        return _prop_scale_decreasing_fast(
            lsc=lsc,
            assets_bau=assets,
            shock_year=int(shock_year),
            assets_retirement_dates=assets_retirement_dates,
            alignment_year=int(alignment_year),
            apply_retirement=bool(apply_retirement),
            logger=logger,
        )

    else:
        # ---------- FAST STAGGERED BRANCH ----------
        need_c = GROUP_COLS + [
            "year",
            "company_trajectory_latesudden",
            "late_sudden_phase",
            "alignment_type",
        ]
        miss_c = [c for c in need_c if c not in late_sudden_trajectories.columns]
        if miss_c:
            raise ValueError(f"late_sudden_trajectories missing columns: {miss_c}")
        need_a = GROUP_COLS + ["asset_id", "year", "asset_activity", "asset_age"]
        miss_a = [c for c in need_a if c not in assets_with_baseline_trajectory.columns]
        if miss_a:
            raise ValueError(
                f"assets_with_baseline_trajectory missing columns: {miss_a}"
            )

        lsc = late_sudden_trajectories.copy()

        logger.info("Using pre-computed asset baseline trajectories")
        assets = assets_with_baseline_trajectory.copy()
        assets["asset_id"] = assets["asset_id"].astype(str)

        return _stagger_decreasing_fast(
            lsc=lsc,
            assets_bau=assets,
            assets_retirement_dates=assets_retirement_dates,
            shock_year=int(shock_year),
            alignment_year=int(alignment_year),
            apply_retirement=apply_retirement,
            g_k=float(g_k),
            n_quantiles=int(n_quantiles),
            logger=logger,
        )


def enforce_retirements_after_alignment(
    dec_df: pd.DataFrame,
    assets_retirement_dates: pd.DataFrame,
    alignment_year: int,
    apply_retirement: bool,
) -> pd.DataFrame:
    """
    (unchanged)
    """
    if dec_df is None or dec_df.empty:
        return dec_df
    if not apply_retirement:
        return dec_df
    if assets_retirement_dates is None or assets_retirement_dates.empty:
        return dec_df
    GROUP_COLS = ["company_id", "scenario_geography", "sector", "technology"]
    need_cols = GROUP_COLS + ["asset_id", "retirement_year"]
    miss = [c for c in need_cols if c not in assets_retirement_dates.columns]
    if miss:
        raise ValueError(f"assets_retirement_dates missing columns: {miss}")

    # Build retirement map
    ret_map = _build_retirement_map(assets_retirement_dates)

    df = dec_df.copy()
    df["asset_id"] = df["asset_id"].astype(str)
    df.sort_values(GROUP_COLS + ["asset_id", "year"], inplace=True)

    def _apply_retire_group(g: pd.DataFrame) -> pd.DataFrame:
        key = (
            g.iloc[0]["company_id"],
            g.iloc[0]["scenario_geography"],
            g.iloc[0]["sector"],
            g.iloc[0]["technology"],
        )
        rdict = ret_map.get(key, {})
        # process each asset independently to preserve chaining
        out_list: List[pd.DataFrame] = []
        for aid, sub in g.groupby("asset_id", sort=False):
            sub = sub.sort_values("year").copy()
            if aid in rdict:
                eff = max(int(rdict[aid]), int(alignment_year) + 1)
                after = sub["capacity_after_shock"].astype(float).to_numpy()
                before = sub["capacity_before_shock"].astype(float).to_numpy()
                years = sub["year"].to_numpy(dtype=int)
                # enforce zeros from eff onward
                if (years >= eff).any():
                    # recompute chain starting at first index where year >= eff
                    start_idx = int(np.argmax(years >= eff))
                    for idx in range(start_idx, len(years)):
                        # before is previous after (or keep original for the first enforced year)
                        if idx == 0:
                            pass
                        else:
                            before[idx] = after[idx - 1]
                        # set after to 0 from eff on
                        after[idx] = 0.0
                        # set late_sudden_phase to "retirement" at the effective retirement year
                        if years[idx] == eff:
                            sub.iloc[idx, sub.columns.get_loc("late_sudden_phase")] = (
                                "retirement"
                            )
                    # also ensure the immediate next year's before equals previous after
                    for idx in range(1, len(years)):
                        before[idx] = after[idx - 1]
                # recompute allocated as after - before
                alloc = after - before
                sub["capacity_before_shock"] = before
                sub["capacity_after_shock"] = after
                sub["allocated_shock"] = alloc
            out_list.append(sub)
        return pd.concat(out_list, ignore_index=True)

    result = df.groupby(GROUP_COLS, sort=False, group_keys=False).apply(
        _apply_retire_group
    )
    return result.reset_index(drop=True)


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
    to_mark_idx: List[int] = []

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


# =========================================================
# ============== INCREASING technologies node =============
# =========================================================


def stagger_increasing_technologies(
    late_sudden_trajectories: pd.DataFrame,
    assets_with_baseline_trajectory: pd.DataFrame,
    shock_year: int,
) -> pd.DataFrame:
    """
    Increasing techs (simple uniform emit):
      - Real assets: BAU passthrough (alloc=0, before=after=BAU).
      - Synthetic: one asset takes max(0, company - S_shock) from shock_year onward.
    """
    GROUP_COLS = ["company_id", "scenario_geography", "sector", "technology"]

    lsc = late_sudden_trajectories.copy()

    # Use pre-computed BAU trajectory instead of calling _bau_fill_assets_until_shock
    assets_bau = assets_with_baseline_trajectory.copy()
    assets_bau["asset_id"] = assets_bau["asset_id"].astype(str)

    comp_by_key = {
        k: g.sort_values("year")[
            [
                "year",
                "company_trajectory_latesudden",
                "late_sudden_phase",
                "alignment_type",
            ]
        ]
        for k, g in lsc.groupby(GROUP_COLS, sort=False)
    }

    parts: List[pd.DataFrame] = []

    for key, comp_years in comp_by_key.items():
        cid, geo, sector, tech = key
        years = comp_years["year"].to_numpy(dtype=np.int32)
        if years.size == 0:
            continue

        # Select asset columns, including baseline trajectory if available
        cols_to_select = ["asset_id", "year", "asset_activity", "asset_age"]
        if "asset_baseline_trajectory" in assets_bau.columns:
            cols_to_select.append("asset_baseline_trajectory")

        aset = assets_bau[
            (assets_bau["company_id"] == cid)
            & (assets_bau["scenario_geography"] == geo)
            & (assets_bau["sector"] == sector)
            & (assets_bau["technology"] == tech)
        ][cols_to_select].copy()

        # ---------- Real assets: BAU passthrough ----------
        if not aset.empty:
            asset_ids = aset["asset_id"].astype(str).unique()
            A = asset_ids.shape[0]

            act_pvt = aset.pivot(
                index="year", columns="asset_id", values="asset_activity"
            ).reindex(index=years, columns=asset_ids, fill_value=0.0)
            age_pvt = (
                aset.pivot(index="year", columns="asset_id", values="asset_age")
                .reindex(index=years, columns=asset_ids)
                .fillna(0.0)
            )

            # Extract baseline trajectory if available
            baseline_mat = None
            if "asset_baseline_trajectory" in aset.columns:
                baseline_pvt = aset.pivot(
                    index="year", columns="asset_id", values="asset_baseline_trajectory"
                ).reindex(index=years, columns=asset_ids, fill_value=0.0)
                baseline_mat = baseline_pvt.to_numpy(dtype=np.float64)  # (T, A)

            base_activity = act_pvt.to_numpy(dtype=np.float64)  # (T, A)
            ages_mat = age_pvt.to_numpy(dtype=np.float64)  # (T, A)

            before_mat = base_activity
            after_mat = base_activity
            alloc_mat = np.zeros_like(before_mat)

            T, A = after_mat.shape
            output_dict = {
                "asset_id": np.tile(asset_ids.astype(str), T),
                "company_id": cid,
                "scenario_geography": geo,
                "sector": sector,
                "technology": tech,
                "year": np.repeat(years.astype(int), A),
                "asset_age": ages_mat.ravel(),
                "capacity_before_shock": before_mat.ravel(),
                "allocated_shock": alloc_mat.ravel(),
                "capacity_after_shock": np.maximum(after_mat, 0.0).ravel(),
                "is_synthetic": False,
                "late_sudden_phase": np.repeat(
                    comp_years["late_sudden_phase"].to_numpy(dtype=object), A
                ),
                "alignment_type": np.repeat(
                    comp_years["alignment_type"].to_numpy(dtype=object), A
                ),
            }

            # Add baseline trajectory if available
            if baseline_mat is not None:
                output_dict["asset_baseline_trajectory"] = baseline_mat.ravel()
            else:
                output_dict["asset_baseline_trajectory"] = np.nan

            parts.append(pd.DataFrame(output_dict))

        # ---------- Synthetic: one asset gets the excess ----------
        synth_id = f"NEW_{cid}_{sector}_{tech}_{geo}"
        if aset.empty:
            S_shock = 0.0
        else:
            shock_slice = aset[aset["year"] == int(shock_year)]
            S_shock = (
                float(shock_slice["asset_activity"].sum())
                if not shock_slice.empty
                else 0.0
            )

        C = comp_years["company_trajectory_latesudden"].to_numpy(dtype=float)
        synth_cap = np.where(
            years >= int(shock_year), np.maximum(0.0, C - S_shock), 0.0
        )
        synth_before = np.concatenate(([0.0], synth_cap[:-1]))
        alloc = synth_cap - synth_before

        pos = synth_cap > 0.0
        if pos.any():
            first_idx = int(np.argmax(pos))
            synth_age = np.where(pos, years - years[first_idx], 0.0).astype(float)
        else:
            synth_age = np.zeros_like(synth_cap, dtype=float)

        synth_output_dict = {
            "asset_id": synth_id,
            "company_id": cid,
            "scenario_geography": geo,
            "sector": sector,
            "technology": tech,
            "year": years.astype(int),
            "asset_age": synth_age,
            "capacity_before_shock": synth_before,
            "allocated_shock": alloc,
            "capacity_after_shock": synth_cap,
            "is_synthetic": True,
            "late_sudden_phase": comp_years["late_sudden_phase"].values,
            "alignment_type": comp_years["alignment_type"].values,
        }

        # For synthetic assets, baseline trajectory is 0 (no historical baseline)
        synth_output_dict["asset_baseline_trajectory"] = np.zeros_like(synth_cap)

        parts.append(pd.DataFrame(synth_output_dict))

    if not parts:
        return pd.DataFrame(columns=RESULT_COLS)
    return pd.concat(parts, ignore_index=True)


def concatenate_staggered_shock_results(
    dec_late_sudden_trajectories: pd.DataFrame,
    inc_late_sudden_trajectories: pd.DataFrame,
) -> pd.DataFrame:
    """
    Concatenate staggered shock results from decreasing and increasing technologies.

    The baseline trajectories are now included directly in the individual
    technology results, so no additional merging is needed.

    Parameters
    ----------
    dec_late_sudden_trajectories : pd.DataFrame
        Results from decreasing technologies staggering (includes asset_baseline_trajectory)
    inc_late_sudden_trajectories : pd.DataFrame
        Results from increasing technologies staggering (includes asset_baseline_trajectory)

    Returns
    -------
    pd.DataFrame
        Combined results with asset_baseline_trajectory column included
    """
    # Simple concatenation - baseline trajectories are already included in both inputs
    assets_staggered_late_sudden = (
        pd.concat(
            [dec_late_sudden_trajectories, inc_late_sudden_trajectories],
            ignore_index=True,
        )
        .reset_index(drop=True)
        .sort_values(
            by=[
                "company_id",
                "scenario_geography",
                "sector",
                "asset_id",
                "technology",
                "year",
            ]
        )
    )

    return assets_staggered_late_sudden
