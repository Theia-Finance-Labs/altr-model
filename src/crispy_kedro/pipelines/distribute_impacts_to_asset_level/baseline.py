"""Asset-level baseline (BAU) trajectories for the distribution stage.

Scales company baseline trajectories down to individual assets over the full
horizon, fills missing asset activity, and optionally zeroes retired
asset-years. Also holds the age-based g-weight core used when staggering.
"""
# ruff: noqa: PLR0915 — long numeric routine, kept whole to stay behaviour-identical
import logging

import numpy as np
import pandas as pd
from tqdm import tqdm

logger = logging.getLogger(__name__)


# ========= NEW: vectorized g-weights core (logistic-sum like your original) =========
def _compute_g_weights_array(
    ages_array: np.ndarray,
    k: float,
    n_quantiles: int,
    for_decreasing: bool,
    min_active_share: float = 1e-12,
) -> np.ndarray:
    """
    Vectorized version of your logistic-sum g(a).
    raw(a) = 1 - sum_q 1/(1+exp(-k*(a - cut_q)))
    If for_decreasing: negate raw so that older => higher after shifting/normalizing.

    Returns a length-A float64 array that sums to 1 (unless A==0).
    """
    A = int(ages_array.shape[0])
    if A == 0:
        return np.zeros((0,), dtype=np.float64)

    ages = ages_array.astype(np.float64, copy=False)
    if n_quantiles <= 1:
        raw = np.ones(A, dtype=np.float64)
    else:
        qs = np.linspace(0.0, 1.0, n_quantiles + 1)[1:-1]  # exclude 0 and 1
        if qs.size == 0:
            raw = np.ones(A, dtype=np.float64)
        else:
            cuts = np.quantile(ages, qs)
            # matrix: [A x Q]
            X = ages[:, None] - cuts[None, :]
            sig = 1.0 / (1.0 + np.exp(-k * X))
            raw = 1.0 - sig.sum(axis=1)

    if for_decreasing:
        raw = -raw

    # shift to positive & normalize
    raw -= np.nanmin(raw)
    raw += float(min_active_share)

    s = np.nansum(raw)
    if not np.isfinite(s) or s <= 0.0:
        return np.full(A, 1.0 / A, dtype=np.float64)
    return raw / s


def _index_company_by_year(
    df_company: pd.DataFrame,
) -> dict[tuple[str, str, str, str], pd.DataFrame]:
    GROUP_COLS = [
        "company_id",
        "company_name",
        "scenario_geography",
        "sector",
        "technology",
    ]
    return {
        k: g.sort_values("year").set_index("year")
        for k, g in df_company.groupby(GROUP_COLS, sort=False)
    }


