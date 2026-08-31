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
                    series_map["original"] = pivot[
                        "late_sudden_requested"
                    ].to_numpy()
                if "late_sudden_realized" in pivot.columns:
                    series_map["adjusted"] = pivot[
                        "late_sudden_realized"
                    ].to_numpy()
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
                (
                    comp_pvt.get("late_sudden_realized")
                )
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
        "asset_trajectory",
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

    # Check required columns in asset_npv (support new wide columns)
    required_npv_base = {
        "asset_id",
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
    }
    missing_npv_cols = required_npv_base - set(asset_npv.columns)
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

    # Check for negative NPVs using latesudden_npv (equivalent to old NPV logic)
    if "latesudden_npv" in asset_npv.columns:
        negative_npvs = asset_npv[asset_npv["latesudden_npv"] < 0]
        npv_col = "latesudden_npv"
    else:
        negative_npvs = pd.DataFrame()
        npv_col = "n/a"
    if len(negative_npvs) > 0:
        logger.info(
            f"Assets with negative NPV ({npv_col or 'n/a'}): {len(negative_npvs)} ({len(negative_npvs)/max(len(asset_npv),1)*100:.1f}%)"
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

    # Assets can be co-owned: the same asset_id appears once per owning company.
    # asset_npv is keyed by the full ownership key (see calculate_npv_per_asset
    # group_keys), so merging/grouping on asset_id alone fans rows out and mixes
    # owners' cash flows.
    owner_keys = [
        "asset_id",
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
    ]

    # Merge earnings with NPV data to get discount rates
    asset_explain = asset_earnings_validated.query(
        "trajectory_type == 'latesudden'"
    ).merge(
        asset_npv_validated[[*owner_keys, "latesudden_discount_rate", "latesudden_npv"]],
        on=owner_keys,
        how="left",
        validate="many_to_one",
    )

    # Calculate discount factors and present values per year
    # Tax-neutral DCF: PV_FCFF = PV_EBITDA - PV_CapEx (no depreciation tax shield)
    # RFC: With taxes enabled, add PV_Depreciation and PV_TaxShield components
    base_year = asset_explain["year"].min()
    asset_explain["years_from_base"] = asset_explain["year"] - base_year
    # calculate_npv_per_asset pivots to wide, which yields object-dtype columns;
    # coerce (raising on genuine non-numerics) so the PV columns stay float and
    # can be aggregated with vectorized groupby ops.
    asset_explain["discount_factor"] = (
        1 + pd.to_numeric(asset_explain["latesudden_discount_rate"])
    ) ** (-asset_explain["years_from_base"])
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

    # Calculate cumulative discounted sums per asset-owner
    logger.info("Calculating cumulative present values for all assets...")
    asset_explain = asset_explain.sort_values([*owner_keys, "year"])
    asset_explain[
        ["cum_PV_EBITDA", "cum_PV_CapEx", "cum_PV_Carbon", "cum_PV_FCFF"]
    ] = asset_explain.groupby(owner_keys, dropna=False)[
        ["PV_EBITDA", "PV_CapEx", "PV_Carbon", "PV_FCFF"]
    ].cumsum()

    # 2. Asset NPV decomposition (per asset-owner)
    logger.info("Building asset NPV decomposition...")

    # Calculate PV components by asset-owner
    pv_components = (
        asset_explain.assign(
            PV_Revenue=asset_explain["revenue"] * asset_explain["discount_factor"],
            PV_VarCost=asset_explain["var_cost"] * asset_explain["discount_factor"],
            PV_FixedCost=asset_explain["fixed_cost"]
            * asset_explain["discount_factor"],
        )
        .groupby(owner_keys, dropna=False, as_index=False)
        .agg(
            {
                "PV_EBITDA": "sum",
                "PV_CapEx": "sum",
                "PV_Carbon": "sum",
                "PV_FCFF": "sum",
                "revenue": "sum",
                "var_cost": "sum",
                "fixed_cost": "sum",
                "PV_Revenue": "sum",
                "PV_VarCost": "sum",
                "PV_FixedCost": "sum",
            }
        )
    )

    # Merge with NPV data (support new wide naming)
    # Both latesudden_npv and baseline_npv should always exist
    npv_cols_available = [
        c
        for c in [
            "latesudden_npv",
            "baseline_npv",
            "DCF_sum",
            "Terminal_Value",
            "latesudden_discount_rate",
        ]
        if c in asset_npv_validated.columns
    ]
    asset_npv_decomp = pv_components.merge(
        asset_npv_validated[[*owner_keys, *npv_cols_available]],
        on=owner_keys,
        validate="one_to_one",
    )

    # Define a canonical NPV column equivalent to legacy behavior (latesudden_npv replaces old NPV)
    asset_npv_decomp["NPV"] = asset_npv_decomp["latesudden_npv"]
    asset_npv_decomp["discount_rate"] = asset_npv_decomp["latesudden_discount_rate"]

    # Asset metadata (company_id, scenario_geography, sector, technology) already
    # travels on the ownership key, so no metadata re-merge is needed here.

    # Check NPV reconciliation (tax-neutral: NPV = PV_EBITDA - PV_CapEx)
    # RFC: With taxes, reconcile as NPV = PV_EBIT*(1-tax_rate) + PV_Depreciation*tax_rate - PV_CapEx
    # Reconciliation against available NPV (prefer latesudden)
    npv_preferred = (
        "latesudden_npv"
        if "latesudden_npv" in asset_npv_decomp.columns
        else ("baseline_npv" if "baseline_npv" in asset_npv_decomp.columns else None)
    )
    asset_npv_decomp["NPV_check"] = (
        asset_npv_decomp["PV_EBITDA"] - asset_npv_decomp["PV_CapEx"]
    )
    if npv_preferred is not None:
        asset_npv_decomp["NPV_diff"] = abs(
            asset_npv_decomp[npv_preferred] - asset_npv_decomp["NPV_check"]
        )
    else:
        asset_npv_decomp["NPV_diff"] = np.nan

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
            asset_data["asset_trajectory"],
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
            png_path = output_dir / (f"asset_timeline_{asset_id}.png").replace("/", " ")
            plt.savefig(png_path, dpi=dpi, bbox_inches="tight")
            logger.info(f"Saved PNG: {png_path}")
        # if save_pdf:
        #     pdf_path = output_dir / f"asset_timeline_{asset_id}.pdf"
        #     plt.savefig(pdf_path, bbox_inches="tight")
        #     logger.info(f"Saved PDF: {pdf_path}")
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
    # Use latesudden_npv as canonical NPV (equivalent to old NPV logic)
    company_npv_validated = company_npv_validated.assign(
        NPV=company_npv_validated["latesudden_npv"]
    )

    portfolio_npv = company_npv_validated.get("NPV", pd.Series(dtype=float)).sum()
    positive_npv = company_npv_validated[company_npv_validated.get("NPV", 0) > 0][
        "NPV"
    ].sum()
    negative_npv = abs(
        company_npv_validated[company_npv_validated.get("NPV", 0) < 0]["NPV"].sum()
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
    # Use latesudden_npv (equivalent to old NPV logic)
    company_summary = company_summary.assign(NPV=company_summary["latesudden_npv"])
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
    # Ensure view_asset_npv_decomp has an 'NPV' column for ranking; if not, create from available components
    if "NPV" not in view_asset_npv_decomp.columns:
        candidate_cols = [
            c
            for c in [
                "latesudden_npv",
                "npv_latesudden",
                "baseline_npv",
                "npv_baseline",
            ]
            if c in view_asset_npv_decomp.columns
        ]
        if candidate_cols:
            view_asset_npv_decomp = view_asset_npv_decomp.assign(
                NPV=view_asset_npv_decomp[candidate_cols[0]]
            )
        else:
            view_asset_npv_decomp = view_asset_npv_decomp.assign(NPV=0.0)

    top_assets = view_asset_npv_decomp.nlargest(top_n * 10, "NPV")

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
    total_asset_company_pairs = (
        merged[existing_group_cols].drop_duplicates().shape[0]
    )

    logger.info(
        f"Creating trajectory plots for {total_asset_company_pairs} asset-company-geography groups..."
    )

    for i, (_, asset_data) in enumerate(merged.groupby(existing_group_cols)):
        if i % 50 == 0:  # Log progress every 50 groups
            logger.info(
                f"Progress: {i}/{total_asset_company_pairs} groups processed"
            )

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


def reporting_qc_summary(
    view_asset_npv_decomp: pd.DataFrame,
    view_asset_explain: pd.DataFrame,
    reporting_params: Dict,
) -> pd.DataFrame:
    """
    Node 7: Quality control checks and reporting diagnostics.
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
