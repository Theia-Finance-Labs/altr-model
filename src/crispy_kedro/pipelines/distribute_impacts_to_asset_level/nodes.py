import warnings
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm


# =========================================================
# =============== Company-level preparation ===============
# =========================================================


def aggregate_late_sudden_trajectories_to_company_level(
    all_assets_late_sudden_trajectories: pd.DataFrame,
) -> pd.DataFrame:
    """
    Aggregate asset-level L&S to company level by year (single row per group-year).

    Group keys:
      company_id, company_name, scenario_geography, sector, technology, alignment_type, year

    We DO NOT group by 'late_sudden_phase' to avoid duplicate year rows.
    We set late_sudden_phase='aligned' as a neutral initial value; later nodes
    can overwrite to 'retirement' or 'compensation' for specific years.
    """
    req_cols = [
        "company_id",
        "company_name",
        "scenario_geography",
        "sector",
        "technology",
        "alignment_type",
        "year",
        "asset_activity",
        "asset_trajectory_baseline",
        "asset_trajectory_target",
        "asset_trajectory_latesudden",
    ]
    missing = [
        c for c in req_cols if c not in all_assets_late_sudden_trajectories.columns
    ]
    if missing:
        raise ValueError(f"Missing required columns in assets L&S: {missing}")

    gcols = [
        "company_id",
        "company_name",
        "scenario_geography",
        "sector",
        "technology",
        "alignment_type",
        "year",
    ]
    companies = (
        all_assets_late_sudden_trajectories[
            gcols
            + [
                "asset_activity",
                "asset_trajectory_baseline",
                "asset_trajectory_target",
                "asset_trajectory_latesudden",
            ]
        ]
        .groupby(gcols, dropna=False, sort=False)
        .agg(
            {
                "asset_activity": lambda x: x.sum() if not pd.isna(x).all() else np.nan,
                "asset_trajectory_baseline": "sum",
                "asset_trajectory_target": "sum",
                "asset_trajectory_latesudden": "sum",
            }
        )
        .rename(
            columns={
                "asset_activity": "company_activity",
                "asset_trajectory_baseline": "company_trajectory_baseline",
                "asset_trajectory_target": "company_trajectory_target",
                "asset_trajectory_latesudden": "company_trajectory_latesudden",
            }
        )
        .reset_index()
        .assign(late_sudden_phase="aligned")
    )
    return companies