def compute_asset_baseline_trajectories(
    companies_late_sudden_trajectories: pd.DataFrame,
    allocated_assets_to_companies: pd.DataFrame,
    assets_retirement_dates: pd.DataFrame = None,
    apply_retirement_baseline: bool = False,
    alignment_year: int = None,
) -> pd.DataFrame:
    """
    Compute asset-level baseline trajectories over the full time horizon (melted input).

    This replaces the old _bau_fill_assets_until_shock logic but extends it
    to compute BAU trajectories for the entire time horizon, not just until shock year.

    The baseline trajectory represents the BAU (Business-as-Usual) path that assets
    would follow based on company baseline trajectories, with proper scaling and
    forward-filling for missing data.

    Additionally, this function fills missing asset_activity values using the same
    logic, ensuring that the staggered shock functions have complete data.

    Parameters
    ----------
    companies_late_sudden_trajectories : pd.DataFrame
        Melted company trajectories with columns including:
        - company_id, scenario_geography, sector, technology, year
        - trajectory_type ('baseline' row required)
        - company_trajectory (values)
        - late_sudden_phase, alignment_type (optional for this routine)
    allocated_assets_to_companies : pd.DataFrame
        Asset data with columns including:
        - company_id, scenario_geography, sector, technology, asset_id, year
        - asset_activity, asset_age
    assets_retirement_dates : pd.DataFrame, optional
        Retirement dates for assets
    apply_retirement_baseline : bool, optional
        Whether to apply retirement zeroing to baseline trajectories
    alignment_year : int, optional
        Alignment year for retirement (retirement cannot occur before alignment_year + 1)

    Returns
    -------
    pd.DataFrame
        Asset data with added column 'asset_baseline_trajectory' representing
        the full-horizon BAU trajectory for each asset, and filled asset_activity values.
    """
    if allocated_assets_to_companies.empty:
        result = allocated_assets_to_companies.copy()
        result["asset_baseline_trajectory"] = pd.Series(dtype=float)
        return result

    GROUP_COLS = [
        "company_id",
        "company_name",
        "scenario_geography",
        "sector",
        "technology",
    ]

    # Expect melted input: filter baseline rows and rename
    need_cols = GROUP_COLS + ["year", "trajectory_type", "company_trajectory"]
    miss = [c for c in need_cols if c not in companies_late_sudden_trajectories.columns]
    if miss:
        raise ValueError(
            f"companies_late_sudden_trajectories missing columns for BAU fill: {miss}"
        )

    comp_base = (
        companies_late_sudden_trajectories[
            companies_late_sudden_trajectories["trajectory_type"] == "baseline"
        ][GROUP_COLS + ["year", "company_trajectory"]]
        .drop_duplicates(GROUP_COLS + ["year"])
        .rename(columns={"company_trajectory": "_company_baseline"})
    )

    out = allocated_assets_to_companies.copy()
    out = out.merge(
        comp_base,
        on=["company_id", "scenario_geography", "sector", "technology", "year"],
        how="left",
    )

    # Group by key + asset
    gcols = ["company_id", "scenario_geography", "sector", "technology", "asset_id"]
    out.sort_values(gcols + ["year"], inplace=True)

    def _compute_baseline_trajectory_and_fill_activity(
        group: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Compute baseline trajectory for a single asset across all years and fill missing asset_activity.

        This replicates the logic from the old _bau_fill_assets_until_shock function:
        1. Use available asset_activity data as anchor points
        2. Scale forward/backward using company baseline trajectory ratios
        3. For post-shock years, fill with constant value from shock year
        4. Forward-fill any remaining missing values
        """
        group = group.copy()

        # Initialize with existing activity
        activity = group["asset_activity"].copy()

        # Find anchor points (years with valid asset_activity data)
        valid_mask = ~activity.isna()
        if not valid_mask.any():
            # No valid data - use zeros
            group["asset_baseline_trajectory"] = 0.0
            group["asset_activity"] = group["asset_activity"].fillna(0.0)
            return group

        # Fill missing values using baseline scaling where possible
        for idx in group.index[~valid_mask]:
            current_year = group.at[idx, "year"]
            current_baseline = group.at[idx, "_company_baseline"]

            if pd.isna(current_baseline) or current_baseline == 0:
                continue

            # Find nearest valid asset value (prefer earlier years, then later)
            valid_indices = group.index[valid_mask]
            if len(valid_indices) == 0:
                continue

            # Find closest year with valid data
            valid_years = group.loc[valid_indices, "year"]
            year_diffs = abs(valid_years - current_year)
            closest_idx = valid_indices[year_diffs.argmin()]

            anchor_value = group.at[closest_idx, "asset_activity"]
            anchor_baseline = group.at[closest_idx, "_company_baseline"]

            if pd.notna(anchor_baseline) and anchor_baseline != 0:
                # Scale using baseline ratio
                ratio = current_baseline / anchor_baseline
                activity.at[idx] = anchor_value * ratio
            else:
                # Fallback to flat carry
                activity.at[idx] = anchor_value

        # Apply post-shock constant filling logic (like old _bau_fill_assets_until_shock)
        # This ensures years after forecast period get constant values
        activity_filled = activity.copy()

        # Forward fill and then backward fill to handle any remaining gaps
        activity_filled = activity_filled.ffill()

        # If there are still NaN values at the beginning, backward fill
        activity_filled = activity_filled.bfill()

        # Fill any remaining NaN with 0
        activity_filled = activity_filled.fillna(0.0)

        # Set both baseline trajectory and filled asset_activity
        group["asset_baseline_trajectory"] = activity_filled
        group["asset_activity"] = activity_filled

        return group

    # Add progress bar for baseline computation. Selecting only the columns the
    # fill reads keeps grouping columns out of apply — operating on them is
    # deprecated in pandas >=2.2, and include_groups= does not exist on the
    # pinned pandas <2.2. Results are written back via index alignment.
    apply_cols = ["year", "asset_activity", "_company_baseline"]
    grouped = out.groupby(gcols, sort=False, group_keys=False)[apply_cols]
    tqdm.pandas(desc="Computing asset baselines and filling activity", unit="asset")
    filled = grouped.progress_apply(_compute_baseline_trajectory_and_fill_activity)
    out["asset_activity"] = filled["asset_activity"]
    out["asset_baseline_trajectory"] = filled["asset_baseline_trajectory"]

    # Apply retirement to baseline trajectories if requested
    if (
        apply_retirement_baseline
        and assets_retirement_dates is not None
        and not assets_retirement_dates.empty
    ):
        logger.info("Applying retirement to baseline trajectories")

        # Vectorized approach: merge retirement dates and apply in bulk
        # Prepare retirement DataFrame with matching columns
        retirement_df = assets_retirement_dates[
            [
                "company_id",
                "scenario_geography",
                "sector",
                "technology",
                "asset_id",
                "retirement_year",
            ]
        ].copy()

        # Convert asset_id to string for consistent matching
        retirement_df["asset_id"] = retirement_df["asset_id"].astype(str)

        # Calculate effective retirement year (cannot be before alignment_year + 1)
        retirement_df["eff_retirement_year"] = retirement_df["retirement_year"].astype(
            int
        )
        if alignment_year is not None:
            retirement_df["eff_retirement_year"] = retirement_df[
                "eff_retirement_year"
            ].clip(lower=int(alignment_year) + 1)

        # Merge retirement info into `out` itself: the merge result carries a
        # fresh RangeIndex while `out` still holds the permuted labels from the
        # earlier sort, so mask and assignment must live on the same frame.
        # Convert asset_id to string temporarily for consistent merging
        out_asset_id_original = out["asset_id"].to_numpy()
        out["asset_id"] = out["asset_id"].astype(str)

        try:
            out = out.merge(
                retirement_df[
                    [
                        "company_id",
                        "scenario_geography",
                        "sector",
                        "technology",
                        "asset_id",
                        "eff_retirement_year",
                    ]
                ],
                on=[
                    "company_id",
                    "scenario_geography",
                    "sector",
                    "technology",
                    "asset_id",
                ],
                how="left",
                validate="many_to_one",
                suffixes=("", "_retirement"),
            )
        finally:
            # Restore original asset_id dtype (row order is preserved by the merge)
            out["asset_id"] = out_asset_id_original

        # Vectorized mask: zero out rows where year >= effective retirement year
        retirement_mask = out["eff_retirement_year"].notna() & (
            out["year"] >= out["eff_retirement_year"]
        )

        # Apply retirement zeroing using vectorized assignment
        out.loc[retirement_mask, "asset_baseline_trajectory"] = 0.0
        out.loc[retirement_mask, "asset_activity"] = 0.0
        out.drop(columns=["eff_retirement_year"], inplace=True)

    # Clean up helper column
    out.drop(columns=["_company_baseline"], inplace=True)
    return out
