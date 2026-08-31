"""Splitting and re-assembly around the asset-level distribution stage.

Splits company late-and-sudden trajectories into decreasing/increasing streams
before staggering, concatenates the two asset-level results afterwards, and
melts the wide asset frame into the long form downstream stages consume.
"""
import logging
from typing import List, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


def split_late_sudden_trajectories_by_alignment_type(
    companies_late_sudden_trajectories: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return (decreasing_df, increasing_df) filtered to L&S only.

    Expects a melted structure with columns including 'trajectory_type' and
    'company_trajectory'. Only rows with trajectory_type == 'latesudden' are
    considered for decreasing/increasing splitting.

    All companies are assigned to either decreasing or increasing based on alignment_type.
    Companies with missing or unrecognized alignment_type are assigned based on fallback logic.
    """
    # Build a company_name map from the full input (not just latesudden)
    df = companies_late_sudden_trajectories.copy()
    if "trajectory_type" in df.columns:
        df = df[df["trajectory_type"] == "latesudden"].copy()

    # Primary decreasing tech alignment types
    dec_mask = df["alignment_type"].isin(
        ["misaligned_high_carbon", "aligned_high_carbon"]
    )

    # Split into decreasing and increasing technologies
    decreasing_df = df[dec_mask].copy()
    increasing_df = df[~dec_mask].copy()

    logger.info(
        f"Split trajectories: {len(decreasing_df)} decreasing tech rows, "
        f"{len(increasing_df)} increasing tech rows"
    )

    return (decreasing_df, increasing_df)


def concatenate_staggered_shock_results(
    dec_late_sudden_trajectories: pd.DataFrame,  # asset-level (decreasing)
    inc_late_sudden_trajectories: pd.DataFrame,  # asset-level (increasing)
    increasing_tech_late_sudden_trajectories: pd.DataFrame,  # company-level (increasing)
    decreasing_tech_late_sudden_trajectories_corrected: pd.DataFrame,  # company-level corrections (decreasing)
    original_companies_late_sudden_trajectories: pd.DataFrame,  # company-level original trajectories
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns:
      - assets_staggered_late_sudden: concatenated asset-level outputs (dec + inc).
      - companies_late_sudden_trajectories: original companies df + dec corrections + inc trajectories.

    Assumes upstream nodes already propagated company_name; only performs minimal fallback fill.
    """
    KEY = ["company_id", "scenario_geography", "sector", "technology", "year"]

    assets_staggered_late_sudden = pd.concat(
        [dec_late_sudden_trajectories, inc_late_sudden_trajectories], ignore_index=True
    )

    # Process decreasing tech corrections: keep BOTH 'latesudden_original' and 'latesudden_adjusted'
    # to enable plotting of both series downstream. Do not rename types here.
    decreasing_corrected = decreasing_tech_late_sudden_trajectories_corrected.copy()

    companies_late_sudden_trajectories = pd.concat(
        [
            increasing_tech_late_sudden_trajectories,
            decreasing_corrected,
        ],
        ignore_index=True,
    )
    companies_late_sudden_trajectories = companies_late_sudden_trajectories.loc[
        :,
        [
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
        ],
    ]

    sort_cols = [c for c in KEY if c in companies_late_sudden_trajectories.columns]
    if sort_cols:
        companies_late_sudden_trajectories = (
            companies_late_sudden_trajectories.sort_values(sort_cols).reset_index(
                drop=True
            )
        )

    # Final set: include all late-sudden variants available (original, adjusted, generic) and baseline
    companies_late_sudden_trajectories_final = pd.concat(
        [
            companies_late_sudden_trajectories[
                companies_late_sudden_trajectories["trajectory_type"].isin(
                    [
                        "latesudden",
                        "latesudden_original",
                        "latesudden_adjusted",
                    ]
                )
            ],
            original_companies_late_sudden_trajectories.query(
                "trajectory_type == 'baseline'"
            ),
        ],
        ignore_index=True,
    ).reset_index(drop=True)

    return assets_staggered_late_sudden, companies_late_sudden_trajectories_final


def melt_asset_staggered_trajectories(
    assets_staggered_late_sudden: pd.DataFrame,
) -> pd.DataFrame:
    """
    Produce a melted asset-level dataframe with trajectory_type and asset_trajectory.

    Input is the debug-friendly wide asset dataframe produced by the stagger nodes,
    containing columns like 'capacity_after_shock' (L&S) and 'asset_baseline_trajectory'.

    Output columns include:
      - asset_id, company_id, company_name, scenario_geography, sector, technology,
        year, asset_age, is_synthetic, late_sudden_phase, alignment_type,
      - trajectory_type in {'baseline','latesudden'}
      - asset_trajectory (values)
    """
    if assets_staggered_late_sudden is None or assets_staggered_late_sudden.empty:
        return pd.DataFrame(
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

    df = assets_staggered_late_sudden.copy()

    id_cols = [
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
    ]

    # Build value cols present
    value_map = [
        ("latesudden", "capacity_after_shock"),
        ("baseline", "asset_baseline_trajectory"),
    ]

    melted_parts: List[pd.DataFrame] = []
    for ttype, col in value_map:
        sub = df[id_cols].copy()
        sub["trajectory_type"] = ttype
        sub["asset_trajectory"] = df[col].astype(float)
        melted_parts.append(sub)

    out = pd.concat(melted_parts, ignore_index=True)
    # Sort for stability
    sort_cols = [
        c
        for c in [
            "company_id",
            "scenario_geography",
            "sector",
            "technology",
            "asset_id",
            "year",
            "trajectory_type",
        ]
        if c in out.columns
    ]
    if sort_cols:
        out = out.sort_values(sort_cols).reset_index(drop=True)
    return out
