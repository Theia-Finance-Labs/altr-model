"""
This is a boilerplate pipeline 'create_late_sudden_trajectories'
generated using Kedro 0.19.12
"""

import pandas as pd
from typing import Tuple, Union
import numpy as np


def determine_companies_technologies_alignment(
    companies_trajectories: pd.DataFrame,
    scenarios_pathways: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Decide whether each company-technology pathway is aligned with the target
    scenario and split results into four buckets.
    """
    key_cols = ["company_id", "scenario_geography", "sector", "technology"]

    # 1) Compute which techs are “increasing” (low‑carbon) vs “decreasing”:
    target_only = scenarios_pathways.query("scenario_type == 'target'")
    sorted_by_year = target_only.sort_values("year")
    tech_first_last = sorted_by_year.groupby("technology")["scenario_pathway"].agg(
        first="first", last="last"
    )
    tech_first_last.loc[:, "increasing"] = (
        tech_first_last["last"] > tech_first_last["first"]
    )

    tech_trend = tech_first_last.loc[:, ["increasing"]].reset_index()

    # 2) Annotate the company trajectories with that flag:
    companies_with_trend = companies_trajectories.merge(
        tech_trend, on="technology", how="left"
    )

    # 3) Keep only rows where we actually have company_activity:
    with_activity = companies_with_trend.dropna(subset=["company_activity"])

    # 4) Aggregate per company×tech and grab sums + final‑year values:
    agg = (
        with_activity.sort_values("year")
        .groupby(key_cols + ["increasing"], as_index=False)
        .agg(
            sum_forecast=("company_activity", "sum"),
            sum_target=("company_trajectory_target", "sum"),
            end_forecast=("company_activity", lambda s: s.iloc[-1]),
            end_target=("company_trajectory_target", lambda s: s.iloc[-1]),
        )
    )

    # 5) Alignment test:
    def _is_aligned(row):
        if row["increasing"]:
            return (
                row["sum_forecast"] >= row["sum_target"]
                and row["end_forecast"] >= row["end_target"]
            )
        else:
            return (
                row["sum_forecast"] <= row["sum_target"]
                and row["end_forecast"] <= row["end_target"]
            )

    agg.loc[:, "aligned"] = agg.apply(_is_aligned, axis=1)

    # ------------------------------------------------------------------
    # 4.  split into the four requested buckets
    # ------------------------------------------------------------------
    misaligned_high_carbon = agg.loc[
        (~agg["aligned"]) & (~agg["increasing"])
    ].reset_index(drop=True)
    misaligned_low_carbon = agg.loc[(~agg["aligned"]) & agg["increasing"]].reset_index(
        drop=True
    )
    aligned_high_carbon = agg.loc[agg["aligned"] & (~agg["increasing"])].reset_index(
        drop=True
    )
    aligned_low_carbon = agg.loc[agg["aligned"] & agg["increasing"]].reset_index(
        drop=True
    )

    return (
        misaligned_high_carbon,
        misaligned_low_carbon,
        aligned_high_carbon,
        aligned_low_carbon,
    )


def late_sudden_misaligned_high_carbon_companies(
    companies_trajectories: pd.DataFrame,
    misaligned_high_carbon_companies: pd.DataFrame,
    shock_year: int,
    alignment_year: int,
) -> pd.DataFrame:
    """
    Build the Late & Sudden pathway for *misaligned high‑carbon* companies.

    Phases (per company_id × scenario_geography × sector × technology):
      1) Forecast: L&S = company_activity for years with available data (<= last GEM year)
         (If an activity value is missing inside that window, we fall back to baseline for that year.)
      2) BAU:      L&S = company_trajectory_baseline for (last_GEM_year, shock_year]
      3) Transition: linear interpolation from baseline(shock_year) to target(alignment_year)
                     for years y in [shock_year, alignment_year)
      4) Alignment + Compensation:
           Start with L&S(y) = target(y) for y >= alignment_year.
           Then compute a single constant compensation so that
           Σ_y (L&S(y) - target(y)) over the full horizon equals 0.
           Apply this constant (negative or zero) uniformly to y >= alignment_year.
           Clip to non‑negative.

    Parameters
    ----------
    companies_trajectories : DataFrame
        Must include:
          ['company_id','scenario_geography','sector','technology','year',
           'company_activity','company_trajectory_baseline','company_trajectory_target']
        Years should be annual and cover the full horizon.
    misaligned_high_carbon_companies : DataFrame
        Output from the alignment step, filtered to the case:
          columns minimally include ['company_id','technology'] (others OK).
    shock_year : int
        Year when the policy shock triggers the transition off BAU.
    alignment_year : int
        Year when the L&S path reaches the target level.

    Returns
    -------
    DataFrame
        Same rows as the relevant subset of `companies_trajectories`, with:
          - 'company_trajectory_latesudden'
          - 'late_sudden_phase' (optional QA aid)
          - 'compensation_volume' (group total, repeated per row)
          - 'compensation_per_year' (applied value, repeated per row, y >= alignment_year)
    """

    # ------------------------------------------------------------------
    # 0) Filter to misaligned high‑carbon company‑technology pairs
    # ------------------------------------------------------------------
    key_cols_for_filter = ["company_id", "technology"]
    pairs = misaligned_high_carbon_companies[key_cols_for_filter].drop_duplicates()

    companies_for_case = companies_trajectories.merge(
        pairs, on=key_cols_for_filter, how="inner"
    ).copy()

    if companies_for_case.empty:
        # Nothing to do; return empty with expected columns.
        out = companies_trajectories.head(0).copy()
        out["company_trajectory_latesudden"] = out.get(
            "company_trajectory_latesudden", pd.Series(dtype=float)
        )
        out["late_sudden_phase"] = out.get("late_sudden_phase", pd.Series(dtype=object))
        out["compensation_volume"] = out.get(
            "compensation_volume", pd.Series(dtype=float)
        )
        out["compensation_per_year"] = out.get(
            "compensation_per_year", pd.Series(dtype=float)
        )
        return out

    # Working group keys
    group_cols = ["company_id", "scenario_geography", "sector", "technology"]

    # Ensure sorted by year inside each group
    companies_for_case = companies_for_case.sort_values(group_cols + ["year"])

    def _build_late_sudden_for_group(g: pd.DataFrame) -> pd.DataFrame:
        g = g.sort_values("year").copy()

        years = g["year"].to_numpy()
        baseline = g["company_trajectory_baseline"].to_numpy(dtype=float)
        target = g["company_trajectory_target"].to_numpy(dtype=float)
        activity = g["company_activity"].to_numpy(dtype=float)

        # Identify last GEM year (last non‑NA company_activity)
        valid_idx = np.where(~np.isnan(activity))[0]
        if valid_idx.size > 0:
            y_last_gem = int(years[valid_idx.max()])
        else:
            # No forecast info -> Phase 1 is empty
            y_last_gem = years.min() - 1

        ls = np.full_like(baseline, np.nan, dtype=float)
        phase = np.array([""] * len(years), dtype=object)

        # ---------------- Phase 1: Forecast (use activity where available) ----------------
        mask_p1 = years <= y_last_gem
        if mask_p1.any():
            # Use activity where present; if NA inside P1, fall back to baseline
            ls_p1 = np.where(
                ~np.isnan(activity[mask_p1]), activity[mask_p1], baseline[mask_p1]
            )
            ls[mask_p1] = ls_p1
            phase[mask_p1] = "forecast"

        # ---------------- Phase 2: BAU ----------------
        mask_p2 = (years > y_last_gem) & (years <= shock_year)
        if mask_p2.any():
            ls[mask_p2] = baseline[mask_p2]
            phase[mask_p2] = "bau"

        # ---------------- Phase 3: Transition (linear to target@alignment) ----------------
        if alignment_year > shock_year:
            mask_p3 = (years >= shock_year) & (years < alignment_year)
            if mask_p3.any():
                # Values at boundaries
                try:
                    v_start = float(baseline[years == shock_year][0])
                except IndexError:
                    raise ValueError(
                        f"Baseline value for shock_year={shock_year} not found in group "
                        f"{tuple(g[name].iloc[0] for name in group_cols)}."
                    )
                try:
                    v_end = float(target[years == alignment_year][0])
                except IndexError:
                    raise ValueError(
                        f"Target value for alignment_year={alignment_year} not found in group "
                        f"{tuple(g[name].iloc[0] for name in group_cols)}."
                    )

                # Linear interpolation excluding the endpoint (alignment_year)
                denom = alignment_year - shock_year
                frac = (years[mask_p3] - shock_year) / denom  # in [0, 1)
                ls[mask_p3] = v_start + frac * (v_end - v_start)
                phase[mask_p3] = "transition"

        # ---------------- Phase 4: Alignment (start at target), then Compensation ----------------
        mask_p4 = years >= alignment_year
        if mask_p4.any():
            # Start aligned to target
            ls[mask_p4] = target[mask_p4]
            phase[mask_p4] = "aligned"

        # ---- Compensation (constant adjustment after alignment) ----
        # Compute total overshoot up to alignment_year (inclusive).
        # Post‑alignment diff is currently zero (since ls == target there).
        pre_mask = years <= alignment_year
        pre_excess = np.nansum(ls[pre_mask] - target[pre_mask])
        post_gap = np.nansum(ls[mask_p4] - target[mask_p4])  # should be 0.0

        compensation_volume = pre_excess - post_gap  # generally >= 0 in this case
        comp_per_year = 0.0

        n_years_comp = int(mask_p4.sum())
        if n_years_comp > 0 and compensation_volume > 0:
            comp_per_year = -compensation_volume / n_years_comp
            ls[mask_p4] = ls[mask_p4] + comp_per_year
            # Non-negativity safeguard
            ls[mask_p4] = np.clip(ls[mask_p4], a_min=0.0, a_max=None)
            phase[mask_p4] = "aligned_compensation"

        # Attach outputs
        g["company_trajectory_latesudden"] = ls
        g["late_sudden_phase"] = phase
        g["compensation_volume"] = compensation_volume
        g["compensation_per_year"] = comp_per_year

        return g

    # Apply per company × geography × sector × technology
    result = (
        companies_for_case.groupby(group_cols, group_keys=False, sort=False)
        .apply(_build_late_sudden_for_group)
        .reset_index(drop=True)
    )

    return result


def late_sudden_misaligned_low_carbon_companies(
    companies_trajectories: pd.DataFrame,
    misaligned_low_carbon_companies: pd.DataFrame,
    shock_year: int,
    alignment_year: int,
) -> pd.DataFrame:
    """
    Build the Late & Sudden pathway for *misaligned low‑carbon* companies.

    Phases (per company_id × scenario_geography × sector × technology):
      1) Forecast:    L&S = company_activity for years with available data (<= last GEM year);
                      if a value is missing inside that window, we fall back to baseline.
      2) BAU:         L&S = company_trajectory_baseline for (last_GEM_year, shock_year]
      3) Transition:  Linear interpolation from baseline(shock_year) to target(alignment_year)
                      for years y in [shock_year, alignment_year)
      4) Alignment:   L&S = company_trajectory_target for y >= alignment_year

    Parameters
    ----------
    companies_trajectories : DataFrame
        Must include:
          ['company_id','scenario_geography','sector','technology','year',
           'company_activity','company_trajectory_baseline','company_trajectory_target']
    misaligned_low_carbon_companies : DataFrame
        Output from the alignment step, filtered to the case.
        Must include at least ['company_id','technology'].
    shock_year : int
        Year when the policy shock triggers the transition.
    alignment_year : int
        Year when the L&S path reaches the target level.

    Returns
    -------
    DataFrame
        Same rows (for the selected companies/techs) as `companies_trajectories`,
        with additional columns:
          - 'company_trajectory_latesudden'
          - 'late_sudden_phase'
    """

    # ------------------------------------------------------------------
    # 0) Filter to misaligned low‑carbon company‑technology pairs
    # ------------------------------------------------------------------
    key_cols_for_filter = ["company_id", "technology"]
    pairs = misaligned_low_carbon_companies[key_cols_for_filter].drop_duplicates()

    companies_for_case = companies_trajectories.merge(
        pairs, on=key_cols_for_filter, how="inner"
    ).copy()

    if companies_for_case.empty:
        # Nothing to compute; return empty with expected columns.
        out = companies_trajectories.head(0).copy()
        out["company_trajectory_latesudden"] = out.get(
            "company_trajectory_latesudden", pd.Series(dtype=float)
        )
        out["late_sudden_phase"] = out.get("late_sudden_phase", pd.Series(dtype=object))
        return out

    group_cols = ["company_id", "scenario_geography", "sector", "technology"]
    companies_for_case = companies_for_case.sort_values(group_cols + ["year"])

    def _build_late_sudden_for_group(g: pd.DataFrame) -> pd.DataFrame:
        g = g.sort_values("year").copy()

        years = g["year"].to_numpy()
        baseline = g["company_trajectory_baseline"].to_numpy(dtype=float)
        target = g["company_trajectory_target"].to_numpy(dtype=float)
        activity = g["company_activity"].to_numpy(dtype=float)

        # Identify last GEM year (last non‑NA company_activity)
        valid_idx = np.where(~np.isnan(activity))[0]
        if valid_idx.size > 0:
            y_last_gem = int(years[valid_idx.max()])
        else:
            # No forecast info -> Phase 1 is empty
            y_last_gem = int(years.min() - 1)

        ls = np.full_like(baseline, np.nan, dtype=float)
        phase = np.array([""] * len(years), dtype=object)

        # ---------------- Phase 1: Forecast ----------------
        mask_p1 = years <= y_last_gem
        if mask_p1.any():
            ls_p1 = np.where(
                ~np.isnan(activity[mask_p1]), activity[mask_p1], baseline[mask_p1]
            )
            ls[mask_p1] = ls_p1
            phase[mask_p1] = "forecast"

        # ---------------- Phase 2: BAU ----------------
        mask_p2 = (years > y_last_gem) & (years <= shock_year)
        if mask_p2.any():
            ls[mask_p2] = baseline[mask_p2]
            phase[mask_p2] = "bau"

        # ---------------- Phase 3: Transition ----------------
        if alignment_year > shock_year:
            mask_p3 = (years >= shock_year) & (years < alignment_year)
            if mask_p3.any():
                # Boundary values
                try:
                    v_start = float(baseline[years == shock_year][0])
                except IndexError:
                    raise ValueError(
                        f"Baseline value for shock_year={shock_year} not found in group "
                        f"{tuple(g[name].iloc[0] for name in group_cols)}."
                    )
                try:
                    v_end = float(target[years == alignment_year][0])
                except IndexError:
                    raise ValueError(
                        f"Target value for alignment_year={alignment_year} not found in group "
                        f"{tuple(g[name].iloc[0] for name in group_cols)}."
                    )

                denom = alignment_year - shock_year
                frac = (years[mask_p3] - shock_year) / denom  # in [0, 1)
                ls[mask_p3] = v_start + frac * (v_end - v_start)
                phase[mask_p3] = "transition"

        # ---------------- Phase 4: Alignment ----------------
        mask_p4 = years >= alignment_year
        if mask_p4.any():
            ls[mask_p4] = target[mask_p4]
            phase[mask_p4] = "aligned"

        # Non‑negativity safeguard
        ls = np.clip(ls, a_min=0.0, a_max=None)

        # Attach outputs
        g["company_trajectory_latesudden"] = ls
        g["late_sudden_phase"] = phase

        return g

    result = (
        companies_for_case.groupby(group_cols, group_keys=False, sort=False)
        .apply(_build_late_sudden_for_group)
        .reset_index(drop=True)
    )

    return result


def late_sudden_aligned_high_carbon_companies(
    companies_trajectories: pd.DataFrame,
    aligned_high_carbon_companies: pd.DataFrame,
    shock_year: int,
    alignment_year: int,
) -> pd.DataFrame:
    """
    Build the Late & Sudden pathway for *aligned high‑carbon* (decreasing) companies.

    Phases (per company_id × scenario_geography × sector × technology):
      1) Forecast:    L&S = company_activity for years with available data (<= last GEM year);
                      if a value is missing inside that window, fall back to baseline.
      2) BAU:         L&S = company_trajectory_baseline for (last_GEM_year, shock_year]
      3) Transition:  Linear interpolation from baseline(shock_year) to target(alignment_year)
                      for years y in [shock_year, alignment_year)
      4) Alignment:   L&S = company_trajectory_target for y >= alignment_year

    Parameters
    ----------
    companies_trajectories : DataFrame
        Must include:
          ['company_id','scenario_geography','sector','technology','year',
           'company_activity','company_trajectory_baseline','company_trajectory_target']
    aligned_high_carbon_companies : DataFrame
        Output from the alignment step, filtered to this case.
        Must include at least ['company_id','technology'].
    shock_year : int
        Year when the policy shock triggers the transition.
    alignment_year : int
        Year when the L&S path reaches the target level.

    Returns
    -------
    DataFrame
        Same rows (for the selected companies/techs) as `companies_trajectories`,
        with added columns:
          - 'company_trajectory_latesudden'
          - 'late_sudden_phase'
    """

    # 0) Filter to aligned high‑carbon company‑technology pairs
    key_cols_for_filter = ["company_id", "technology"]
    pairs = aligned_high_carbon_companies[key_cols_for_filter].drop_duplicates()

    companies_for_case = companies_trajectories.merge(
        pairs, on=key_cols_for_filter, how="inner"
    ).copy()

    if companies_for_case.empty:
        out = companies_trajectories.head(0).copy()
        out["company_trajectory_latesudden"] = out.get(
            "company_trajectory_latesudden", pd.Series(dtype=float)
        )
        out["late_sudden_phase"] = out.get("late_sudden_phase", pd.Series(dtype=object))
        return out

    group_cols = ["company_id", "scenario_geography", "sector", "technology"]
    companies_for_case = companies_for_case.sort_values(group_cols + ["year"])

    def _build_late_sudden_for_group(g: pd.DataFrame) -> pd.DataFrame:
        g = g.sort_values("year").copy()

        years = g["year"].to_numpy()
        baseline = g["company_trajectory_baseline"].to_numpy(dtype=float)
        target = g["company_trajectory_target"].to_numpy(dtype=float)
        activity = g["company_activity"].to_numpy(dtype=float)

        # Last GEM year = last non‑NA company_activity
        valid_idx = np.where(~np.isnan(activity))[0]
        if valid_idx.size > 0:
            y_last_gem = int(years[valid_idx.max()])
        else:
            y_last_gem = int(years.min() - 1)  # no Phase 1

        ls = np.full_like(baseline, np.nan, dtype=float)
        phase = np.array([""] * len(years), dtype=object)

        # Phase 1: Forecast
        mask_p1 = years <= y_last_gem
        if mask_p1.any():
            ls_p1 = np.where(
                ~np.isnan(activity[mask_p1]), activity[mask_p1], baseline[mask_p1]
            )
            ls[mask_p1] = ls_p1
            phase[mask_p1] = "forecast"

        # Phase 2: BAU
        mask_p2 = (years > y_last_gem) & (years <= shock_year)
        if mask_p2.any():
            ls[mask_p2] = baseline[mask_p2]
            phase[mask_p2] = "bau"

        # Phase 3: Transition (downward for high‑carbon if baseline(shock) > target(align))
        if alignment_year > shock_year:
            mask_p3 = (years >= shock_year) & (years < alignment_year)
            if mask_p3.any():
                try:
                    v_start = float(baseline[years == shock_year][0])
                except IndexError:
                    raise ValueError(
                        f"Baseline value for shock_year={shock_year} not found in group "
                        f"{tuple(g[name].iloc[0] for name in group_cols)}."
                    )
                try:
                    v_end = float(target[years == alignment_year][0])
                except IndexError:
                    raise ValueError(
                        f"Target value for alignment_year={alignment_year} not found in group "
                        f"{tuple(g[name].iloc[0] for name in group_cols)}."
                    )

                denom = alignment_year - shock_year
                frac = (years[mask_p3] - shock_year) / denom  # in [0,1)
                ls[mask_p3] = v_start + frac * (v_end - v_start)
                phase[mask_p3] = "transition"

        # Phase 4: Alignment
        mask_p4 = years >= alignment_year
        if mask_p4.any():
            ls[mask_p4] = target[mask_p4]
            phase[mask_p4] = "aligned"

        # Non‑negativity safeguard
        ls = np.clip(ls, a_min=0.0, a_max=None)

        g["company_trajectory_latesudden"] = ls
        g["late_sudden_phase"] = phase
        return g

    result = (
        companies_for_case.groupby(group_cols, group_keys=False, sort=False)
        .apply(_build_late_sudden_for_group)
        .reset_index(drop=True)
    )

    return result


def late_sudden_aligned_low_carbon_companies(
    companies_trajectories: pd.DataFrame,
    aligned_low_carbon_companies: pd.DataFrame,
    shock_year: int,
    alignment_year: Union[int, None] = None,  # kept only for a uniform signature
) -> pd.DataFrame:
    """
    Late-and-sudden pathway for *aligned low-carbon* company-technologies.

    Phase logic (per company_id × geography × sector × technology)
    --------------------------------------------------------------
    1) **Forecast**   – years ≤ last GEM year
         L&S = company_activity where available, else fallback to baseline.
    2) **BAU**        – (last GEM, shock_year]
         L&S = company_trajectory_baseline.
    3) **Aligned**    – years  > shock_year
         Let v0 = L&S(shock_year).
         For every subsequent year y :
             L&S(y) = L&S(y-1) · target(y) / target(y-1)            (same growth rate as target)

    Parameters
    ----------
    companies_trajectories : DataFrame
        Required cols:
            company_id, scenario_geography, sector, technology, year,
            company_activity, company_trajectory_baseline, company_trajectory_target
    aligned_low_carbon_companies : DataFrame
        At least ['company_id','technology'] for the pairs that belong to this case.
    shock_year : int
        Year the policy shock begins.  Must exist in the horizon.
    alignment_year : int | None
        Unused for this case; kept to match the other function signatures.

    Returns
    -------
    DataFrame  – same rows (for the selected pairs) as `companies_trajectories`,
                 with extra columns described above.
    """

    # ---------------------------------------------------------------
    # 0) isolate the company-technology pairs for this case
    # ---------------------------------------------------------------
    filter_keys = ["company_id", "technology"]
    pairs = aligned_low_carbon_companies[filter_keys].drop_duplicates()

    subset = companies_trajectories.merge(pairs, on=filter_keys, how="inner").copy()

    if subset.empty:
        # Return an empty frame with the expected columns
        out = companies_trajectories.head(0).copy()
        out["company_trajectory_latesudden"] = pd.Series(dtype=float)
        out["late_sudden_phase"] = pd.Series(dtype=object)
        return out

    group_cols = ["company_id", "scenario_geography", "sector", "technology"]
    subset = subset.sort_values(group_cols + ["year"])

    # ---------------------------------------------------------------
    # helper that builds L&S for *one* company × tech × geo × sector
    # ---------------------------------------------------------------
    def _build_late_sudden(g: pd.DataFrame) -> pd.DataFrame:
        g = g.sort_values("year").copy()

        years = g["year"].to_numpy()
        baseline = g["company_trajectory_baseline"].to_numpy(dtype=float)
        target = g["company_trajectory_target"].to_numpy(dtype=float)
        activity = g["company_activity"].to_numpy(dtype=float)

        # last GEM year (last non-NA activity)
        valid_idx = np.where(~np.isnan(activity))[0]
        y_last_gem = (
            int(years[valid_idx.max()]) if valid_idx.size else int(years.min() - 1)
        )

        ls = np.full_like(baseline, np.nan, dtype=float)
        phase = np.array([""] * len(years), dtype=object)

        # -------- Phase 1: Forecast --------------------------------
        mask_p1 = years <= y_last_gem
        if mask_p1.any():
            ls[mask_p1] = np.where(
                ~np.isnan(activity[mask_p1]), activity[mask_p1], baseline[mask_p1]
            )
            phase[mask_p1] = "forecast"

        # -------- Phase 2: BAU -------------------------------------
        mask_p2 = (years > y_last_gem) & (years <= shock_year)
        if mask_p2.any():
            ls[mask_p2] = baseline[mask_p2]
            phase[mask_p2] = "bau"

        # ensure we have an anchor value at shock_year
        try:
            anchor_val = float(ls[years == shock_year][0])
        except IndexError:
            raise ValueError(
                f"shock_year={shock_year} not found in data for "
                f"{tuple(g[c].iloc[0] for c in group_cols)}"
            )

        # -------- Phase 3: Aligned (target growth rate) ------------
        mask_p3 = years > shock_year
        if mask_p3.any():
            # initialise previous year value
            prev_ls = anchor_val
            prev_target = float(target[years == shock_year][0])

            for idx in np.where(mask_p3)[0]:
                curr_target = target[idx]
                growth = 0.0
                if prev_target > 0:
                    growth = curr_target / prev_target
                # if prev_target == 0, fall back to target value directly
                prev_ls = prev_ls * growth if prev_target > 0 else curr_target
                ls[idx] = prev_ls
                phase[idx] = "aligned"
                prev_target = curr_target

        # clip negatives (shouldn’t happen, but safe-guard)
        ls = np.clip(ls, a_min=0.0, a_max=None)

        g["company_trajectory_latesudden"] = ls
        g["late_sudden_phase"] = phase
        return g

    result = (
        subset.groupby(group_cols, group_keys=False, sort=False)
        .apply(_build_late_sudden)
        .reset_index(drop=True)
    )

    return result


def concatenate_late_sudden_results(
    late_sudden_misaligned_high_carbon: pd.DataFrame,
    late_sudden_misaligned_low_carbon: pd.DataFrame,
    late_sudden_aligned_high_carbon: pd.DataFrame,
    late_sudden_aligned_low_carbon: pd.DataFrame,
    misaligned_high_carbon_companies: pd.DataFrame,
    misaligned_low_carbon_companies: pd.DataFrame,
    aligned_high_carbon_companies: pd.DataFrame,
    aligned_low_carbon_companies: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Concatenate all late sudden trajectory results and all alignment classification results.

    Parameters
    ----------
    late_sudden_misaligned_high_carbon : pd.DataFrame
        Late sudden trajectories for misaligned high carbon companies
    late_sudden_misaligned_low_carbon : pd.DataFrame
        Late sudden trajectories for misaligned low carbon companies
    late_sudden_aligned_high_carbon : pd.DataFrame
        Late sudden trajectories for aligned high carbon companies
    late_sudden_aligned_low_carbon : pd.DataFrame
        Late sudden trajectories for aligned low carbon companies
    misaligned_high_carbon_companies : pd.DataFrame
        Classification results for misaligned high carbon companies
    misaligned_low_carbon_companies : pd.DataFrame
        Classification results for misaligned low carbon companies
    aligned_high_carbon_companies : pd.DataFrame
        Classification results for aligned high carbon companies
    aligned_low_carbon_companies : pd.DataFrame
        Classification results for aligned low carbon companies

    Returns
    -------
    Tuple[pd.DataFrame, pd.DataFrame]
        First dataframe: All late sudden trajectories concatenated with alignment_type column
        Second dataframe: All alignment classifications concatenated with alignment_type column
    """

    # Concatenate late sudden trajectories with alignment type labels
    late_sudden_dfs = []

    if not late_sudden_misaligned_high_carbon.empty:
        df = late_sudden_misaligned_high_carbon.copy()
        df["alignment_type"] = "misaligned_high_carbon"
        late_sudden_dfs.append(df)

    if not late_sudden_misaligned_low_carbon.empty:
        df = late_sudden_misaligned_low_carbon.copy()
        df["alignment_type"] = "misaligned_low_carbon"
        late_sudden_dfs.append(df)

    if not late_sudden_aligned_high_carbon.empty:
        df = late_sudden_aligned_high_carbon.copy()
        df["alignment_type"] = "aligned_high_carbon"
        late_sudden_dfs.append(df)

    if not late_sudden_aligned_low_carbon.empty:
        df = late_sudden_aligned_low_carbon.copy()
        df["alignment_type"] = "aligned_low_carbon"
        late_sudden_dfs.append(df)

    # Concatenate all late sudden results
    if late_sudden_dfs:
        all_late_sudden = pd.concat(late_sudden_dfs, ignore_index=True)
    else:
        # Create empty dataframe with expected columns if no data
        all_late_sudden = pd.DataFrame(
            columns=[
                "company_id",
                "scenario_geography",
                "sector",
                "technology",
                "year",
                "company_activity",
                "company_trajectory_baseline",
                "company_trajectory_target",
                "company_trajectory_latesudden",
                "late_sudden_phase",
                "alignment_type",
            ]
        )

    # Concatenate alignment classifications with alignment type labels
    alignment_dfs = []

    if not misaligned_high_carbon_companies.empty:
        df = misaligned_high_carbon_companies.copy()
        df["alignment_type"] = "misaligned_high_carbon"
        alignment_dfs.append(df)

    if not misaligned_low_carbon_companies.empty:
        df = misaligned_low_carbon_companies.copy()
        df["alignment_type"] = "misaligned_low_carbon"
        alignment_dfs.append(df)

    if not aligned_high_carbon_companies.empty:
        df = aligned_high_carbon_companies.copy()
        df["alignment_type"] = "aligned_high_carbon"
        alignment_dfs.append(df)

    if not aligned_low_carbon_companies.empty:
        df = aligned_low_carbon_companies.copy()
        df["alignment_type"] = "aligned_low_carbon"
        alignment_dfs.append(df)

    # Concatenate all alignment results
    if alignment_dfs:
        all_alignments = pd.concat(alignment_dfs, ignore_index=True)
    else:
        # Create empty dataframe with expected columns if no data
        all_alignments = pd.DataFrame(
            columns=[
                "company_id",
                "scenario_geography",
                "sector",
                "technology",
                "increasing",
                "sum_forecast",
                "sum_target",
                "end_forecast",
                "end_target",
                "aligned",
                "alignment_type",
            ]
        )

    return all_late_sudden, all_alignments
