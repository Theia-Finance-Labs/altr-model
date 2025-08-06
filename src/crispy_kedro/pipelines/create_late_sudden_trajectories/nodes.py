"""
This is a boilerplate pipeline 'create_late_sudden_trajectories'
generated using Kedro 0.19.12
"""

import pandas as pd
from typing import Tuple, Union
import numpy as np
import matplotlib.pyplot as plt
import os
from pathlib import Path
import re


def determine_companies_technologies_alignment(
    companies_trajectories: pd.DataFrame,
    increasing_or_decreasing_techs: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Decide whether each company-technology pathway is aligned with the target
    scenario and split results into four buckets.
    """

    # 2) Annotate the company trajectories with that flag:
    companies_with_trend = companies_trajectories.merge(
        increasing_or_decreasing_techs, on="technology", how="left"
    )

    # 3) Keep only rows where we actually have company_activity:
    with_activity = companies_with_trend.dropna(subset=["company_activity"])

    # 4) Aggregate per companyxtech and grab sums + final-year values:
    agg = (
        with_activity.sort_values("year")
        .groupby(
            ["company_id", "scenario_geography", "sector", "technology", "increasing"],
            as_index=False,
        )
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
    assets_retirement_dates: pd.DataFrame,
    shock_year: int,
    alignment_year: int,
) -> pd.DataFrame:
    """
    Late & Sudden pathway for *misaligned high-carbon* companies with *asset retirement*.

        Retirement rule (permanent capacity reduction):
      For each asset (company_id, sector, technology) that retires in year y_r with a given
      `capacity`, subtract that capacity from the L&S pathway for all years >= y_r (cumulative
      for multiple assets). Values are clipped to >= 0.

    Phase labeling:
      - Base phases: forecast / bau / transition / aligned / aligned_compensation
      - The specific year when a retirement event occurs gets the "retirement" phase.
      - Retirement phase remains "retirement" even when compensation is applied.

    Inputs
    ------
    companies_trajectories : DataFrame with columns
        ['company_id','scenario_geography','sector','technology','year',
         'company_activity','company_trajectory_baseline','company_trajectory_target']
    misaligned_high_carbon_companies : DataFrame with at least
        ['company_id','technology']
    assets_retirement_dates : DataFrame with columns
        ['company_id','scenario_geography','sector','technology','retirement_year','capacity']
        capacity treated as non-negative.
    shock_year, alignment_year : int

    Returns
    -------
    DataFrame with added columns:
      - company_trajectory_latesudden
      - late_sudden_phase
      - compensation_volume (>=0, group total)
      - compensation_per_year (<=0, applied for y >= alignment_year)
    """

    # -------------------- 0) Filter to misaligned high-carbon pairs --------------------
    key_cols_for_filter = ["company_id", "technology"]
    pairs = misaligned_high_carbon_companies[key_cols_for_filter].drop_duplicates()

    companies_for_case = companies_trajectories.merge(
        pairs, on=key_cols_for_filter, how="inner"
    ).copy()

    # Empty early-exit with expected columns
    if companies_for_case.empty:
        out = companies_trajectories.head(0).copy()
        for col, dtype in [
            ("company_trajectory_latesudden", float),
            ("late_sudden_phase", object),
            ("compensation_volume", float),
            ("compensation_per_year", float),
        ]:
            out[col] = out.get(col, pd.Series(dtype=dtype))
        return out

    # -------------------- Normalize retirement table --------------------
    retire_df = assets_retirement_dates.copy()

    # Index retirement events by (company_id, sector, technology)
    retire_key_cols = ["company_id", "scenario_geography", "sector", "technology"]
    events_by_key = {}
    if not retire_df.empty:
        # Sort for deterministic application
        retire_df = retire_df.sort_values(retire_key_cols + ["retirement_year"])
        for key, sub in retire_df.groupby(retire_key_cols, sort=False):
            # simple list of (year, capacity)
            events_by_key[key] = list(
                zip(
                    sub["retirement_year"].tolist(),
                    sub["capacity"].astype(float).tolist(),
                )
            )

    # -------------------- Work per company x geography x sector x technology --------------------
    group_cols = ["company_id", "scenario_geography", "sector", "technology"]
    companies_for_case = companies_for_case.sort_values(group_cols + ["year"]).copy()

    def _build_late_sudden_for_group(g: pd.DataFrame) -> pd.DataFrame:
        g = g.sort_values("year").copy()

        years = g["year"].to_numpy()
        baseline = g["company_trajectory_baseline"].to_numpy(dtype=float)
        target = g["company_trajectory_target"].to_numpy(dtype=float)
        activity = g["company_activity"].to_numpy(dtype=float)

        # -------- Phase 1: Forecast --------
        valid_idx = np.where(~np.isnan(activity))[0]
        y_last_gem = (
            int(years[valid_idx.max()]) if valid_idx.size > 0 else int(years.min() - 1)
        )

        ls = np.full_like(baseline, np.nan, dtype=float)
        phase = np.array([""] * len(years), dtype=object)

        mask_p1 = years <= y_last_gem
        if mask_p1.any():
            ls[mask_p1] = np.where(
                ~np.isnan(activity[mask_p1]), activity[mask_p1], baseline[mask_p1]
            )
            phase[mask_p1] = "forecast"

        # -------- Phase 2: BAU --------
        mask_p2 = (years > y_last_gem) & (years < shock_year)
        if mask_p2.any():
            ls[mask_p2] = baseline[mask_p2]
            phase[mask_p2] = "bau"

        # -------- Phase 3: Transition (linear from baseline@(shock-1) to target@alignment) --------

        mask_p3 = (years >= shock_year) & (years <= alignment_year)

        v_start = float(baseline[years == (shock_year - 1)][0])
        v_end = float(target[years == alignment_year][0])

        denom = alignment_year - shock_year
        frac = (years[mask_p3] - (shock_year - 1)) / (
            denom + 1
        )  # shock_year gets frac = 1/(denom+1)
        ls[mask_p3] = v_start + frac * (v_end - v_start)
        phase[mask_p3] = "transition"

        # -------- Phase 4: Align to target (pre-retirement, pre-compensation) --------
        mask_p4 = years > alignment_year
        if mask_p4.any():
            ls[mask_p4] = target[mask_p4]
            phase[mask_p4] = "aligned"

        # -------- Phase 4a: Apply ASSET RETIREMENT (permanent capacity reduction) --------
        # For each event at y_r with capacity C: ls[y >= y_r] -= C (cumulative), clip >= 0.
        # Only the retirement year gets "retirement" phase label.
        key_ret = (
            g["company_id"].iloc[0],
            g["scenario_geography"].iloc[0],
            g["sector"].iloc[0],
            g["technology"].iloc[0],
        )
        events = events_by_key.get(key_ret, [])

        if events:
            retirement_years = set()  # Track which years have retirement events

            # Sort events by year to apply them chronologically
            events_sorted = sorted(events, key=lambda x: x[0])

            for y_r, cap in events_sorted:
                # Find the index for the retirement year
                idx_retirement = np.where(years == y_r)[0]
                if idx_retirement.size == 0:
                    continue  # retirement year not in our data

                idx_retirement = idx_retirement[0]

                # Get the late sudden value at retirement year
                ls_at_retirement = ls[idx_retirement]

                if ls_at_retirement > 0:
                    # Calculate the percentage decrease
                    percentage_decrease = cap / ls_at_retirement
                    # Cap the percentage to avoid negative values
                    percentage_decrease = min(percentage_decrease, 1.0)

                    # Apply this percentage decrease to all years >= y_r
                    idx_after = np.where(years >= y_r)[0]
                    if idx_after.size > 0:
                        ls[idx_after] *= 1 - percentage_decrease

                # Mark the retirement year
                retirement_years.add(y_r)

            # Mark only the specific retirement years as "retirement" phase
            for y_r in retirement_years:
                idx_exact = np.where(years == y_r)[0]
                if idx_exact.size > 0:
                    phase[idx_exact[0]] = "retirement"

        # -------- Phase 4b: Compensation (uniform, non-positive; same logic, computed AFTER retirements) --------
        pre_mask = years <= alignment_year
        post_mask = years > alignment_year
        pre_excess = float(np.nansum(ls[pre_mask] - target[pre_mask]))
        post_gap = float(np.nansum(ls[post_mask] - target[post_mask]))
        compensation_volume = max(pre_excess - post_gap, 0.0)

        comp_per_year = 0.0
        n_years_comp = int(post_mask.sum())
        if n_years_comp > 0 and compensation_volume > 0:
            comp_per_year = -compensation_volume / n_years_comp  # <= 0
            ls[post_mask] = np.maximum(ls[post_mask] + comp_per_year, 0.0)
            # Upgrade alignment labels to reflect compensation
            # Keep retirement phase as-is, only modify aligned phases
            phase[post_mask] = np.where(
                phase[post_mask] == "retirement",
                "retirement",  # Keep retirement phase unchanged
                "aligned_compensation",
            )

        # -------- Attach outputs --------
        g["company_trajectory_latesudden"] = ls
        g["late_sudden_phase"] = phase

        return g

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
    Build the Late & Sudden pathway for *misaligned low-carbon* companies.

    Phases (per company_id x scenario_geography x sector x technology):
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
    # 0) Filter to misaligned low-carbon company-technology pairs
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

        # Identify last GEM year (last non-NA company_activity)
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

        # ---------------- Phase 3: Transition (from baseline@(shock-1) to target@alignment) ----------------
        if alignment_year > shock_year:
            mask_p3 = (years >= shock_year) & (years <= alignment_year)
            if mask_p3.any():
                # Boundary values
                v_start = float(baseline[years == (shock_year - 1)][0])
                try:
                    v_end = float(target[years == alignment_year][0])
                except IndexError:
                    raise ValueError(
                        f"Target value for alignment_year={alignment_year} not found in group "
                        f"{tuple(g[name].iloc[0] for name in group_cols)}."
                    )

                denom = alignment_year - shock_year
                frac = (years[mask_p3] - (shock_year - 1)) / (
                    denom + 1
                )  # shock_year gets frac = 1/(denom+1)
                ls[mask_p3] = v_start + frac * (v_end - v_start)
                phase[mask_p3] = "transition"

        # ---------------- Phase 4: Alignment ----------------
        mask_p4 = years > alignment_year
        if mask_p4.any():
            ls[mask_p4] = target[mask_p4]
            phase[mask_p4] = "aligned"

        # Non-negativity safeguard
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
    Build the Late & Sudden pathway for *aligned high-carbon* (decreasing) companies.

    Phases (per company_id x scenario_geography x sector x technology):
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

    # 0) Filter to aligned high-carbon company-technology pairs
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

        # Last GEM year = last non-NA company_activity
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

        # Phase 3: Transition (from baseline@(shock-1) to target@alignment for high-carbon)
        if alignment_year > shock_year:
            mask_p3 = (years >= shock_year) & (years <= alignment_year)
            if mask_p3.any():
                v_start = float(baseline[years == (shock_year - 1)][0])
                try:
                    v_end = float(target[years == alignment_year][0])
                except IndexError:
                    raise ValueError(
                        f"Target value for alignment_year={alignment_year} not found in group "
                        f"{tuple(g[name].iloc[0] for name in group_cols)}."
                    )

                denom = alignment_year - shock_year
                frac = (years[mask_p3] - (shock_year - 1)) / (
                    denom + 1
                )  # shock_year gets frac = 1/(denom+1)
                ls[mask_p3] = v_start + frac * (v_end - v_start)
                phase[mask_p3] = "transition"

        # Phase 4: Alignment
        mask_p4 = years > alignment_year
        if mask_p4.any():
            ls[mask_p4] = target[mask_p4]
            phase[mask_p4] = "aligned"

        # Non-negativity safeguard
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

    Phase logic (per company_id x geography x sector x technology)
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
    # helper that builds L&S for *one* company x tech x geo x sector
    # ---------------------------------------------------------------
    def _build_late_sudden_for_group(g: pd.DataFrame) -> pd.DataFrame:
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
        .apply(_build_late_sudden_for_group)
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
