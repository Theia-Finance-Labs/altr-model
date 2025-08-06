"""
This is a boilerplate pipeline 'distribute_impacts_to_asset_level'
generated using Kedro 0.19.12
"""

import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


def _compute_g_weights(
    ages: pd.Series,
    k: float,
    min_active_share: float = 1e-12,
    n_quantiles: int = 3,
) -> pd.Series:
    """
    Compute and normalize g-factor weights for a series of asset ages.

    g(a) = 1 - \sum_{j=1..n_quantiles} [1 / (1 + exp(-k*(age - age_quantile_j)))]
    Clip to min_active_share and normalize to sum to 1. Fallback to uniform if degenerate.
    """
    # 1. Compute intermediate quantiles
    qs = np.linspace(0, 1, n_quantiles + 1)[1:-1]
    age_q = np.quantile(ages, qs)

    # 2. Raw g computation
    def g_val(age: float) -> float:
        return 1.0 - sum(1.0 / (1.0 + np.exp(-k * (age - q))) for q in age_q)

    raw = ages.map(g_val)
    clipped = raw.clip(lower=min_active_share)
    total = clipped.sum()

    # 3. Normalize or fallback
    if total <= min_active_share:
        return pd.Series(1.0 / len(clipped), index=clipped.index)
    return clipped / total


