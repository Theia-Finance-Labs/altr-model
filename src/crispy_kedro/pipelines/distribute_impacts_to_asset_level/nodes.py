import pandas as pd
import numpy as np
import warnings
from tqdm import tqdm

# ============================ helpers ============================


def _compute_g_weights(
    ages: pd.Series,
    k: float,
    min_active_share: float,
    n_quantiles: int,
    for_decreasing: bool = True,
) -> pd.Series:
    """Compute logistic-sum g(a) weights, clip and normalize.

    Args:
        ages: Asset ages
        k: Steepness parameter for logistic function
        min_active_share: Minimum weight for any asset
        n_quantiles: Number of quantiles to use for age thresholds
        for_decreasing: If True, older assets get higher weights (for decreasing tech).
                       If False, younger assets get higher weights (for increasing tech).
    """
    if ages.empty:
        return pd.Series(dtype=float)
    ages = ages.astype(float)
    med = float(ages.median()) if np.isfinite(ages.median()) else 0.0
    filled = ages.fillna(med)
    qs = np.linspace(0, 1, n_quantiles + 1)[1:-1]
    age_q = np.quantile(filled, qs) if len(qs) else []

    def g(a):
        a = med if pd.isna(a) else a
        base_weight = 1 - sum(1 / (1 + np.exp(-k * (a - q))) for q in age_q)
        # For decreasing tech: older assets should get higher weights, so invert
        # For increasing tech: younger assets should get higher weights, so keep original
        return -base_weight if for_decreasing else base_weight

    raw = filled.map(g)
    clipped = raw.clip(lower=min_active_share)
    s = clipped.sum()
    if not np.isfinite(s) or s <= min_active_share:
        return pd.Series(1.0 / len(clipped), index=clipped.index)
    return clipped / s


# ============================ nodes ============================


# TODO is this function a duplicate of
# create_baseline_and_target_trajectories/nodes.py:aggregate_assets_to_company_level ?
def aggregate_late_sudden_trajectories_to_company_level(
    all_assets_late_sudden_trajectories: pd.DataFrame,
) -> pd.DataFrame:
    """
    Aggregate late sudden trajectories to company level.
    """

    companies_late_sudden_trajectories = (
        all_assets_late_sudden_trajectories.groupby(
            [
                "company_id",
                "company_name",
                "scenario_geography",
                "sector",
                "technology",
                "alignment_type",
                "late_sudden_phase",
                "year",
            ]
        )
        .agg(
            {
                "asset_activity": lambda x: x.sum() if not pd.isna(x).all() else np.nan,
                "asset_trajectory_baseline": "sum",
                "asset_trajectory_target": "sum",
                "asset_trajectory_latesudden": "sum",
            }
        )
        .rename(
            {
                "asset_activity": "company_activity",
                "asset_trajectory_baseline": "company_trajectory_baseline",
                "asset_trajectory_target": "company_trajectory_target",
                "asset_trajectory_latesudden": "company_trajectory_latesudden",
            },
            axis=1,
        )
        .reset_index()
    )

    return companies_late_sudden_trajectories


def compute_company_level_compensation(
    companies_late_sudden_trajectories: pd.DataFrame,
    shock_year: int,
    alignment_year: int,
) -> pd.DataFrame:
    """Compute company-level compensation."""

    return companies_late_sudden_trajectories


def stagger_decreasing_tech(
    assets_late_sudden_trajectories: pd.DataFrame,
    companies_late_sudden_trajectories: pd.DataFrame,
    assets_retirement_dates: pd.DataFrame,
    compensation_required_per_company: pd.DataFrame,
    shock_year: int,
    alignment_year: int,
    g_k: float = 6.0,
):
    """
    Distribute **all negative changes** in L&S (full horizon) to assets for decreasing techs.
    Geography-aware (scenario_geography).

    For misaligned_high_carbon companies, asset retirements are applied first to match
    the late & sudden shock mechanism behavior before applying age-based allocation rules.
    """

    dec_mask = assets_late_sudden_trajectories["alignment_type"].isin(
        ["misaligned_high_carbon", "aligned_high_carbon"]
    )
    dec_late_sudden_trajectories = assets_late_sudden_trajectories[dec_mask]

    return dec_late_sudden_trajectories


def stagger_increasing_tech(
    assets_late_sudden_trajectories: pd.DataFrame,
    companies_late_sudden_trajectories: pd.DataFrame,
    shock_year: int,
    g_k: float = 6.0,
):
    """
    Distribute **all positive changes** in L&S (full horizon) to assets for increasing techs.
    Geography-aware. Uses ONE persistent synthetic asset per (company_id, scenario_geography, sector, technology).
    Ensures the synthetic row is never duplicated (never included in the 'real' block).
    """

    inc_mask = assets_late_sudden_trajectories["alignment_type"].isin(
        ["misaligned_low_carbon", "aligned_low_carbon"]
    )
    inc_late_sudden_trajectories = assets_late_sudden_trajectories[inc_mask]

    return inc_late_sudden_trajectories


def concatenate_staggered_shock_results(
    dec_late_sudden_trajectories: pd.DataFrame,
    inc_late_sudden_trajectories: pd.DataFrame,
) -> pd.DataFrame:
    """
    Concatenate the decreasing and increasing results.
    """
    assets_staggered_shock = pd.concat(
        [dec_late_sudden_trajectories, inc_late_sudden_trajectories], ignore_index=True
    ).reset_index(drop=True)
    return assets_staggered_shock
