"""
This is a boilerplate pipeline 'report_outputs'
generated using Kedro 0.19.12
"""

import pandas as pd
import matplotlib.pyplot as plt
import re
from pathlib import Path
import os


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

    # Create base directory
    base_dir = Path("data/08_reporting/companies_trajectories_plots")
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

            # Check if we have the required trajectory columns
            required_cols = [
                "company_trajectory_target",
                "company_trajectory_baseline",
                "company_trajectory_latesudden",
            ]
            available_cols = [
                col for col in required_cols if col in group_sorted.columns
            ]

            if not available_cols:
                print(
                    f"Warning: No trajectory columns found for {company_name} - {technology} - {scenario_geography}"
                )
                continue

            # Create the plot with extra space for legends outside
            fig, ax = plt.subplots(figsize=(16, 10))

            years = group_sorted["year"]

            # Plot each available trajectory
            if "company_trajectory_target" in group_sorted.columns:
                target_data = group_sorted["company_trajectory_target"].dropna()
                if not target_data.empty:
                    ax.plot(
                        years,
                        group_sorted["company_trajectory_target"],
                        label="Target Trajectory",
                        linewidth=2.5,
                        linestyle="--",
                        color="green",
                        alpha=0.8,
                    )

            if "company_trajectory_baseline" in group_sorted.columns:
                baseline_data = group_sorted["company_trajectory_baseline"].dropna()
                if not baseline_data.empty:
                    ax.plot(
                        years,
                        group_sorted["company_trajectory_baseline"],
                        label="Baseline Trajectory",
                        linewidth=2.5,
                        linestyle="-.",
                        color="blue",
                        alpha=0.8,
                    )

            # Plot Late & Sudden trajectory with phase coloring
            if "company_trajectory_latesudden" in group_sorted.columns:
                latesudden_data = group_sorted["company_trajectory_latesudden"].dropna()
                if not latesudden_data.empty:
                    # Plot the main late sudden trajectory
                    ax.plot(
                        years,
                        group_sorted["company_trajectory_latesudden"],
                        label="Late & Sudden Trajectory",
                        linewidth=3,
                        color="red",
                        alpha=0.9,
                    )

                    # Add phase visualization if phase information is available
                    if "late_sudden_phase" in group_sorted.columns:
                        # Create colored background areas for each phase
                        phase_spans = []
                        current_phase = None
                        phase_start = None

                        # Group consecutive years by phase to create spans
                        for i, (year, phase) in enumerate(
                            zip(years, group_sorted["late_sudden_phase"])
                        ):
                            if phase != current_phase:
                                # End previous phase span
                                if (
                                    current_phase is not None
                                    and phase_start is not None
                                ):
                                    # End the previous phase at the current year to avoid gaps
                                    phase_spans.append(
                                        (current_phase, phase_start, year - 1)
                                    )

                                # Start new phase span at the same year where previous phase ended
                                # to ensure no gaps between phases
                                current_phase = phase
                                phase_start = year - 1

                        # Don't forget the last phase - extend it slightly beyond the last data point
                        if current_phase is not None and phase_start is not None:
                            # Extend the last phase to cover the full plot area
                            last_year = years.iloc[-1]
                            year_range = years.max() - years.min()
                            extended_end = last_year + (
                                year_range * 0.02
                            )  # Add 2% of total range
                            phase_spans.append(
                                (current_phase, phase_start, extended_end)
                            )

                        # Draw colored background areas for each phase
                        phase_legend_elements = []
                        for phase, start_year, end_year in phase_spans:
                            if pd.notna(phase) and phase != "":
                                color = phase_colors.get(phase, "#333333")

                                # Create semi-transparent background area
                                ax.axvspan(
                                    start_year,
                                    end_year,
                                    alpha=0.15,
                                    color=color,
                                    zorder=0,
                                )

                                # Add more prominent vertical line at phase start (except first phase)
                                if start_year != years.iloc[0]:
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


