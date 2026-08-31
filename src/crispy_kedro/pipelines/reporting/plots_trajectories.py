"""Reporting stage: company late & sudden trajectory plots.

Stage 8 of the ALTR pipeline. Renders one figure per
company-technology-geography, overlaying the late & sudden, baseline and target
trajectories with the alignment phase spans described in the ALTR
Documentation, late & sudden section.
"""

import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import _style  # noqa: F401  (applies the shared plotting style on import)


def plot_late_sudden_trajectories(
    late_sudden_trajectories: pd.DataFrame,
) -> None:
    """
    Plot the late sudden trajectories for each company-technology-geography combination.

    Creates plots showing company_trajectory_target, company_trajectory_baseline,
    and company_trajectory_latesudden over time and saves them in organized folders
    by alignment type. Visual indicators show different phases of the late sudden trajectory.

    Parameters
    ----------
    late_sudden_trajectories : pd.DataFrame
        DataFrame containing trajectory data with columns:
        company_id, scenario_geography, technology, year,
        company_trajectory_target, company_trajectory_baseline, company_trajectory_latesudden,
        late_sudden_phase, alignment_type
    """

    # Clean company names for folder creation (remove special characters)
    def clean_name_for_folder(name):
        if pd.isna(name):
            return "Unknown"
        # Replace special characters with underscores and limit length
        cleaned = re.sub(r'[<>:"/\\|?*]', "_", str(name))
        cleaned = re.sub(r"[^\w\s-]", "_", cleaned)
        cleaned = re.sub(r"\s+", "_", cleaned)
        return cleaned[:100]  # Limit length to avoid filesystem issues

    late_sudden_trajectories["company_name_clean"] = late_sudden_trajectories[
        "company_name"
    ].apply(clean_name_for_folder)

    # Create base directory and clean it
    base_dir = Path("data/08_reporting/companies_trajectories_plots")

    # Clean up existing directory if it exists
    if base_dir.exists():
        import shutil

        shutil.rmtree(base_dir)
        print(f"Cleaned up existing directory: {base_dir}")

    base_dir.mkdir(parents=True, exist_ok=True)

    # Define phase colors for visual distinction
    phase_colors = {
        "forecast": "#1f77b4",  # Blue
        "bau": "#ff7f0e",  # Orange
        "transition": "#2ca02c",  # Green
        "aligned": "#d62728",  # Red
        "aligned_compensation": "#9467bd",  # Purple
        "retirement": "#7f7f7f",  # Gray
        "phased_out": "#bcbd22",  # Olive
    }

    # Group by alignment type first to create subfolders
    if "alignment_type" not in late_sudden_trajectories.columns:
        print(
            "Warning: alignment_type column not found. Creating plots in single folder."
        )
        alignment_groups = [("general", late_sudden_trajectories)]
    else:
        alignment_groups = list(late_sudden_trajectories.groupby("alignment_type"))

    for alignment_type, alignment_data in alignment_groups:
        # Create subfolder for this alignment type
        alignment_dir = base_dir / str(alignment_type)
        alignment_dir.mkdir(parents=True, exist_ok=True)

        # Group by company, technology, and geography within this alignment type
        group_cols = [
            "company_id",
            "company_name",
            "company_name_clean",
            "technology",
            "scenario_geography",
        ]

        # Plot for each group within this alignment type
        for group_keys, group in alignment_data.groupby(group_cols):
            # Extract values from the first row of the group
            company_id = group["company_id"].iloc[0]
            company_name = group["company_name"].iloc[0]
            company_name_clean = group["company_name_clean"].iloc[0]
            technology = group["technology"].iloc[0]
            scenario_geography = group["scenario_geography"].iloc[0]

            # Skip if any required data is missing
            if (
                pd.isna(company_name_clean)
                or pd.isna(technology)
                or pd.isna(scenario_geography)
            ):
                continue

            # Clean technology and geography names for filename
            tech_clean = clean_name_for_folder(technology)
            geo_clean = clean_name_for_folder(scenario_geography)
            filename = f"{tech_clean}-{company_name_clean}-{geo_clean}.png"
            filepath = alignment_dir / filename

            # Sort by year for plotting
            group_sorted = group.sort_values("year")

            # Build series from melted structure: prefer 'latesudden_original' and 'latesudden_adjusted'
            # Fall back to 'latesudden' if present. Ignore baseline.
            has_melted = {"trajectory_type", "company_trajectory"}.issubset(
                set(group_sorted.columns)
            )
            series_map = {}
            if has_melted:
                pivot = (
                    group_sorted.pivot_table(
                        index="year",
                        columns="trajectory_type",
                        values="company_trajectory",
                        aggfunc="first",
                    )
                    .sort_index()
                    .fillna(np.nan)
                )
                years = pivot.index.to_numpy()
                if "latesudden_original" in pivot.columns:
                    series_map["original"] = pivot["latesudden_original"].to_numpy()
                if "latesudden_adjusted" in pivot.columns:
                    series_map["adjusted"] = pivot["latesudden_adjusted"].to_numpy()
                if not series_map and "latesudden" in pivot.columns:
                    series_map["latesudden"] = pivot["latesudden"].to_numpy()
                # Also support baseline and target if present (optional)
                if "baseline" in pivot.columns:
                    series_map["baseline"] = pivot["baseline"].to_numpy()
                if "target" in pivot.columns:
                    series_map["target"] = pivot["target"].to_numpy()
                if len(series_map) == 0:
                    print(
                        f"Warning: No latesudden trajectories found for {company_name} - {technology} - {scenario_geography}"
                    )
                    continue
            else:
                # Backward compatibility with wide format
                years = group_sorted["year"].to_numpy()
                if "company_trajectory_latesudden" in group_sorted.columns:
                    series_map["latesudden"] = group_sorted[
                        "company_trajectory_latesudden"
                    ].to_numpy()
                if "company_trajectory_target" in group_sorted.columns:
                    series_map["target"] = group_sorted[
                        "company_trajectory_target"
                    ].to_numpy()
                if len(series_map) == 0:
                    print(
                        f"Warning: No trajectory columns found for {company_name} - {technology} - {scenario_geography}"
                    )
                    continue

            # Create the plot with extra space for legends outside
            fig, ax = plt.subplots(figsize=(16, 10))

            # Plot trajectories
            if "original" in series_map:
                ax.plot(
                    years,
                    series_map["original"],
                    label="L&S Original",
                    linewidth=2.5,
                    linestyle="-",
                    color="red",
                    alpha=0.85,
                    zorder=2,
                )
            if "adjusted" in series_map:
                ax.plot(
                    years,
                    series_map["adjusted"],
                    label="L&S Adjusted",
                    linewidth=2.5,
                    linestyle="--",
                    color="darkred",
                    alpha=0.9,
                    zorder=3,
                )
            if "latesudden" in series_map:
                ax.plot(
                    years,
                    series_map["latesudden"],
                    label="L&S",
                    linewidth=3,
                    linestyle="-",
                    color="red",
                    alpha=0.9,
                    zorder=2,
                )
            if "baseline" in series_map:
                ax.plot(
                    years,
                    series_map["baseline"],
                    label="Baseline",
                    linewidth=2.5,
                    linestyle="-.",
                    color="blue",
                    alpha=0.8,
                    zorder=1,
                )
            if "target" in series_map:
                ax.plot(
                    years,
                    series_map["target"],
                    label="Target",
                    linewidth=2.5,
                    linestyle="--",
                    color="green",
                    alpha=0.8,
                    zorder=4,
                )
            # Add phase visualization if phase information is available
            phase_legend_elements = []
            if "late_sudden_phase" in group_sorted.columns:
                # Create colored background areas for each phase
                phase_spans = []
                current_phase = None
                phase_start = None

                # Ensure we have exactly one phase value per year in chronological order
                phase_years_df = (
                    group_sorted[["year", "late_sudden_phase"]]
                    .dropna(subset=["late_sudden_phase"])
                    .drop_duplicates(subset=["year"])
                    .sort_values("year")
                )

                for year, phase in zip(
                    phase_years_df["year"].to_numpy(),
                    phase_years_df["late_sudden_phase"].to_numpy(),
                ):
                    if current_phase is None:
                        current_phase = phase
                        phase_start = year
                        continue
                    if phase != current_phase:
                        # Close the previous span at the boundary year (no off-by-one)
                        phase_spans.append((current_phase, phase_start, year))
                        current_phase = phase
                        phase_start = year

                # Close the last span, extend slightly beyond the last data point for aesthetics
                if current_phase is not None and phase_start is not None:
                    last_year = years[-1]
                    year_range = years.max() - years.min()
                    extended_end = last_year + (
                        year_range * 0.02
                    )  # Add 2% of total range
                    phase_spans.append((current_phase, phase_start, extended_end))

                # Draw colored background areas for each phase
                for phase, start_year, end_year in phase_spans:
                    if pd.notna(phase) and phase != "":
                        color = phase_colors.get(phase, "#333333")

                        # Create semi-transparent background area
                        ax.axvspan(
                            start_year, end_year, alpha=0.15, color=color, zorder=0
                        )

                        # Add more prominent vertical line at phase start (except first phase)
                        if (
                            phase_years_df.shape[0] > 0
                            and start_year != phase_years_df["year"].iloc[0]
                        ):
                            ax.axvline(
                                x=start_year,
                                color=color,
                                linestyle="--",
                                alpha=0.8,
                                linewidth=2,
                                zorder=1,
                            )

                        # Add phase label at the top of the plot area
                        mid_year = start_year + (end_year - start_year) / 2
                        ax.text(
                            mid_year,
                            ax.get_ylim()[1] * 0.95,  # Near top of plot
                            phase.replace("_", " ").title(),
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

                        # Create legend entry for this phase
                        phase_legend_elements.append(
                            plt.Rectangle(
                                (0, 0),
                                1,
                                1,
                                facecolor=color,
                                alpha=0.3,
                                label=f"Phase: {phase.replace('_', ' ').title()}",
                            )
                        )

            # Customize the plot
            ax.set_xlabel("Year", fontsize=12)
            ax.set_ylabel("Production/Activity", fontsize=12)
            ax.set_title(
                f"{company_name}\n{technology} - {scenario_geography}\nAlignment Type: {alignment_type}",
                fontsize=14,
                fontweight="bold",
            )

            # Create main legend for trajectories - place outside on the right
            main_legend = ax.legend(
                loc="center left",
                bbox_to_anchor=(1.02, 0.5),  # Outside right, centered vertically
                fontsize=10,
                framealpha=0.9,
                fancybox=True,
                shadow=True,
            )

            # Add phase legend if phases are present - place outside on the right, below main legend
            if "late_sudden_phase" in group_sorted.columns and phase_legend_elements:
                # Remove duplicates from phase legend (in case same phase appears multiple times)
                seen_phases = set()
                unique_phase_elements = []
                for element in phase_legend_elements:
                    phase_label = element.get_label()
                    if phase_label not in seen_phases:
                        unique_phase_elements.append(element)
                        seen_phases.add(phase_label)

                phase_legend = ax.legend(
                    handles=unique_phase_elements,
                    loc="upper left",
                    bbox_to_anchor=(1.02, 0.3),  # Outside right, below main legend
                    fontsize=9,
                    title="Late & Sudden Phases",
                    title_fontsize=10,
                    framealpha=0.9,
                    fancybox=True,
                    shadow=True,
                )
                ax.add_artist(main_legend)  # Keep both legends

            ax.grid(True, alpha=0.3)

            # Format x-axis to show years nicely
            plt.xticks(rotation=45)

            # Adjust layout to make room for legends outside the plot
            plt.subplots_adjust(right=0.75)  # Leave space for legends on the right

            # Save the plot
            try:
                plt.savefig(filepath, dpi=300, bbox_inches="tight", facecolor="white")
                print(f"Saved plot: {filepath}")
            except Exception as e:
                print(
                    f"Error saving plot for {company_name} - {technology} - {scenario_geography}: {e}"
                )

            # Close the figure to free memory
            plt.close()

    print(f"Plotting completed. All plots saved in: {base_dir}")
    print(
        f"Subfolders created for alignment types: {[str(alignment_dir.name) for alignment_dir in base_dir.iterdir() if alignment_dir.is_dir()]}"
    )
