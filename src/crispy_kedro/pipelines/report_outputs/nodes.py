"""
This is a boilerplate pipeline 'report_outputs'
generated using Kedro 0.19.12
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import re
import os
from pathlib import Path

import os
import re
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


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
    assets_forecasts: pd.DataFrame,
    asset_level_df: pd.DataFrame,
    output_dir: str = "data/08_reporting/companies_staggered_shock_plots",
    asset_after_col: str = "capacity_after_shock",
    asset_before_col: str = "capacity_before_shock",
    include_before_sum: bool = True,
    include_synthetic: bool = True,
    min_points_for_asset: int = 1,
    debug: bool = False,
):
    """
    For each unique (scenario_geography, company_id, technology) in late_sudden_trajectories, save:
      1) Company L&S trajectory vs. original asset forecasts vs. post-shock asset forecasts
      2) Asset ages and shock absorption visualization

    Notes
    -----
    - Uses 'scenario_geography' at all times (geo-aware).
    - Shows original asset forecasts extended to the end of the time period
    - Shows post-shock asset forecasts (asset-level late sudden)
    - Shows company total shock late sudden trajectory
    - Annotates assets with ages
    - Shows bar plots of shock absorption/residual
    - Can optionally include synthetic assets (is_synthetic==True) or drop them.
    - Expects asset_level_df to include: ['asset_id','company_id','scenario_geography','technology','year',
                                          'asset_age', asset_before_col, asset_after_col, 'is_synthetic', 'allocated_shock'].
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

    def _extend_original_forecasts(assets_forecasts, cid, geo, sector, tech, max_year):
        """Extend original asset forecasts to the end of the time period"""
        original_assets = assets_forecasts[
            (assets_forecasts["company_id"] == cid)
            & (assets_forecasts["scenario_geography"] == geo)
            & (assets_forecasts["sector"] == sector)
            & (assets_forecasts["technology"] == tech)
        ].copy()

        if original_assets.empty:
            return pd.DataFrame()

        # For each asset, extend capacity to max_year
        extended_list = []
        for asset_id, asset_data in original_assets.groupby("asset_id"):
            asset_data = asset_data.sort_values("year")
            last_capacity = asset_data["capacity"].iloc[-1]
            last_year = int(asset_data["year"].max())
            last_age = (
                asset_data["asset_age"].iloc[-1]
                if "asset_age" in asset_data.columns
                else 0
            )

            # Create extended years
            if last_year < max_year:
                extended_years = range(last_year + 1, int(max_year) + 1)
                for i, year in enumerate(extended_years):
                    extended_row = asset_data.iloc[-1].copy()
                    extended_row["year"] = year
                    extended_row["capacity"] = last_capacity  # Keep constant capacity
                    if "asset_age" in extended_row:
                        extended_row["asset_age"] = last_age + i + 1
                    extended_list.append(extended_row)

            # Add original data
            extended_list.extend([row for _, row in asset_data.iterrows()])

        if extended_list:
            return pd.DataFrame(extended_list).sort_values(["asset_id", "year"])
        return pd.DataFrame()

    def _calculate_shock_residuals(late_sudden_traj, asset_level_data, years):
        """Calculate shock residuals for bar plot visualization"""
        residuals = []

        for year in years:
            # Company shock for this year
            company_shock_data = late_sudden_traj[late_sudden_traj["year"] == year]
            if company_shock_data.empty:
                residuals.append(0.0)
                continue

            # Get company trajectory value and previous year to calculate shock
            company_val = company_shock_data["company_trajectory_latesudden"].iloc[0]
            prev_year_data = late_sudden_traj[late_sudden_traj["year"] == year - 1]
            if not prev_year_data.empty:
                prev_val = prev_year_data["company_trajectory_latesudden"].iloc[0]
                company_shock = company_val - prev_val
            else:
                company_shock = 0.0

            # Sum of allocated shock to assets for this year
            asset_year_data = asset_level_data[asset_level_data["year"] == year]
            if "allocated_shock" in asset_year_data.columns:
                allocated_shock = asset_year_data["allocated_shock"].sum()
            else:
                allocated_shock = 0.0

            # Residual = company shock - allocated shock
            residual = company_shock - allocated_shock
            residuals.append(residual)

        return residuals

    # add company_name if missing (best-effort)
    traj = late_sudden_trajectories.copy()
    if "company_name" not in traj.columns:
        traj = traj.merge(
            assets_forecasts[["company_id", "company_name"]].drop_duplicates(),
            on="company_id",
            how="left",
        )

    # guarantee required cols exist
    needed_traj = {
        "scenario_geography",
        "company_id",
        "technology",
        "year",
        "company_trajectory_latesudden",
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
            comp_name = row.get("company_name", np.nan)

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
            company_vals = comp["company_trajectory_latesudden"].to_numpy(dtype=float)
            max_year = max(years)

            # asset-level (filter geo-aware, optionally drop synthetic)
            aset = asset_level_df[
                (asset_level_df["scenario_geography"] == geo)
                & (asset_level_df["company_id"] == cid)
                & (asset_level_df["technology"] == tech)
            ].copy()
            if not include_synthetic and "is_synthetic" in aset.columns:
                aset = aset[~aset["is_synthetic"].fillna(False)].copy()

            # Get extended original forecasts
            orig_forecasts = _extend_original_forecasts(
                assets_forecasts,
                cid,
                geo,
                tech,
                tech,
                max_year,
            )

            # Create the plot with subplots: main plot + bar plot
            fig = plt.figure(figsize=(14, 10))
            gs = gridspec.GridSpec(2, 1, height_ratios=[3, 1], hspace=0.3)

            # Main trajectory plot
            ax1 = fig.add_subplot(gs[0])

            # Company L&S trajectory
            ax1.plot(
                years,
                company_vals,
                lw=3.0,
                label="Company L&S Trajectory",
                color="red",
                alpha=0.8,
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

            # Original asset forecasts
            if not orig_forecasts.empty:
                orig_year = (
                    orig_forecasts.groupby("year", as_index=False)
                    .agg(total_orig=("capacity", "sum"))
                    .sort_values("year")
                )

                ax1.plot(
                    orig_year["year"].to_numpy(dtype=int),
                    orig_year["total_orig"].to_numpy(dtype=float),
                    lw=2.0,
                    linestyle=":",
                    label="Sum of assets (original forecasts)",
                    color="green",
                    alpha=0.8,
                )

                # Individual original asset lines (lighter)
                for aid, df_orig in orig_forecasts.groupby("asset_id"):
                    df_orig = df_orig.sort_values("year")
                    if len(df_orig) < min_points_for_asset:
                        continue
                    ax1.plot(
                        df_orig["year"].to_numpy(dtype=int),
                        df_orig["capacity"].to_numpy(dtype=float),
                        lw=1.0,
                        alpha=0.4,
                        color="green",
                    )

            ax1.set_xlabel("Year")
            ax1.set_ylabel("Production / Capacity")
            title_name = comp_name if pd.notna(comp_name) else cid
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
                ax1.legend(
                    kept, kept_labels, bbox_to_anchor=(1.05, 1), loc="upper left"
                )
            else:
                ax1.legend(bbox_to_anchor=(1.05, 1), loc="upper left")

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
                ax2.legend()

                # Add text annotations for non-zero residuals
                for year, residual in zip(years, residuals):
                    if abs(residual) > 1e-6:  # Only annotate significant residuals
                        ax2.text(
                            year,
                            residual,
                            f"{residual:.2e}",
                            ha="center",
                            va="bottom" if residual > 0 else "top",
                            fontsize=8,
                            alpha=0.8,
                        )
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

            # plt.tight_layout()
            tech_clean = _clean(tech)
            geo_clean = _clean(geo)
            comp_clean = _clean(title_name)
            save_path = os.path.join(
                subdir, f"{tech_clean}-{comp_clean}-{geo_clean}.png"
            )
            plt.savefig(save_path, dpi=300, bbox_inches="tight")
            plt.close()
            print(f"Saved plot: {save_path}")

    print(f"All plots saved under {output_dir}")