def apply_company_level_retirements(
    companies_late_sudden_trajectories: pd.DataFrame,
    assets_retirement_dates: pd.DataFrame,
    alignment_year: int,
) -> pd.DataFrame:
    """
    Apply *company-level* retirement removals:
      For each event (y_r, cap) in a (company, geo, sector, tech) group,
      reduce company_trajectory_latesudden by a percentage from y_r onward,
      where percentage = min(cap / LS(y_r), 1.0) using the current LS(y_r).
      Only the exact retirement year gets phase 'retirement'.

    Retirement years <= alignment_year are shifted to the first year strictly
    after alignment_year that exists in the group's horizon (same as your prior logic).
    """
    result = companies_late_sudden_trajectories.copy()

    # index retirement events
    key_cols = ["company_id", "scenario_geography", "sector", "technology"]
    if assets_retirement_dates is None or assets_retirement_dates.empty:
        return result

    # Normalize input columns
    need = key_cols + ["retirement_year", "asset_activity"]
    missing = [c for c in need if c not in assets_retirement_dates.columns]
    if missing:
        raise ValueError(f"Missing columns in assets_retirement_dates: {missing}")

    retire_sorted = assets_retirement_dates[
        key_cols + ["retirement_year", "asset_activity"]
    ].sort_values(key_cols + ["retirement_year"])

    events_by_key: Dict[Tuple[str, str, str, str], List[Tuple[int, float]]] = {}
    for k, sub in retire_sorted.groupby(key_cols, sort=False):
        events_by_key[k] = list(
            zip(sub["retirement_year"].astype(int), sub["asset_activity"].astype(float))
        )

    # Work per company x geo x sector x tech
    group_cols = key_cols
    out_parts = []
    for key, g in result.groupby(group_cols, sort=False):
        g = g.sort_values("year").copy()
        years = g["year"].to_numpy(dtype=int)
        ls = g["company_trajectory_latesudden"].to_numpy(dtype=float)
        phase = g["late_sudden_phase"].to_numpy(dtype=object)

        evts = events_by_key.get(key, [])
        if evts:
            # find first available year strictly after alignment_year
            years_after = years[years > alignment_year]
            next_after = int(years_after.min()) if years_after.size > 0 else None

            # push events <= alignment_year
            adjusted = []
            for y_r, cap in evts:
                if next_after is not None and y_r <= alignment_year:
                    adjusted.append((next_after, cap))
                else:
                    adjusted.append((y_r, cap))

            # chronological apply
            for y_r, cap in sorted(adjusted, key=lambda x: x[0]):
                idx = np.where(years == int(y_r))[0]
                if idx.size == 0:
                    continue
                i = idx[0]
                base = float(ls[i])
                if base <= 0:
                    # if zero, the percentage would be undefined; skip marking (nothing to remove)
                    continue
                pct = min(float(cap) / base, 1.0)
                if pct <= 0:
                    continue
                # apply cumulatively from y_r onward
                ls[i:] *= 1.0 - pct
                # mark only the exact year as retirement
                phase[i] = "retirement"

        g["company_trajectory_latesudden"] = ls
        g["late_sudden_phase"] = phase
        out_parts.append(g)

    return pd.concat(out_parts, ignore_index=True) if out_parts else result


def apply_company_level_compensation(
    companies_late_sudden_trajectories: pd.DataFrame,
    alignment_year: int,
) -> pd.DataFrame:
    """
    Apply uniform post-alignment compensation only to misaligned_high_carbon groups.
    """

    def _apply_comp(g: pd.DataFrame) -> pd.DataFrame:
        g = g.sort_values("year").copy()
        years = g["year"].to_numpy(dtype=int)
        target = g["company_trajectory_target"].to_numpy(dtype=float)
        ls = g["company_trajectory_latesudden"].to_numpy(dtype=float)
        phase = g["late_sudden_phase"].to_numpy(dtype=object)

        pre_mask = years <= alignment_year
        post_mask = years > alignment_year

        pre_excess = float(np.nansum(ls[pre_mask] - target[pre_mask]))
        post_gap = float(np.nansum(ls[post_mask] - target[post_mask]))
        comp_volume = max(pre_excess - post_gap, 0.0)

        if comp_volume > 0 and post_mask.any():
            per_year = -comp_volume / int(post_mask.sum())
            ls[post_mask] = np.maximum(ls[post_mask] + per_year, 0.0)
            # only mark post years as 'compensation' where we actually reduced
            phase[post_mask] = np.where(per_year < 0, "compensation", phase[post_mask])

        g["company_trajectory_latesudden"] = ls
        g["late_sudden_phase"] = phase
        return g

    res = companies_late_sudden_trajectories.copy()
    misaligned = res["alignment_type"] == "misaligned_high_carbon"
    res.loc[misaligned] = (
        res[misaligned]
        .groupby(
            ["company_id", "scenario_geography", "sector", "technology"],
            group_keys=False,
            sort=False,
        )
        .apply(_apply_comp)
        .reset_index(drop=True)
    )
    return res


def split_late_sudden_trajectories_by_alignment_type(
    assets_late_sudden_trajectories: pd.DataFrame,
):
    """Return (decreasing_df, increasing_df)."""
    dec_mask = assets_late_sudden_trajectories["alignment_type"].isin(
        ["misaligned_high_carbon", "aligned_high_carbon"]
    )
    inc_mask = assets_late_sudden_trajectories["alignment_type"].isin(
        ["misaligned_low_carbon", "aligned_low_carbon"]
    )
    return (
        assets_late_sudden_trajectories[dec_mask].copy(),
        assets_late_sudden_trajectories[inc_mask].copy(),
    )


