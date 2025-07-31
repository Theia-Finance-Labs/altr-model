"""
This is a boilerplate pipeline 'distribute_impacts_to_asset_level'
generated using Kedro 0.19.12
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional
import matplotlib.pyplot as plt
import os


def staggered_shock(
    late_sudden_trajectories: pd.DataFrame,
    companies_ownership_tree: pd.DataFrame,
    increasing_or_decreasing_techs: pd.DataFrame,
    assets_forecasts: pd.DataFrame,
    shock_year: int,
    g_k: float = 6.0,
    min_active_share: float = 1e-12,
) -> pd.DataFrame:
    """
    Distribute company/technology-level Late&SUDDEN trajectories to assets using
    a staggered-shock method with asset-level capacity ceilings.

    Steps implemented
    -----------------
    1) Seed asset P_{y0,a} at y0 = shock_year-1 from GEM:
         - For each asset, take its last available GEM year y_gem_last and compute
           P_gem_last = capacity * capacity_factor at that year.
         - Extrapolate to y0 with BAU rate-of-change at (sector,technology) level:
              P_{y0,a} = P_gem_last * [ S_baseline(y0,t) / S_baseline(y_gem_last,t) ]
           where S_baseline is the sum of company_trajectory_baseline after dropping
           company granularity (grouped by scenario_geography, sector, technology, year).
         - If multiple assets exist for a (company,tech), rescale proportionally so that
           sum_a P_{y0,a} == company_trajectory_latesudden(y0) for that (company,tech).
           If all P_{y0,a} are 0, we fall back to equal split to hit the company total.
         - Enforce capacity ceilings at y0 (clip to capacity if exceeded).

    2) For each year y >= shock_year, compute company-level shock:
           Shock_y = Plate_y - Plate_{y-1}
       and distribute to assets with min–max constraints:

       Negative shock (production reduction):
         - Allocation preference: older -> newer assets.
         - Never drop an asset below 0 in that year.

       Positive shock (production increase):
         - Allocation preference: newer -> older assets (then older -> newer if needed).
         - Never raise an asset above its capacity ceiling.
         - Any remainder after all assets hit capacity is recorded as `new_asset_production`.

    Parameters
    ----------
    late_sudden_trajectories : DataFrame
        Required columns:
          ['company_id','scenario_geography','sector','technology','year',
           'company_trajectory_latesudden','company_trajectory_baseline']
    companies_ownership_tree : DataFrame
        Required columns:
          ['asset_id','company_id','sector','technology_category','year','ownership_percentage']
        Note: 'year' is taken as commissioning year (integer).
    increasing_or_decreasing_techs : DataFrame
        ['technology','increasing'] (not strictly required in this sign-driven allocation).
    assets_forecasts : DataFrame
        Required columns:
          ['asset_id','sector','technology','year','capacity','capacity_factor',
           'company_id','ownership_percentage']
        Can contain multiple years per asset; the **max** capacity observed per asset is used
        as the capacity ceiling for all post-shock years.
        The **last** year per asset is used to seed P_{y0,a}.
    shock_year : int
        First year where the company-level delta is allocated to assets.
    g_k : float
        Steepness parameter for priority weights (larger → stronger priority).
    min_active_share : float
        Numerical floor to avoid zero weights.

    Returns
    -------
    DataFrame with columns:
      ['company_id','sector','technology','asset_id','year',
       'asset_plate_latesudden','allocated_shock','unallocated_remainder','new_asset_production']
    """

    # --------- small helpers -------------------------------------------------

    def compute_g_weights(ages: np.ndarray, preference: str, k: float) -> np.ndarray:
        """
        Smooth weights that sum to 1. preference in {'older','newer'}.
        Older: higher weight to larger ages; Newer: higher to smaller ages.
        """
        if ages.size == 0:
            return np.array([])
        order = np.argsort(ages)  # ascending age
        ranks = np.empty_like(order, dtype=float)
        ranks[order] = np.linspace(0.0, 1.0, len(ages), endpoint=True)
        if preference == "older":
            score = np.exp(k * ranks)
        else:
            score = np.exp(k * (1.0 - ranks))
        score = np.clip(score, min_active_share, None)
        return score / score.sum()

    # capacities from assets_forecasts: max capacity observed per asset
    af = assets_forecasts.copy()
    af = af[af["ownership_percentage"] > 0].copy()
    af["year"] = af["year"].astype(float)
    cap_max = af.groupby("asset_id", as_index=True)["capacity"].max().to_dict()

    # last GEM production per asset (capacity * CF at the last year we have)
    # if CF is missing, assume 1.0 (as in the example)
    af.loc[:, "capacity_factor"] = af.loc[:, "capacity_factor"].fillna(1.0)
    last_idx = (
        af.sort_values(["asset_id", "year"])
        .groupby("asset_id", as_index=False)
        .tail(1)[["asset_id", "year", "capacity", "capacity_factor"]]
    )
    last_idx["P_gem_last"] = last_idx["capacity"] * last_idx["capacity_factor"]
    last_dict_year = dict(zip(last_idx["asset_id"], last_idx["year"]))
    last_dict_prod = dict(zip(last_idx["asset_id"], last_idx["P_gem_last"]))

    # commissioning year from ownership_tree (preferred)
    ot = companies_ownership_tree.copy()
    ot = ot[ot["ownership_percentage"] > 0].copy()
    ot = ot.rename({"technology_category": "technology"}, axis=1)
    ot["commissioning_year"] = ot["year"].astype(int)

    # build (asset -> commissioning_year); if duplicates, take min year
    com_year = (
        ot.groupby("asset_id", as_index=False)["commissioning_year"]
        .min()
        .set_index("asset_id")["commissioning_year"]
        .to_dict()
    )

    # ----- technology-level baseline S(y,t) after dropping company dimension ---
    lts = late_sudden_trajectories.copy()
    lts = lts.rename(columns={"technology_category": "technology"})
    s_base = lts.groupby(["sector", "technology", "year"], as_index=False).agg(
        S_baseline=("company_trajectory_baseline", "sum")
    )
    s_base = s_base.sort_values(["sector", "technology", "year"])

    # ratio to y0 per (sector,technology)
    def add_ratio(g):
        y0 = shock_year - 1
        if (g["year"] == y0).any():
            base = g.loc[g["year"] == y0, "S_baseline"].iloc[0]
            g["S_ratio_to_y0"] = g["S_baseline"] / (base if base != 0 else 1.0)
        else:
            g["S_ratio_to_y0"] = 1.0
        return g

    s_base = s_base.groupby(["sector", "technology"], group_keys=False).apply(add_ratio)
    s_ratio = s_base.set_index(["sector", "technology", "year"])[
        "S_ratio_to_y0"
    ].to_dict()

    # fast lookup for company series
    key_cols = ["company_id", "scenario_geography", "sector", "technology", "year"]
    lts_key = lts.set_index(key_cols)

    # ------------ main allocation --------------------------------------------
    out = []
    group_cols = ["company_id", "scenario_geography", "sector", "technology"]

    for (cid, geo, sec, tech), df_ct in lts.groupby(group_cols, sort=False):
        df_ct = df_ct.sort_values("year")
        years = df_ct["year"].unique().tolist()
        if min(years) > shock_year - 1:
            # need y0 present
            continue

        # assets belonging to this company-tech (direct ownership only)
        # join via ownership tree, then intersect with assets_forecasts set
        assets_ct = ot[(ot["company_id"] == cid) & (ot["technology"] == tech)][
            ["asset_id", "commissioning_year"]
        ].drop_duplicates()
        if assets_ct.empty:
            # still record company-level remainder if desired; skip asset allocation
            continue

        # seed P_{y0,a} from GEM last-year + BAU extrapolation to y0
        y0 = shock_year - 1
        plate_y0 = float(
            lts_key.loc[(cid, geo, sec, tech, y0), "company_trajectory_latesudden"]
        )
        p0_raw = []
        a_list = []
        for a, cy in assets_ct.itertuples(index=False):
            # if no GEM record for this asset, P_gem_last defaults to 0
            P_last = float(last_dict_prod.get(a, 0.0))
            y_last = last_dict_year.get(a, y0)  # if not present, treat as already at y0
            ratio_y0 = s_ratio.get((sec, tech, y0), 1.0)
            ratio_yl = s_ratio.get((sec, tech, int(y_last)), 1.0)
            scale = ratio_y0 / (ratio_yl if ratio_yl != 0 else 1.0)
            p0 = P_last * scale
            # if asset is not yet commissioned by y0, it should not have production
            if cy > y0:
                p0 = 0.0
            p0_raw.append(p0)
            a_list.append(a)

        p0_raw = np.array(p0_raw, dtype=float)
        sum_raw = p0_raw.sum()

        if sum_raw <= 1e-12:
            # fallback: equal split across active assets (commissioned <= y0)
            active_mask = np.array(
                [com_year.get(a, y0) <= y0 for a in a_list], dtype=bool
            )
            n_active = int(active_mask.sum())
            p0 = np.zeros_like(p0_raw)
            if n_active > 0:
                p0[active_mask] = plate_y0 / n_active
            else:
                # no active assets yet; nothing to allocate at y0
                p0[:] = 0.0
        else:
            # proportional rescale to match company total at y0
            p0 = p0_raw * (plate_y0 / sum_raw)

        # enforce capacity ceilings at y0
        caps = np.array([cap_max.get(a, float("inf")) for a in a_list], dtype=float)
        p0 = np.minimum(p0, caps)

        # store previous-year vector
        prod_prev = dict(zip(a_list, p0))

        # write y0 rows
        for a in a_list:
            out.append(
                {
                    "company_id": cid,
                    "sector": sec,
                    "technology": tech,
                    "asset_id": a,
                    "year": int(y0),
                    "asset_plate_latesudden": float(prod_prev[a]),
                    "allocated_shock": 0.0,
                    "unallocated_remainder": 0.0,
                    "new_asset_production": 0.0,
                }
            )

        # iterate shock years
        for y in [yy for yy in years if yy >= shock_year]:
            plate_y = float(
                lts_key.loc[(cid, geo, sec, tech, y), "company_trajectory_latesudden"]
            )
            plate_ym1 = float(
                lts_key.loc[
                    (cid, geo, sec, tech, y - 1), "company_trajectory_latesudden"
                ]
            )
            shock = plate_y - plate_ym1

            # active assets are those commissioned <= y-1
            active_assets = [a for a in a_list if com_year.get(a, y) <= (y - 1)]
            if len(active_assets) == 0:
                # if positive shock with no active assets, treat as new builds
                if shock > 0:
                    out.append(
                        {
                            "company_id": cid,
                            "sector": sec,
                            "technology": tech,
                            "asset_id": f"NEW_{cid}_{tech}_{y}",
                            "year": int(y),
                            "asset_plate_latesudden": float(shock),
                            "allocated_shock": float(shock),
                            "unallocated_remainder": 0.0,
                            "new_asset_production": float(shock),
                        }
                    )
                continue

            ages = np.array(
                [(y - 1) - com_year.get(a, (y - 1)) for a in active_assets], dtype=float
            )
            prev_vec = np.array([prod_prev[a] for a in active_assets], dtype=float)
            caps_vec = np.array(
                [cap_max.get(a, float("inf")) for a in active_assets], dtype=float
            )

            # allocator routines
            def allocate_negative(shock_value: float):
                remaining = shock_value  # negative
                alloc = np.zeros_like(prev_vec)
                active_mask = prev_vec > 0
                guard = 0
                while remaining < -1e-12 and active_mask.any():
                    w = compute_g_weights(ages[active_mask], "older", g_k)
                    prop = np.zeros_like(prev_vec)
                    prop[active_mask] = w * remaining  # negative
                    lower = -prev_vec
                    capped = np.maximum(prop, lower)
                    alloc += capped
                    remaining = shock_value - alloc.sum()
                    active_mask = (prev_vec + alloc) > 1e-12
                    guard += 1
                    if guard > 1000:
                        break
                return alloc, remaining

            def allocate_positive(shock_value: float):
                remaining = shock_value
                alloc = np.zeros_like(prev_vec)

                for pref in ["newer", "older"]:
                    if remaining <= 1e-12:
                        break
                    headroom = np.maximum(caps_vec - (prev_vec + alloc), 0.0)
                    active_mask = headroom > 1e-12
                    guard = 0
                    while remaining > 1e-12 and active_mask.any():
                        w = compute_g_weights(ages[active_mask], pref, g_k)
                        prop = np.zeros_like(prev_vec)
                        prop[active_mask] = w * remaining
                        capped = np.minimum(prop, headroom)
                        alloc += capped
                        remaining = shock_value - alloc.sum()
                        headroom = np.maximum(caps_vec - (prev_vec + alloc), 0.0)
                        active_mask = headroom > 1e-12
                        guard += 1
                        if guard > 1000:
                            break

                new_asset_vol = max(remaining, 0.0)
                return alloc, max(remaining, 0.0), new_asset_vol

            if abs(shock) <= 1e-12:
                alloc_vec = np.zeros_like(prev_vec)
                remainder = 0.0
                new_vol = 0.0
            elif shock < 0:
                alloc_vec, remainder = allocate_negative(shock)
                new_vol = 0.0
            else:
                alloc_vec, remainder, new_vol = allocate_positive(shock)

            next_vec = prev_vec + alloc_vec

            # write rows (store remainder/new_volume once)
            for i, a in enumerate(active_assets):
                out.append(
                    {
                        "company_id": cid,
                        "sector": sec,
                        "technology": tech,
                        "asset_id": a,
                        "year": int(y),
                        "asset_plate_latesudden": float(next_vec[i]),
                        "allocated_shock": float(alloc_vec[i]),
                        "unallocated_remainder": float(remainder) if i == 0 else 0.0,
                        "new_asset_production": float(new_vol) if i == 0 else 0.0,
                    }
                )

            if new_vol > 1e-12:
                out.append(
                    {
                        "company_id": cid,
                        "sector": sec,
                        "technology": tech,
                        "asset_id": f"NEW_{cid}_{tech}_{y}",
                        "year": int(y),
                        "asset_plate_latesudden": float(new_vol),
                        "allocated_shock": float(new_vol),
                        "unallocated_remainder": 0.0,
                        "new_asset_production": float(new_vol),
                    }
                )

            # carry forward
            for i, a in enumerate(active_assets):
                prod_prev[a] = float(next_vec[i])

    out_df = pd.DataFrame(out)
    if not out_df.empty:
        for c in [
            "asset_plate_latesudden",
            "allocated_shock",
            "unallocated_remainder",
            "new_asset_production",
        ]:
            out_df[c] = out_df[c].astype(float).round(12)
    return out_df


def plot_staggered_shock(
    late_sudden_trajectories: pd.DataFrame,
    asset_level_df: pd.DataFrame,
    output_dir: str = "data/08_reporting/companies_staggered_shock_plots",
):
    """
    For each unique (scenario_geography, company_id, technology) in the
    late_sudden_trajectories, generates and saves:
      1) A plot of the original company‐level Late&SUDDEN trajectory vs.
         each asset and their sum,
      2) A plot of the year‐by‐year difference (asset sum − company).

    Files are saved to `output_dir` with names:
      {technology}-{scenario_geography}-{company_id}.png
      {technology}-{scenario_geography}-{company_id}-diff.png

    Parameters
    ----------
    late_sudden_trajectories : pd.DataFrame
        Columns:
          ['scenario_geography','company_id','sector','technology',
           'year','company_trajectory_latesudden']
    asset_level_df : pd.DataFrame
        Columns:
          ['company_id','sector','technology','asset_id','year',
           'asset_plate_latesudden']
    output_dir : str
        Directory in which to save the plots. Will be created if it doesn't exist.
    """
    # ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # identify all combos
    combos = (
        late_sudden_trajectories[["scenario_geography", "company_id", "technology"]]
        .drop_duplicates()
        .sort_values(["scenario_geography", "company_id", "technology"])
    )

    for _, (geo, cid, tech) in combos.iterrows():
        # filter company series
        comp = late_sudden_trajectories[
            (late_sudden_trajectories["scenario_geography"] == geo)
            & (late_sudden_trajectories["company_id"] == cid)
            & (late_sudden_trajectories["technology"] == tech)
        ].sort_values("year")
        if comp.empty:
            continue

        years = comp["year"].values
        company_vals = comp["company_trajectory_latesudden"].values

        # filter asset-level series
        assets = asset_level_df[
            (asset_level_df["company_id"] == cid)
            & (asset_level_df["technology"] == tech)
        ]

        # --- Plot 1: company + assets + sum ---
        plt.figure(figsize=(10, 6))
        plt.plot(
            years, company_vals, lw=2.5, label="Company Late&SUDDEN", color="black"
        )

        for aid in assets["asset_id"].unique():
            df_a = assets[assets["asset_id"] == aid].sort_values("year")
            plt.plot(
                df_a["year"],
                df_a["asset_plate_latesudden"],
                lw=1.2,
                alpha=0.7,
                label=f"Asset {aid}",
            )

        agg = (
            assets.groupby("year", as_index=False)
            .agg(total_asset_plate=("asset_plate_latesudden", "sum"))
            .sort_values("year")
        )
        plt.plot(
            agg["year"],
            agg["total_asset_plate"],
            lw=2,
            linestyle="--",
            label="Sum of Assets",
        )

        plt.xlabel("Year")
        plt.ylabel("Production")
        plt.title(f"{tech} • {geo} • {cid}\nCompany vs. Asset trajectories")
        plt.legend(bbox_to_anchor=(1.05, 1), loc="upper left")
        plt.tight_layout()

        # save first figure
        fname = f"{tech}-{geo}-{cid}.png".replace(" ", "_")
        plt.savefig(os.path.join(output_dir, fname), dpi=300)
        plt.close()

        # --- Plot 2: difference over time ---
        diff = []
        for y, cval in zip(years, company_vals):
            aval = (
                float(agg.loc[agg["year"] == y, "total_asset_plate"].iloc[0])
                if (agg["year"] == y).any()
                else 0.0
            )
            diff.append(aval - cval)

        plt.figure(figsize=(8, 4))
        plt.plot(years, diff, marker="o")
        plt.axhline(0, linestyle="--", color="grey")
        plt.xlabel("Year")
        plt.ylabel("Asset Sum − Company")
        plt.title(f"{tech} • {geo} • {cid}\nDifference Over Time")
        plt.tight_layout()

        # save second figure
        fname_diff = f"{tech}-{geo}-{cid}-diff.png".replace(" ", "_")
        plt.savefig(os.path.join(output_dir, fname_diff), dpi=300)
        plt.close()
