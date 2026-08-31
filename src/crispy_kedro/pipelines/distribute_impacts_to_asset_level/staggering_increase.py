"""Shock distribution for increasing (low-carbon) technologies.

Real assets pass through on their BAU path; a synthetic build-out asset per
company/technology tops the group up to the company late-and-sudden series
from the shock year onwards.
"""
# ruff: noqa: PLR0912, PLR0915 — long allocation routine, kept whole
import logging

import numpy as np
import pandas as pd
from tqdm import tqdm

from ._shared import _index_assets_by_group

logger = logging.getLogger(__name__)


def stagger_increasing_technologies(
    late_sudden_trajectories: pd.DataFrame,
    assets_with_baseline_trajectory: pd.DataFrame,
    shock_year: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
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

        asset_parts: list[pd.DataFrame] = []
        company_parts: list[pd.DataFrame] = []

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
