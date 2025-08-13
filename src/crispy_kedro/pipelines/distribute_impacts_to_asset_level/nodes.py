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

    out = out.groupby(gcols, sort=False, group_keys=False).apply(_fill_one)

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
    apply_retirement: bool = True,
    g_k: float = 6.0,
    n_quantiles: int = 3,
) -> pd.DataFrame:
    """
    Decreasing techs:

    - y < shock_year: follow forecast/BAU (no allocations).
    - shock_year ≤ y ≤ alignment_year: allocate negative company deltas by g-weights
      with caps, using *previous year's after* as the per-asset base/floor.
    - y > alignment_year: enforce retirements (effective retirement =
      max(retirement_year, alignment_year+1)) and keep allocating remaining
      negative deltas by g-weights with caps, still chaining from last year's after.
    """
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

    # Step 1–2: BAU fill up to shock year (you already had this)
    assets = _bau_fill_assets_until_shock(
        lsc=lsc, assets=allocated_assets_to_companies.copy(), shock_year=shock_year
    )
    assets["year"] = _ensure_int_year(assets["year"])
    assets["asset_id"] = assets["asset_id"].astype(str)

    comp_by_key = _index_company_by_year(lsc)
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
            aid: max(int(y_r), int(alignment_year) + 1) for aid, y_r in raw_ret.items()
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
                    {aid: prev_after_by_asset.get(aid, 0.0) for aid in idx}, dtype=float
                )
                # keep age alignment for all ids we track
                if not ages_y.empty:
                    ages_y = ages_y.reindex(before.index).ffill().bfill().fillna(0.0)
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
    lsc = late_sudden_trajectories.copy()
    need_c = GROUP_COLS + ["year", "company_trajectory_latesudden"]
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
        k: g.sort_values("year")[["year", "company_trajectory_latesudden"]]
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
                comp_years[["year"]], on="year", how="inner"  # align to LS years
            )
            if not aset_key.empty:
                before = aset_key.set_index("asset_id")[
                    ["year", "asset_activity", "asset_age"]
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
                block["late_sudden_phase"] = ""
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
                    "late_sudden_phase": "",
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


def compute_capex_indicators(
    assets_staggered_late_sudden: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build capex indicators per asset based on assets_staggered_late_sudden.

    Inputs (required columns):
      - company_id, asset_id, year, capacity_after_shock, is_synthetic, late_sudden_phase

    Rules:
      - retired_max_cap: for decreasing technologies in misaligned_high_carbon that retire
        (identified by any row with late_sudden_phase == "retirement"). Value = max(capacity_after_shock)
        over the asset's horizon.
      - roll_over_cap: for decreasing tech assets (late_sudden_phase != "") that do NOT retire and have
        last known capacity_after_shock > 0. Value = last capacity_after_shock.
      - new_buildout_cap: for newly created synthetic assets in increasing technologies
        (is_synthetic == True). Value = max(capacity_after_shock).

    Output columns:
      - company_id, asset_id, capex_indicator, capex_capacity
    """
    need_cols = [
        "company_id",
        "asset_id",
        "year",
        "capacity_after_shock",
        "is_synthetic",
        "late_sudden_phase",
    ]
    missing = [c for c in need_cols if c not in assets_staggered_late_sudden.columns]
    if missing:
        raise ValueError(
            f"assets_staggered_late_sudden missing required columns for capex indicators: {missing}"
        )

    df = assets_staggered_late_sudden.copy()
    if df.empty:
        return pd.DataFrame(
            columns=["company_id", "asset_id", "capex_indicator", "capex_capacity"]
        )

    # normalize types
    df["company_id"] = df["company_id"].astype(str)
    df["asset_id"] = df["asset_id"].astype(str)
    df["year"] = _ensure_int_year(df["year"]).astype(int)
    df["capacity_after_shock"] = df["capacity_after_shock"].astype(float)
    df["is_synthetic"] = df["is_synthetic"].fillna(False).astype(bool)
    df["late_sudden_phase"] = df["late_sudden_phase"].fillna("").astype(str)

    out_rows: List[Dict[str, object]] = []

    # 1) Decreasing tech assets: identified by presence of any non-empty phase
    dec_real = df[(~df["is_synthetic"]) & (df["late_sudden_phase"] != "")]

    if not dec_real.empty:
        g = dec_real.groupby(["company_id", "asset_id"], sort=False)

        # retired_max_cap: any row marked as retirement
        retired_flag = (
            g["late_sudden_phase"]
            .apply(lambda s: (s == "retirement").any())
            .rename("is_retired")
        )
        max_cap = g["capacity_after_shock"].max().rename("max_cap")
        last_row = g.apply(lambda x: x.sort_values("year").iloc[-1])
        last_cap = last_row["capacity_after_shock"].rename("last_cap")

        retired_assets = retired_flag[retired_flag].index.tolist()
        for comp_id, asset_id in retired_assets:
            out_rows.append(
                {
                    "company_id": comp_id,
                    "asset_id": asset_id,
                    "capex_indicator": "retired_max_cap",
                    "capex_capacity": float(max_cap.loc[(comp_id, asset_id)]),
                }
            )

        # roll_over_cap: dec, not retired, last cap > 0
        not_retired = retired_flag[~retired_flag].index.tolist()
        for comp_id, asset_id in not_retired:
            cap_last = float(last_cap.loc[(comp_id, asset_id)])
            if cap_last > 0.0:
                out_rows.append(
                    {
                        "company_id": comp_id,
                        "asset_id": asset_id,
                        "capex_indicator": "roll_over_cap",
                        "capex_capacity": cap_last,
                    }
                )

    # 2) Increasing tech synthetic assets (new builds)
    synth = df[df["is_synthetic"]]
    if not synth.empty:
        g_s = synth.groupby(["company_id", "asset_id"], sort=False)
        max_s = g_s["capacity_after_shock"].max()
        for (comp_id, asset_id), cap in max_s.items():
            out_rows.append(
                {
                    "company_id": comp_id,
                    "asset_id": asset_id,
                    "capex_indicator": "new_buildout_cap",
                    "capex_capacity": float(cap),
                }
            )

    if not out_rows:
        return pd.DataFrame(
            columns=["company_id", "asset_id", "capex_indicator", "capex_capacity"]
        )

    out_df = pd.DataFrame(
        out_rows,
        columns=[
            "company_id",
            "asset_id",
            "capex_indicator",
            "capex_capacity",
        ],
    )
    return out_df
