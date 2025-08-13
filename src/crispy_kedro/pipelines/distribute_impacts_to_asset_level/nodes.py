import numpy as np
import pandas as pd
from typing import Dict, Tuple, List
from tqdm import tqdm


# =========================================================
# ==================== Common helpers =====================
# =========================================================

GROUP_COLS = ["company_id", "scenario_geography", "sector", "technology"]


def _ensure_int_year(s: pd.Series) -> pd.Series:
    return s.fillna(0).astype(int)


def _compute_g_weights(
    ages: pd.Series,
    k: float,
    n_quantiles: int,
    for_decreasing: bool,
    min_active_share: float = 1e-12,
) -> pd.Series:
    """
    Logistic-sum g(a) per your spec. We invert sign for decreasing (older favored).
    Then shift to positive, clip by min_active_share, and normalize to sum=1.
    """
    ages = ages.astype(float)
    if ages.empty:
        return pd.Series(dtype=float, index=ages.index)

    qs = np.linspace(0, 1, n_quantiles + 1)[1:-1]  # exclude 0 and 1
    cuts = np.quantile(ages.values, qs) if len(qs) else np.array([])

    def base(a):
        if cuts.size == 0:
            return 1.0
        return 1.0 - np.sum(1.0 / (1.0 + np.exp(-k * (a - cuts))))

    raw = ages.map(base)
    if for_decreasing:
        raw = -raw  # older => higher

    raw = raw - raw.min() + min_active_share
    s = raw.sum()
    if not np.isfinite(s) or s <= 0:
        return pd.Series(1.0 / len(raw), index=ages.index)
    return raw / s


def _solve_negative_with_floors(b: np.ndarray, w: np.ndarray, R: float) -> np.ndarray:
    """
    Reduce total amount R (>0) from vector b using weights w >= 0 with floors at 0:
      d_i = min(alpha * w_i, b_i),   sum(d_i) = R
    If R >= sum(b), saturates at b (all-to-zero).
    Returns d (nonnegative reductions). Use alloc = -d.
    """
    b = np.asarray(b, dtype=float)
    w = np.asarray(w, dtype=float)

    if R <= 0.0 or b.size == 0:
        return np.zeros_like(b)

    B = b.sum()
    if R >= B:
        return b.copy()

    mask = w > 0
    if not mask.any():
        # fallback: proportional to capacity
        return (R / B) * b

    t = np.full_like(w, np.inf, dtype=float)
    t[mask] = b[mask] / w[mask]
    lo, hi = 0.0, float(np.max(t[mask]))
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        d = np.minimum(mid * w, b)
        s = float(d.sum())
        if s < R:
            lo = mid
        else:
            hi = mid
    d = np.minimum(hi * w, b)
    # tiny correction
    err = d.sum() - R
    if abs(err) > 1e-9:
        d -= err / max(1, len(d))
        d = np.clip(d, 0.0, b)
    return d


def _index_company_by_year(
    df_company: pd.DataFrame,
) -> Dict[Tuple[str, str, str, str], pd.DataFrame]:
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

    need_cols = GROUP_COLS + ["asset_id", "retirement_year"]
    miss = [c for c in need_cols if c not in assets_retirement_dates.columns]
    if miss:
        raise ValueError(f"assets_retirement_dates missing columns: {miss}")

    ret_map: Dict[Tuple[str, str, str, str], Dict[str, int]] = {}
    tmp = assets_retirement_dates[need_cols].copy()
    tmp["retirement_year"] = _ensure_int_year(tmp["retirement_year"])

    for key, sub in tmp.groupby(GROUP_COLS, sort=False):
        r = dict(zip(sub["asset_id"].astype(str), sub["retirement_year"].astype(int)))
        ret_map[key] = r
    return ret_map