def plot_staggered_shock(
    late_sudden_trajectories: pd.DataFrame,
    assets_forecasts: pd.DataFrame,
    asset_level_df: pd.DataFrame,
    output_dir: str = "data/08_reporting/companies_staggered_shock_plots",
    asset_prod_col: str = "capacity_after_shock",  # <-- set this to the true column name
):
    """
    For each unique (scenario_geography, company_id, technology) in the
    late_sudden_trajectories, generates and saves:
      1) A plot of the original company‐level Late&SUDDEN trajectory vs.
         each asset and their sum,
      2) A plot of the year‐by‐year difference (asset sum − company).
    """

    os.makedirs(output_dir, exist_ok=True)

    def _clean(name: str) -> str:
        if pd.isna(name):
            return "Unknown"
        cleaned = re.sub(r'[<>:"/\\|?*]', "_", str(name))
        cleaned = re.sub(r"[^\w\s-]", "_", cleaned)
        cleaned = re.sub(r"\s+", "_", cleaned)
        return cleaned[:100]

    # pull company_name from trajectories (if present)
    traj = late_sudden_trajectories.copy()
    if "company_name" not in traj:
        # fallback: try merging from assets_forecasts
        traj = traj.merge(
            assets_forecasts[["company_id", "company_name"]].drop_duplicates(),
            on="company_id",
            how="left",
        )

    # group by alignment_type
    if "alignment_type" in traj:
        groups = traj.groupby("alignment_type")
    else:
        groups = [("general", traj)]

    for alignment_type, df_align in groups:
        subdir = os.path.join(output_dir, str(alignment_type))
        os.makedirs(subdir, exist_ok=True)

        combos = (
            df_align[["scenario_geography", "company_id", "technology", "company_name"]]
            .drop_duplicates()
            .sort_values(["scenario_geography", "company_id", "technology"])
        )

        for _, row in combos.iterrows():
            geo, cid, tech, comp_name = (
                row["scenario_geography"],
                row["company_id"],
                row["technology"],
                row["company_name"],
            )
            comp = df_align[
                (df_align["scenario_geography"] == geo)
                & (df_align["company_id"] == cid)
                & (df_align["technology"] == tech)
            ].sort_values("year")
            if comp.empty:
                continue

            years = comp["year"].to_numpy()
            company_vals = comp["company_trajectory_latesudden"].to_numpy()

            assets = asset_level_df[
                (asset_level_df["company_id"] == cid)
                & (asset_level_df["technology"] == tech)
            ].copy()
            if assets.empty:
                continue

            # --- Plot 1: company vs assets vs sum ---
            plt.figure(figsize=(10, 6))
            plt.plot(
                years, company_vals, lw=2.5, color="black", label="Company Late&SUDDEN"
            )

            # individual assets
            for aid, df_a in assets.groupby("asset_id"):
                df_a = df_a.sort_values("year")
                plt.plot(
                    df_a["year"],
                    df_a[asset_prod_col],
                    lw=1.2,
                    alpha=0.7,
                    label=f"Asset {aid}",
                )

            # sum of assets
            agg = (
                assets.groupby("year", as_index=False)
                .agg(total_asset_plate=(asset_prod_col, "sum"))
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
            plt.ylabel("Production / Capacity")
            plt.title(
                f"{tech} • {geo} • {cid}\n"
                f"Company vs Asset trajectories\nAlignment: {alignment_type}"
            )
            plt.legend(bbox_to_anchor=(1.05, 1), loc="upper left")
            plt.tight_layout()

            tech_clean = _clean(tech)
            geo_clean = _clean(geo)
            comp_clean = _clean(comp_name)
            fname = f"{tech_clean}-{comp_clean}-{geo_clean}.png"
            save_path = os.path.join(subdir, fname)
            plt.savefig(save_path, dpi=300)
            plt.close()
            print(f"Saved plot: {save_path}")

            # --- Plot 2: difference (sum_assets − company) ---
            sum_series = agg.set_index("year")["total_asset_plate"].reindex(
                years, fill_value=0
            )
            diffs = sum_series.values - company_vals

            plt.figure(figsize=(8, 4))
            plt.plot(years, diffs, marker="o")
            plt.axhline(0, linestyle="--", color="grey")
            plt.xlabel("Year")
            plt.ylabel("Asset Sum − Company")
            plt.title(
                f"{tech} • {geo} • {cid}\n"
                f"Difference Over Time\n"
                f"Alignment: {alignment_type}"
            )
            plt.tight_layout()

            fname2 = f"{tech_clean}-{comp_clean}-{geo_clean}-diff.png"
            save_path2 = os.path.join(subdir, fname2)
            plt.savefig(save_path2, dpi=300)
            plt.close()
            print(f"Saved plot: {save_path2}")

    print(f"All plots saved under {output_dir}")
