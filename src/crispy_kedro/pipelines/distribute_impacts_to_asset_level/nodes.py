import logging
import numpy as np
import pandas as pd
from typing import Dict, Tuple, List
from tqdm import tqdm

logger = logging.getLogger(__name__)
# =========================================================
# ==================== Common helpers =====================
# =========================================================


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
    tmp["retirement_year"] = _ensure_int_year(tmp["retirement_year"])

    for key, sub in tmp.groupby(GROUP_COLS, sort=False):
        r = dict(zip(sub["asset_id"].astype(str), sub["retirement_year"].astype(int)))
        ret_map[key] = r
    return ret_map


def _emit_rows(
    key: Tuple[str, str, str, str],
    year: int,
    before: pd.Series,
    alloc: pd.Series,
    ages: pd.Series,
    synthetic_mask: pd.Series = None,
    late_sudden_phase: pd.Series = None,
    alignment_type: pd.Series = None,
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
            "alignment_type": alignment_type.reindex(before.index)
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
    and fill NA years in (y0, shock_year] using business-as-usual scaling:
        asset_activity[y] = asset_activity[y0] * (company_baseline[y] / company_baseline[y0]).

    From the shock year onward (y > shock_year), fill NA values with a constant equal to the
    shock-year level (or the last available level <= shock_year if shock year row is absent).

    - Uses lsc['company_trajectory_baseline'] for the baseline.
    - Rows are filled the entire way to the end of the forecast.
    - Returns a copy of `assets` with asset_activity filled.
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
    out["year"] = _ensure_int_year(out["year"])
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
    out = grouped.apply(
        _fill_one, progress_bar=tqdm(total=len(grouped), desc="BAU fill", unit="grp")
    )

    # Clean up helper column
    out.drop(columns=["_company_baseline"], inplace=True)
    return out


def _reduce_weighted_with_caps(
    floors: pd.Series,  # >=0, per-asset max reducible this year = Plate_{y-1,a}
    g_weights: pd.Series,  # >=0, sum to 1 (we'll renormalize on the fly)
    R: float,  # >0 total amount to reduce this year
) -> pd.Series:
    """
    Allocate R across assets by g-weights with per-asset caps (floors),
    with iterative reweighting as assets saturate. Returns *negative* deltas.
    """
    alloc_pos = pd.Series(0.0, index=floors.index, dtype=float)
    if R <= 1e-12 or floors.empty:
        return alloc_pos.rename("allocated_pos") * -1.0  # negative outward

    rem = float(R)
    cap = floors.clip(lower=0.0).astype(float).copy()
    w = g_weights.clip(lower=0.0).astype(float).reindex(cap.index).fillna(0.0)

    # iterative water-filling
    for _ in range(len(cap)):
        ws = w.sum()
        if ws <= 0 or rem <= 1e-12:
            break
        share = rem * (w / ws)
        take = np.minimum(share, cap)
        alloc_pos += take
        rem -= float(take.sum())
        cap -= take
        # zero out saturated assets and renormalize next round
        w[cap <= 1e-12] = 0.0

    return -alloc_pos  # return negative allocations


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


def stagger_decreasing_technologies(
    late_sudden_trajectories: pd.DataFrame,
    allocated_assets_to_companies: pd.DataFrame,
    assets_retirement_dates: pd.DataFrame,
    shock_year: int,
    alignment_year: int,
    apply_retirement: bool,
    apply_decreasing_staggered_shock: bool,
    g_k: float = 6.0,
    n_quantiles: int = 3,
) -> pd.DataFrame:
    """
    Decreasing techs:

    - If apply_decreasing_staggered_shock is False: from shock_year onward, scale each asset
      proportionally to its share at the shock year so that the sum across assets matches the
      company late-sudden trajectory exactly. No age weighting; no negatives.
    - If True: use staggered allocation with age-based g-weights and per-asset caps.

    Retirement is not handled here; it can be applied later by a dedicated node.
    """
    GROUP_COLS = ["company_id", "scenario_geography", "sector", "technology"]
    if not apply_decreasing_staggered_shock:
        need_c = GROUP_COLS + ["year", "company_trajectory_latesudden"]
        miss_c = [c for c in need_c if c not in late_sudden_trajectories.columns]
        if miss_c:
            raise ValueError(f"late_sudden_trajectories missing columns: {miss_c}")
        need_a = GROUP_COLS + ["asset_id", "year", "asset_activity", "asset_age"]
        miss_a = [c for c in need_a if c not in allocated_assets_to_companies.columns]
        if miss_a:
            raise ValueError(f"allocated_assets_to_companies missing columns: {miss_a}")

        lsc = late_sudden_trajectories.copy()
        lsc["year"] = _ensure_int_year(lsc["year"])

        # BAU fill to shock year and constant thereafter for missing values
        assets = _bau_fill_assets_until_shock(
            lsc=lsc, assets=allocated_assets_to_companies.copy(), shock_year=shock_year
        )
        assets["year"] = _ensure_int_year(assets["year"])
        assets["asset_id"] = assets["asset_id"].astype(str)

        comp_by_key = _index_company_by_year(lsc)
        out_parts: List[pd.DataFrame] = []

        for key, comp_years in tqdm(
            list(comp_by_key.items()), desc="Prop-scale dec", unit="grp"
        ):
            cid, geo, sector, tech = key
            aset_g = assets[
                (assets["company_id"] == cid)
                & (assets["scenario_geography"] == geo)
                & (assets["sector"] == sector)
                & (assets["technology"] == tech)
            ][["asset_id", "year", "asset_activity", "asset_age"]].copy()
            if aset_g.empty:
                continue

            # shock-year shares (use last <= shock if exact year missing)
            sub_shock = aset_g[aset_g["year"] == int(shock_year)]
            if sub_shock.empty:
                sub_shock = (
                    aset_g[aset_g["year"] <= int(shock_year)]
                    .sort_values(["asset_id", "year"])
                    .groupby("asset_id", sort=False)
                    .tail(1)
                )
            vals = (
                sub_shock.set_index("asset_id")["asset_activity"]
                .astype(float)
                .clip(lower=0.0)
            )
            S = float(vals.sum())
            if S > 0.0:
                w = (vals / S).astype(float)
            else:
                # no real capacity at shock -> keep zeros
                w = pd.Series(0.0, index=vals.index, dtype=float)

            years = sorted(map(int, comp_years.index.tolist()))
            prev_after_by_asset: Dict[str, float] = {}

            for i, y in enumerate(years):
                C_y = float(comp_years.at[y, "company_trajectory_latesudden"])
                # Get the company phase for this year (like in staggered branch)
                comp_phase = (
                    str(comp_years.at[y, "late_sudden_phase"])
                    if "late_sudden_phase" in comp_years.columns
                    else ""
                )

                sub = aset_g[aset_g["year"] == y].copy()
                sub["asset_id"] = sub["asset_id"].astype(str)
                ages_y = sub.set_index("asset_id")["asset_age"].astype(float)

                # Determine before baseline
                if y < int(shock_year):
                    before = sub.set_index("asset_id")["asset_activity"].astype(float)
                    after = before.copy()
                elif i == 0:
                    # first year at/after shock: before is BAU/forecast, after is proportional to company
                    before = sub.set_index("asset_id")["asset_activity"].astype(float)
                    idx = sorted(set(before.index) | set(w.index))
                    w_idx = w.reindex(idx).fillna(0.0)
                    ages_y = ages_y.reindex(idx).ffill().bfill().fillna(0.0)
                    after = pd.Series((w_idx * C_y).values, index=idx, dtype=float)
                else:
                    # chain: before is last year's after; after follows company shape with fixed shares
                    idx = sorted(set(prev_after_by_asset.keys()) | set(w.index))
                    before = pd.Series(
                        {aid: prev_after_by_asset.get(aid, 0.0) for aid in idx},
                        dtype=float,
                    )
                    w_idx = w.reindex(idx).fillna(0.0)
                    if not ages_y.empty:
                        ages_y = ages_y.reindex(idx).ffill().bfill().fillna(0.0)
                    else:
                        ages_y = pd.Series(0.0, index=idx, dtype=float)
                    after = pd.Series((w_idx * C_y).values, index=idx, dtype=float)

                after = after.clip(lower=0.0)
                alloc = after.add(-before, fill_value=0.0)
                prev_after_by_asset = {aid: float(after.at[aid]) for aid in after.index}

                out_parts.append(
                    _emit_rows(
                        key,
                        year=y,
                        before=before,
                        alloc=alloc,
                        ages=ages_y,
                        synthetic_mask=pd.Series(False, index=before.index),
                        late_sudden_phase=pd.Series(
                            comp_phase, index=before.index, dtype=object
                        ),
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
                "alignment_type",
            ]
        )
    else:
        need_c = GROUP_COLS + ["year", "company_trajectory_latesudden"]
        miss_c = [c for c in need_c if c not in late_sudden_trajectories.columns]
        if miss_c:
            raise ValueError(f"late_sudden_trajectories missing columns: {miss_c}")
        need_a = GROUP_COLS + ["asset_id", "year", "asset_activity", "asset_age"]
        miss_a = [c for c in need_a if c not in allocated_assets_to_companies.columns]
        if miss_a:
            raise ValueError(f"allocated_assets_to_companies missing columns: {miss_a}")

        lsc = late_sudden_trajectories.copy()
        lsc["year"] = _ensure_int_year(lsc["year"])

        # Step 1–2: BAU fill up to shock year
        logger.info("BAU filling assets until shock year")
        assets = _bau_fill_assets_until_shock(
            lsc=lsc, assets=allocated_assets_to_companies.copy(), shock_year=shock_year
        )
        # assets["year"] = _ensure_int_year(assets["year"])
        # assets["asset_id"] = assets["asset_id"].astype(str)
        logger.info("Indexing company by year")
        comp_by_key = _index_company_by_year(lsc)
        logger.info("Building retirement map")
        ret_map_by_key = _build_retirement_map(assets_retirement_dates)
        out_parts: List[pd.DataFrame] = []

        for key, comp_years in tqdm(
            list(comp_by_key.items()), desc="Stagger dec", unit="grp"
        ):
            cid, geo, sector, tech = key
            aset_g = assets[
                (assets["company_id"] == cid)
                & (assets["scenario_geography"] == geo)
                & (assets["sector"] == sector)
                & (assets["technology"] == tech)
            ][["asset_id", "year", "asset_activity", "asset_age"]].copy()
            if aset_g.empty:
                continue

            raw_ret = ret_map_by_key.get(key, {})
            # effective retirement after alignment
            eff_ret = {
                aid: max(int(y_r), int(alignment_year) + 1)
                for aid, y_r in raw_ret.items()
            }

            years = sorted(map(int, comp_years.index.tolist()))
            prev_company = None

            # THIS is the key state: Plate_{y-1,a} (previous year's after-shock)
            prev_after_by_asset: Dict[str, float] = {}

            for i, y in enumerate(years):
                C_y = float(comp_years.at[y, "company_trajectory_latesudden"])
                comp_phase = str(comp_years.at[y, "late_sudden_phase"])
                alignment_type = str(comp_years.at[y, "alignment_type"])

                # Pull ages for g-weights from the forecast table for this year (fallback to prev+1)
                sub = aset_g[aset_g["year"] == y].copy()
                sub["asset_id"] = sub["asset_id"].astype(str)
                ages_y = sub.set_index("asset_id")["asset_age"].astype(float)

                # -------- Determine 'before' (the base we modify this year)
                if y < int(shock_year):
                    # Before shock year: always use BAU-filled forecast values
                    before = sub.set_index("asset_id")["asset_activity"].astype(float)
                elif i == 0:
                    # First year at/after shock: anchor on forecast/BAU
                    before = sub.set_index("asset_id")["asset_activity"].astype(float)
                else:
                    # After first year at/after shock: chain from last year's after (modified values)
                    # include any new assets appearing with 0 base so they don't create oscillations
                    idx = sorted(set(prev_after_by_asset.keys()) | set(sub["asset_id"]))
                    before = pd.Series(
                        {aid: prev_after_by_asset.get(aid, 0.0) for aid in idx},
                        dtype=float,
                    )
                    # keep age alignment for all ids we track
                    if not ages_y.empty:
                        ages_y = (
                            ages_y.reindex(before.index).ffill().bfill().fillna(0.0)
                        )
                    else:
                        ages_y = pd.Series(0.0, index=before.index, dtype=float)

                # -------- company delta (negative part from shock year onward)
                if prev_company is None:
                    shock_neg = 0.0
                else:
                    delta = C_y - prev_company
                    shock_neg = min(delta, 0.0) if y >= int(shock_year) else 0.0
                prev_company = C_y

                # -------- retirement only AFTER alignment_year and for misaligned_high_carbon companies
                forced = pd.Series(0.0, index=before.index, dtype=float)
                phase = pd.Series(comp_phase, index=before.index, dtype=object)
                if (
                    apply_retirement
                    and alignment_type == "misaligned_high_carbon"
                    and y > int(alignment_year)
                    and eff_ret
                ):
                    retire_now = [
                        aid
                        for aid, yr in eff_ret.items()
                        if aid in before.index and y >= yr
                    ]
                    if retire_now:
                        forced.loc[retire_now] = -before.loc[retire_now].astype(float)
                    for aid, yr in eff_ret.items():
                        if aid in before.index and y == yr:
                            phase.at[aid] = "retirement"

                # -------- apply negative shock by g-weights with caps (Plate_{y-1,a})
                extra = pd.Series(0.0, index=before.index, dtype=float)
                remaining = shock_neg - float(forced.sum())  # ≤ 0 desired
                if remaining < -1e-12:
                    # active = those not force-retired this year
                    active = before.index[forced >= 0.0]
                    if len(active) > 0:
                        # Plate_{y-1,a} = 'before' (because we are chaining)
                        floors = before.loc[active].clip(lower=0.0)
                        g = _compute_g_weights(
                            ages_y.loc[active],
                            k=g_k,
                            n_quantiles=n_quantiles,
                            for_decreasing=True,
                        )
                        extra.loc[active] = _reduce_weighted_with_caps(
                            floors=floors, g_weights=g, R=-remaining
                        )

                alloc = forced.add(extra, fill_value=0.0)
                after = before.add(alloc, fill_value=0.0).clip(lower=0.0)

                # update Plate_{y,a} for next year
                prev_after_by_asset = {aid: float(after.at[aid]) for aid in after.index}

                out_parts.append(
                    _emit_rows(
                        key,
                        year=y,
                        before=before,
                        alloc=alloc,
                        ages=ages_y,
                        synthetic_mask=pd.Series(False, index=before.index),
                        late_sudden_phase=phase,
                        alignment_type=pd.Series(
                            alignment_type, index=before.index, dtype=object
                        ),
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
                "alignment_type",
            ]
        )


def enforce_retirements_after_alignment(
    dec_df: pd.DataFrame,
    assets_retirement_dates: pd.DataFrame,
    alignment_year: int,
    apply_retirement: bool,
) -> pd.DataFrame:
    """
    Enforce retirements after the alignment year by zeroing capacity from the
    effective retirement year onward for assets present in assets_retirement_dates.

    - effective retirement year = max(retirement_year, alignment_year+1)
    - Recomputes capacity_before_shock and allocated_shock to maintain chaining
    - Sets late_sudden_phase to "retirement" at the effective retirement year
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
    df["year"] = _ensure_int_year(df["year"]).astype(int)
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
    Mark assets that phase out (capacity_after_shock becomes 0 and stays 0 thereafter)
    as retired by setting late_sudden_phase == "retirement" at the first year of
    permanent zero capacity. Only applies to real assets (is_synthetic == False).
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

    df["year"] = _ensure_int_year(df["year"]).astype(int)
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
    allocated_assets_to_companies: pd.DataFrame,
    shock_year: int,
) -> pd.DataFrame:
    """
    Increasing techs (vectorized, simple):
      - Keep real assets at BAU/forecast for all years.
      - From shock_year onward, assign all capacity above S_shock
        (sum of BAU real assets at shock_year) to ONE synthetic asset.
      - No retirements.
    """
    GROUP_COLS = ["company_id", "scenario_geography", "sector", "technology"]
    lsc = late_sudden_trajectories.copy()
    need_c = GROUP_COLS + [
        "year",
        "company_trajectory_latesudden",
        "late_sudden_phase",
        "alignment_type",
    ]
    miss_c = [c for c in need_c if c not in lsc.columns]
    if miss_c:
        raise ValueError(f"late_sudden_trajectories missing columns: {miss_c}")

    need_a = GROUP_COLS + ["asset_id", "year", "asset_activity", "asset_age"]
    miss_a = [c for c in need_a if c not in allocated_assets_to_companies.columns]
    if miss_a:
        raise ValueError(f"allocated_assets_to_companies missing columns: {miss_a}")

    # Ensure numeric years
    lsc["year"] = _ensure_int_year(lsc["year"])

    # BAU fill up to shock & hold constant for missing values after (your helper)
    assets_bau = _bau_fill_assets_until_shock(
        lsc=lsc, assets=allocated_assets_to_companies.copy(), shock_year=shock_year
    )
    assets_bau["year"] = _ensure_int_year(assets_bau["year"])
    assets_bau["asset_id"] = assets_bau["asset_id"].astype(str)

    # Preindex company LS by key/year (vectorized join later)
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

    out_real = []
    out_synth = []

    for key, comp_years in comp_by_key.items():
        cid, geo, sector, tech = key
        synth_id = f"NEW_{cid}_{sector}_{tech}_{geo}"

        # Filter assets of this bucket and keep only years present in company LS
        aset = assets_bau[
            (assets_bau["company_id"] == cid)
            & (assets_bau["scenario_geography"] == geo)
            & (assets_bau["sector"] == sector)
            & (assets_bau["technology"] == tech)
        ][["asset_id", "year", "asset_activity", "asset_age"]].copy()

        years = comp_years["year"].to_numpy()
        if aset.empty and years.size == 0:
            continue

        # -------- Real assets: keep BAU for all years (vectorized)
        if not aset.empty:
            aset_key = aset.merge(
                comp_years[["year", "late_sudden_phase", "alignment_type"]],
                on="year",
                how="inner",  # align to LS years
            )
            if not aset_key.empty:
                before = aset_key.set_index("asset_id")[
                    [
                        "year",
                        "asset_activity",
                        "asset_age",
                        "late_sudden_phase",
                        "alignment_type",
                    ]
                ]
                # emit rows per year by simple rename (alloc = 0, after = before)
                block = before.reset_index().rename(
                    columns={"asset_activity": "capacity_before_shock"}
                )
                block["allocated_shock"] = 0.0
                block["capacity_after_shock"] = block["capacity_before_shock"]
                block["company_id"] = cid
                block["scenario_geography"] = geo
                block["sector"] = sector
                block["technology"] = tech
                block["is_synthetic"] = False
                block["late_sudden_phase"] = block["late_sudden_phase"]
                block["alignment_type"] = block["alignment_type"]
                out_real.append(
                    block[
                        [
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
                        ]
                    ]
                )

        # -------- Synthetic: from shock_year onward, max(0, LS - S_shock)
        # Compute S_shock from BAU snapshot at shock_year (sum over real assets)
        if aset.empty:
            S_shock = 0.0
        else:
            shock_slice = aset[aset["year"] == int(shock_year)]
            S_shock = (
                float(shock_slice["asset_activity"].sum())
                if not shock_slice.empty
                else 0.0
            )

        if years.size > 0:
            # Vectorized series for LS
            C = comp_years["company_trajectory_latesudden"].to_numpy(dtype=float)
            # synthetic capacity per year
            synth_cap = np.where(
                years >= int(shock_year), np.maximum(0.0, C - S_shock), 0.0
            )
            # capacity_before (prev year's synthetic), allocated = delta
            synth_before = np.concatenate(([0.0], synth_cap[:-1]))
            alloc = synth_cap - synth_before

            # synthetic age: 0 at first positive year, then +1 each subsequent positive year,
            # stays 0 when capacity is 0.
            pos = synth_cap > 0.0
            if pos.any():
                first_idx = np.argmax(pos)  # first True position
                synth_age = np.where(pos, years - years[first_idx], 0.0).astype(float)
            else:
                synth_age = np.zeros_like(synth_cap, dtype=float)

            synth_df = pd.DataFrame(
                {
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
            )
            out_synth.append(synth_df)

    # concat results
    parts = []
    if out_real:
        parts.append(pd.concat(out_real, ignore_index=True))
    if out_synth:
        parts.append(pd.concat(out_synth, ignore_index=True))
    if parts:
        return pd.concat(parts, ignore_index=True)

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
            "alignment_type",
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
