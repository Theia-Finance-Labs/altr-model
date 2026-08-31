"""Staggered shock allocation for decreasing (high-carbon) technologies.

Two modes: proportional scaling with shock-year shares, or age-staggered
allocation via g-weights with capped reductions. Both emit asset-level
capacities plus the company-level original/adjusted correction table.
"""
import logging
from typing import List, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm

from ._shared import _allocate_reduction_with_caps_array, _index_assets_by_group
from .baseline import _compute_g_weights_array, _index_company_by_year
from .retirement import _build_retirement_map

logger = logging.getLogger(__name__)


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
        # Same convention as _prop_scale_decreasing_fast: original series
        # pre-shock, capacity actually held by the assets from the shock year
        # on, so retirement losses show up at company level in both modes.
        adjusted_traj = C_base.copy()
        post_idx = np.where(years >= int(shock_year))[0]
        if post_idx.size > 0:
            t0_adj = int(post_idx[0])
            adjusted_traj[t0_adj:] = after_mat[t0_adj:, :].sum(axis=1)
        adj_df["company_trajectory"] = adjusted_traj
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
    Proportional-scaling for decreasing techs (fast), with retirement applied once:
      - Shares fixed at shock-year (w). AFTER[t] = w * C_adj[t] for t >= shock_year.
      - If an asset retires at year t (> alignment_year), it is zeroed from t onwards
        AFTER allocation; its capacity is lost, never redistributed. C_adj is not
        pre-reduced as well, which would charge the retired share twice.
      - Returns (asset_level_df, company_corrections_df) where the adjusted company
        trajectory is the post-retirement asset total per year.
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

        # Retirement is applied ONCE, by zeroing retired assets after allocation
        # (below). C_adj must stay at C_base here: pre-reducing it by the retiring
        # share as well would leave the survivors carrying (1 - r)^2 * C.

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
        # Adjusted company path: the original series pre-shock (so the
        # asset-vs-company residual diagnostic stays informative there),
        # spliced to the capacity actually held by the assets from the shock
        # year on, so capacity lost to retirement shows up at company level.
        adjusted_traj = C_base.copy()
        if t0 is not None:
            adjusted_traj[t0:] = after_mat[t0:, :].sum(axis=1)
        adj_df["company_trajectory"] = adjusted_traj
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
    apply_retirement_shock: bool,
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
            apply_retirement=bool(apply_retirement_shock),
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
        apply_retirement=apply_retirement_shock,
        g_k=float(g_k),
        n_quantiles=int(n_quantiles),
        logger=logger,
    )
    return assets_df, corrections_df