# =========================================================
# ================= Allocation helpers ====================
# =========================================================


def _compute_g_weights(
    ages: pd.Series,
    k: float,
    n_quantiles: int,
    for_decreasing: bool,
    min_active_share: float = 1e-12,
) -> pd.Series:
    """
    Logistic-sum g(a) per your original spec; invert sign for decreasing.
    Normalize to sum=1 over nonzero weights, clip by min_active_share.
    """
    ages = ages.astype(float)
    if ages.empty:
        return pd.Series(dtype=float)

    # quantile cut points (exclude 0 and 1)
    qs = np.linspace(0, 1, n_quantiles + 1)[1:-1]
    cuts = np.quantile(ages.to_numpy(), qs) if len(qs) else np.array([])

    def base(a):
        return 1.0 - np.sum(1.0 / (1.0 + np.exp(-k * (a - cuts)))) if cuts.size else 1.0

    raw = ages.map(lambda a: base(a))
    if for_decreasing:
        raw = -raw  # older => higher

    # make positive, clip and normalize
    raw = raw - raw.min() + min_active_share
    s = raw.sum()
    if not np.isfinite(s) or s <= 0:
        return pd.Series(1.0 / len(raw), index=ages.index)
    return raw / s


def _solve_negative_with_floors(b: np.ndarray, w: np.ndarray, R: float) -> np.ndarray:
    """
    Reduce total R (>0) from vector b using weights w, with floors at 0:
      d_i = min(alpha * w_i, b_i),   sum(d_i) = R
    If R >= sum(b), saturates at b (all to zero).

    Returns d (nonnegative reductions). Use alloc = -d for allocated_shock.
    """
    b = np.asarray(b, dtype=float)
    w = np.asarray(w, dtype=float)
    if R <= 0 or b.size == 0:
        return np.zeros_like(b)

    B = b.sum()
    if R >= B:
        return b.copy()

    # binary search on alpha in [0, max(b_i / w_i)]
    mask = w > 0
    if not mask.any():
        # equal split on available capacity
        return (R / B) * b

    t = np.full_like(w, np.inf, dtype=float)
    t[mask] = b[mask] / w[mask]
    lo, hi = 0.0, float(np.max(t[mask]))
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        d = np.minimum(mid * w, b)
        s = d.sum()
        if s < R:
            lo = mid
        else:
            hi = mid
    alpha = hi
    d = np.minimum(alpha * w, b)
    # tiny numerical fix to hit R exactly
    err = d.sum() - R
    if abs(err) > 1e-9:
        d -= err / max(b.size, 1)
        d = np.clip(d, 0.0, b)
    return d


# =========================================================
# ================== Staggering allocators =================
# =========================================================


def _emit_rows_for_year(
    key_row: dict,
    year: int,
    before: pd.Series,
    alloc: pd.Series,
    ages: pd.Series,
    is_synthetic_flags: pd.Series = None,
    late_sudden_phase: str = "",
) -> pd.DataFrame:
    after = before + alloc
    out = pd.DataFrame(
        {
            "asset_id": before.index,
            "company_id": key_row["company_id"],
            "scenario_geography": key_row["scenario_geography"],
            "sector": key_row["sector"],
            "technology": key_row["technology"],
            "year": int(year),
            "asset_age": ages.reindex(before.index).astype(float).values,
            "capacity_before_shock": before.values.astype(float),
            "allocated_shock": alloc.values.astype(float),
            "capacity_after_shock": after.values.astype(float),
            "is_synthetic": (
                is_synthetic_flags.reindex(before.index).values
                if is_synthetic_flags is not None
                else np.zeros_like(before.values, dtype=bool)
            ),
            "late_sudden_phase": late_sudden_phase or "",
        }
    )
    # clip tiny negatives due to fp
    out["capacity_after_shock"] = np.where(
        out["capacity_after_shock"] < 0,
        np.maximum(out["capacity_after_shock"], 0.0),
        out["capacity_after_shock"],
    )
    return out


