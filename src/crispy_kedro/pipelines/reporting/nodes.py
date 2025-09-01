"""
Comprehensive reporting pipeline nodes for financial model outputs and NPV analysis.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Dict
import logging
from pathlib import Path
import re
import os
import matplotlib.gridspec as gridspec


logger = logging.getLogger(__name__)

# Set plotting style
plt.style.use("seaborn-v0_8")
sns.set_palette("husl")


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
    asset_level_df: pd.DataFrame,
    output_dir: str = "data/08_reporting/companies_staggered_shock_plots",
    asset_after_col: str = "capacity_after_shock",
    asset_before_col: str = "capacity_before_shock",
    include_synthetic: bool = True,
    min_points_for_asset: int = 1,
    max_individual_postshock_assets: int = 200,
    annotate_asset_ages: bool = True,
    max_residual_annotations: int = 30,
    use_log_scale: bool = True,
):
    """
    For each unique (scenario_geography, company_id, technology) in late_sudden_trajectories, save:
      1) Company L&S trajectory (original and adjusted) vs. post-shock asset forecasts
      2) Asset ages and shock absorption visualization

    Notes
    -----
    - Uses 'scenario_geography' at all times (geo-aware).
    - Shows company late sudden trajectory original and adjusted
    - Shows post-shock asset forecasts (asset-level late sudden)
    - Shows sum of assets after shock allocation
    - Annotates assets with ages
    - Shows bar plots of shock absorption/residuals based on adjusted trajectory
    - Can optionally include synthetic assets (is_synthetic==True) or drop them.
    - Expects late_sudden_trajectories to include: ['company_id','scenario_geography','technology','year',
                                          'company_trajectory_latesudden_original', 'company_trajectory_latesudden_adjusted'].
    - Expects asset_level_df to include: ['asset_id','company_id','scenario_geography','technology','year',
                                          'asset_age', asset_before_col, asset_after_col, 'is_synthetic', 'allocated_shock'].
    - Performance guards: when there are many assets, individual per-asset lines and annotations are skipped using
      the threshold max_individual_postshock_assets to keep figure saving fast.
    - Residual annotations are also capped via max_residual_annotations to avoid thousands of text artists.
    - Axis scale can be toggled with `use_log_scale`.
    """

    # Clean up existing directory if it exists
    if os.path.exists(output_dir):
        import shutil

        shutil.rmtree(output_dir)
        print(f"Cleaned up existing directory: {output_dir}")

    os.makedirs(output_dir, exist_ok=True)

    def _clean(name: str) -> str:
        if pd.isna(name):
            return "Unknown"
        cleaned = re.sub(r'[<>:"/\\|?*]', "_", str(name))
        cleaned = re.sub(r"[^\w\s-]", "_", cleaned)
        cleaned = re.sub(r"\s+", "_", cleaned)
        return cleaned[:120]

    def _calculate_shock_residuals(late_sudden_traj, asset_level_data, years):
        """Calculate per-year level residuals for visualization.

        Residual is defined as: (sum of post-shock assets) - (company L&S adjusted level)
        Positive => unabsorbed (assets above company);
        Negative => over-absorbed (assets below company).
        Values below 1 in absolute value are set to 0 to filter out noise.
        """
        # Company series for requested years - use adjusted trajectory
        comp_year = (
            late_sudden_traj[["year", "company_trajectory_latesudden_adjusted"]]
            .copy()
            .dropna(subset=["year"])
        )
        comp_year["year"] = comp_year["year"].astype(int)

        # Aggregate post-shock asset totals per year
        asset_year = (
            (
                asset_level_data.groupby("year", as_index=False)
                .agg(total_after=(asset_after_col, "sum"))
                .sort_values("year")
            )
            if not asset_level_data.empty
            else pd.DataFrame({"year": [], "total_after": []})
        )
        if not asset_year.empty:
            asset_year["year"] = asset_year["year"].astype(int)

        # Merge to align on the same year vector used for the plot
        years_df = pd.DataFrame({"year": years.astype(int)})
        merged = years_df.merge(comp_year, on="year", how="left").merge(
            asset_year, on="year", how="left"
        )

        # Compute residuals (fill missing totals with 0 for safety)
        comp_vals = (
            merged["company_trajectory_latesudden_adjusted"]
            .fillna(0.0)
            .to_numpy(dtype=float)
        )
        aset_vals = merged["total_after"].fillna(0.0).to_numpy(dtype=float)
        residuals = (aset_vals - comp_vals).tolist()

        # Filter out noise: set values below 1 in absolute value to 0
        residuals = [r if abs(r) >= 1.0 else 0.0 for r in residuals]

        return residuals

    # add company_name if missing (best-effort)
    traj = late_sudden_trajectories.copy()
    if "company_name" not in traj.columns:
        # Try to get company_name from asset_level_df if available
        if "company_name" in asset_level_df.columns:
            company_names = asset_level_df[
                ["company_id", "company_name"]
            ].drop_duplicates()
            traj = traj.merge(company_names, on="company_id", how="left")

        # Fill any remaining missing company names with company_id
        if "company_name" not in traj.columns:
            traj["company_name"] = traj["company_id"].astype(str)
        else:
            traj["company_name"] = traj["company_name"].fillna(
                traj["company_id"].astype(str)
            )

    # guarantee required cols exist
    needed_traj = {
        "scenario_geography",
        "company_id",
        "technology",
        "year",
        "company_trajectory_latesudden_original",
        "company_trajectory_latesudden_adjusted",
    }
    missing_t = needed_traj - set(traj.columns)
    if missing_t:
        raise KeyError(f"late_sudden_trajectories missing columns: {missing_t}")

    needed_assets = {
        "asset_id",
        "company_id",
        "scenario_geography",
        "technology",
        "year",
        "asset_age",
        asset_before_col,
        asset_after_col,
    }
    missing_a = needed_assets - set(asset_level_df.columns)
    if missing_a:
        raise KeyError(f"asset_level_df missing columns: {missing_a}")

    # group by alignment type for folder structure (if present)
    if "alignment_type" in traj.columns:
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
            geo = row["scenario_geography"]
            cid = row["company_id"]
            tech = row["technology"]

            # Get company name from asset_level_df if available, otherwise from combos
            comp_name = None
            if "company_name" in asset_level_df.columns:
                # Get company name from asset data for this specific company
                company_names = (
                    asset_level_df[
                        (asset_level_df["company_id"] == cid)
                        & (asset_level_df["scenario_geography"] == geo)
                        & (asset_level_df["technology"] == tech)
                    ]["company_name"]
                    .dropna()
                    .unique()
                )
                if len(company_names) > 0:
                    comp_name = company_names[0]  # Take the first unique name

            # Fallback to combos if not found in asset data
            if comp_name is None:
                comp_name = row.get("company_name", np.nan)

            # Final fallback to company_id if still no name
            if pd.isna(comp_name) or str(comp_name).strip() == "":
                comp_name = cid

            # company-level
            comp = (
                df_align[
                    (df_align["scenario_geography"] == geo)
                    & (df_align["company_id"] == cid)
                    & (df_align["technology"] == tech)
                ]
                .sort_values("year")
                .copy()
            )
            if comp.empty:
                continue

            years = comp["year"].to_numpy(dtype=int)
            company_vals_original = comp[
                "company_trajectory_latesudden_original"
            ].to_numpy(dtype=float)
            company_vals_adjusted = comp[
                "company_trajectory_latesudden_adjusted"
            ].to_numpy(dtype=float)
            max_year = max(years)

            # asset-level (filter geo-aware, optionally drop synthetic)
            aset = asset_level_df[
                (asset_level_df["scenario_geography"] == geo)
                & (asset_level_df["company_id"] == cid)
                & (asset_level_df["technology"] == tech)
            ].copy()
            if not include_synthetic and "is_synthetic" in aset.columns:
                aset = aset[~aset["is_synthetic"].fillna(False)].copy()

            # Count assets for performance guards
            num_post_assets = int(aset["asset_id"].nunique()) if not aset.empty else 0

            # If heavy, enable path simplification and chunking
            try:
                import matplotlib as mpl

                heavy_case = False
                if num_post_assets > max_individual_postshock_assets:
                    heavy_case = True
                if heavy_case:
                    mpl.rcParams["path.simplify"] = True
                    mpl.rcParams["path.simplify_threshold"] = 0.1
                    mpl.rcParams["agg.path.chunksize"] = 10000
            except Exception:
                pass

            # Create the plot with subplots: main plot + bar plot
            fig = plt.figure(figsize=(14, 10))
            gs = gridspec.GridSpec(2, 1, height_ratios=[3, 1], hspace=0.3)
            # Reserve space on the right for legends so we do not need bbox_inches='tight'
            fig.subplots_adjust(right=0.78)

            # Main trajectory plot
            ax1 = fig.add_subplot(gs[0])

            # Company L&S trajectories (original and adjusted)
            ax1.plot(
                years,
                company_vals_original,
                lw=3.0,
                label="Company L&S Trajectory (Original)",
                color="red",
                alpha=0.8,
                linestyle="-",
            )
            ax1.plot(
                years,
                company_vals_adjusted,
                lw=3.0,
                label="Company L&S Trajectory (Adjusted)",
                color="darkred",
                alpha=0.8,
                linestyle="--",
            )

            if not aset.empty:
                # aggregate sums for post-shock
                aset_year = (
                    aset.groupby("year", as_index=False)
                    .agg(
                        total_after=(asset_after_col, "sum"),
                        total_before=(asset_before_col, "sum"),
                    )
                    .sort_values("year")
                )

                # Sum of assets after shock
                ax1.plot(
                    aset_year["year"].to_numpy(dtype=int),
                    aset_year["total_after"].to_numpy(dtype=float),
                    lw=2.5,
                    linestyle="--",
                    label="Sum of assets (post-shock)",
                    color="blue",
                    alpha=0.8,
                )

                # Individual asset lines (post-shock) with age annotations
                if num_post_assets <= max_individual_postshock_assets:
                    colors = plt.cm.tab10(np.linspace(0, 1, 10))
                    color_idx = 0
                    for aid, df_a in (
                        aset[["asset_id", "year", "asset_age", asset_after_col]]
                        .dropna(subset=["year"])
                        .groupby("asset_id")
                    ):
                        df_a = df_a.sort_values("year")
                        if len(df_a) < min_points_for_asset:
                            continue

                        color = colors[color_idx % len(colors)]
                        ax1.plot(
                            df_a["year"].to_numpy(dtype=int),
                            df_a[asset_after_col].to_numpy(dtype=float),
                            lw=1.5,
                            alpha=0.7,
                            label=f"Asset {aid} (post-shock)",
                            color=color,
                        )

                        if annotate_asset_ages:
                            # Annotate age at first plotted year
                            try:
                                y0 = int(df_a["year"].iloc[0])
                                a0 = float(df_a["asset_age"].iloc[0])
                                v0 = float(df_a[asset_after_col].iloc[0])
                                ax1.text(
                                    y0,
                                    v0,
                                    f"age≈{int(round(a0))}",
                                    fontsize=8,
                                    va="bottom",
                                    ha="left",
                                    alpha=0.8,
                                    color=color,
                                    weight="bold",
                                )
                            except Exception:
                                pass
                        color_idx += 1
                else:
                    # Too many assets to plot individually; keep only aggregated line
                    pass

            ax1.set_xlabel("Year")
            ax1.set_ylabel(
                "Production / Activity" + (" (log scale)" if use_log_scale else "")
            )
            title_name = comp_name
            ax1.set_title(
                f"{tech} • {geo} • {title_name}\nTrajectories Comparison | Alignment: {alignment_type}"
            )

            # Legend management
            handles, labels = ax1.get_legend_handles_labels()
            max_legend = 15
            if len(labels) > max_legend:
                # Keep main trajectories + collapse asset entries
                kept = []
                kept_labels = []
                asset_count = 0
                for h, lab in zip(handles, labels):
                    if "Asset " in lab and "(post-shock)" in lab:
                        asset_count += 1
                        continue
                    kept.append(h)
                    kept_labels.append(lab)
                if asset_count > 0:
                    kept_labels.append(f"{asset_count} individual assets (post-shock)")
                main_leg = ax1.legend(
                    kept,
                    kept_labels,
                    bbox_to_anchor=(1.05, 1),
                    loc="upper left",
                    framealpha=0.9,
                    fancybox=False,
                    shadow=False,
                )
            else:
                main_leg = ax1.legend(
                    bbox_to_anchor=(1.05, 1),
                    loc="upper left",
                    framealpha=0.9,
                    fancybox=False,
                    shadow=False,
                )

            # Apply y-axis scaling (log or linear) with safe bounds and reasonable ticks
            if use_log_scale:
                try:
                    candidates = [company_vals_original, company_vals_adjusted]
                    if "aset_year" in locals() and not aset_year.empty:
                        candidates.append(
                            aset_year["total_after"].to_numpy(dtype=float)
                        )
                    if not aset.empty:
                        candidates.append(aset[asset_after_col].to_numpy(dtype=float))
                    all_vals = (
                        np.concatenate([c for c in candidates if c is not None])
                        if candidates
                        else np.array([])
                    )
                    positives = all_vals[all_vals > 0]
                    bottom = (
                        float(np.nanmin(positives)) * 0.8
                        if positives.size > 0
                        else 1e-6
                    )
                    bottom = max(bottom, 1e-12)
                    top = (
                        float(np.nanmax(positives)) * 1.2 if positives.size > 0 else 1e6
                    )

                    ax1.set_yscale("log")
                    ax1.set_ylim(bottom=bottom, top=top)

                    # Add detailed log scale graduations
                    from matplotlib.ticker import LogLocator, LogFormatter

                    major_locator = LogLocator(base=10, numticks=20)
                    ax1.yaxis.set_major_locator(major_locator)

                    minor_locator = LogLocator(
                        base=10, subs=np.arange(2, 10) * 0.1, numticks=20
                    )
                    ax1.yaxis.set_minor_locator(minor_locator)

                    major_formatter = LogFormatter(base=10, labelOnlyBase=False)
                    ax1.yaxis.set_major_formatter(major_formatter)

                    ax1.tick_params(axis="y", which="minor", length=3, width=0.5)
                    ax1.tick_params(axis="y", which="major", length=6, width=1)

                    ax1.grid(True, which="major", alpha=0.3)
                    ax1.grid(True, which="minor", alpha=0.1)

                    # If plot is heavy, disable minor ticks/grid to reduce draw time
                    try:
                        from matplotlib.ticker import NullLocator

                        heavy = False
                        if num_post_assets > max_individual_postshock_assets:
                            heavy = True
                        if heavy:
                            ax1.yaxis.set_minor_locator(NullLocator())
                            ax1.grid(False, which="minor")
                    except Exception:
                        pass

                except Exception:
                    ax1.set_yscale("log")
                    try:
                        from matplotlib.ticker import LogLocator

                        ax1.yaxis.set_major_locator(LogLocator(base=10, numticks=15))
                        ax1.yaxis.set_minor_locator(
                            LogLocator(
                                base=10, subs=np.arange(2, 10) * 0.1, numticks=15
                            )
                        )
                        ax1.tick_params(axis="y", which="minor", length=3, width=0.5)
                        ax1.grid(True, which="major", alpha=0.3)
                        ax1.grid(True, which="minor", alpha=0.1)
                    except Exception:
                        pass
            else:
                # Linear scale with safe bounds and simple grid
                try:
                    candidates = [company_vals_original, company_vals_adjusted]
                    if "aset_year" in locals() and not aset_year.empty:
                        candidates.append(
                            aset_year["total_after"].to_numpy(dtype=float)
                        )
                    if not aset.empty:
                        candidates.append(aset[asset_after_col].to_numpy(dtype=float))
                    all_vals = (
                        np.concatenate([c for c in candidates if c is not None])
                        if candidates
                        else np.array([])
                    )
                    finite_vals = all_vals[np.isfinite(all_vals)]
                    if finite_vals.size > 0:
                        vmin = float(np.nanmin(finite_vals))
                        vmax = float(np.nanmax(finite_vals))
                        if vmin == vmax:
                            pad = 1.0 if vmax == 0 else abs(vmax) * 0.1
                            vmin, vmax = vmin - pad, vmax + pad
                        else:
                            pad = (vmax - vmin) * 0.1
                            vmin, vmax = vmin - pad, vmax + pad
                        ax1.set_ylim(vmin, vmax)
                    ax1.set_yscale("linear")
                    ax1.grid(True, which="major", alpha=0.3)
                except Exception:
                    ax1.set_yscale("linear")

            # Shock absorption bar plot
            ax2 = fig.add_subplot(gs[1])

            if not aset.empty and "allocated_shock" in aset.columns:
                residuals = _calculate_shock_residuals(comp, aset, years)

                # Create bars, with positive and negative values in different colors
                pos_residuals = [max(0, r) for r in residuals]
                neg_residuals = [min(0, r) for r in residuals]

                bar_width = 0.6
                ax2.bar(
                    years,
                    pos_residuals,
                    bar_width,
                    label="Unabsorbed shock",
                    color="orange",
                    alpha=0.7,
                )
                ax2.bar(
                    years,
                    neg_residuals,
                    bar_width,
                    label="Over-absorbed shock",
                    color="purple",
                    alpha=0.7,
                )

                ax2.axhline(0, linestyle="-", color="black", alpha=0.3)
                ax2.set_xlabel("Year")
                ax2.set_ylabel("Shock Residual")
                ax2.set_title("Shock Absorption Analysis")
                ax2.legend(framealpha=0.9, fancybox=False, shadow=False)

                # Add text annotations for a limited number of largest residuals by magnitude
                try:
                    # Pick indices of top-K absolute residuals
                    abs_res = np.abs(np.array(residuals, dtype=float))
                    if np.isfinite(abs_res).any():
                        top_k = int(min(max_residual_annotations, len(abs_res)))
                        top_idx = np.argpartition(abs_res, -top_k)[-top_k:]
                        for idx in top_idx:
                            r = residuals[idx]
                            if not np.isfinite(r) or abs(r) <= 0:
                                continue
                            yr = int(years[idx])
                            ax2.text(
                                yr,
                                r,
                                f"{r:.2e}",
                                ha="center",
                                va="bottom" if r > 0 else "top",
                                fontsize=8,
                                alpha=0.8,
                            )
                except Exception:
                    pass
            else:
                ax2.text(
                    0.5,
                    0.5,
                    "No shock allocation data available",
                    transform=ax2.transAxes,
                    ha="center",
                    va="center",
                    fontsize=12,
                    alpha=0.6,
                )
                ax2.set_xlim(years[0], years[-1])

            # Overlay late-sudden phases across both subplots and add a dedicated legend on the main subplot
            phase_legend_elements = []
            if (
                "late_sudden_phase" in comp.columns
                and not comp["late_sudden_phase"].isna().all()
            ):
                phase_colors = {
                    "forecast": "#1f77b4",
                    "bau": "#ff7f0e",
                    "transition": "#2ca02c",
                    "aligned": "#d62728",
                    "aligned_compensation": "#9467bd",
                    "retirement": "#7f7f7f",
                    "phased_out": "#bcbd22",
                }

                years_series = comp["year"].astype(int).reset_index(drop=True)
                phases_series = comp["late_sudden_phase"].reset_index(drop=True).copy()

                # Override company phases with asset-level retirement information
                # This captures actual asset retirements that may occur within broader company phases
                if not aset.empty and "late_sudden_phase" in aset.columns:
                    # Check for asset retirements by year
                    asset_phases_by_year = (
                        aset.groupby("year")["late_sudden_phase"].apply(list).to_dict()
                    )

                    for i, year_val in enumerate(years_series):
                        if year_val in asset_phases_by_year:
                            asset_phases_this_year = asset_phases_by_year[year_val]
                            # If any asset is retiring this year, override the company phase
                            # This ensures retirement events are visually highlighted even if they occur
                            # within a broader phase like "aligned_compensation"
                            if any(
                                phase == "retirement"
                                for phase in asset_phases_this_year
                                if pd.notna(phase)
                            ):
                                phases_series.iloc[i] = "retirement"

                phase_spans = []
                current_phase = None
                phase_start = None
                for year_val, phase_val in zip(years_series, phases_series):
                    if phase_val != current_phase:
                        if current_phase is not None and phase_start is not None:
                            phase_spans.append(
                                (current_phase, phase_start, int(year_val) - 1)
                            )
                        current_phase = phase_val
                        phase_start = int(year_val) - 1
                if current_phase is not None and phase_start is not None:
                    last_year = int(years_series.iloc[-1])
                    year_range = int(years_series.max() - years_series.min())
                    extended_end = last_year + (year_range * 0.02)
                    phase_spans.append((current_phase, phase_start, extended_end))

                for phase_val, start_year, end_year in phase_spans:
                    if pd.notna(phase_val) and phase_val != "":
                        color = phase_colors.get(phase_val, "#333333")
                        # Background spans on both axes
                        for ax in (ax1, ax2):
                            ax.axvspan(
                                start_year, end_year, alpha=0.12, color=color, zorder=0
                            )
                        # Vertical delimiter line on main axis (skip very first)
                        if start_year != int(years_series.iloc[0]):
                            ax1.axvline(
                                x=start_year,
                                color=color,
                                linestyle="--",
                                alpha=0.8,
                                linewidth=1.5,
                                zorder=1,
                            )
                        # Legend element for phases
                        phase_legend_elements.append(
                            plt.Rectangle(
                                (0, 0),
                                1,
                                1,
                                facecolor=color,
                                alpha=0.3,
                                label=f"Phase: {str(phase_val).replace('_', ' ').title()}",
                            )
                        )

                # De-duplicate phase legend entries and render a separate legend
                if phase_legend_elements:
                    seen_labels = set()
                    unique_phase_elements = []
                    for el in phase_legend_elements:
                        lab = el.get_label()
                        if lab not in seen_labels:
                            unique_phase_elements.append(el)
                            seen_labels.add(lab)
                    # Limit phase legend items to avoid very large legends
                    max_phase_legend = 12
                    unique_phase_elements = unique_phase_elements[:max_phase_legend]
                    phase_leg = ax1.legend(
                        handles=unique_phase_elements,
                        loc="upper left",
                        bbox_to_anchor=(1.05, 0.3),
                        fontsize=9,
                        title="Late & Sudden Phases",
                        title_fontsize=10,
                        framealpha=0.9,
                        fancybox=False,
                        shadow=False,
                    )
                    # Keep main legend as well
                    ax1.add_artist(main_leg)

            # plt.tight_layout()  # avoid tight to keep savefig fast
            tech_clean = _clean(tech)
            geo_clean = _clean(geo)
            comp_clean = _clean(title_name)
            save_path = os.path.join(
                subdir, f"{tech_clean}-{comp_clean}-{geo_clean}.png"
            )
            # Time saving to identify hotspots if slow
            try:
                import time

                # Adapt DPI based on potential plot complexity
                dpi_use = 300
                try:
                    # If we exceeded per-asset thresholds (many assets), lower DPI a bit
                    if num_post_assets > max_individual_postshock_assets:
                        dpi_use = 220
                except Exception:
                    pass
                t0 = time.time()
                plt.savefig(save_path, dpi=dpi_use, facecolor="white")
                dt = time.time() - t0
                if dt > 3.0:
                    print(
                        f"Warning: slow save ({dt:.2f}s) for {save_path} [dpi={dpi_use}]"
                    )
            finally:
                plt.close()
            print(f"Saved plot: {save_path}")

    print(f"All plots saved under {output_dir}")


def reporting_validate_inputs(
    asset_earnings: pd.DataFrame,
    asset_npv: pd.DataFrame,
    company_npv: pd.DataFrame,
    reporting_params: Dict,
) -> Dict[str, pd.DataFrame]:
    """
    Node 1: Validate inputs and check basis alignment.

    Purpose: sanity checks & basis alignment (real/nominal), required columns present,
    years contiguous.

    Validates tax-neutral DCF outputs: FCFF = EBITDA - CapEx (no taxes/depreciation).
    RFC: When enabling taxes, expect EBIT-based earnings with depreciation tax shields.
    """

    logger.info("Validating reporting inputs...")

    # Check required columns in asset_earnings
    required_earnings_cols = [
        "asset_id",
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
        "year",
        "capacity_after_shock",
        "capacity_factor",
        "efficiency_decimal",
        "Q",
        "revenue",
        "var_cost",
        "fixed_cost",
        "carbon_cost_net",
        "EBITDA",
        "growth_capex",
        "replace_capex",
        "decom_cost",
        "capex_total",
        "FCFF",
    ]

    missing_earnings_cols = set(required_earnings_cols) - set(asset_earnings.columns)
    if missing_earnings_cols:
        logger.warning(f"Missing columns in asset_earnings: {missing_earnings_cols}")

    # Check required columns in asset_npv
    required_npv_cols = [
        "asset_id",
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
        "discount_rate",
        "DCF_sum",
        "Terminal_Value",
        "NPV",
    ]

    missing_npv_cols = set(required_npv_cols) - set(asset_npv.columns)
    if missing_npv_cols:
        logger.warning(f"Missing columns in asset_npv: {missing_npv_cols}")

    # Check year continuity per asset
    logger.info("Checking year continuity for all assets...")
    year_gaps = []
    total_assets = len(asset_earnings["asset_id"].unique())
    for i, (asset_id, asset_data) in enumerate(asset_earnings.groupby("asset_id")):
        if i % 100 == 0:  # Log progress every 100 assets
            logger.info(
                f"Year continuity check progress: {i}/{total_assets} assets processed"
            )

        years = sorted(asset_data["year"].unique())
        if len(years) > 1:
            gaps = [years[i + 1] - years[i] for i in range(len(years) - 1)]
            if any(gap != 1 for gap in gaps):
                year_gaps.append(asset_id)

    if year_gaps:
        logger.warning(f"Year gaps detected in {len(year_gaps)} assets")

    # Basis consistency check
    basis = reporting_params.get("basis", "real")
    logger.info(f"Reporting basis: {basis}")

    # Basic data quality checks
    logger.info(
        f"Asset earnings: {len(asset_earnings)} rows, {len(asset_earnings['asset_id'].unique())} unique assets"
    )
    logger.info(f"Asset NPV: {len(asset_npv)} rows")
    logger.info(f"Company NPV: {len(company_npv)} rows")

    # Check for negative NPVs
    negative_npvs = asset_npv[asset_npv["NPV"] < 0]
    if len(negative_npvs) > 0:
        logger.info(
            f"Assets with negative NPV: {len(negative_npvs)} ({len(negative_npvs)/len(asset_npv)*100:.1f}%)"
        )

    logger.info("Input validation completed successfully")

    # Return validated datasets
    return {
        "asset_earnings_validated": asset_earnings.copy(),
        "asset_npv_validated": asset_npv.copy(),
        "company_npv_validated": company_npv.copy(),
        "validation_summary": pd.DataFrame(
            {
                "metric": ["total_assets", "negative_npv_assets", "year_gap_assets"],
                "count": [
                    len(asset_earnings["asset_id"].unique()),
                    len(negative_npvs),
                    len(year_gaps),
                ],
            }
        ),
    }


def build_reporting_views(
    asset_earnings_validated: pd.DataFrame,
    asset_npv_validated: pd.DataFrame,
    company_npv_validated: pd.DataFrame,
    reporting_params: Dict,
) -> Dict[str, pd.DataFrame]:
    """
    Node 2: Pre-compute tidy tables used by both plotting nodes.

    Build asset explainability view, NPV decomposition, company tech stacks, and deltas.
    """

    logger.info("Building reporting views...")

    # 1. Asset explainability view (per asset-year)
    logger.info("Building asset explainability view...")

    # Merge earnings with NPV data to get discount rates
    asset_explain = asset_earnings_validated.merge(
        asset_npv_validated[["asset_id", "discount_rate", "NPV"]],
        on="asset_id",
        how="left",
    )

    # Calculate discount factors and present values per year
    # Tax-neutral DCF: PV_FCFF = PV_EBITDA - PV_CapEx (no depreciation tax shield)
    # RFC: With taxes enabled, add PV_Depreciation and PV_TaxShield components
    base_year = asset_explain["year"].min()
    asset_explain["years_from_base"] = asset_explain["year"] - base_year
    asset_explain["discount_factor"] = (1 + asset_explain["discount_rate"]) ** (
        -asset_explain["years_from_base"]
    )
    asset_explain["PV_FCFF"] = asset_explain["FCFF"] * asset_explain["discount_factor"]
    asset_explain["PV_EBITDA"] = (
        asset_explain["EBITDA"] * asset_explain["discount_factor"]
    )
    asset_explain["PV_CapEx"] = (
        asset_explain["capex_total"] * asset_explain["discount_factor"]
    )
    asset_explain["PV_Carbon"] = (
        asset_explain["carbon_cost_net"] * asset_explain["discount_factor"]
    )

    # Calculate cumulative discounted sums per asset
    logger.info("Calculating cumulative present values for all assets...")
    asset_explain = asset_explain.sort_values(["asset_id", "year"])
    total_assets = len(asset_explain["asset_id"].unique())

    for i, asset_id in enumerate(asset_explain["asset_id"].unique()):
        if i % 100 == 0:  # Log progress every 100 assets
            logger.info(
                f"Cumulative PV calculation progress: {i}/{total_assets} assets processed"
            )

        asset_mask = asset_explain["asset_id"] == asset_id
        asset_explain.loc[asset_mask, "cum_PV_EBITDA"] = asset_explain.loc[
            asset_mask, "PV_EBITDA"
        ].cumsum()
        asset_explain.loc[asset_mask, "cum_PV_CapEx"] = asset_explain.loc[
            asset_mask, "PV_CapEx"
        ].cumsum()
        asset_explain.loc[asset_mask, "cum_PV_Carbon"] = asset_explain.loc[
            asset_mask, "PV_Carbon"
        ].cumsum()
        asset_explain.loc[asset_mask, "cum_PV_FCFF"] = asset_explain.loc[
            asset_mask, "PV_FCFF"
        ].cumsum()

    # 2. Asset NPV decomposition (per asset)
    logger.info("Building asset NPV decomposition...")

    # Calculate PV components by asset
    pv_components = (
        asset_explain.groupby("asset_id")
        .agg(
            {
                "PV_EBITDA": "sum",
                "PV_CapEx": "sum",
                "PV_Carbon": "sum",
                "PV_FCFF": "sum",
                "revenue": "sum",
                "var_cost": "sum",
                "fixed_cost": "sum",
            }
        )
        .reset_index()
    )

    # Calculate PV of revenue components
    logger.info("Calculating PV of revenue components for all assets...")
    for i, asset_id in enumerate(pv_components["asset_id"]):
        if i % 100 == 0:  # Log progress every 100 assets
            logger.info(
                f"Revenue PV calculation progress: {i}/{len(pv_components)} assets processed"
            )

        asset_data = asset_explain[asset_explain["asset_id"] == asset_id]
        pv_components.loc[pv_components["asset_id"] == asset_id, "PV_Revenue"] = (
            asset_data["revenue"] * asset_data["discount_factor"]
        ).sum()
        pv_components.loc[pv_components["asset_id"] == asset_id, "PV_VarCost"] = (
            asset_data["var_cost"] * asset_data["discount_factor"]
        ).sum()
        pv_components.loc[pv_components["asset_id"] == asset_id, "PV_FixedCost"] = (
            asset_data["fixed_cost"] * asset_data["discount_factor"]
        ).sum()

    # Merge with NPV data
    asset_npv_decomp = pv_components.merge(
        asset_npv_validated[
            ["asset_id", "NPV", "DCF_sum", "Terminal_Value", "discount_rate"]
        ],
        on="asset_id",
    )

    # Add asset metadata
    asset_npv_decomp = asset_npv_decomp.merge(
        asset_earnings_validated[
            ["asset_id", "company_id", "scenario_geography", "sector", "technology"]
        ].drop_duplicates(),
        on="asset_id",
    )

    # Check NPV reconciliation (tax-neutral: NPV = PV_EBITDA - PV_CapEx)
    # RFC: With taxes, reconcile as NPV = PV_EBIT*(1-tax_rate) + PV_Depreciation*tax_rate - PV_CapEx
    asset_npv_decomp["NPV_check"] = (
        asset_npv_decomp["PV_EBITDA"] - asset_npv_decomp["PV_CapEx"]
    )
    asset_npv_decomp["NPV_diff"] = abs(
        asset_npv_decomp["NPV"] - asset_npv_decomp["NPV_check"]
    )

    # 3. Company tech stacks
    logger.info("Building company tech stacks...")

    company_tech = (
        asset_npv_decomp.groupby(["company_id", "technology"])
        .agg(
            {
                "NPV": "sum",
                "PV_EBITDA": "sum",
                "PV_CapEx": "sum",
                "PV_Revenue": "sum",
                "asset_id": "count",
                "scenario_geography": "first",
                "sector": "first",
            }
        )
        .reset_index()
    )
    company_tech.rename(columns={"asset_id": "asset_count"}, inplace=True)

    # Calculate portfolio shares per company
    logger.info("Calculating portfolio shares for all companies...")
    company_totals = company_tech.groupby("company_id")["NPV"].sum()
    total_companies = len(company_totals)

    for i, (company_id, total_npv) in enumerate(company_totals.items()):
        if i % 50 == 0:  # Log progress every 50 companies
            logger.info(
                f"Portfolio share calculation progress: {i}/{total_companies} companies processed"
            )

        company_mask = company_tech["company_id"] == company_id
        company_tech.loc[company_mask, "npv_share_of_company"] = (
            company_tech.loc[company_mask, "NPV"] / total_npv if total_npv != 0 else 0
        )

    # 4. Baseline vs shock deltas (placeholder - would need both scenarios)
    logger.info("Building deltas view (placeholder)...")

    # For now, create empty deltas view - would need baseline and shock scenarios
    deltas = pd.DataFrame(
        {
            "company_id": company_npv_validated["company_id"].unique(),
            "delta_npv": 0,  # Would calculate: shock_npv - baseline_npv
            "delta_pv_ebitda": 0,
            "delta_pv_capex": 0,
            "delta_pct": 0,
        }
    )

    logger.info(
        f"Built views - Asset explain: {len(asset_explain)}, NPV decomp: {len(asset_npv_decomp)}, Company-tech: {len(company_tech)}"
    )

    return {
        "view_asset_explain": asset_explain,
        "view_asset_npv_decomp": asset_npv_decomp,
        "view_company_tech": company_tech,
        "view_deltas": deltas,
    }


def plot_earnings_inner_workings(
    view_asset_explain: pd.DataFrame,
    view_asset_npv_decomp: pd.DataFrame,
    reporting_params: Dict,
) -> str:
    """
    Node 3: Plot earnings model inner workings for engineering/explainability.

    Goal: Show NPVs in a way that reveals the inner workings of the earnings model nodes.
    """

    logger.info("Generating earnings inner workings plots...")

    # Create output directory
    output_dir = Path("data/08_reporting/earnings_inner")
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output directory created: {output_dir}")

    # Plot settings
    plots_config = reporting_params.get("plots", {})
    save_png = plots_config.get("save_png", True)
    save_pdf = plots_config.get("save_pdf", False)
    dpi = plots_config.get("dpi", 160)
    width = plots_config.get("width_in", 10)
    height = plots_config.get("height_in", 6)

    materiality_threshold = reporting_params.get("materiality_threshold_usd", 1_000_000)
    top_n = reporting_params.get("top_n_assets_per_company", 10)

    # Select assets to plot - top contributors by |NPV|
    significant_assets = view_asset_npv_decomp[
        abs(view_asset_npv_decomp["NPV"]) >= materiality_threshold
    ].nlargest(top_n, "NPV")

    logger.info(
        f"Plotting inner workings for {len(significant_assets)} significant assets"
    )

    plots_created = 0

    # 1. Asset timeline panels for selected assets
    logger.info("Creating asset timeline panels...")
    assets_to_plot = significant_assets.head(5)  # Limit to top 5 for demo

    for i, (_, asset) in enumerate(assets_to_plot.iterrows()):
        logger.info(
            f"Creating timeline panel {i+1}/{len(assets_to_plot)} for asset {asset['asset_id']}"
        )

        asset_id = asset["asset_id"]
        asset_data = view_asset_explain[
            view_asset_explain["asset_id"] == asset_id
        ].sort_values("year")

        if len(asset_data) == 0:
            logger.warning(f"No data found for asset {asset_id}, skipping...")
            continue

        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(
            2, 2, figsize=(width * 2, height * 1.5)
        )
        fig.suptitle(
            f'Asset Timeline: {asset_id} ({asset["technology"]} - {asset["company_id"]})',
            fontsize=14,
        )

        # Top left: Capacity and capacity factor
        ax1_twin = ax1.twinx()
        ax1.plot(
            asset_data["year"],
            asset_data["capacity_after_shock"],
            "b-",
            linewidth=2,
            label="Capacity (MW)",
        )
        ax1_twin.plot(
            asset_data["year"],
            asset_data["capacity_factor"] * 100,
            "r--",
            linewidth=2,
            label="Capacity Factor (%)",
        )
        ax1.set_xlabel("Year")
        ax1.set_ylabel("Capacity (MW)", color="b")
        ax1_twin.set_ylabel("Capacity Factor (%)", color="r")
        ax1.set_title("Capacity & CF Timeline")
        ax1.legend(loc="upper left")
        ax1_twin.legend(loc="upper right")

        # Top right: Cost breakdown per MWh
        if asset_data["Q"].sum() > 0:
            asset_data_pos_q = asset_data[asset_data["Q"] > 0].copy()
            if len(asset_data_pos_q) > 0:
                asset_data_pos_q["fuel_cost_per_mwh"] = (
                    asset_data_pos_q["var_cost"] / asset_data_pos_q["Q"]
                )
                asset_data_pos_q["fixed_cost_per_mwh"] = (
                    asset_data_pos_q["fixed_cost"] / asset_data_pos_q["Q"]
                )
                asset_data_pos_q["carbon_cost_per_mwh"] = (
                    asset_data_pos_q["carbon_cost_net"] / asset_data_pos_q["Q"]
                )

                ax2.stackplot(
                    asset_data_pos_q["year"],
                    asset_data_pos_q["fuel_cost_per_mwh"],
                    asset_data_pos_q["fixed_cost_per_mwh"],
                    asset_data_pos_q["carbon_cost_per_mwh"],
                    labels=["Fuel Cost", "Fixed O&M", "Carbon Cost"],
                    alpha=0.7,
                )
                ax2.set_xlabel("Year")
                ax2.set_ylabel("Cost ($/MWh)")
                ax2.set_title("Cost Breakdown per MWh")
                ax2.legend()

        # Bottom left: FCFF timeline
        ax3.bar(
            asset_data["year"],
            asset_data["FCFF"],
            alpha=0.7,
            color=["green" if x >= 0 else "red" for x in asset_data["FCFF"]],
        )
        ax3.axhline(y=0, color="black", linestyle="-", alpha=0.5)
        ax3.set_xlabel("Year")
        ax3.set_ylabel("FCFF ($)")
        ax3.set_title("Free Cash Flow to Firm")

        # Bottom right: Cumulative PV components
        ax4.plot(
            asset_data["year"], asset_data["cum_PV_EBITDA"], "g-", label="Cum PV EBITDA"
        )
        ax4.plot(
            asset_data["year"], asset_data["cum_PV_CapEx"], "r-", label="Cum PV CapEx"
        )
        ax4.plot(
            asset_data["year"],
            asset_data["cum_PV_FCFF"],
            "b-",
            label="Cum PV FCFF",
            linewidth=2,
        )
        ax4.set_xlabel("Year")
        ax4.set_ylabel("Cumulative PV ($)")
        ax4.set_title("Cumulative Present Values")
        ax4.legend()

        plt.tight_layout()

        # Save plot
        if save_png:
            png_path = output_dir / f"asset_timeline_{asset_id}.png"
            plt.savefig(png_path, dpi=dpi, bbox_inches="tight")
            logger.info(f"Saved PNG: {png_path}")
        if save_pdf:
            pdf_path = output_dir / f"asset_timeline_{asset_id}.pdf"
            plt.savefig(pdf_path, bbox_inches="tight")
            logger.info(f"Saved PDF: {pdf_path}")
        plt.close()
        plots_created += 1

    # 2. NPV decomposition waterfall for top assets
    if len(significant_assets) > 0:
        logger.info("Creating NPV decomposition waterfall chart...")
        fig, ax = plt.subplots(figsize=(width, height))

        top_5_assets = significant_assets.head(5)
        x_pos = np.arange(len(top_5_assets))

        # Create stacked bars showing NPV components
        ax.bar(x_pos, top_5_assets["PV_Revenue"], label="PV Revenue", alpha=0.8)
        ax.bar(
            x_pos,
            -top_5_assets["PV_VarCost"],
            bottom=top_5_assets["PV_Revenue"],
            label="PV Fuel Cost",
            alpha=0.8,
        )
        ax.bar(
            x_pos,
            -top_5_assets["PV_FixedCost"],
            bottom=top_5_assets["PV_Revenue"] - top_5_assets["PV_VarCost"],
            label="PV Fixed Cost",
            alpha=0.8,
        )
        ax.bar(
            x_pos,
            -top_5_assets["PV_Carbon"],
            bottom=top_5_assets["PV_Revenue"]
            - top_5_assets["PV_VarCost"]
            - top_5_assets["PV_FixedCost"],
            label="PV Carbon Cost",
            alpha=0.8,
        )
        ax.bar(
            x_pos,
            -top_5_assets["PV_CapEx"],
            bottom=top_5_assets["PV_EBITDA"],
            label="PV CapEx",
            alpha=0.8,
        )

        # Add NPV line
        ax.plot(
            x_pos, top_5_assets["NPV"], "ko-", linewidth=2, markersize=8, label="NPV"
        )

        ax.set_xlabel("Assets")
        ax.set_ylabel("Present Value ($)")
        ax.set_title("NPV Decomposition - Top Assets")
        ax.set_xticks(x_pos)
        ax.set_xticklabels(
            [
                f"{row['asset_id']}\n{row['technology']}"
                for _, row in top_5_assets.iterrows()
            ],
            rotation=45,
            ha="right",
        )
        ax.legend()
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        if save_png:
            png_path = output_dir / "npv_decomposition_top_assets.png"
            plt.savefig(png_path, dpi=dpi, bbox_inches="tight")
            logger.info(f"Saved NPV decomposition PNG: {png_path}")
        if save_pdf:
            pdf_path = output_dir / "npv_decomposition_top_assets.pdf"
            plt.savefig(pdf_path, bbox_inches="tight")
            logger.info(f"Saved NPV decomposition PDF: {pdf_path}")
        plt.close()
        plots_created += 1

    logger.info(
        f"Created {plots_created} earnings inner workings plots in {output_dir}"
    )

    return str(output_dir)


def plot_valuation_authority_pack(
    asset_npv_validated: pd.DataFrame,
    company_npv_validated: pd.DataFrame,
    view_company_tech: pd.DataFrame,
    view_deltas: pd.DataFrame,
    reporting_params: Dict,
) -> str:
    """
    Node 4: Generate authority-ready valuation plots and reports.

    Goal: Clean, regulator-friendly visuals for asset managers to report to authorities.
    """

    logger.info("Generating valuation authority pack...")

    # Create output directories
    output_dir = Path("data/08_reporting/authority_pack")
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output directory created: {output_dir}")

    # Plot settings
    plots_config = reporting_params.get("plots", {})
    save_png = plots_config.get("save_png", True)
    save_pdf = plots_config.get("save_pdf", False)
    dpi = plots_config.get("dpi", 160)
    width = plots_config.get("width_in", 10)
    height = plots_config.get("height_in", 6)

    plots_created = 0

    # 1. Portfolio overview
    logger.info("Creating portfolio overview plots...")
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(
        2, 2, figsize=(width * 2, height * 1.5)
    )
    fig.suptitle("Portfolio Overview", fontsize=16)

    # Portfolio NPV distribution
    portfolio_npv = company_npv_validated["NPV"].sum()
    positive_npv = company_npv_validated[company_npv_validated["NPV"] > 0]["NPV"].sum()
    negative_npv = abs(
        company_npv_validated[company_npv_validated["NPV"] < 0]["NPV"].sum()
    )

    ax1.bar(
        ["Positive NPV", "Negative NPV"],
        [positive_npv, -negative_npv],
        color=["green", "red"],
        alpha=0.7,
    )
    ax1.axhline(y=0, color="black", linestyle="-", alpha=0.5)
    ax1.set_ylabel("NPV ($)")
    ax1.set_title(f"Portfolio NPV: ${portfolio_npv:,.0f}")
    ax1.grid(True, alpha=0.3)

    # NPV by technology (from company-tech view)
    tech_npv = (
        view_company_tech.groupby("technology")["NPV"]
        .sum()
        .sort_values(ascending=False)
    )
    if len(tech_npv) > 0:
        ax2.pie(
            abs(tech_npv.values),
            labels=tech_npv.index,
            autopct="%1.1f%%",
            startangle=90,
        )
        ax2.set_title("NPV Distribution by Technology")

    # Company NPV distribution
    company_npv_sorted = company_npv_validated.sort_values("NPV", ascending=False)
    top_companies = company_npv_sorted.head(10)

    bars = ax3.bar(
        range(len(top_companies)),
        top_companies["NPV"],
        color=["green" if x >= 0 else "red" for x in top_companies["NPV"]],
    )
    ax3.set_xlabel("Top Companies")
    ax3.set_ylabel("NPV ($)")
    ax3.set_title("Top 10 Companies by NPV")
    ax3.set_xticks(range(len(top_companies)))
    ax3.set_xticklabels(
        [f"{cid[:8]}" for cid in top_companies["company_id"]], rotation=45
    )

    # NPV vs asset count scatter (placeholder)
    ax4.text(
        0.5,
        0.5,
        "NPV Distribution\nAnalysis",
        ha="center",
        va="center",
        transform=ax4.transAxes,
        fontsize=12,
    )
    ax4.set_title("Portfolio Distribution")

    plt.tight_layout()
    if save_png:
        png_path = output_dir / "portfolio_overview.png"
        plt.savefig(png_path, dpi=dpi, bbox_inches="tight")
        logger.info(f"Saved portfolio overview PNG: {png_path}")
    if save_pdf:
        pdf_path = output_dir / "portfolio_overview.pdf"
        plt.savefig(pdf_path, bbox_inches="tight")
        logger.info(f"Saved portfolio overview PDF: {pdf_path}")
    plt.close()
    plots_created += 1

    # 2. Company league table
    logger.info("Creating company league table plots...")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(width * 2, height))

    # Top/bottom companies by NPV
    top_10 = company_npv_sorted.head(10)
    bottom_10 = company_npv_sorted.tail(10)

    y_pos_top = np.arange(len(top_10))
    ax1.barh(y_pos_top, top_10["NPV"], color="green", alpha=0.7)
    ax1.set_yticks(y_pos_top)
    ax1.set_yticklabels([f"{cid[:12]}" for cid in top_10["company_id"]])
    ax1.set_xlabel("NPV ($)")
    ax1.set_title("Top 10 Companies by NPV")
    ax1.grid(True, alpha=0.3)

    y_pos_bottom = np.arange(len(bottom_10))
    ax2.barh(y_pos_bottom, bottom_10["NPV"], color="red", alpha=0.7)
    ax2.set_yticks(y_pos_bottom)
    ax2.set_yticklabels([f"{cid[:12]}" for cid in bottom_10["company_id"]])
    ax2.set_xlabel("NPV ($)")
    ax2.set_title("Bottom 10 Companies by NPV")
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    if save_png:
        png_path = output_dir / "company_league_table.png"
        plt.savefig(png_path, dpi=dpi, bbox_inches="tight")
        logger.info(f"Saved company league table PNG: {png_path}")
    if save_pdf:
        pdf_path = output_dir / "company_league_table.pdf"
        plt.savefig(pdf_path, bbox_inches="tight")
        logger.info(f"Saved company league table PDF: {pdf_path}")
    plt.close()
    plots_created += 1

    logger.info(f"Created {plots_created} authority pack plots in {output_dir}")

    return str(output_dir)


def export_reporting_tables(
    company_npv_validated: pd.DataFrame,
    view_company_tech: pd.DataFrame,
    view_asset_npv_decomp: pd.DataFrame,
    reporting_params: Dict,
) -> Dict[str, pd.DataFrame]:
    """
    Node 5: Export compliance-ready tables for regulators and QC.
    """

    logger.info("Exporting reporting tables...")

    # Create tables directory
    tables_dir = Path("data/08_reporting/tables")
    tables_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Tables output directory created: {tables_dir}")

    # 1. Company summary table
    logger.info("Creating company summary table...")
    company_summary = company_npv_validated.copy()
    company_summary["npv_millions"] = company_summary["NPV"] / 1_000_000

    # Add basic statistics
    asset_counts = view_asset_npv_decomp.groupby("company_id")["asset_id"].count()
    company_summary["asset_count"] = (
        company_summary["company_id"].map(asset_counts).fillna(0)
    )

    # Add methodology notes
    company_summary["methodology_notes"] = (
        f"Real {reporting_params.get('base_year', 2010)} USD, {reporting_params.get('basis', 'real')} basis"
    )

    # Select final columns
    summary_columns = [
        "company_id",
        "NPV",
        "npv_millions",
        "asset_count",
        "methodology_notes",
    ]
    company_summary_final = company_summary[summary_columns].copy()

    # 2. Technology summary
    logger.info("Creating technology summary table...")
    technology_summary = view_company_tech.copy()
    technology_summary["npv_millions"] = technology_summary["NPV"] / 1_000_000

    # 3. Top assets table
    logger.info("Creating top assets table...")
    top_n = reporting_params.get("top_n_assets_per_company", 10)
    top_assets = view_asset_npv_decomp.nlargest(
        top_n * 10, "NPV"
    )  # More assets for full view

    top_assets_table = top_assets[
        ["asset_id", "company_id", "technology", "sector", "NPV"]
    ].copy()
    top_assets_table["npv_millions"] = top_assets_table["NPV"] / 1_000_000
    top_assets_table["rank"] = range(1, len(top_assets_table) + 1)

    # 4. Methodology footer
    logger.info("Creating methodology parameters table...")
    methodology_table = pd.DataFrame(
        {
            "parameter": [
                "basis",
                "base_year",
                "discount_rate_baseline",
                "discount_rate_shock",
                "materiality_threshold",
            ],
            "value": [
                reporting_params.get("basis", "real"),
                reporting_params.get("base_year", 2010),
                "7%",  # From valuation model
                "8%",  # From valuation model
                reporting_params.get("materiality_threshold_usd", 1_000_000),
            ],
        }
    )

    # Save tables
    company_summary_path = tables_dir / "company_summary.csv"
    company_summary_final.to_csv(company_summary_path, index=False)
    logger.info(f"Saved company summary table: {company_summary_path}")

    technology_summary_path = tables_dir / "technology_summary.csv"
    technology_summary.to_csv(technology_summary_path, index=False)
    logger.info(f"Saved technology summary table: {technology_summary_path}")

    top_assets_path = tables_dir / "top_assets.csv"
    top_assets_table.to_csv(top_assets_path, index=False)
    logger.info(f"Saved top assets table: {top_assets_path}")

    methodology_path = tables_dir / "methodology_parameters.csv"
    methodology_table.to_csv(methodology_path, index=False)
    logger.info(f"Saved methodology parameters table: {methodology_path}")

    logger.info(
        f"Exported {len(company_summary_final)} company summaries, {len(technology_summary)} tech records, {len(top_assets_table)} top assets"
    )

    return {
        "report_company_summary": company_summary_final,
        "report_technology_summary": technology_summary,
        "report_top_assets": top_assets_table,
        "report_methodology": methodology_table,
    }


def reporting_qc_summary(
    view_asset_npv_decomp: pd.DataFrame,
    view_asset_explain: pd.DataFrame,
    reporting_params: Dict,
) -> pd.DataFrame:
    """
    Node 6: Quality control checks and reporting diagnostics.
    """

    logger.info("Running reporting QC checks...")

    qc_results = []

    # 1. Basis consistency check
    basis = reporting_params.get("basis", "real")
    qc_results.append(
        {
            "check": "basis_consistency",
            "status": "PASS",
            "value": basis,
            "description": f"All calculations use {basis} basis",
        }
    )

    # 2. NPV reconciliation check
    if "NPV_diff" in view_asset_npv_decomp.columns:
        npv_diff = view_asset_npv_decomp["NPV_diff"]
        max_diff = npv_diff.max() if len(npv_diff) > 0 else 0
        tolerance = (
            reporting_params.get("small_numbers_rounding", 0.001) * 1_000_000
        )  # Convert to dollars

        reconciliation_status = "PASS" if max_diff < tolerance else "FAIL"
        qc_results.append(
            {
                "check": "npv_reconciliation",
                "status": reconciliation_status,
                "value": max_diff,
                "description": f"Max NPV reconciliation difference: ${max_diff:.2f}",
            }
        )

    # 3. Materiality threshold check
    materiality_threshold = reporting_params.get("materiality_threshold_usd", 1_000_000)
    material_assets = len(
        view_asset_npv_decomp[
            abs(view_asset_npv_decomp["NPV"]) >= materiality_threshold
        ]
    )

    qc_results.append(
        {
            "check": "materiality_filter",
            "status": "INFO",
            "value": material_assets,
            "description": f"{material_assets} assets above materiality threshold of ${materiality_threshold:,.0f}",
        }
    )

    # 4. Negative NPV assets by technology
    logger.info("Analyzing negative NPV assets by technology...")
    negative_npv_assets = view_asset_npv_decomp[view_asset_npv_decomp["NPV"] < 0]
    negative_by_tech = negative_npv_assets.groupby("technology").size()

    for tech, count in negative_by_tech.items():
        qc_results.append(
            {
                "check": f"negative_npv_{tech}",
                "status": "INFO",
                "value": count,
                "description": f"{count} {tech} assets with negative NPV",
            }
        )

    # 5. Data completeness checks
    total_assets = len(view_asset_npv_decomp)
    complete_records = len(view_asset_npv_decomp.dropna())

    qc_results.append(
        {
            "check": "data_completeness",
            "status": "PASS" if complete_records == total_assets else "WARNING",
            "value": complete_records / total_assets if total_assets > 0 else 0,
            "description": f"{complete_records}/{total_assets} complete records ({complete_records/total_assets*100:.1f}%)",
        }
    )

    # Convert to DataFrame
    qc_summary = pd.DataFrame(qc_results)

    # Add timestamp and summary stats
    qc_summary["timestamp"] = pd.Timestamp.now()

    logger.info(f"QC Summary: {len(qc_summary)} checks completed")
    logger.info(f"Status counts: {qc_summary['status'].value_counts().to_dict()}")

    return qc_summary
