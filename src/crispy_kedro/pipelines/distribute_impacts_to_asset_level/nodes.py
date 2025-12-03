import logging
import numpy as np
import pandas as pd
from typing import Dict, Tuple, List
from tqdm import tqdm

logger = logging.getLogger(__name__)


def split_late_sudden_trajectories_by_alignment_type(
    companies_late_sudden_trajectories: pd.DataFrame,
):
    """Return (decreasing_df, increasing_df) filtered to L&S only.

    Expects a melted structure with columns including 'trajectory_type' and
    'company_trajectory'. Only rows with trajectory_type == 'latesudden' are
    considered for decreasing/increasing splitting.

    All companies are assigned to either decreasing or increasing based on alignment_type.
    Companies with missing or unrecognized alignment_type are assigned based on fallback logic.
    """
    # Build a company_name map from the full input (not just latesudden)
    df = companies_late_sudden_trajectories.copy()
    if "trajectory_type" in df.columns:
        df = df[df["trajectory_type"] == "latesudden"].copy()

    # Primary decreasing tech alignment types
    dec_mask = df["alignment_type"].isin(
        ["misaligned_high_carbon", "aligned_high_carbon"]
    )

    # Split into decreasing and increasing technologies
    decreasing_df = df[dec_mask].copy()
    increasing_df = df[~dec_mask].copy()

    logger.info(
        f"Split trajectories: {len(decreasing_df)} decreasing tech rows, "
        f"{len(increasing_df)} increasing tech rows"
    )

    return (decreasing_df, increasing_df)


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


def concatenate_staggered_shock_results(
    dec_late_sudden_trajectories: pd.DataFrame,  # asset-level (decreasing)
    inc_late_sudden_trajectories: pd.DataFrame,  # asset-level (increasing)
    increasing_tech_late_sudden_trajectories: pd.DataFrame,  # company-level (increasing)
    decreasing_tech_late_sudden_trajectories_corrected: pd.DataFrame,  # company-level corrections (decreasing)
    original_companies_late_sudden_trajectories: pd.DataFrame,  # company-level original trajectories
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns:
      - assets_staggered_late_sudden: concatenated asset-level outputs (dec + inc).
      - companies_late_sudden_trajectories: original companies df + dec corrections + inc trajectories.

    Assumes upstream nodes already propagated company_name; only performs minimal fallback fill.
    """
    KEY = ["company_id", "scenario_geography", "sector", "technology", "year"]

    assets_staggered_late_sudden = pd.concat(
        [dec_late_sudden_trajectories, inc_late_sudden_trajectories], ignore_index=True
    )

    # Process decreasing tech corrections: keep BOTH 'latesudden_original' and 'latesudden_adjusted'
    # to enable plotting of both series downstream. Do not rename types here.
    decreasing_corrected = decreasing_tech_late_sudden_trajectories_corrected.copy()

    companies_late_sudden_trajectories = pd.concat(
        [
            increasing_tech_late_sudden_trajectories,
            decreasing_corrected,
        ],
        ignore_index=True,
    )
    companies_late_sudden_trajectories = companies_late_sudden_trajectories.loc[
        :,
        [
            "company_id",
            "company_name",
            "scenario_geography",
            "sector",
            "technology",
            "year",
            "trajectory_type",
            "company_trajectory",
            "late_sudden_phase",
            "alignment_type",
        ],
    ]

    sort_cols = [c for c in KEY if c in companies_late_sudden_trajectories.columns]
    if sort_cols:
        companies_late_sudden_trajectories = (
            companies_late_sudden_trajectories.sort_values(sort_cols).reset_index(
                drop=True
            )
        )

    # Final set: include all late-sudden variants available (original, adjusted, generic) and baseline
    companies_late_sudden_trajectories_final = pd.concat(
        [
            companies_late_sudden_trajectories[
                companies_late_sudden_trajectories["trajectory_type"].isin(
                    [
                        "latesudden",
                        "latesudden_original",
                        "latesudden_adjusted",
                    ]
                )
            ],
            original_companies_late_sudden_trajectories.query(
                "trajectory_type == 'baseline'"
            ),
        ],
        ignore_index=True,
    ).reset_index(drop=True)

    return assets_staggered_late_sudden, companies_late_sudden_trajectories_final


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
    GROUP_COLS = [
        "company_id",
        "company_name",
        "scenario_geography",
        "sector",
        "technology",
    ]
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
    assets_retirement_dates: pd.DataFrame = None,
    apply_retirement: bool = False,
    alignment_year: int = None,
) -> pd.DataFrame:
    """
    Compute asset-level baseline trajectories over the full time horizon (melted input).

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
        Melted company trajectories with columns including:
        - company_id, scenario_geography, sector, technology, year
        - trajectory_type ('baseline' row required)
        - company_trajectory (values)
        - late_sudden_phase, alignment_type (optional for this routine)
    allocated_assets_to_companies : pd.DataFrame
        Asset data with columns including:
        - company_id, scenario_geography, sector, technology, asset_id, year
        - asset_activity, asset_age
    assets_retirement_dates : pd.DataFrame, optional
        Retirement dates for assets
    apply_retirement : bool, optional
        Whether to apply retirement zeroing to baseline trajectories
    alignment_year : int, optional
        Alignment year for retirement (retirement cannot occur before alignment_year + 1)

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

    GROUP_COLS = [
        "company_id",
        "company_name",
        "scenario_geography",
        "sector",
        "technology",
    ]

    # Expect melted input: filter baseline rows and rename
    need_cols = GROUP_COLS + ["year", "trajectory_type", "company_trajectory"]
    miss = [c for c in need_cols if c not in companies_late_sudden_trajectories.columns]
    if miss:
        raise ValueError(
            f"companies_late_sudden_trajectories missing columns for BAU fill: {miss}"
        )

    comp_base = (
        companies_late_sudden_trajectories[
            companies_late_sudden_trajectories["trajectory_type"] == "baseline"
        ][GROUP_COLS + ["year", "company_trajectory"]]
        .drop_duplicates(GROUP_COLS + ["year"])
        .rename(columns={"company_trajectory": "_company_baseline"})
    )

    out = allocated_assets_to_companies.copy()
    out = out.merge(
        comp_base,
        on=["company_id", "scenario_geography", "sector", "technology", "year"],
        how="left",
    )

    # Group by key + asset
    gcols = ["company_id", "scenario_geography", "sector", "technology", "asset_id"]
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

    # Apply retirement to baseline trajectories if requested
    if (
        apply_retirement
        and assets_retirement_dates is not None
        and not assets_retirement_dates.empty
    ):
        logger.info("Applying retirement to baseline trajectories")

        # Vectorized approach: merge retirement dates and apply in bulk
        # Prepare retirement DataFrame with matching columns
        retirement_df = assets_retirement_dates[
            [
                "company_id",
                "scenario_geography",
                "sector",
                "technology",
                "asset_id",
                "retirement_year",
            ]
        ].copy()

        # Convert asset_id to string for consistent matching
        retirement_df["asset_id"] = retirement_df["asset_id"].astype(str)

        # Calculate effective retirement year (cannot be before alignment_year + 1)
        retirement_df["eff_retirement_year"] = retirement_df["retirement_year"].astype(
            int
        )
        if alignment_year is not None:
            retirement_df["eff_retirement_year"] = retirement_df[
                "eff_retirement_year"
            ].clip(lower=int(alignment_year) + 1)

        # Merge retirement info with output DataFrame
        # Use left merge to keep all rows from out, adding retirement info where available
        # Convert asset_id to string temporarily for consistent merging
        out_asset_id_original = out["asset_id"]
        out["asset_id"] = out["asset_id"].astype(str)

        try:
            out_with_retirement = out.merge(
                retirement_df[
                    [
                        "company_id",
                        "scenario_geography",
                        "sector",
                        "technology",
                        "asset_id",
                        "eff_retirement_year",
                    ]
                ],
                on=[
                    "company_id",
                    "scenario_geography",
                    "sector",
                    "technology",
                    "asset_id",
                ],
                how="left",
                suffixes=("", "_retirement"),
            )
        finally:
            # Restore original asset_id dtype
            out["asset_id"] = out_asset_id_original

        # Vectorized mask: zero out rows where year >= effective retirement year
        retirement_mask = out_with_retirement["eff_retirement_year"].notna() & (
            out_with_retirement["year"] >= out_with_retirement["eff_retirement_year"]
        )

        # Apply retirement zeroing using vectorized assignment
        # retirement_mask has the same index as out (left merge preserves left index)
        out.loc[retirement_mask, "asset_baseline_trajectory"] = 0.0
        out.loc[retirement_mask, "asset_activity"] = 0.0

    # Clean up helper column
    out.drop(columns=["_company_baseline"], inplace=True)
    return out


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
) -> Dict[Tuple[str, str, str, str], pd.DataFrame]:
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


