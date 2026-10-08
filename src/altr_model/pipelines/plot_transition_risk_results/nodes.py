"""
Comprehensive reporting pipeline nodes for financial model outputs and NPV analysis.
"""

import logging
import os
import re
from pathlib import Path
from typing import Dict

import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

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

            # Build series from the canonical requested/realized long structure.
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
                if "late_sudden_requested" in pivot.columns:
                    series_map["original"] = pivot["late_sudden_requested"].to_numpy()
                if "late_sudden_realized" in pivot.columns:
                    series_map["adjusted"] = pivot["late_sudden_realized"].to_numpy()
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


def plot_staggered_shock(
    late_sudden_trajectories: pd.DataFrame,
    asset_level_df: pd.DataFrame,
    output_dir: str = "data/08_reporting/companies_staggered_shock_plots",
    include_synthetic: bool = True,
    min_points_for_asset: int = 1,
    max_individual_postshock_assets: int = 200,
    annotate_asset_ages: bool = True,
    max_residual_annotations: int = 30,
    use_log_scale: bool = True,
    show_shock_absorption: bool = False,
):
    """
    For each unique (scenario_geography, company_id, technology) in late_sudden_trajectories, save:
      1) Company L&S trajectory (original and optionally adjusted) vs. post-shock asset forecasts
      2) Asset ages and optionally shock absorption visualization

    Notes
    -----
    - Uses 'scenario_geography' at all times (geo-aware).
    - Shows company late sudden trajectory original (always) and adjusted (when show_shock_absorption=True)
    - Shows post-shock asset forecasts (asset-level late sudden)
    - Shows sum of assets after shock allocation
    - Annotates assets with ages
    - Shows bar plots of shock absorption/residuals based on adjusted trajectory (when show_shock_absorption=True)
    - Can optionally include synthetic assets (is_synthetic==True) or drop them.
    - Expects late_sudden_trajectories (melted) to include: ['company_id','company_name','scenario_geography','technology','year','trajectory_type','company_trajectory', 'late_sudden_phase','alignment_type'] with trajectory_type in { 'latesudden_original','latesudden_adjusted','latesudden' }.
    - Expects asset_level_df (melted) to include: ['asset_id','company_id','company_name','scenario_geography','technology','year','asset_age','is_synthetic','late_sudden_phase','alignment_type','trajectory_type','asset_trajectory'] with trajectory_type in { 'baseline','latesudden' }.
    - Performance guards: when there are many assets, individual per-asset lines and annotations are skipped using
      the threshold max_individual_postshock_assets to keep figure saving fast.
    - Residual annotations are also capped via max_residual_annotations to avoid thousands of text artists.
    - Axis scale can be toggled with `use_log_scale`.
    - Shock absorption analysis (adjusted trajectory and residual bar plot) can be toggled with `show_shock_absorption`.
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
        # The realized company series is defined by the post-allocation asset sum.
        comp_pvt = late_sudden_traj.pivot_table(
            index="year",
            columns="trajectory_type",
            values="company_trajectory",
            aggfunc="first",
        ).sort_index()
        comp_series = comp_pvt.get(
            "late_sudden_realized", pd.Series(dtype=float)
        ).copy()
        comp_year = comp_series.reset_index().rename(
            columns={0: "company_trajectory_latesudden_adjusted"}
        )
        comp_year.columns = ["year", "company_trajectory_latesudden_adjusted"]
        comp_year = comp_year.dropna(subset=["year"])
        comp_year["year"] = comp_year["year"].astype(int)

        # Aggregate post-shock asset totals per year from melted latesudden trajectories
        aset_ls = asset_level_data[
            asset_level_data["trajectory_type"] == "latesudden"
        ].copy()
        asset_year = (
            (
                aset_ls.groupby("year", as_index=False)
                .agg(total_after=("asset_trajectory", "sum"))
                .sort_values("year")
            )
            if not aset_ls.empty
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

    # guarantee required cols exist (melted)
    needed_traj = {
        "scenario_geography",
        "company_id",
        "technology",
        "year",
        "trajectory_type",
        "company_trajectory",
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
        "trajectory_type",
        "asset_trajectory",
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

            # Build company requested/realized series from the canonical table.
            comp_pvt = comp.pivot_table(
                index="year",
                columns="trajectory_type",
                values="company_trajectory",
                aggfunc="first",
            ).sort_index()
            years = comp_pvt.index.to_numpy(dtype=int)
            company_vals_original = (
                comp_pvt.get(
                    "late_sudden_requested",
                    pd.Series(index=comp_pvt.index, dtype=float),
                )
                .reindex(comp_pvt.index)
                .to_numpy(dtype=float)
            )
            company_vals_adjusted = (
                (comp_pvt.get("late_sudden_realized"))
                .reindex(comp_pvt.index)
                .to_numpy(dtype=float)
            )
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

            # Create the plot with subplots: main plot + (optionally) bar plot
            if show_shock_absorption:
                fig = plt.figure(figsize=(14, 10))
                gs = gridspec.GridSpec(2, 1, height_ratios=[3, 1], hspace=0.3)
            else:
                fig = plt.figure(figsize=(14, 8))
                gs = gridspec.GridSpec(1, 1)
            # Reserve space on the right for legends so we do not need bbox_inches='tight'
            fig.subplots_adjust(right=0.78)

            # Main trajectory plot
            ax1 = fig.add_subplot(gs[0])

            # Company L&S trajectories (original)
            ax1.plot(
                years,
                company_vals_original,
                lw=3.0,
                label="Company L&S Trajectory (Original)",
                color="red",
                alpha=0.8,
                linestyle="-",
            )

            # Company L&S trajectories (adjusted) - only shown when shock absorption is enabled
            if show_shock_absorption:
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
                # aggregate sums for post-shock from melted 'latesudden'
                aset_ls = aset[aset["trajectory_type"] == "latesudden"].copy()
                aset_year = (
                    aset_ls.groupby("year", as_index=False)
                    .agg(total_after=("asset_trajectory", "sum"))
                    .sort_values("year")
                )

                # Sum of assets after shock
                if not aset_year.empty:
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
                    colors = plt.cm.get_cmap("tab10")(np.linspace(0, 1, 10))
                    color_idx = 0
                    for aid, df_a in (
                        aset_ls[["asset_id", "year", "asset_age", "asset_trajectory"]]
                        .dropna(subset=["year"])
                        .groupby("asset_id")
                    ):
                        df_a = df_a.sort_values("year")
                        if len(df_a) < min_points_for_asset:
                            continue

                        color = colors[color_idx % len(colors)]
                        ax1.plot(
                            df_a["year"].to_numpy(dtype=int),
                            df_a["asset_trajectory"].to_numpy(dtype=float),
                            lw=1.5,
                            alpha=0.7,
                            label=f"Asset {aid} (post-shock)",
                            color=color,
                        )

                        if annotate_asset_ages:
                            try:
                                y0 = int(df_a["year"].iloc[0])
                                a0 = float(df_a["asset_age"].iloc[0])
                                v0 = float(df_a["asset_trajectory"].iloc[0])
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
                    candidates = [company_vals_original]
                    if show_shock_absorption:
                        candidates.append(company_vals_adjusted)
                    if "aset_year" in locals() and not aset_year.empty:
                        candidates.append(
                            aset_year["total_after"].to_numpy(dtype=float)
                        )
                    if "aset_ls" in locals() and not aset_ls.empty:
                        candidates.append(
                            aset_ls["asset_trajectory"].to_numpy(dtype=float)
                        )
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
                    from matplotlib.ticker import LogFormatter, LogLocator

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
                    candidates = [company_vals_original]
                    if show_shock_absorption:
                        candidates.append(company_vals_adjusted)
                    if "aset_year" in locals() and not aset_year.empty:
                        candidates.append(
                            aset_year["total_after"].to_numpy(dtype=float)
                        )
                    if "aset_ls" in locals() and not aset_ls.empty:
                        candidates.append(
                            aset_ls["asset_trajectory"].to_numpy(dtype=float)
                        )
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

            # Shock absorption bar plot - only shown when shock absorption is enabled
            if show_shock_absorption:
                ax2 = fig.add_subplot(gs[1])

                if not aset.empty:
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
                        # Background spans on axes (ax1 always, ax2 only if shock absorption is enabled)
                        axes_to_span = [ax1]
                        if show_shock_absorption:
                            axes_to_span.append(ax2)
                        for ax in axes_to_span:
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


def plot_asset_financial_trajectories(
    yearly_npv_trajectories: pd.DataFrame,
    asset_earnings: pd.DataFrame,
    reporting_params: Dict,
) -> str:
    """
    Plot financial component trajectories for each asset, comparing trajectory types.

    Creates grid plots showing revenue, var_cost, fixed_cost, carbon_cost_net,
    capex_total, EBITDA, and FCFF trajectories with different trajectory types
    overlaid for comparison.

    Parameters
    ----------
    yearly_npv_trajectories : pd.DataFrame
        DataFrame with yearly trajectories containing financial components
        and trajectory_type column
    reporting_params : Dict
        Reporting configuration parameters

    Returns
    -------
    str
        Path to output directory
    """

    logger.info("Creating asset financial trajectory plots...")

    # Create output directory
    output_dir = Path("data/08_reporting/asset_financial_trajectories")
    if output_dir.exists():
        import shutil

        shutil.rmtree(output_dir)
        logger.info(f"Cleaned up existing directory: {output_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output directory created: {output_dir}")

    # Financial components to plot
    financial_components = [
        "revenue",
        "var_cost",
        "fixed_cost",
        "carbon_cost_net",
        "capex_total",
        "EBITDA",
        "FCFF",
    ]

    # Merge in earnings metadata and the production series.
    melted_cols = [
        "asset_id",
        "company_id",
        "company_name",
        "asset_name",
        "scenario_geography",
        "technology",
        "year",
        "trajectory_type",
        "asset_trajectory",
    ]
    melted_use = asset_earnings[melted_cols].copy()
    merged = yearly_npv_trajectories.merge(
        melted_use,
        on=[
            "asset_id",
            "company_id",
            "scenario_geography",
            "technology",
            "year",
            "trajectory_type",
        ],
        how="left",
        suffixes=("", "_melted"),
    )

    # Check which components are available
    available_components = [
        comp for comp in financial_components if comp in merged.columns
    ]
    if not available_components:
        logger.warning("No financial components found in yearly_npv_trajectories")
        return str(output_dir)

    logger.info(
        f"Found {len(available_components)} financial components: {available_components}"
    )

    # Plot settings
    plots_config = reporting_params.get("plots", {})
    dpi = plots_config.get("dpi", 160)

    # Define colors and styles for trajectory types to handle overlapping lines
    trajectory_styles = {
        "baseline": {
            "color": "#1f77b4",  # Blue
            "linestyle": "-",  # Solid line
            "marker": "o",  # Circle marker
            "linewidth": 3.0,
            "alpha": 0.8,
            "markersize": 6,
            "markeredgewidth": 1,
            "markeredgecolor": "white",
        },
        "latesudden": {
            "color": "#ff7f0e",  # Orange
            "linestyle": "--",  # Dashed line
            "marker": "s",  # Square marker
            "linewidth": 2.5,
            "alpha": 0.9,
            "markersize": 5,
            "markeredgewidth": 1,
            "markeredgecolor": "white",
        },
        "target": {
            "color": "#2ca02c",  # Green
            "linestyle": "-.",  # Dash-dot line
            "marker": "^",  # Triangle marker
            "linewidth": 2.5,
            "alpha": 0.8,
            "markersize": 5,
            "markeredgewidth": 1,
            "markeredgecolor": "white",
        },
    }

    def clean_name_for_filename(name):
        """Clean name for use in filename"""
        if pd.isna(name):
            return "Unknown"
        cleaned = re.sub(r'[<>:"/\\|?*]', "_", str(name))
        cleaned = re.sub(r"[^\w\s-]", "_", cleaned)
        cleaned = re.sub(r"\s+", "_", cleaned)
        return cleaned[:100]  # Limit length

    # Group by asset and required metadata
    group_cols = [
        "asset_id",
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
    ]

    # Add company_name and asset_name if available
    if "company_name" in yearly_npv_trajectories.columns:
        group_cols.append("company_name")
    if "asset_name" in yearly_npv_trajectories.columns:
        group_cols.append("asset_name")

    # Filter group_cols to only include existing columns
    existing_group_cols = [
        col for col in group_cols if col in yearly_npv_trajectories.columns
    ]

    plots_created = 0
    total_asset_company_pairs = merged[existing_group_cols].drop_duplicates().shape[0]

    logger.info(
        f"Creating trajectory plots for {total_asset_company_pairs} asset-company-geography groups..."
    )

    for i, (_, asset_data) in enumerate(merged.groupby(existing_group_cols)):
        if i % 50 == 0:  # Log progress every 50 groups
            logger.info(f"Progress: {i}/{total_asset_company_pairs} groups processed")

        # Get asset metadata
        first_row = asset_data.iloc[0]
        asset_id = first_row.get("asset_id", "Unknown")
        company_id = first_row.get("company_id", "Unknown")
        company_name = first_row.get("company_name", company_id)
        asset_name = first_row.get("asset_name", asset_id)
        technology = first_row.get("technology", "Unknown")
        scenario_geography = first_row.get("scenario_geography", "Unknown")

        # Clean names for filename
        company_clean = clean_name_for_filename(company_name)
        asset_clean = clean_name_for_filename(asset_name)
        tech_clean = clean_name_for_filename(technology)
        geo_clean = clean_name_for_filename(scenario_geography)

        # Create filename
        filename = f"{company_clean}-{tech_clean}-{asset_clean}-{geo_clean}.png"
        filepath = output_dir / filename

        # Sort by year for plotting
        asset_data_sorted = asset_data.sort_values(["trajectory_type", "year"])

        # Create subplot grid (3 rows, 3 columns for 7 components + production)
        fig, axes = plt.subplots(3, 3, figsize=(18, 12))
        fig.suptitle(
            f"Financial Trajectories: {company_name}\n{technology} - {asset_name} - {scenario_geography}",
            fontsize=16,
            fontweight="bold",
        )

        # Flatten axes for easier indexing
        axes_flat = axes.flatten()

        # Define component categories for visual identification
        basic_financial = [
            "revenue",
            "var_cost",
            "fixed_cost",
            "carbon_cost_net",
            "capex_total",
        ]
        composed_financial = ["EBITDA", "FCFF"]
        production_components = ["asset_trajectory"]

        # Category colors for subplot backgrounds
        category_colors = {
            "basic": "#f0f8ff",  # Light blue background
            "composed": "#f0fff0",  # Light green background
            "production": "#fff5ee",  # Light orange background
        }

        # All components to plot (financial + production)
        all_components = available_components.copy()
        if "asset_trajectory" in asset_data_sorted.columns:
            all_components.append("asset_trajectory")

        # Plot each component
        for comp_idx, component in enumerate(all_components):
            if comp_idx >= len(axes_flat):
                break  # Safety check

            ax = axes_flat[comp_idx]

            # Determine component category and set background color
            if component in basic_financial:
                category = "basic"
                ax.set_facecolor(category_colors["basic"])
            elif component in composed_financial:
                category = "composed"
                ax.set_facecolor(category_colors["composed"])
            elif component == "asset_trajectory":
                category = "production"
                ax.set_facecolor(category_colors["production"])
            else:
                category = "other"

            # Plot each trajectory type
            for traj_type, traj_data in asset_data_sorted.groupby("trajectory_type"):
                if (
                    component in traj_data.columns
                    and not traj_data[component].isna().all()
                ):
                    # Get style for this trajectory type (default style for unknown types)
                    style = trajectory_styles.get(
                        traj_type,
                        {
                            "color": "#333333",
                            "linestyle": ":",
                            "marker": "x",
                            "linewidth": 2.0,
                            "alpha": 0.7,
                            "markersize": 4,
                            "markeredgewidth": 1,
                            "markeredgecolor": "white",
                        },
                    )

                    # Plot all data including zero values to show complete trajectories
                    plot_data = traj_data

                    if len(plot_data) > 0:
                        ax.plot(
                            plot_data["year"],
                            plot_data[component],
                            label=traj_type.replace("_", " ").title(),
                            **style,  # Unpack all style parameters
                        )

            # Customize subplot based on component type
            if component == "asset_trajectory":
                title = "Production (Asset Capacity)"
                ylabel = "MW or Activity Level"
            else:
                title = component.replace("_", " ").title()
                ylabel = (
                    f"{component} ($)" if component != "capacity_factor" else component
                )

            ax.set_title(title, fontsize=12, fontweight="bold")
            ax.set_xlabel("Year")
            ax.set_ylabel(ylabel)
            ax.grid(True, alpha=0.3)
            ax.legend(fontsize=9)

            # Format y-axis for currency values
            if component in [
                "revenue",
                "var_cost",
                "fixed_cost",
                "carbon_cost_net",
                "capex_total",
                "EBITDA",
                "FCFF",
            ]:
                ax.ticklabel_format(style="scientific", axis="y", scilimits=(0, 0))

        # Hide unused subplots
        for comp_idx in range(len(all_components), len(axes_flat)):
            axes_flat[comp_idx].set_visible(False)

        # Adjust layout
        plt.tight_layout()

        # Save plot
        try:
            plt.savefig(filepath, dpi=dpi, bbox_inches="tight", facecolor="white")
            plots_created += 1
        except Exception as e:
            logger.warning(f"Error saving plot for asset {asset_id}: {e}")

        # Close figure to free memory
        plt.close()

    logger.info(
        f"Created {plots_created} asset-company financial trajectory plots in {output_dir}"
    )

    return str(output_dir)