def staggered_shock(
    late_sudden_trajectories: pd.DataFrame,
    companies_ownership_tree: pd.DataFrame,
    increasing_or_decreasing_techs: pd.DataFrame,
    assets_forecasts: pd.DataFrame,
    shock_year: int,
    g_k: float = 6.0,
    min_active_share: float = 1e-12,
    max_recursion_depth: int = 100,
    debug: bool = False,
) -> pd.DataFrame:
    """
    Distribute company-tech level late-sudden shocks down to individual assets.

    Input DataFrames must have:
      - late_sudden_trajectories: ['company_id','technology','year','company_trajectory_latesudden']
      - companies_ownership_tree: ['asset_id','company_id','technology','ownership_level','ownership_percentage','year']
      - increasing_or_decreasing_techs: ['technology','increasing']
      - assets_forecasts: ['asset_id','technology','year','capacity','asset_age','company_id']

    The 'capacity' column in assets_forecasts serves both as the
    baseline activity (or capacity) series and as the ceiling for increases.

    Returns:
      - asset-level DataFrame with columns:
         ['asset_id','company_id','technology','year',
          'capacity','asset_age','capacity_after_shock']
      - if debug=True, also returns a diagnostics DataFrame
    """
    # --- 1) Validation ---
    req_lt = {"company_id", "technology", "year", "company_trajectory_latesudden"}
    req_ow = {
        "asset_id",
        "company_id",
        "technology",
        "ownership_level",
        "ownership_percentage",
        "year",
    }
    req_inc = {"technology", "increasing"}
    req_af = {"asset_id", "technology", "year", "capacity", "asset_age", "company_id"}

    if not req_lt.issubset(late_sudden_trajectories.columns):
        raise KeyError(
            f"late_sudden_trajectories missing {req_lt - set(late_sudden_trajectories.columns)}"
        )
    if not req_ow.issubset(companies_ownership_tree.columns):
        raise KeyError(
            f"companies_ownership_tree missing {req_ow - set(companies_ownership_tree.columns)}"
        )
    if not req_inc.issubset(increasing_or_decreasing_techs.columns):
        raise KeyError(
            f"increasing_or_decreasing_techs missing {req_inc - set(increasing_or_decreasing_techs.columns)}"
        )
    if not req_af.issubset(assets_forecasts.columns):
        raise KeyError(
            f"assets_forecasts missing {req_af - set(assets_forecasts.columns)}"
        )

    # Copy data
    lt = late_sudden_trajectories.copy()
    ow = companies_ownership_tree.copy()
    inc = increasing_or_decreasing_techs.copy()
    full_af = assets_forecasts.copy()

    # Step 2: identify assets missing shock_year-1 or shock_year
    min_years = [shock_year - 1, shock_year]
    key_cols = ["asset_id", "technology"]

    # Find last known record ≤ shock_year - 1
    last_known = (
        full_af[full_af["year"] <= shock_year - 1]
        .sort_values("year")
        .drop_duplicates(subset=key_cols, keep="last")
    )

    # Expand into missing years
    filler = []
    for y in min_years:
        extended = last_known.copy()
        extended["year"] = y
        filler.append(extended)

    # Combine filler rows with full data
    af = pd.concat([full_af, *filler], ignore_index=True)

    # Deduplicate by keeping latest real value or fallback
    af = af.sort_values("year").drop_duplicates(subset=key_cols + ["year"], keep="last")

    # Harmonize tech in ownership tree
    ow = ow.rename(columns={"technology": "technology"})

    # --- 2) Build ownership mapping at shock_year ---
    ow_primary = (
        ow[ow["year"] <= shock_year]
        .sort_values("year")
        .drop_duplicates(["asset_id"], keep="last")
    )

    # --- 3) Compute company-tech shocks ---
    lt = lt.sort_values(["company_id", "technology", "year"]).copy()
    lt["prev_val"] = lt.groupby(["company_id", "technology"])[
        "company_trajectory_latesudden"
    ].shift(1)
    lt = lt[lt["year"] >= shock_year]
    lt["shock"] = lt["company_trajectory_latesudden"] - lt["prev_val"]
    lt = lt.merge(inc, on="technology", how="left").fillna({"increasing": True})

    # --- 4) Prepare asset data ---
    af = af[af["year"] >= shock_year - 1].copy()
    if af.empty:
        raise ValueError("No assets_forecasts entries for required years")

    # Link to companies via ownership
    af = af.merge(
        ow_primary[["asset_id", "company_id", "technology"]],
        on=["asset_id", "company_id", "technology"],
        how="inner",
    )

    # Map ages once
    age_map = af.drop_duplicates("asset_id").set_index("asset_id")["asset_age"]

    outputs = []
    diagnostics = []

    # Loop by company-tech-year
    for (cid, tech, year), sub in lt.groupby(["company_id", "technology", "year"]):
        shock_val = float(sub["shock"].iloc[0])
        is_inc = bool(sub["increasing"].iloc[0])

        # Extract previous and current asset states
        prev = af[
            (af["company_id"] == cid)
            & (af["technology"] == tech)
            & (af["year"] == year - 1)
        ].set_index("asset_id")
        curr = af[
            (af["company_id"] == cid)
            & (af["technology"] == tech)
            & (af["year"] == year)
        ].set_index("asset_id")

        # Handle no existing assets case
        if prev.empty:
            new_id = f"NEW_{cid}_{tech}_{year}"
            alloc = shock_val if shock_val > 0 else 0.0
            rec = {
                "asset_id": new_id,
                "company_id": cid,
                "technology": tech,
                "year": year,
                "capacity": alloc,
                "asset_age": 0.0,
                "capacity_after_shock": alloc,
            }
            outputs.append(pd.DataFrame([rec]))
            if debug:
                diagnostics.append(
                    {
                        "company": cid,
                        "technology": tech,
                        "year": year,
                        "residual": 0.0,
                        "depth": 0,
                    }
                )
            continue

        # Compute g-weights
        ages = age_map.reindex(prev.index)
        g_w = _compute_g_weights(ages, k=g_k, min_active_share=min_active_share)

        # Order assets by age
        order = ages.sort_values(ascending=(not is_inc)).index

        # Initialize allocation and loop
        alloc = pd.Series(0.0, index=order)
        remaining = shock_val
        depth = 0

        while (not np.isclose(remaining, 0.0)) and (depth < max_recursion_depth):
            depth += 1
            if shock_val < 0:
                active = alloc.index[(prev["capacity"] + alloc) > 0]
            else:
                headroom = curr["capacity"] - prev["capacity"]
                active = alloc.index[headroom.loc[alloc.index] > 0]
            if len(active) == 0:
                break

            gw = g_w.reindex(active)
            gw = gw / gw.sum()
            delta = gw * remaining

            for aid in active:
                base = prev.at[aid, "capacity"]
                if shock_val < 0:
                    lower = -base
                    alloc[aid] += max(delta[aid], lower - alloc[aid])
                else:
                    hr = curr.at[aid, "capacity"] - base
                    alloc[aid] += min(delta[aid], hr - alloc[aid])
            remaining = shock_val - alloc.sum()

        # Synthetic asset for leftover positive shock
        new_rows = []
        if (remaining > 0) and is_inc:
            new_id = f"NEW_{cid}_{tech}_{year}"
            new_rows.append(
                {
                    "asset_id": new_id,
                    "company_id": cid,
                    "technology": tech,
                    "year": year,
                    "capacity": remaining,
                    "asset_age": 0.0,
                    "capacity_after_shock": remaining,
                }
            )
            alloc[new_id] = remaining

        # Build output for existing
        out = prev.copy()
        out["company_id"] = cid
        out["technology"] = tech
        out["year"] = year
        out["asset_age"] = ages
        out["capacity_after_shock"] = prev["capacity"] + alloc.reindex(
            prev.index
        ).fillna(0.0)

        # Append synthetic if any
        if new_rows:
            out = pd.concat([out, pd.DataFrame(new_rows).set_index("asset_id")], axis=0)

        outputs.append(out.reset_index())
        if debug:
            diagnostics.append(
                {
                    "company": cid,
                    "technology": tech,
                    "year": year,
                    "residual": remaining,
                    "depth": depth,
                }
            )

    # Concatenate all
    asset_level = pd.concat(outputs, ignore_index=True)
    if debug:
        return asset_level, pd.DataFrame(diagnostics)
    return asset_level