def _assets_for_year(
    assets_group: pd.DataFrame,
    year: int,
    retire_year_by_asset: Dict[str, int],
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Slice asset forecasts for a given year and apply retirement constraints.

    Returns:
      before: Series[asset_id] of forecast capacity (asset_activity) for this year
      forced_alloc: Series[asset_id] of *negative* allocation to enforce full retirement
                    (= -before for assets with retirement_year <= year, else 0)
      ages: Series[asset_id] of asset_age for this year (NaN allowed but uncommon here)
    """
    sub = assets_group[assets_group["year"] == year]
    if sub.empty:
        return (
            pd.Series(dtype=float),
            pd.Series(dtype=float),
            pd.Series(dtype=float),
        )

    sub = sub.copy()
    sub["asset_id"] = sub["asset_id"].astype(str)

    before = sub.set_index("asset_id")["asset_activity"].astype(float)
    ages = sub.set_index("asset_id")["asset_age"].astype(float)

    # Full retirement from retirement_year onward
    forced = pd.Series(0.0, index=before.index, dtype=float)
    if retire_year_by_asset:
        for aid, y_r in retire_year_by_asset.items():
            if aid in forced.index and year >= int(y_r):
                forced.at[aid] = -float(before.at[aid])  # drop to zero

    return before, forced, ages


def _emit_rows(
    key: Tuple[str, str, str, str],
    year: int,
    before: pd.Series,
    alloc: pd.Series,
    ages: pd.Series,
    synthetic_mask: pd.Series = None,
    late_sudden_phase: pd.Series = None,
) -> pd.DataFrame:
    after = before.add(alloc, fill_value=0.0)
    if synthetic_mask is None:
        synthetic_mask = pd.Series(False, index=before.index)
    if late_sudden_phase is None:
        late_sudden_phase = pd.Series("", index=before.index)

    out = pd.DataFrame(
        {
            "asset_id": before.index,
            "company_id": key[0],
            "scenario_geography": key[1],
            "sector": key[2],
            "technology": key[3],
            "year": int(year),
            "asset_age": ages.reindex(before.index).astype(float).values,
            "capacity_before_shock": before.values.astype(float),
            "allocated_shock": alloc.reindex(before.index)
            .fillna(0.0)
            .values.astype(float),
            "capacity_after_shock": after.reindex(before.index)
            .fillna(0.0)
            .values.astype(float),
            "is_synthetic": synthetic_mask.reindex(before.index)
            .fillna(False)
            .astype(bool)
            .values,
            "late_sudden_phase": late_sudden_phase.reindex(before.index)
            .fillna("")
            .astype(str)
            .values,
        }
    )
    # numeric hygiene
    out["capacity_after_shock"] = np.maximum(out["capacity_after_shock"], 0.0)
    return out


def _bau_fill_assets_until_shock(
    lsc: pd.DataFrame,
    assets: pd.DataFrame,
    shock_year: int,
) -> pd.DataFrame:
    """
    Step 2 (BAU extrapolation): for each (company, geo, sector, tech, asset_id),
    find y0 = last year <= shock_year where asset_activity is not NA (GEM or forecast),
    and fill NA years in (y0, shock_year] with:
        asset_activity[y] = asset_activity[y0] * (company_baseline[y] / company_baseline[y0])

    - Uses lsc['company_trajectory_baseline'] as S^{baseline}_{y,t}.
    - If baseline at y0 is 0/NA, we carry forward v0 (no growth).
    - Rows > shock_year are left unchanged.
    - Returns a copy of `assets` with asset_activity filled.
    """
    if assets.empty:
        return assets.copy()

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
    out["year"] = _ensure_int_year(out["year"])
    out = out.merge(comp_base, on=GROUP_COLS + ["year"], how="left")

    # Work only on years <= shock_year
    pre = out["year"] <= int(shock_year)

    # Group by key + asset
    gcols = GROUP_COLS + ["asset_id"]
    out.sort_values(gcols + ["year"], inplace=True)

    def _fill_one(group: pd.DataFrame) -> pd.DataFrame:
        mask_pre = group["year"] <= int(shock_year)
        if not mask_pre.any():
            return group

        gpre = group.loc[mask_pre].copy()
        # last known y0 with non-NA asset_activity
        notna = ~gpre["asset_activity"].isna()
        if not notna.any():
            # nothing to anchor on -> leave as-is
            return group

        # y0 and v0
        idx0 = gpre.index[notna][-1]  # last non-NA row index
        y0 = int(group.at[idx0, "year"])
        v0 = float(group.at[idx0, "asset_activity"])

        B0 = (
            float(group.at[idx0, "_company_baseline"])
            if pd.notna(group.at[idx0, "_company_baseline"])
            else np.nan
        )
        if not np.isfinite(B0) or B0 == 0.0:
            B0 = np.nan  # triggers "no growth" fallback

        # Fill NA for years in (y0, shock_year]
        tgt = mask_pre & group["asset_activity"].isna() & (group["year"] > y0)
        if tgt.any():
            By = group.loc[tgt, "_company_baseline"].astype(float)
            if np.isnan(B0).all():
                filled = v0  # no baseline anchor -> flat
            else:
                ratio = By / B0
                # if some By are NA, default to 1.0 (flat) for those
                ratio = ratio.fillna(1.0)
                filled = v0 * ratio.values
            group.loc[tgt, "asset_activity"] = filled

        return group

    out = out.groupby(gcols, sort=False, group_keys=False).apply(_fill_one)

    # Clean up helper column
    out.drop(columns=["_company_baseline"], inplace=True)
    return out


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


def stagger_decreasing_from_company(
    late_sudden_trajectories: pd.DataFrame,
    allocated_assets_to_companies: pd.DataFrame,
    assets_retirement_dates: pd.DataFrame,
    shock_year: int,
    alignment_year: int,
    g_k: float = 6.0,
    n_quantiles: int = 3,
) -> pd.DataFrame:
    """
    Original staggered-shock (company -> assets) for decreasing techs.

    Per (company_id, scenario_geography, sector, technology, year):
      - Compute company shock: Δ_y = company_LS[y] - company_LS[y-1]; keep only negative.
      - Build 'before' from asset forecasts (asset_activity) for that year.
      - Apply *full* retirement at asset level in that year: forced negative alloc = -before for assets with retirement_year <= y.
      - Remaining negative (if any) is distributed to *non-retired* assets by g-weights (older first), floored at zero.
      - We *do not* add capacity back if forced retirement exceeds Δ_y (residual can be positive; visible in plots).

    Output columns:
      ['asset_id','company_id','scenario_geography','sector','technology','year',
       'asset_age','capacity_before_shock','allocated_shock','capacity_after_shock',
       'is_synthetic','late_sudden_phase']
    """

    lsc = late_sudden_trajectories.copy()

    need_c = GROUP_COLS + ["year", "company_trajectory_latesudden"]
    miss_c = [c for c in need_c if c not in lsc.columns]
    if miss_c:
        raise ValueError(f"late_sudden_trajectories missing columns: {miss_c}")

    need_a = GROUP_COLS + ["asset_id", "year", "asset_activity", "asset_age"]
    miss_a = [c for c in need_a if c not in allocated_assets_to_companies.columns]
    if miss_a:
        raise ValueError(f"allocated_assets_to_companies missing columns: {miss_a}")

    lsc = lsc.copy()
    lsc["year"] = _ensure_int_year(lsc["year"])

    assets = _bau_fill_assets_until_shock(
        lsc=lsc,
        assets=allocated_assets_to_companies.copy(),
        shock_year=shock_year,
    )
    assets["year"] = _ensure_int_year(assets["year"])
    assets["asset_id"] = assets["asset_id"].astype(str)

    # Pre-index
    comp_by_key = _index_company_by_year(lsc)
    ret_map_by_key = _build_retirement_map(assets_retirement_dates)
    out_parts: List[pd.DataFrame] = []

    for key, comp_years in tqdm(
        list(comp_by_key.items()), desc="Stagger dec", unit="grp"
    ):
        # Slice asset pool for this key
        aset_g = assets[
            (assets["company_id"] == key[0])
            & (assets["scenario_geography"] == key[1])
            & (assets["sector"] == key[2])
            & (assets["technology"] == key[3])
        ][["asset_id", "year", "asset_activity", "asset_age"]].copy()

        if aset_g.empty:
            continue

        retire_year_by_asset = ret_map_by_key.get(key, {})

        years = list(map(int, comp_years.index.tolist()))
        years.sort()

        prev_company = None
        for y in years:
            C_y = float(comp_years.at[y, "company_trajectory_latesudden"])
            before, forced_alloc, ages = _assets_for_year(
                aset_g, y, retire_year_by_asset
            )

            # mark 'retirement' only on the exact retirement year for those assets
            phase = pd.Series("", index=before.index, dtype=object)
            if retire_year_by_asset:
                for aid, y_r in retire_year_by_asset.items():
                    if aid in phase.index and y == int(y_r):
                        phase.at[aid] = "retirement"

            # company shock (negative part only)
            if prev_company is None:
                shock_neg = 0.0
            else:
                delta = C_y - prev_company
                shock_neg = min(delta, 0.0)

            prev_company = C_y

            # forced retirement is already negative
            forced_sum = float(forced_alloc.sum())

            # Remaining negative to apply beyond forced retirement
            remaining = (
                shock_neg - forced_sum
            )  # (≤ 0 desired; if >0, nothing more to reduce)
            extra_alloc = pd.Series(0.0, index=before.index)

            if remaining < -1e-12:
                # allocate to currently *non-retired this year* assets with positive headroom
                active_mask = forced_alloc >= 0.0  # true when not forced-retired (==0)
                active_ids = before.index[active_mask.values]
                if len(active_ids) > 0:
                    b = before.loc[active_ids].to_numpy()
                    ages_active = ages.loc[active_ids]
                    w = _compute_g_weights(
                        ages_active, k=g_k, n_quantiles=n_quantiles, for_decreasing=True
                    ).to_numpy()
                    reductions = _solve_negative_with_floors(b=b, w=w, R=-remaining)
                    extra_alloc.loc[active_ids] = -reductions  # negative

            alloc = forced_alloc.add(extra_alloc, fill_value=0.0)
            out_parts.append(
                _emit_rows(
                    key,
                    year=y,
                    before=before,
                    alloc=alloc,
                    ages=ages,
                    synthetic_mask=pd.Series(False, index=before.index),
                    late_sudden_phase=phase,
                )
            )

    if out_parts:
        return pd.concat(out_parts, ignore_index=True)
    return pd.DataFrame(
        columns=[
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
        ]
    )


# =========================================================
# ============== INCREASING technologies node =============
# =========================================================


def stagger_increasing_from_company(
    late_sudden_trajectories: pd.DataFrame,
    allocated_assets_to_companies: pd.DataFrame,
    assets_retirement_dates: pd.DataFrame,
    shock_year: int,
    use_synthetic_from_shock: bool = True,
) -> pd.DataFrame:
    """
    Increasing techs (company -> assets).

    Policy (kept simple & robust):
      - Real assets follow their forecast lines; we apply *full asset retirement* (drop to zero from retirement year).
      - Positive company deltas:
          * If use_synthetic_from_shock=True: for y >= shock_year, ALL positive deltas go to one
            persistent synthetic asset NEW_{cid}_{sector}_{tech}_{geo}. For y < shock_year, we do not
            add capacity (residual shows in plots).
          * If False: we could redistribute to youngest real assets, but defaults to synthetic path.
      - Negative company deltas (rare): we do NOT reduce real assets here (kept 0), so residual may be negative.

    Output schema same as decreasing (synthetic rows flagged with is_synthetic=True).
    """
    lsc = late_sudden_trajectories.copy()

    need_c = GROUP_COLS + ["year", "company_trajectory_latesudden"]
    miss_c = [c for c in need_c if c not in lsc.columns]
    if miss_c:
        raise ValueError(f"late_sudden_trajectories missing columns: {miss_c}")

    need_a = GROUP_COLS + ["asset_id", "year", "asset_activity", "asset_age"]
    miss_a = [c for c in need_a if c not in allocated_assets_to_companies.columns]
    if miss_a:
        raise ValueError(f"allocated_assets_to_companies missing columns: {miss_a}")

    lsc = lsc.copy()
    lsc["year"] = _ensure_int_year(lsc["year"])

    assets = _bau_fill_assets_until_shock(
        lsc=lsc,
        assets=allocated_assets_to_companies.copy(),
        shock_year=shock_year,
    )
    assets["year"] = _ensure_int_year(assets["year"])
    assets["asset_id"] = assets["asset_id"].astype(str)

    comp_by_key = _index_company_by_year(lsc)
    ret_map_by_key = _build_retirement_map(assets_retirement_dates)
    out_parts: List[pd.DataFrame] = []

    for key, comp_years in tqdm(
        list(comp_by_key.items()), desc="Stagger inc", unit="grp"
    ):
        cid, geo, sector, tech = key
        synth_id = f"NEW_{cid}_{sector}_{tech}_{geo}"

        aset_g = assets[
            (assets["company_id"] == cid)
            & (assets["scenario_geography"] == geo)
            & (assets["sector"] == sector)
            & (assets["technology"] == tech)
        ][["asset_id", "year", "asset_activity", "asset_age"]].copy()

        if aset_g.empty and not use_synthetic_from_shock:
            continue

        retire_year_by_asset = ret_map_by_key.get(key, {})

        years = list(map(int, comp_years.index.tolist()))
        years.sort()

        prev_company = None
        synth_prev_cap = 0.0
        synth_prev_age = 0.0
        have_synth = False

        for y in years:
            C_y = float(comp_years.at[y, "company_trajectory_latesudden"])
            before, forced_alloc, ages = _assets_for_year(
                aset_g, y, retire_year_by_asset
            )

            # Real assets: only apply retirement (forced negative), otherwise carry-through
            alloc_real = forced_alloc.copy()

            # company delta (positive part)
            if prev_company is None:
                delta_pos = 0.0
            else:
                delta = C_y - prev_company
                delta_pos = max(delta, 0.0)
            prev_company = C_y

            # Emit real assets first
            out_parts.append(
                _emit_rows(
                    key,
                    year=y,
                    before=before,
                    alloc=alloc_real,
                    ages=ages,
                    synthetic_mask=pd.Series(False, index=before.index),
                    late_sudden_phase=pd.Series(
                        [
                            (
                                "retirement"
                                if (
                                    aid in retire_year_by_asset
                                    and y == int(retire_year_by_asset[aid])
                                )
                                else ""
                            )
                            for aid in before.index
                        ],
                        index=before.index,
                    ),
                )
            )

            # Synthetic (from shock_year onward, positive delta only)
            if use_synthetic_from_shock and y >= int(shock_year) and delta_pos > 1e-12:
                have_synth = True
                synth_before = pd.Series(
                    [synth_prev_cap],
                    index=[synth_id],
                    dtype=float,
                    name="capacity_before_shock",
                )
                # Create alloc for synthetic
                synth_alloc = pd.Series(
                    [delta_pos], index=[synth_id], dtype=float, name="allocated_shock"
                )
                # Age: 0 at creation, then +1 each year thereafter
                synth_prev_age = 0.0 if synth_prev_cap == 0.0 else synth_prev_age + 1.0
                synth_age = pd.Series(
                    [synth_prev_age], index=[synth_id], dtype=float, name="asset_age"
                )
                synth_mask = pd.Series([True], index=[synth_id], dtype=bool)
                out_parts.append(
                    pd.DataFrame(
                        {
                            "asset_id": synth_before.index,
                            "company_id": cid,
                            "scenario_geography": geo,
                            "sector": sector,
                            "technology": tech,
                            "year": int(y),
                            "asset_age": synth_age.values,
                            "capacity_before_shock": synth_before.values,
                            "allocated_shock": synth_alloc.values,
                            "capacity_after_shock": (synth_before + synth_alloc).values,
                            "is_synthetic": synth_mask.values,
                            "late_sudden_phase": [""],
                        }
                    )
                )
                synth_prev_cap = float((synth_before + synth_alloc).iloc[0])

            # carry synthetic forward with zero alloc if it exists and y >= shock_year
            elif use_synthetic_from_shock and y >= int(shock_year) and have_synth:
                synth_prev_age = synth_prev_age + 1.0
                synth_before = pd.Series(
                    [synth_prev_cap], index=[synth_id], dtype=float
                )
                out_parts.append(
                    pd.DataFrame(
                        {
                            "asset_id": [synth_id],
                            "company_id": [cid],
                            "scenario_geography": [geo],
                            "sector": [sector],
                            "technology": [tech],
                            "year": [int(y)],
                            "asset_age": [synth_prev_age],
                            "capacity_before_shock": [synth_prev_cap],
                            "allocated_shock": [0.0],
                            "capacity_after_shock": [synth_prev_cap],
                            "is_synthetic": [True],
                            "late_sudden_phase": [""],
                        }
                    )
                )

    if out_parts:
        return pd.concat(out_parts, ignore_index=True)
    return pd.DataFrame(
        columns=[
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
        ]
    )


def concatenate_staggered_shock_results(
    dec_late_sudden_trajectories: pd.DataFrame,
    inc_late_sudden_trajectories: pd.DataFrame,
) -> pd.DataFrame:

    assets_staggered_late_sudden = pd.concat(
        [dec_late_sudden_trajectories, inc_late_sudden_trajectories], ignore_index=True
    ).reset_index(drop=True)

    return assets_staggered_late_sudden