def stagger_decreasing_tech(
    assets_late_sudden_trajectories: pd.DataFrame,
    companies_late_sudden_trajectories: pd.DataFrame,
    shock_year: int,
    alignment_year: int,
    g_k: float = 6.0,
    n_quantiles: int = 3,
    debug: bool = False,
) -> pd.DataFrame:
    """
    For decreasing technologies:
      - Per (c,geo,sector,tech,year), compute Δ_y = C_y - Σ assets_LS_y
      - If Δ_y < 0, allocate the reduction to real assets using g-weights
        (older first) with a floor at 0.
      - If Δ_y >= 0, do nothing (we keep asset L&S as-is).
      - For years flagged 'retirement' at the company level, copy that phase
        value to every asset row for that year.

    Output columns:
      asset_id, company_id, scenario_geography, sector, technology, year,
      asset_age, capacity_before_shock, allocated_shock, capacity_after_shock,
      is_synthetic, late_sudden_phase
    """
    # index helpers
    kcols = ["company_id", "scenario_geography", "sector", "technology"]
    aset = assets_late_sudden_trajectories.copy()
    comp = companies_late_sudden_trajectories.copy()

    # We rely on asset ages being provided (per your clarification)
    need_a = kcols + ["asset_id", "year", "asset_age", "asset_trajectory_latesudden"]
    miss_a = [c for c in need_a if c not in aset.columns]
    if miss_a:
        raise ValueError(f"Missing columns in assets L&S: {miss_a}")

    need_c = kcols + ["year", "company_trajectory_latesudden", "late_sudden_phase"]
    miss_c = [c for c in need_c if c not in comp.columns]
    if miss_c:
        raise ValueError(f"Missing columns in companies L&S: {miss_c}")

    # Grouped views for speed
    comp_g = {
        k: g.sort_values("year").set_index("year")
        for k, g in comp.groupby(kcols, sort=False)
    }
    out_parts = []

    # Work by (company, geo, sector, tech)
    for key, g_assets in tqdm(
        list(aset.groupby(kcols, sort=False)), desc="Stagger (decreasing)", unit="grp"
    ):
        comp_years = comp_g.get(key)
        if comp_years is None or comp_years.empty:
            continue

        g_assets = g_assets[
            ["asset_id", "year", "asset_age", "asset_trajectory_latesudden"]
        ].copy()
        # build per-year views
        years = sorted(comp_years.index.astype(int).tolist())

        for y in years:
            comp_row = comp_years.loc[y]
            C_y = float(comp_row["company_trajectory_latesudden"])
            ls_y = g_assets[g_assets["year"] == y]
            if ls_y.empty:
                # No assets this year -> nothing to emit
                continue

            before = ls_y.set_index("asset_id")["asset_trajectory_latesudden"].astype(
                float
            )
            ages = ls_y.set_index("asset_id")["asset_age"].astype(float)

            A_y = float(before.sum())
            delta = C_y - A_y

            if delta < -1e-12:
                # need to reduce |delta|
                w = _compute_g_weights(
                    ages, k=g_k, n_quantiles=n_quantiles, for_decreasing=True
                )
                reductions = _solve_negative_with_floors(
                    b=before.to_numpy(), w=w.to_numpy(), R=-delta
                )
                alloc = pd.Series(
                    -reductions, index=before.index
                )  # negative allocated_shock
            else:
                # do nothing, but we still emit rows (allocated_shock=0)
                alloc = pd.Series(0.0, index=before.index)

            # phase: copy 'retirement' to assets only on that exact year
            phase = (
                str(comp_row.get("late_sudden_phase", ""))
                if isinstance(comp_row, pd.Series)
                else ""
            )
            phase_label = "retirement" if phase == "retirement" else ""

            key_row = dict(zip(kcols, key))
            out_parts.append(
                _emit_rows_for_year(
                    key_row=key_row,
                    year=int(y),
                    before=before,
                    alloc=alloc,
                    ages=ages,
                    is_synthetic_flags=pd.Series(False, index=before.index),
                    late_sudden_phase=phase_label,
                )
            )

    res = (
        pd.concat(out_parts, ignore_index=True)
        if out_parts
        else pd.DataFrame(
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
    )
    if debug and not res.empty:
        # sanity: exact company totals
        pass
    return res


def stagger_increasing_tech(
    assets_late_sudden_trajectories: pd.DataFrame,
    companies_late_sudden_trajectories: pd.DataFrame,
    shock_year: int,
) -> pd.DataFrame:
    """
    Variant A:
      - For y < shock_year: keep real assets unchanged (allocated_shock=0).
        If delta < 0 (company < assets), reduce real assets using negative solver (older first).
      - For y >= shock_year: no reallocation to real assets. If delta > 0, put ALL delta
        on a single synthetic asset NEW_{company}_{sector}_{tech}_{geo}. If delta < 0, reduce real
        assets with negative solver to keep sums exact.
    """
    kcols = ["company_id", "scenario_geography", "sector", "technology"]
    aset = assets_late_sudden_trajectories.copy()
    comp = companies_late_sudden_trajectories.copy()

    need_a = kcols + ["asset_id", "year", "asset_age", "asset_trajectory_latesudden"]
    miss_a = [c for c in need_a if c not in aset.columns]
    if miss_a:
        raise ValueError(f"Missing columns in assets L&S: {miss_a}")

    need_c = kcols + ["year", "company_trajectory_latesudden"]
    miss_c = [c for c in need_c if c not in comp.columns]
    if miss_c:
        raise ValueError(f"Missing columns in companies L&S: {miss_c}")

    comp_g = {
        k: g.sort_values("year").set_index("year")
        for k, g in comp.groupby(kcols, sort=False)
    }
    out_parts = []

    for key, g_assets in tqdm(
        list(aset.groupby(kcols, sort=False)), desc="Stagger (increasing)", unit="grp"
    ):
        comp_years = comp_g.get(key)
        if comp_years is None or comp_years.empty:
            continue

        cid, geo, sector, tech = key
        synth_id = f"NEW_{cid}_{sector}_{tech}_{geo}"

        g_assets = g_assets[
            ["asset_id", "year", "asset_age", "asset_trajectory_latesudden"]
        ].copy()
        years = sorted(comp_years.index.astype(int).tolist())

        # Keep synthetic carry-forward state
        synth_prev_cap = 0.0
        synth_prev_age = 0.0
        have_synth = False

        for y in years:
            C_y = float(comp_years.loc[y, "company_trajectory_latesudden"])
            ls_y = g_assets[g_assets["year"] == y]

            if ls_y.empty:
                # even if no real assets this year, we may still need to emit synthetic if delta>0 post-shock
                before = pd.Series(dtype=float)
                ages = pd.Series(dtype=float)
            else:
                before = ls_y.set_index("asset_id")[
                    "asset_trajectory_latesudden"
                ].astype(float)
                ages = ls_y.set_index("asset_id")["asset_age"].astype(float)

            A_y = float(before.sum())
            delta = C_y - A_y

            # 1) Real assets: default is carry-through (alloc=0)
            real_alloc = pd.Series(0.0, index=before.index)

            if y < shock_year:
                if delta < -1e-12 and not before.empty:
                    # Reduce real assets to match company < assets
                    w = _compute_g_weights(
                        ages, k=6.0, n_quantiles=3, for_decreasing=True
                    )
                    reductions = _solve_negative_with_floors(
                        b=before.to_numpy(), w=w.to_numpy(), R=-delta
                    )
                    real_alloc = pd.Series(-reductions, index=before.index)
                # If delta > 0 before shock, we leave it as drift in company; no synthetic pre-shock
                synth_this_year = None
            else:
                # y >= shock_year
                if delta < -1e-12 and not before.empty:
                    # If company is below assets (rare for increasing), reduce real assets
                    w = _compute_g_weights(
                        ages, k=6.0, n_quantiles=3, for_decreasing=True
                    )
                    reductions = _solve_negative_with_floors(
                        b=before.to_numpy(), w=w.to_numpy(), R=-delta
                    )
                    real_alloc = pd.Series(-reductions, index=before.index)

                # Positive delta entirely to the synthetic asset
                synth_alloc = max(delta, 0.0)
                if synth_alloc > 1e-12:
                    have_synth = True
                    age_y = (
                        0.0
                        if (y == shock_year and synth_prev_age == 0.0)
                        else (synth_prev_age + 1.0)
                    )
                    synth_before = synth_prev_cap
                    synth_after = synth_before + synth_alloc
                    synth_prev_cap = synth_after
                    synth_prev_age = age_y

                    synth_this_year = pd.Series(
                        data=[synth_before],
                        index=[synth_id],
                        dtype=float,
                        name="capacity_before_shock",
                    )
                    synth_alloc_series = pd.Series(
                        data=[synth_alloc],
                        index=[synth_id],
                        dtype=float,
                        name="allocated_shock",
                    )
                    synth_age_series = pd.Series(
                        data=[age_y],
                        index=[synth_id],
                        dtype=float,
                        name="asset_age",
                    )
                else:
                    # carry-forward synthetic if it already exists
                    if have_synth:
                        synth_prev_age = synth_prev_age + 1.0  # aging
                        synth_this_year = pd.Series(
                            data=[synth_prev_cap],
                            index=[synth_id],
                            dtype=float,
                            name="capacity_before_shock",
                        )
                        synth_alloc_series = pd.Series(
                            data=[0.0],
                            index=[synth_id],
                            dtype=float,
                            name="allocated_shock",
                        )
                        synth_age_series = pd.Series(
                            data=[synth_prev_age],
                            index=[synth_id],
                            dtype=float,
                            name="asset_age",
                        )
                    else:
                        synth_this_year = None

            # Emit real assets
            key_row = {
                "company_id": cid,
                "scenario_geography": geo,
                "sector": sector,
                "technology": tech,
            }
            out_parts.append(
                _emit_rows_for_year(
                    key_row=key_row,
                    year=int(y),
                    before=before,
                    alloc=real_alloc,
                    ages=ages,
                    is_synthetic_flags=pd.Series(False, index=before.index),
                    late_sudden_phase="",
                )
            )

            # Emit synthetic (if any)
            if y >= shock_year and synth_this_year is not None:
                synth_before = synth_this_year
                synth_alloc_series = synth_alloc_series  # from above branch
                synth_after = synth_before + synth_alloc_series
                synth_is = pd.Series(True, index=synth_before.index)

                out_parts.append(
                    pd.DataFrame(
                        {
                            "asset_id": synth_before.index,
                            "company_id": cid,
                            "scenario_geography": geo,
                            "sector": sector,
                            "technology": tech,
                            "year": int(y),
                            "asset_age": synth_age_series.reindex(synth_before.index)
                            .astype(float)
                            .values,
                            "capacity_before_shock": synth_before.values.astype(float),
                            "allocated_shock": synth_alloc_series.values.astype(float),
                            "capacity_after_shock": synth_after.values.astype(float),
                            "is_synthetic": synth_is.values.astype(bool),
                            "late_sudden_phase": "",
                        }
                    )
                )

    res = (
        pd.concat(out_parts, ignore_index=True)
        if out_parts
        else pd.DataFrame(
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
    )
    return res


def concatenate_staggered_shock_results(
    dec_late_sudden_trajectories: pd.DataFrame,
    inc_late_sudden_trajectories: pd.DataFrame,
) -> pd.DataFrame:

    assets_staggered_late_sudden = pd.concat(
        [dec_late_sudden_trajectories, inc_late_sudden_trajectories], ignore_index=True
    ).reset_index(drop=True)

    return assets_staggered_late_sudden
