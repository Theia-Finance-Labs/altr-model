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
    assets_forecasts: pd.DataFrame,
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
    assets_forecasts : pd.DataFrame
        DataFrame containing company information with columns:
        company_id, company_name
    """

    # Merge with company names
    late_sudden_trajectories_with_company_name = late_sudden_trajectories.merge(
        assets_forecasts[["company_id", "company_name"]].drop_duplicates(),
        on="company_id",
        how="left",
    )

    # Clean company names for folder creation (remove special characters)
    def clean_name_for_folder(name):
        if pd.isna(name):
            return "Unknown"
        # Replace special characters with underscores and limit length
        cleaned = re.sub(r'[<>:"/\\|?*]', "_", str(name))
        cleaned = re.sub(r"[^\w\s-]", "_", cleaned)
        cleaned = re.sub(r"\s+", "_", cleaned)
        return cleaned[:100]  # Limit length to avoid filesystem issues

    late_sudden_trajectories_with_company_name["company_name_clean"] = (
        late_sudden_trajectories_with_company_name["company_name"].apply(
            clean_name_for_folder
        )
    )

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
        "aligned_retired": "#8c564b",  # Brown
        "bau_retired": "#e377c2",  # Pink
        "transition_retired": "#7f7f7f",  # Gray
        "aligned_retired_compensation": "#bcbd22",  # Olive
    }

    # Group by alignment type first to create subfolders
    if "alignment_type" not in late_sudden_trajectories_with_company_name.columns:
        print(
            "Warning: alignment_type column not found. Creating plots in single folder."
        )
        alignment_groups = [("general", late_sudden_trajectories_with_company_name)]
    else:
        alignment_groups = list(
            late_sudden_trajectories_with_company_name.groupby("alignment_type")
        )

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
                                        (current_phase, phase_start, year)
                                    )

                                # Start new phase span
                                current_phase = phase
                                phase_start = year

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
    asset_level_df: pd.DataFrame,
    output_dir: str = "data/08_reporting/companies_staggered_shock_plots",
):
    """
    For each unique (scenario_geography, company_id, technology) in the
    late_sudden_trajectories, generates and saves:
      1) A plot of the original company‐level Late&SUDDEN trajectory vs.
         each asset and their sum,
      2) A plot of the year‐by‐year difference (asset sum − company).

    Files are saved to `output_dir` with subfolders organized by alignment_type
    with names:
      {alignment_type}/{technology}-{company_name}-{scenario_geography}.png
      {alignment_type}/{technology}-{company_name}-{scenario_geography}-diff.png

    Parameters
    ----------
    late_sudden_trajectories : pd.DataFrame
        Columns:
          ['scenario_geography','company_id','sector','technology',
           'year','company_trajectory_latesudden','alignment_type']
    asset_level_df : pd.DataFrame
        Columns:
          ['company_id','sector','technology','asset_id','year',
           'asset_plate_latesudden']
    output_dir : str
        Directory in which to save the plots. Will be created if it doesn't exist.
    """
    # ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Helper to sanitise strings for use in file names (same logic as in
    # `plot_late_sudden_trajectories`)
    def _clean(name: str) -> str:  # local helper, keeps scope tight
        if pd.isna(name):
            return "Unknown"
        cleaned = re.sub(r'[<>:"/\\|?*]', "_", str(name))
        cleaned = re.sub(r"[^\w\s-]", "_", cleaned)
        cleaned = re.sub(r"\s+", "_", cleaned)
        return cleaned[:100]

    # Group by alignment type first to create subfolders
    if "alignment_type" not in late_sudden_trajectories.columns:
        print(
            "Warning: alignment_type column not found in staggered shock plotting. Using single folder."
        )
        alignment_groups = [("general", late_sudden_trajectories)]
    else:
        alignment_groups = list(late_sudden_trajectories.groupby("alignment_type"))

    for alignment_type, alignment_data in alignment_groups:
        # Create subfolder for this alignment type
        alignment_output_dir = os.path.join(output_dir, str(alignment_type))
        os.makedirs(alignment_output_dir, exist_ok=True)

        # identify all combos within this alignment type
        combos = (
            alignment_data[["scenario_geography", "company_id", "technology"]]
            .drop_duplicates()
            .sort_values(["scenario_geography", "company_id", "technology"])
        )

        for _, (geo, cid, tech) in combos.iterrows():
            # filter company series
            comp = alignment_data[
                (alignment_data["scenario_geography"] == geo)
                & (alignment_data["company_id"] == cid)
                & (alignment_data["technology"] == tech)
            ].sort_values("year")
            if comp.empty:
                continue

            # --- Prepare cleaned identifiers for file naming ---
            tech_clean = _clean(tech)
            geo_clean = _clean(geo)
            comp_name_raw = (
                comp["company_name"].iloc[0]
                if "company_name" in comp.columns
                else str(cid)
            )
            company_name_clean = _clean(comp_name_raw)

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
            plt.title(
                f"{tech} • {geo} • {cid}\nCompany vs. Asset trajectories\nAlignment Type: {alignment_type}"
            )
            plt.legend(bbox_to_anchor=(1.05, 1), loc="upper left")
            plt.tight_layout()

            # save first figure
            fname = f"{tech_clean}-{company_name_clean}-{geo_clean}.png"
            save_path = os.path.join(alignment_output_dir, fname)
            plt.savefig(save_path, dpi=300)
            print(f"Saved plot: {save_path}")
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
            plt.title(
                f"{tech} • {geo} • {cid}\nDifference Over Time\nAlignment Type: {alignment_type}"
            )
            plt.tight_layout()

            # save second figure
            fname_diff = f"{tech_clean}-{company_name_clean}-{geo_clean}-diff.png"
            save_diff_path = os.path.join(alignment_output_dir, fname_diff)
            plt.savefig(save_diff_path, dpi=300)
            print(f"Saved plot: {save_diff_path}")
            plt.close()

    print(f"Staggered shock plotting completed. All plots saved in: {output_dir}")
    alignment_dirs = [
        d for d in os.listdir(output_dir) if os.path.isdir(os.path.join(output_dir, d))
    ]
    print(f"Subfolders created for alignment types: {alignment_dirs}")
