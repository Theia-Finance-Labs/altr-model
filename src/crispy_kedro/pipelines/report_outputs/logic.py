import re
from typing import List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def clean_name_for_folder(name) -> str:
    if pd.isna(name):
        return "Unknown"
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", str(name))
    cleaned = re.sub(r"[^\w\s-]", "_", cleaned)
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:120]


def get_phase_colors() -> dict:
    return {
        "forecast": "#1f77b4",  # Blue
        "bau": "#ff7f0e",  # Orange
        "transition": "#2ca02c",  # Green
        "aligned": "#d62728",  # Red
        "aligned_compensation": "#9467bd",  # Purple
        "retirement": "#7f7f7f",  # Gray
        "phased_out": "#bcbd22",  # Olive
    }


def infer_trajectory_columns(
    df: pd.DataFrame,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return the column names for (target, baseline, latesudden) if present.

    Supports both company_trajectory_* and asset_trajectory_* naming.
    """
    mapping_options = [
        (
            "company_trajectory_target",
            "company_trajectory_baseline",
            "company_trajectory_latesudden",
        ),
        (
            "asset_trajectory_target",
            "asset_trajectory_baseline",
            "asset_trajectory_latesudden",
        ),
    ]
    for tgt, base, late in mapping_options:
        if tgt in df.columns or base in df.columns or late in df.columns:
            return (
                tgt if tgt in df.columns else None,
                base if base in df.columns else None,
                late if late in df.columns else None,
            )
    return (None, None, None)


def _compute_phase_spans(years: pd.Series, phases: pd.Series) -> List[tuple]:
    """Compute contiguous phase spans from year and phase series.

    Returns list of tuples: (phase_name, start_year, end_year)
    """
    phase_spans = []
    current_phase = None
    phase_start = None

    for year, phase in zip(years, phases):
        if phase != current_phase:
            if current_phase is not None and phase_start is not None:
                phase_spans.append((current_phase, phase_start, year - 1))
            current_phase = phase
            phase_start = year - 1

    if current_phase is not None and phase_start is not None:
        last_year = years.iloc[-1]
        year_range = years.max() - years.min()
        extended_end = last_year + (year_range * 0.02)
        phase_spans.append((current_phase, phase_start, extended_end))

    return phase_spans


def draw_late_sudden_trajectories(
    ax: plt.Axes,
    years: pd.Series,
    df_sorted: pd.DataFrame,
    phase_colors: Optional[dict] = None,
) -> List[plt.Rectangle]:
    """Draw target, baseline and late&sudden trajectories and shade phases.

    Returns list of legend rectangles for the phases. Phase shading is only added
    if a 'late_sudden_phase' column exists.
    """
    if phase_colors is None:
        phase_colors = get_phase_colors()

    target_col, baseline_col, late_col = infer_trajectory_columns(df_sorted)

    phase_legend_elements: List[plt.Rectangle] = []

    # Plot target
    if target_col is not None:
        target_data = df_sorted[target_col].dropna()
        if not target_data.empty:
            ax.plot(
                years,
                df_sorted[target_col],
                label="Target Trajectory",
                linewidth=2.5,
                linestyle="--",
                color="green",
                alpha=0.8,
            )

    # Plot baseline
    if baseline_col is not None:
        baseline_data = df_sorted[baseline_col].dropna()
        if not baseline_data.empty:
            ax.plot(
                years,
                df_sorted[baseline_col],
                label="Baseline Trajectory",
                linewidth=2.5,
                linestyle="-.",
                color="blue",
                alpha=0.8,
            )

    # Plot late & sudden trajectory
    if late_col is not None:
        latesudden_data = df_sorted[late_col].dropna()
        if not latesudden_data.empty:
            ax.plot(
                years,
                df_sorted[late_col],
                label="Late & Sudden Trajectory",
                linewidth=3,
                color="red",
                alpha=0.9,
            )

            # Phase shading and labels
            if "late_sudden_phase" in df_sorted.columns:
                phase_spans = _compute_phase_spans(
                    years, df_sorted["late_sudden_phase"]
                )
                for phase, start_year, end_year in phase_spans:
                    if pd.notna(phase) and phase != "":
                        color = phase_colors.get(phase, "#333333")
                        ax.axvspan(
                            start_year, end_year, alpha=0.15, color=color, zorder=0
                        )
                        if start_year != years.iloc[0]:
                            ax.axvline(
                                x=start_year,
                                color=color,
                                linestyle="--",
                                alpha=0.8,
                                linewidth=2,
                                zorder=1,
                            )
                        mid_year = start_year + (end_year - start_year) / 2
                        ax.text(
                            mid_year,
                            ax.get_ylim()[1] * 0.95,
                            str(phase).replace("_", " ").title(),
                            ha="center",
                            va="top",
                            fontsize=8,
                            color=color,
                            fontweight="bold",
                            bbox=dict(
                                boxstyle="round,pad=0.3",
                                facecolor="white",
                                edgecolor=color,
                                alpha=0.8,
                            ),
                        )
                        phase_legend_elements.append(
                            plt.Rectangle(
                                (0, 0),
                                1,
                                1,
                                facecolor=color,
                                alpha=0.3,
                                label=f"Phase: {str(phase).replace('_', ' ').title()}",
                            )
                        )

    return phase_legend_elements