# =========================================================
# ============== DECREASING technologies node =============
# =========================================================


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
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Vectorized staggered allocation for decreasing technologies, with retirement-compensation:
      - When an asset retires at year t (> alignment_year), the freed capacity at t is
        spread uniformly over remaining future years of the company's series.
      - This creates an *adjusted* company L&S path C_adj. We compute reductions with C_adj.
      - We return both the asset-level allocations and a per-company/year correction table:
            correction = C_adj - C_base
    """
    # Expect melted input; filter to latesudden
    if "trajectory_type" in lsc.columns:
        lsc = lsc[lsc["trajectory_type"] == "latesudden"].copy()

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
    corr_parts: List[pd.DataFrame] = []

    if logger:
        logger.info(
            "Applying staggered shock (fast) with retirement-compensation uplift"
        )

    for key, comp_years in tqdm(
        comp_by_key.items(), desc="Stagger decreasing", unit="company"
    ):
        years = comp_years.index.to_numpy(dtype=np.int32)
        if years.size == 0:
            continue

        # Extract company info from key: (company_id, company_name, scenario_geography, sector, technology)
        company_id, company_name, scenario_geography, sector, technology = key

        # Base & adjusted company trajectories
        C_base = comp_years["company_trajectory"].to_numpy(dtype=np.float64)
        C_adj = C_base.copy()

        comp_phase_by_year = comp_years["late_sudden_phase"].astype(object).to_numpy()
        align_type_by_year = comp_years["alignment_type"].astype(object).to_numpy()

        # Extract 4-element key for asset lookup: (company_id, scenario_geography, sector, technology)
        asset_key = (company_id, scenario_geography, sector, technology)
        aset = assets_by_key.get(asset_key)
        if aset is None or aset.empty:
            # Still emit corrections (all zeros) for this key
            corr_parts.append(
                pd.DataFrame(
                    {
                        "company_id": company_id,
                        "company_name": np.repeat(company_name, years.shape[0]),
                        "scenario_geography": scenario_geography,
                        "sector": sector,
                        "technology": technology,
                        "year": years.astype(int),
                        "company_trajectory_latesudden_original": C_base,
                        "company_trajectory_latesudden_adjusted": C_adj,
                        "late_sudden_phase": comp_phase_by_year,
                        "alignment_type": align_type_by_year,
                    }
                )
            )
            continue

        asset_ids = aset["asset_id"].astype(str).unique()
        A = asset_ids.shape[0]
        if "asset_name" in aset.columns:
            name_map = (
                aset.drop_duplicates("asset_id")
                .set_index("asset_id")["asset_name"]
                .astype(str)
            )
            asset_names = name_map.reindex(asset_ids, fill_value="").to_numpy()
        else:
            asset_names = np.array([""] * A, dtype=object)

        # Build matrices
        act_pvt = aset.pivot(
            index="year", columns="asset_id", values="asset_activity"
        ).reindex(index=years, columns=asset_ids, fill_value=0.0)
        age_pvt = (
            aset.pivot(index="year", columns="asset_id", values="asset_age")
            .reindex(index=years, columns=asset_ids)
            .fillna(0.0)
        )

        baseline_mat = None
        if "asset_baseline_trajectory" in aset.columns:
            baseline_pvt = aset.pivot(
                index="year", columns="asset_id", values="asset_baseline_trajectory"
            ).reindex(index=years, columns=asset_ids, fill_value=0.0)
            baseline_mat = baseline_pvt.to_numpy(dtype=np.float64)

        base_activity = act_pvt.to_numpy(dtype=np.float64)  # (T, A)
        ages_mat = age_pvt.to_numpy(dtype=np.float64)  # (T, A)

        # Retirement map → effective years (per asset)
        raw_ret = ret_map_by_key.get(asset_key, {})
        eff_ret_year = np.full(A, np.iinfo(np.int32).max, dtype=np.int32)
        if raw_ret:
            for j, aid in enumerate(asset_ids):
                y_r = raw_ret.get(str(aid))
                if y_r is not None and pd.notna(y_r):
                    eff_ret_year[j] = max(int(y_r), int(alignment_year) + 1)

        T = years.shape[0]
        before_mat = np.zeros((T, A), dtype=np.float64)
        alloc_mat = np.zeros((T, A), dtype=np.float64)
        after_mat = np.zeros((T, A), dtype=np.float64)
        phase_mat = np.empty((T, A), dtype=object)

        after_prev = None

        for t in range(T):
            y = int(years[t])

            # REDUCTION required this year from adjusted series
            prev_C = C_adj[t - 1] if t > 0 else C_adj[t]
            dC = C_adj[t] - prev_C
            shock_neg_t = np.minimum(dC, 0.0) if y >= int(shock_year) else 0.0

            # BEFORE chaining
            before = (
                base_activity[t, :].copy()
                if (y < int(shock_year) or after_prev is None)
                else after_prev.copy()
            )

            phase_t = np.full(A, comp_phase_by_year[t], dtype=object)

            # Forced retirements + **NEW uplift to C_adj for future years**
            forced = np.zeros(A, dtype=np.float64)
            if apply_retirement and y > int(alignment_year):
                retire_mask = y >= eff_ret_year
                if retire_mask.any():
                    # Force to zero now
                    forced[retire_mask] = -before[retire_mask]

                    # Tag retirement exactly at the effective year
                    tag_now = y == eff_ret_year
                    if tag_now.any():
                        phase_t[tag_now] = "retirement"

                    # REMOVED: Retirement compensation logic
                    # This was adding freed capacity back to C_adj, causing unintended revenue boosts.
                    # Commenting out as per user request.
                    # freed_total = float(np.clip(before[retire_mask], 0.0, None).sum())
                    # remaining = T - (t + 1)
                    # if freed_total > 0.0 and remaining > 0:
                    #     per_year_add = freed_total / remaining
                    #     C_adj[t + 1 :] = C_adj[t + 1 :] + per_year_add

            # Remaining reduction to allocate via caps + g-weights
            remaining_to_cut = shock_neg_t - forced.sum()
            extra = np.zeros(A, dtype=np.float64)
            if remaining_to_cut < -1e-12:
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
                        floors=floors, weights=g, target=-remaining_to_cut
                    )
                    extra[active] = extra_active  # negative

            alloc = forced + extra
            after = np.clip(before + alloc, a_min=0.0, a_max=None)

            before_mat[t, :] = before
            alloc_mat[t, :] = alloc
            after_mat[t, :] = after
            phase_mat[t, :] = phase_t

            after_prev = after

        # ——— Emit assets
        T, A = after_mat.shape
        output_dict = {
            "asset_id": np.tile(asset_ids.astype(str), T),
            "asset_name": np.tile(asset_names, T),
            "company_id": company_id,
            "company_name": company_name,
            "scenario_geography": scenario_geography,
            "sector": sector,
            "technology": technology,
            "year": np.repeat(years.astype(int), A),
            "asset_age": ages_mat.ravel(),
            "capacity_before_shock": before_mat.ravel(),
            "allocated_shock": alloc_mat.ravel(),
            "capacity_after_shock": np.maximum(after_mat, 0.0).ravel(),
            "is_synthetic": False,
            "late_sudden_phase": phase_mat.ravel(),
            "alignment_type": np.repeat(align_type_by_year, A),
        }
        if baseline_mat is not None:
            output_dict["asset_baseline_trajectory"] = baseline_mat.ravel()
        else:
            output_dict["asset_baseline_trajectory"] = np.nan
        out_parts.append(pd.DataFrame(output_dict))

        # ——— Emit corrections
        base_df = pd.DataFrame(
            {
                "company_id": company_id,
                "company_name": np.repeat(company_name, years.shape[0]),
                "scenario_geography": scenario_geography,
                "sector": sector,
                "technology": technology,
                "year": years.astype(int),
                "trajectory_type": "latesudden_original",
                "company_trajectory": C_base,
                "late_sudden_phase": comp_phase_by_year,
                "alignment_type": align_type_by_year,
            }
        )
        adj_df = base_df.copy()
        adj_df["trajectory_type"] = "latesudden_adjusted"
        adj_df["company_trajectory"] = C_adj
        corr_parts.append(pd.concat([base_df, adj_df], ignore_index=True))

    assets_df = pd.concat(out_parts, ignore_index=True)
    corrections_df = (
        pd.concat(corr_parts, ignore_index=True)
        if corr_parts
        else pd.DataFrame(
            columns=[
                "company_id",
                "company_name",
                "scenario_geography",
                "sector",
                "technology",
                "year",
                "trajectory_type",
                "company_trajectory",
                "late_sudden_phase",
                "alignment_type",
            ]
        )
    )
    return assets_df, corrections_df


def _prop_scale_decreasing_fast(
    lsc: pd.DataFrame,
    assets_bau: pd.DataFrame,
    shock_year: int,
    assets_retirement_dates: pd.DataFrame = None,
    alignment_year: int = None,
    apply_retirement: bool = False,
    logger=None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Proportional-scaling for decreasing techs (fast), with retirement-compensation uplift:
      - Shares fixed at shock-year (w). AFTER[t] = w * C_adj[t] for t >= shock_year.
      - If an asset retires at year t (> alignment_year), we *pre-uplift* C_adj[t+1..]
        by (freed_t / remaining_years), where freed_t ≈ w_retiring * C_adj[t].
      - We still zero retired assets afterward (no redistribution semantics unchanged).
      - Returns (asset_level_df, company_corrections_df) where correction = C_adj - C_base.
    """
    # Expect melted input; filter to latesudden
    if "trajectory_type" in lsc.columns:
        lsc = lsc[lsc["trajectory_type"] == "latesudden"].copy()

    if logger:
        logger.info("Indexing company by year (prop fast)")
    comp_by_key = _index_company_by_year(lsc)

    if logger:
        logger.info("Indexing assets by group (prop fast)")
    assets_by_key = _index_assets_by_group(assets_bau)

    ret_map_by_key = (
        _build_retirement_map(assets_retirement_dates)
        if apply_retirement
        and assets_retirement_dates is not None
        and not assets_retirement_dates.empty
        else {}
    )

    out_parts: List[pd.DataFrame] = []
    corr_parts: List[pd.DataFrame] = []

    for key, comp_years in tqdm(
        comp_by_key.items(), desc="Prop-scale decreasing", unit="company"
    ):
        years = comp_years.index.to_numpy(dtype=np.int32)
        if years.size == 0:
            continue

        # Extract company info from key: (company_id, company_name, scenario_geography, sector, technology)
        company_id, company_name, scenario_geography, sector, technology = key

        C_base = comp_years["company_trajectory"].to_numpy(dtype=np.float64)
        C_adj = C_base.copy()

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

        # Extract 4-element key for asset lookup: (company_id, scenario_geography, sector, technology)
        asset_key = (company_id, scenario_geography, sector, technology)
        aset = assets_by_key.get(asset_key)
        if aset is None or aset.empty:
            base_df = pd.DataFrame(
                {
                    "company_id": company_id,
                    "company_name": np.repeat(company_name, years.shape[0]),
                    "scenario_geography": scenario_geography,
                    "sector": sector,
                    "technology": technology,
                    "year": years.astype(int),
                    "trajectory_type": "latesudden_original",
                    "company_trajectory": C_base,
                    "late_sudden_phase": comp_phase_by_year,
                    "alignment_type": align_type_by_year,
                }
            )
            adj_df = base_df.copy()
            adj_df["trajectory_type"] = "latesudden_adjusted"
            adj_df["company_trajectory"] = C_adj
            corr_parts.append(pd.concat([base_df, adj_df], ignore_index=True))
            continue

        asset_ids = aset["asset_id"].astype(str).unique()
        A = asset_ids.shape[0]
        if "asset_name" in aset.columns:
            name_map = (
                aset.drop_duplicates("asset_id")
                .set_index("asset_id")["asset_name"]
                .astype(str)
            )
            asset_names = name_map.reindex(asset_ids, fill_value="").to_numpy()
        else:
            asset_names = np.array([""] * A, dtype=object)

        act_pvt = aset.pivot(
            index="year", columns="asset_id", values="asset_activity"
        ).reindex(index=years, columns=asset_ids, fill_value=0.0)
        age_pvt = (
            aset.pivot(index="year", columns="asset_id", values="asset_age")
            .reindex(index=years, columns=asset_ids)
            .fillna(0.0)
        )

        baseline_mat = None
        if "asset_baseline_trajectory" in aset.columns:
            baseline_pvt = aset.pivot(
                index="year", columns="asset_id", values="asset_baseline_trajectory"
            ).reindex(index=years, columns=asset_ids, fill_value=0.0)
            baseline_mat = baseline_pvt.to_numpy(dtype=np.float64)

        base_activity = act_pvt.to_numpy(dtype=np.float64)  # (T, A)
        ages_mat = age_pvt.to_numpy(dtype=np.float64)  # (T, A)

        # Shock-year share vector (fixed post-shock)
        post_mask = years >= int(shock_year)
        t0 = int(np.argmax(post_mask)) if post_mask.any() else None

        pre_mask = years <= int(shock_year)
        if pre_mask.any():
            shock_ref = np.where(pre_mask)[0][-1]
            numer = np.clip(base_activity[shock_ref, :], 0.0, None)
        else:
            shock_ref = None
            numer = np.zeros(A, dtype=np.float64)

        S = float(numer.sum())
        w = (numer / S) if S > 0.0 else np.zeros(A, dtype=np.float64)

        # NEW: Reduce C_adj when assets retire (instead of redistributing capacity)
        # When an asset retires, we subtract its proportional share from C_adj for future years
        # This ensures the company total decreases by the retired asset's capacity
        if apply_retirement and ret_map_by_key:
            raw_ret = ret_map_by_key.get(asset_key, {})
            if raw_ret:
                eff_idx_by_asset: Dict[int, int] = {}
                for j, aid in enumerate(asset_ids):
                    yr = raw_ret.get(str(aid))
                    if yr is None or pd.isna(yr):
                        continue
                    eff = int(yr)
                    if alignment_year is not None:
                        eff = max(eff, int(alignment_year) + 1)
                    hit = np.where(years == eff)[0]
                    if hit.size > 0:
                        eff_idx_by_asset[j] = int(hit[0])

                # Reduce C_adj from retirement year onwards by the retiring asset's share
                for t in range(0, len(years)):
                    retiring_js = [j for j, ti in eff_idx_by_asset.items() if ti == t]
                    if not retiring_js:
                        continue
                    # Subtract the retiring assets' proportional share from this year onwards
                    freed_t = float(np.sum(w[retiring_js]) * C_adj[t])
                    C_adj[t:] = C_adj[t:] - freed_t

        # Build BEFORE/AFTER (no retirement applied yet)
        T = years.shape[0]
        before_mat = np.zeros((T, A), dtype=np.float64)
        after_mat = np.zeros((T, A), dtype=np.float64)
        phase_mat = np.empty((T, A), dtype=object)

        if t0 is None:
            before_mat[:] = base_activity
            after_mat[:] = base_activity
            phase_mat[:] = comp_phase_by_year[:, None]
        else:
            if t0 > 0:
                before_mat[:t0, :] = base_activity[:t0, :]
                after_mat[:t0, :] = base_activity[:t0, :]
                phase_mat[:t0, :] = comp_phase_by_year[:t0, None]

            # Allocate at shock year (t0) and beyond using fixed proportional weights
            before_mat[t0, :] = base_activity[t0, :]
            after_mat[t0, :] = w * C_adj[t0]
            phase_mat[t0, :] = comp_phase_by_year[t0]

            if t0 + 1 < T:
                before_mat[t0 + 1 :, :] = after_mat[t0 : T - 1, :]
                after_mat[t0 + 1 :, :] = C_adj[t0 + 1 :, None] * w[None, :]
                phase_mat[t0 + 1 :, :] = comp_phase_by_year[t0 + 1 :, None]

        # Apply retirement zeroing AFTER proportional allocation
        # This ensures retired assets' capacity is "lost" rather than redistributed
        if apply_retirement and ret_map_by_key:
            raw_ret = ret_map_by_key.get(asset_key, {})
            if raw_ret:
                eff_ret_year = np.full(A, np.iinfo(np.int32).max, dtype=np.int32)
                for j, aid in enumerate(asset_ids):
                    yr = raw_ret.get(str(aid))
                    if yr is not None and pd.notna(yr):
                        eff_ret_year[j] = int(yr)
                        if alignment_year is not None:
                            eff_ret_year[j] = max(
                                eff_ret_year[j], int(alignment_year) + 1
                            )

                for j in range(A):
                    eff = eff_ret_year[j]
                    if eff <= years[-1]:
                        mask = years >= eff
                        after_mat[mask, j] = 0.0
                        hit = np.where(years == eff)[0]
                        if hit.size > 0:
                            phase_mat[hit[0], j] = "retirement"

                # Re-chain BEFORE post-shock to reflect retirements
                if t0 is None:
                    before_mat[:] = base_activity
                else:
                    if t0 > 0:
                        before_mat[:t0, :] = base_activity[:t0, :]
                    before_mat[t0, :] = base_activity[t0, :]
                    if t0 + 1 < T:
                        before_mat[t0 + 1 :, :] = after_mat[t0 : T - 1, :]

        alloc_mat = after_mat - before_mat

        # ——— Emit assets
        output_dict = {
            "asset_id": np.tile(asset_ids.astype(str), T),
            "asset_name": np.tile(asset_names, T),
            "company_id": company_id,
            "company_name": company_name,
            "scenario_geography": scenario_geography,
            "sector": sector,
            "technology": technology,
            "year": np.repeat(years.astype(int), A),
            "asset_age": ages_mat.ravel(),
            "capacity_before_shock": before_mat.ravel(),
            "allocated_shock": alloc_mat.ravel(),
            "capacity_after_shock": np.maximum(after_mat, 0.0).ravel(),
            "is_synthetic": False,
            "late_sudden_phase": phase_mat.ravel(),
            "alignment_type": np.repeat(align_type_by_year, A),
        }
        if baseline_mat is not None:
            output_dict["asset_baseline_trajectory"] = baseline_mat.ravel()
        else:
            output_dict["asset_baseline_trajectory"] = np.nan
        out_parts.append(pd.DataFrame(output_dict))

        # ——— Emit corrections
        base_df = pd.DataFrame(
            {
                "company_id": company_id,
                "company_name": np.repeat(company_name, years.shape[0]),
                "scenario_geography": scenario_geography,
                "sector": sector,
                "technology": technology,
                "year": years.astype(int),
                "trajectory_type": "latesudden_original",
                "company_trajectory": C_base,
                "late_sudden_phase": comp_phase_by_year,
                "alignment_type": align_type_by_year,
            }
        )
        adj_df = base_df.copy()
        adj_df["trajectory_type"] = "latesudden_adjusted"
        adj_df["company_trajectory"] = C_adj
        corr_parts.append(pd.concat([base_df, adj_df], ignore_index=True))

    assets_df = pd.concat(out_parts, ignore_index=True)
    corrections_df = (
        pd.concat(corr_parts, ignore_index=True)
        if corr_parts
        else pd.DataFrame(
            columns=[
                "company_id",
                "company_name",
                "scenario_geography",
                "sector",
                "technology",
                "year",
                "trajectory_type",
                "company_trajectory",
                "late_sudden_phase",
                "alignment_type",
            ]
        )
    )
    return assets_df, corrections_df


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
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Decreasing techs.

    If apply_decreasing_staggered_shock is False:
        → proportional scaling with retirement-compensation uplift.
    If True:
        → staggered allocation with retirement-compensation uplift.

    RETURNS
    -------
    (decreasing_tech_staggered_shock_df, company_corrections_df)

    company_corrections_df columns:
        ['company_id','scenario_geography','sector','technology','year',
         'company_trajectory_latesudden_original',
         'company_trajectory_latesudden_adjusted',
         'late_sudden_phase','alignment_type']
    """
    GROUP_COLS = [
        "company_id",
        "company_name",
        "scenario_geography",
        "sector",
        "technology",
    ]

    if not apply_decreasing_staggered_shock:
        need_c = GROUP_COLS + ["year", "trajectory_type", "company_trajectory"]
        miss_c = [c for c in need_c if c not in late_sudden_trajectories.columns]
        if miss_c:
            raise ValueError(f"late_sudden_trajectories missing columns: {miss_c}")

        lsc = late_sudden_trajectories.copy()
        # keep only latesudden
        lsc = lsc[lsc["trajectory_type"] == "latesudden"].copy()
        if "late_sudden_phase" not in lsc.columns:
            lsc["late_sudden_phase"] = ""
        if "alignment_type" not in lsc.columns:
            lsc["alignment_type"] = ""

        assets = assets_with_baseline_trajectory.copy()
        assets["asset_id"] = assets["asset_id"].astype(str)

        assets_df, corrections_df = _prop_scale_decreasing_fast(
            lsc=lsc,
            assets_bau=assets,
            shock_year=int(shock_year),
            assets_retirement_dates=assets_retirement_dates,
            alignment_year=int(alignment_year),
            apply_retirement=bool(apply_retirement),
            logger=logger,
        )
        return assets_df, corrections_df

    # ---------- FAST STAGGERED BRANCH ----------

    lsc = late_sudden_trajectories.copy()
    lsc = lsc[lsc["trajectory_type"] == "latesudden"].copy()
    assets = assets_with_baseline_trajectory.copy()
    assets["asset_id"] = assets["asset_id"].astype(str)

    assets_df, corrections_df = _stagger_decreasing_fast(
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
    return assets_df, corrections_df


# =========================================================
# ============== INCREASING technologies node =============
# =========================================================


def stagger_increasing_technologies(
    late_sudden_trajectories: pd.DataFrame,
    assets_with_baseline_trajectory: pd.DataFrame,
    shock_year: int,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Increasing techs:
      - Real assets: BAU passthrough (alloc=0, before=after=BAU).
      - Synthetic: for each year t >= shock_year, take max(0, company[t] - sum_real[t]).
        This guarantees sum(real + synthetic) matches the company L&S each year
        even when real BAU grows after the shock.

    Returns:
        Tuple[pd.DataFrame, pd.DataFrame]: (asset_level_results, company_level_trajectories)
    """
    GROUP_COLS = [
        "company_id",
        "company_name",
        "scenario_geography",
        "sector",
        "technology",
    ]

    lsc = late_sudden_trajectories.copy()
    if not lsc.empty:
        # Use pre-computed BAU trajectory (already full-horizon)
        assets_bau = assets_with_baseline_trajectory.copy()
        assets_bau["asset_id"] = assets_bau["asset_id"].astype(str)

        # Ensure melted input; keep only latesudden rows
        need_cols = [
            "company_id",
            "scenario_geography",
            "sector",
            "technology",
            "year",
            "trajectory_type",
            "company_trajectory",
        ]
        miss = [c for c in need_cols if c not in lsc.columns]
        if miss:
            raise ValueError(f"late_sudden_trajectories missing columns: {miss}")
        lsc = lsc[lsc["trajectory_type"] == "latesudden"].copy()

        comp_by_key = {
            k: g.sort_values("year")[
                [
                    "year",
                    "company_trajectory",
                    "late_sudden_phase",
                    "alignment_type",
                    *(["company_name"] if "company_name" in g.columns else []),
                ]
            ]
            for k, g in lsc.groupby(GROUP_COLS, sort=False)
        }

        # Index assets for fast lookup
        if logger:
            logger.info("Indexing assets by group (increasing fast)")
        assets_by_key = _index_assets_by_group(assets_bau)

        # Pre-check for baseline column
        has_baseline = "asset_baseline_trajectory" in assets_bau.columns

        asset_parts: List[pd.DataFrame] = []
        company_parts: List[pd.DataFrame] = []

        for key, comp_years in tqdm(
            comp_by_key.items(), desc="Stagger increasing", unit="company"
        ):
            cid, company_name, geo, sector, tech = key
            years = comp_years["year"].to_numpy(dtype=np.int32)
            if years.size == 0:
                continue

            # Lookup assets using (company_id, geo, sector, tech)
            asset_key = (cid, geo, sector, tech)
            aset = assets_by_key.get(asset_key)

            if aset is None:
                aset = pd.DataFrame()

            C = comp_years["company_trajectory"].to_numpy(dtype=float)
            T = years.shape[0]

            # ---------- Real assets: BAU passthrough ----------
            real_parts = None
            sum_real_by_year = np.zeros(T, dtype=np.float64)
            if not aset.empty:
                asset_ids = aset["asset_id"].astype(str).unique()
                A = asset_ids.shape[0]
                if "asset_name" in aset.columns:
                    name_map = (
                        aset.drop_duplicates("asset_id")
                        .set_index("asset_id")["asset_name"]
                        .astype(str)
                    )
                    asset_names = name_map.reindex(asset_ids, fill_value="").to_numpy()
                else:
                    asset_names = np.array([""] * A, dtype=object)

                act_pvt = aset.pivot(
                    index="year", columns="asset_id", values="asset_activity"
                ).reindex(index=years, columns=asset_ids, fill_value=0.0)
                age_pvt = (
                    aset.pivot(index="year", columns="asset_id", values="asset_age")
                    .reindex(index=years, columns=asset_ids)
                    .fillna(0.0)
                )

                baseline_mat = None
                if has_baseline:
                    baseline_pvt = aset.pivot(
                        index="year",
                        columns="asset_id",
                        values="asset_baseline_trajectory",
                    ).reindex(index=years, columns=asset_ids, fill_value=0.0)
                    baseline_mat = baseline_pvt.to_numpy(dtype=np.float64)

                base_activity = act_pvt.to_numpy(dtype=np.float64)  # (T, A)
                ages_mat = age_pvt.to_numpy(dtype=np.float64)  # (T, A)

                before_mat = base_activity.copy()
                after_mat = base_activity.copy()  # BAU passthrough
                alloc_mat = np.zeros_like(before_mat)

                sum_real_by_year = after_mat.sum(axis=1)

                out = {
                    "asset_id": np.tile(asset_ids.astype(str), T),
                    "asset_name": np.tile(asset_names, T),
                    "company_id": cid,
                    "company_name": company_name,
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
                if baseline_mat is not None:
                    out["asset_baseline_trajectory"] = baseline_mat.ravel()
                else:
                    out["asset_baseline_trajectory"] = np.nan

                real_parts = pd.DataFrame(out)
                asset_parts.append(real_parts)

            # ---------- Synthetic: per-year top-up to hit company series ----------
            tmask = years >= int(shock_year)
            synth_cap = np.zeros(T, dtype=np.float64)
            # top-up = company minus real sum (never negative)
            synth_cap[tmask] = np.clip(
                C[tmask] - sum_real_by_year[tmask], a_min=0.0, a_max=None
            )

            synth_before = np.concatenate(([0.0], synth_cap[:-1]))
            synth_alloc = synth_cap - synth_before

            # Age: start when it first turns positive
            pos = synth_cap > 0.0
            if pos.any():
                first_idx = int(np.argmax(pos))
                synth_age = np.where(pos, years - years[first_idx], 0.0).astype(float)
            else:
                synth_age = np.zeros_like(synth_cap, dtype=float)

            synth_dict = {
                "asset_id": f"NEW_{cid}_{sector}_{tech}_{geo}",
                "asset_name": f"NEW_{cid}_{sector}_{tech}_{geo}",
                "company_id": cid,
                "company_name": company_name,
                "scenario_geography": geo,
                "sector": sector,
                "technology": tech,
                "year": years.astype(int),
                "asset_age": synth_age,
                "capacity_before_shock": synth_before,
                "allocated_shock": synth_alloc,
                "capacity_after_shock": synth_cap,
                "is_synthetic": True,
                "late_sudden_phase": comp_years["late_sudden_phase"].values,
                "alignment_type": comp_years["alignment_type"].values,
                # baseline for a synthetic build is 0
                "asset_baseline_trajectory": np.zeros_like(synth_cap, dtype=float),
            }
            asset_parts.append(pd.DataFrame(synth_dict))

            # ---------- Company-level trajectories (melted form) ----------
            company_df = pd.DataFrame(
                {
                    "company_id": cid,
                    "company_name": company_name,
                    "scenario_geography": geo,
                    "sector": sector,
                    "technology": tech,
                    "year": years.astype(int),
                    "trajectory_type": "latesudden",
                    "company_trajectory": comp_years["company_trajectory"].values,
                    "late_sudden_phase": comp_years["late_sudden_phase"].values,
                    "alignment_type": comp_years["alignment_type"].values,
                }
            )
            company_parts.append(company_df)

        # Combine results
        assets_df = pd.concat(asset_parts, ignore_index=True)

        companies_df = (
            pd.concat(company_parts, ignore_index=True)
            if company_parts
            else pd.DataFrame(
                columns=[
                    "company_id",
                    "company_name",
                    "scenario_geography",
                    "sector",
                    "technology",
                    "year",
                    "trajectory_type",
                    "company_trajectory",
                    "late_sudden_phase",
                    "alignment_type",
                ]
            )
        )
    else:
        assets_df = pd.DataFrame(
            columns=[
                "asset_id",
                "asset_name",
                "company_id",
                "company_name",
                "scenario_geography",
                "sector",
                "technology",
                "year",
                "asset_age",
                "is_synthetic",
                "late_sudden_phase",
                "alignment_type",
                "trajectory_type",
                "asset_trajectory",
            ]
        )
        companies_df = pd.DataFrame(
            columns=[
                "company_id",
                "company_name",
                "scenario_geography",
                "sector",
                "technology",
                "year",
                "trajectory_type",
                "company_trajectory",
                "late_sudden_phase",
                "alignment_type",
            ]
        )

    return assets_df, companies_df


# =========================================================
# ============== Reshaping/melt helper ====================
# =========================================================


def create_frozen_capacity_at_retirement(
    asset_level_staggered_shock: pd.DataFrame,
    assets_retirement_dates: pd.DataFrame,
) -> pd.DataFrame:
    """
    Create a dataframe tracking frozen capacity at retirement time for decreasing technologies.

    For each asset that retires:
    - Captures its capacity at the retirement year
    - Extends that frozen capacity constant through all years up to 2050

    Args:
        asset_level_staggered_shock: Wide asset-level dataframe with capacity_after_shock
        assets_retirement_dates: Dataframe with retirement_year for each asset

    Returns:
        DataFrame with columns: asset_id, company_id, scenario_geography, sector,
        technology, year, frozen_capacity_at_retirement
    """
    logger.info("Creating frozen capacity at retirement...")

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

    # Keep only the columns we need for the lookup
    retirement_capacity = retirement_capacity[
        [
            "asset_id",
            "company_id",
            "scenario_geography",
            "sector",
            "technology",
            "frozen_capacity_at_retirement",
        ]
    ].drop_duplicates()

    # Get all unique years from the asset data to extend through
    all_years = sorted(assets["year"].unique())

    # Create a complete timeline for each retiring asset
    frozen_records = []
    for _, row in retirement_capacity.iterrows():
        asset_retirement_year = assets_retirement_dates[
            (assets_retirement_dates["asset_id"] == row["asset_id"])
            & (assets_retirement_dates["company_id"] == row["company_id"])
            & (
                assets_retirement_dates["scenario_geography"]
                == row["scenario_geography"]
            )
            & (assets_retirement_dates["sector"] == row["sector"])
            & (assets_retirement_dates["technology"] == row["technology"])
        ]["retirement_year"].iloc[0]

        # Create rows for retirement year and all subsequent years
        for year in all_years:
            if year >= asset_retirement_year:
                frozen_records.append(
                    {
                        "asset_id": row["asset_id"],
                        "company_id": row["company_id"],
                        "scenario_geography": row["scenario_geography"],
                        "sector": row["sector"],
                        "technology": row["technology"],
                        "year": year,
                        "frozen_capacity_at_retirement": row[
                            "frozen_capacity_at_retirement"
                        ],
                    }
                )

    if not frozen_records:
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

    frozen_capacity_df = pd.DataFrame(frozen_records)

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


def melt_asset_staggered_trajectories(
    assets_staggered_late_sudden: pd.DataFrame,
) -> pd.DataFrame:
    """
    Produce a melted asset-level dataframe with trajectory_type and asset_trajectory.

    Input is the debug-friendly wide asset dataframe produced by the stagger nodes,
    containing columns like 'capacity_after_shock' (L&S) and 'asset_baseline_trajectory'.

    Output columns include:
      - asset_id, company_id, company_name, scenario_geography, sector, technology,
        year, asset_age, is_synthetic, late_sudden_phase, alignment_type,
      - trajectory_type in {'baseline','latesudden'}
      - asset_trajectory (values)
    """
    if assets_staggered_late_sudden is None or assets_staggered_late_sudden.empty:
        return pd.DataFrame(
            columns=[
                "asset_id",
                "asset_name",
                "company_id",
                "company_name",
                "scenario_geography",
                "sector",
                "technology",
                "year",
                "asset_age",
                "is_synthetic",
                "late_sudden_phase",
                "alignment_type",
                "trajectory_type",
                "asset_trajectory",
            ]
        )

    df = assets_staggered_late_sudden.copy()

    id_cols = [
        "asset_id",
        "asset_name",
        "company_id",
        "company_name",
        "scenario_geography",
        "sector",
        "technology",
        "year",
        "asset_age",
        "is_synthetic",
        "late_sudden_phase",
        "alignment_type",
    ]

    # Build value cols present
    value_map = [
        ("latesudden", "capacity_after_shock"),
        ("baseline", "asset_baseline_trajectory"),
    ]

    melted_parts: List[pd.DataFrame] = []
    for ttype, col in value_map:
        sub = df[id_cols].copy()
        sub["trajectory_type"] = ttype
        sub["asset_trajectory"] = df[col].astype(float)
        melted_parts.append(sub)

    out = pd.concat(melted_parts, ignore_index=True)
    # Sort for stability
    sort_cols = [
        c
        for c in [
            "company_id",
            "scenario_geography",
            "sector",
            "technology",
            "asset_id",
            "year",
            "trajectory_type",
        ]
        if c in out.columns
    ]
    if sort_cols:
        out = out.sort_values(sort_cols).reset_index(drop=True)
    return out
