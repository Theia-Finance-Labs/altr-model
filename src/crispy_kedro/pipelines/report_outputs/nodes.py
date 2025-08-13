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

from .logic import (
    clean_name_for_folder,
    draw_late_sudden_trajectories,
    get_phase_colors,
)


"""
This is a boilerplate pipeline 'report_outputs'
generated using Kedro 0.19.12
"""


def plot_companies_late_sudden_trajectories(
    companies_late_sudden_trajectories: pd.DataFrame,
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

    phase_colors = get_phase_colors()

    companies_late_sudden_trajectories["company_name_clean"] = (
        companies_late_sudden_trajectories["company_name"].apply(clean_name_for_folder)
    )

    base_dir = Path("data/08_reporting/companies_trajectories_plots")

    if base_dir.exists():
        import shutil

        shutil.rmtree(base_dir)
        print(f"Cleaned up existing directory: {base_dir}")

    base_dir.mkdir(parents=True, exist_ok=True)

    if "alignment_type" not in companies_late_sudden_trajectories.columns:
        print(
            "Warning: alignment_type column not found. Creating plots in single folder."
        )
        alignment_groups = [("general", companies_late_sudden_trajectories)]
    else:
        alignment_groups = list(
            companies_late_sudden_trajectories.groupby("alignment_type")
        )

    for alignment_type, alignment_data in alignment_groups:
        alignment_dir = base_dir / str(alignment_type)
        alignment_dir.mkdir(parents=True, exist_ok=True)

        group_cols = [
            "company_id",
            "company_name",
            "company_name_clean",
            "technology",
            "scenario_geography",
        ]

        for group_keys, group in alignment_data.groupby(group_cols):
            company_id = group["company_id"].iloc[0]
            company_name = group["company_name"].iloc[0]
            company_name_clean = group["company_name_clean"].iloc[0]
            technology = group["technology"].iloc[0]
            scenario_geography = group["scenario_geography"].iloc[0]

            if (
                pd.isna(company_name_clean)
                or pd.isna(technology)
                or pd.isna(scenario_geography)
            ):
                continue

            tech_clean = clean_name_for_folder(technology)
            geo_clean = clean_name_for_folder(scenario_geography)
            filename = f"{tech_clean}-{company_name_clean}-{geo_clean}.png"
            filepath = alignment_dir / filename

            group_sorted = group.sort_values("year")
            years = group_sorted["year"]

            fig, ax = plt.subplots(figsize=(16, 10))

            phase_legend_elements = draw_late_sudden_trajectories(
                ax=ax, years=years, df_sorted=group_sorted, phase_colors=phase_colors
            )

            ax.set_xlabel("Year", fontsize=12)
            ax.set_ylabel("Production/Activity", fontsize=12)
            ax.set_title(
                f"{company_name}\n{technology} - {scenario_geography}\nAlignment Type: {alignment_type}",
                fontsize=14,
                fontweight="bold",
            )

            main_legend = ax.legend(
                loc="center left",
                bbox_to_anchor=(1.02, 0.5),
                fontsize=10,
                framealpha=0.9,
                fancybox=True,
                shadow=True,
            )

            if "late_sudden_phase" in group_sorted.columns and phase_legend_elements:
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
                    bbox_to_anchor=(1.02, 0.3),
                    fontsize=9,
                    title="Late & Sudden Phases",
                    title_fontsize=10,
                    framealpha=0.9,
                    fancybox=True,
                    shadow=True,
                )
                ax.add_artist(main_legend)

            ax.grid(True, alpha=0.3)
            plt.xticks(rotation=45)
            plt.subplots_adjust(right=0.75)

            try:
                plt.savefig(filepath, dpi=300, bbox_inches="tight", facecolor="white")
                print(f"Saved plot: {filepath}")
            except Exception as e:
                print(
                    f"Error saving plot for {company_name} - {technology} - {scenario_geography}: {e}"
                )
            plt.close()

    print(f"Plotting completed. All plots saved in: {base_dir}")
    print(
        f"Subfolders created for alignment types: {[str(alignment_dir.name) for alignment_dir in base_dir.iterdir() if alignment_dir.is_dir()]}"
    )


def plot_assets_late_sudden_trajectories(
    assets_late_sudden_trajectories: pd.DataFrame,
) -> None:
    """
    Plot the late sudden trajectories for each asset (asset_id, asset_name) per technology and geography.

    Folder structure:
    - <base_dir>/<alignment_type>/<company_name>-<company_id>-<technology>-<scenario_geography>/<asset plots>

    Alignment is defined at the (company_id, technology, scenario_geography) level, so the
    same asset may appear under multiple company combos.

    Expects columns:
    - company_id, company_name, scenario_geography, technology, year,
      asset_id, asset_name
    - asset_trajectory_target, asset_trajectory_baseline, asset_trajectory_latesudden
    - late_sudden_phase (optional)
    - alignment_type (optional)
    """

    phase_colors = get_phase_colors()

    # Ensure names for folder safety
    assets_late_sudden_trajectories = assets_late_sudden_trajectories.copy()
    if "company_name" not in assets_late_sudden_trajectories.columns:
        assets_late_sudden_trajectories["company_name"] = (
            assets_late_sudden_trajectories["company_id"].astype(str)
        )

    assets_late_sudden_trajectories["company_name_clean"] = (
        assets_late_sudden_trajectories["company_name"].apply(clean_name_for_folder)
    )
    if "asset_name" in assets_late_sudden_trajectories.columns:
        assets_late_sudden_trajectories["asset_name_clean"] = (
            assets_late_sudden_trajectories["asset_name"].apply(clean_name_for_folder)
        )
    else:
        assets_late_sudden_trajectories["asset_name_clean"] = (
            assets_late_sudden_trajectories["asset_id"].astype(str)
        )

    base_dir = Path("data/08_reporting/assets_trajectories_plots")

    if base_dir.exists():
        import shutil

        shutil.rmtree(base_dir)
        print(f"Cleaned up existing directory: {base_dir}")

    base_dir.mkdir(parents=True, exist_ok=True)

    # Group by alignment type (top-level folder)
    if "alignment_type" in assets_late_sudden_trajectories.columns:
        align_groups = assets_late_sudden_trajectories.groupby("alignment_type")
    else:
        align_groups = [("general", assets_late_sudden_trajectories)]

    for alignment_type, df_align in align_groups:
        align_dir = base_dir / clean_name_for_folder(str(alignment_type))
        align_dir.mkdir(parents=True, exist_ok=True)

        # Group by company + tech + geo (alignment is defined at this level)
        combos = (
            df_align[
                [
                    "company_id",
                    "company_name",
                    "company_name_clean",
                    "technology",
                    "scenario_geography",
                ]
            ]
            .drop_duplicates()
            .sort_values(["company_id", "technology", "scenario_geography"])
        )

        for _, combo in combos.iterrows():
            cid = combo["company_id"]
            cname = combo["company_name"]
            cname_clean = combo["company_name_clean"]
            tech = combo["technology"]
            geo = combo["scenario_geography"]

            tech_clean = clean_name_for_folder(tech)
            geo_clean = clean_name_for_folder(geo)

            combo_dir = align_dir / f"{cname_clean}-{cid}-{geo_clean}"
            combo_dir.mkdir(parents=True, exist_ok=True)

            # Filter data for this combo
            df_combo = df_align[
                (df_align["company_id"] == cid)
                & (df_align["technology"] == tech)
                & (df_align["scenario_geography"] == geo)
            ]

            # Group by asset
            for _, group in df_combo.groupby(
                ["asset_id", "asset_name", "asset_name_clean"]
            ):
                asset_id = group["asset_id"].iloc[0]
                asset_name = group["asset_name"].iloc[0]
                asset_name_clean = group["asset_name_clean"].iloc[0]

                if pd.isna(asset_name_clean):
                    continue

                filename = f"{tech_clean}-{asset_name_clean}-{asset_id}.png"
                filepath = combo_dir / filename

                group_sorted = group.sort_values("year")
                years = group_sorted["year"]

                fig, ax = plt.subplots(figsize=(16, 10))

                phase_legend_elements = draw_late_sudden_trajectories(
                    ax=ax,
                    years=years,
                    df_sorted=group_sorted,
                    phase_colors=phase_colors,
                )

                ax.set_xlabel("Year", fontsize=12)
                ax.set_ylabel("Production/Activity", fontsize=12)
                ax.set_title(
                    f"{asset_name} (Asset {asset_id})\n{tech} - {geo} • Company: {cname} • Alignment: {alignment_type}",
                    fontsize=14,
                    fontweight="bold",
                )

                main_legend = ax.legend(
                    loc="center left",
                    bbox_to_anchor=(1.02, 0.5),
                    fontsize=10,
                    framealpha=0.9,
                    fancybox=True,
                    shadow=True,
                )

                if (
                    "late_sudden_phase" in group_sorted.columns
                    and phase_legend_elements
                ):
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
                        bbox_to_anchor=(1.02, 0.3),
                        fontsize=9,
                        title="Late & Sudden Phases",
                        title_fontsize=10,
                        framealpha=0.9,
                        fancybox=True,
                        shadow=True,
                    )
                    ax.add_artist(main_legend)

                ax.grid(True, alpha=0.3)
                plt.xticks(rotation=45)
                plt.subplots_adjust(right=0.75)

                try:
                    plt.savefig(
                        filepath, dpi=300, bbox_inches="tight", facecolor="white"
                    )
                    print(f"Saved plot: {filepath}")
                except Exception as e:
                    print(
                        f"Error saving plot for asset {asset_id} - {tech} - {geo}: {e}"
                    )
                plt.close()

    print(f"Assets plotting completed. All plots saved in: {base_dir}")


def plot_staggered_shock(
    late_sudden_trajectories: pd.DataFrame,
    assets_forecasts: pd.DataFrame,  # kept for pipeline signature, unused here
    asset_level_df: pd.DataFrame,
    output_dir: str = "data/08_reporting/companies_staggered_shock_plots",
    asset_after_col: str = "capacity_after_shock",
    asset_before_col: str = "capacity_before_shock",
    include_before_sum: bool = False,  # off by default now
    include_synthetic: bool = True,
    min_points_for_asset: int = 1,
    debug: bool = False,
):
    """
    Produce, for each (scenario_geography, company_id, sector?, technology):
      • Top plot: company late-sudden total vs. sum of asset late-sudden (post-stagger)
      • Bottom plot: residual = company - sum(assets)

    Assumptions / required columns:
      late_sudden_trajectories  → ['company_id','scenario_geography','technology','year','company_trajectory_latesudden']
                                   optionally: ['sector','company_name','alignment_type']
      asset_level_df            → ['asset_id','company_id','scenario_geography','technology','year',
                                   'asset_age', asset_before_col, asset_after_col, 'allocated_shock', 'is_synthetic']
                                   optionally: ['sector','late_sudden_phase']
    """

    # ---- helpers ----
    def _clean(name: str) -> str:
        if pd.isna(name):
            return "Unknown"
        cleaned = re.sub(r'[<>:"/\\|?*]', "_", str(name))
        cleaned = re.sub(r"[^\w\s-]", "_", cleaned)
        cleaned = re.sub(r"\s+", "_", cleaned)
        return cleaned[:120]

    def _present_keys(df, base_keys):
        return [k for k in base_keys if k in df.columns]

    # ---- checks ----
    need_comp = {
        "company_id",
        "scenario_geography",
        "technology",
        "year",
        "company_trajectory_latesudden",
    }
    miss_comp = need_comp - set(late_sudden_trajectories.columns)
    if miss_comp:
        raise KeyError(
            f"late_sudden_trajectories missing required columns: {miss_comp}"
        )

    need_asset = {
        "asset_id",
        "company_id",
        "scenario_geography",
        "technology",
        "year",
        "asset_age",
        asset_before_col,
        asset_after_col,
    }
    miss_asset = need_asset - set(asset_level_df.columns)
    if miss_asset:
        raise KeyError(f"asset_level_df missing required columns: {miss_asset}")

    # Add company_name best-effort if missing
    comp_df = late_sudden_trajectories.copy()
    if "company_name" not in comp_df.columns:
        if "company_name" in asset_level_df.columns:
            comp_df = comp_df.merge(
                asset_level_df[["company_id", "company_name"]].drop_duplicates(),
                on="company_id",
                how="left",
            )

    # Prepare output directory
    if os.path.exists(output_dir):
        import shutil

        shutil.rmtree(output_dir)
        print(f"Cleaned up existing directory: {output_dir}")
    os.makedirs(output_dir, exist_ok=True)

    # Grouping keys (sector is optional but recommended)
    base_keys = ["scenario_geography", "company_id", "sector", "technology"]
    comp_keys = _present_keys(comp_df, base_keys)
    aset_keys = _present_keys(asset_level_df, base_keys)
    if comp_keys != aset_keys:
        # Harmonize: use intersection to avoid mismatches
        keys = [k for k in base_keys if k in comp_keys and k in aset_keys]
    else:
        keys = comp_keys

    # For folder organization
    align_present = "alignment_type" in comp_df.columns
    align_groups = (
        comp_df.groupby("alignment_type") if align_present else [("general", comp_df)]
    )

    total_plots = 0
    for alignment_type, comp_align in align_groups:
        subdir = os.path.join(output_dir, str(alignment_type))
        os.makedirs(subdir, exist_ok=True)

        combos = comp_align[keys + ["company_name"]].drop_duplicates().sort_values(keys)

        for _, combo in combos.iterrows():
            filt = dict(combo[keys])
            comp_g = comp_align.copy()
            for k, v in filt.items():
                comp_g = comp_g[comp_g[k] == v]

            if comp_g.empty:
                continue

            # sort by year
            comp_g = comp_g.sort_values("year")
            years = comp_g["year"].to_numpy(dtype=int)
            company_vals = comp_g["company_trajectory_latesudden"].to_numpy(dtype=float)

            # asset slice (post-staggered)
            aset_g = asset_level_df.copy()
            for k, v in filt.items():
                aset_g = aset_g[aset_g[k] == v]

            if not include_synthetic and "is_synthetic" in aset_g.columns:
                aset_g = aset_g[~aset_g["is_synthetic"].fillna(False)]

            # Aggregate by year (post-stagger)
            aset_year = (
                aset_g.groupby("year", as_index=False)
                .agg(
                    total_after=(asset_after_col, "sum"),
                    total_before=(asset_before_col, "sum"),
                )
                .sort_values("year")
            )

            # Build aligned series over company years
            aset_after_series = (
                aset_year.set_index("year")["total_after"]
                .reindex(years, fill_value=0.0)
                .to_numpy(dtype=float)
            )
            aset_before_series = (
                aset_year.set_index("year")["total_before"]
                .reindex(years, fill_value=0.0)
                .to_numpy(dtype=float)
            )

            # Residual (company - assets_sum_after)
            residual = (company_vals - aset_after_series).tolist()

            # Plot
            import matplotlib.pyplot as plt
            import matplotlib.gridspec as gridspec

            fig = plt.figure(figsize=(12, 8))
            gs = gridspec.GridSpec(2, 1, height_ratios=[3, 1], hspace=0.28)

            ax1 = fig.add_subplot(gs[0])

            ax1.plot(years, company_vals, lw=3.0, label="Company L&S", alpha=0.9)
            ax1.plot(
                years,
                aset_after_series,
                lw=2.5,
                linestyle="--",
                label="Σ Assets (post-stagger)",
                alpha=0.9,
            )

            if include_before_sum:
                ax1.plot(
                    years,
                    aset_before_series,
                    lw=1.5,
                    linestyle=":",
                    label="Σ Assets (before)",
                    alpha=0.8,
                )

            # Optional: draw individual asset curves (post-stagger) lightly
            # (kept lightweight; disable by setting min_points_for_asset > large number)
            colors = plt.cm.tab20(np.linspace(0, 1, 20))
            color_idx = 0
            for aid, df_a in (
                aset_g[["asset_id", "year", "asset_age", asset_after_col]]
                .dropna(subset=["year"])
                .groupby("asset_id")
            ):
                df_a = df_a.sort_values("year")
                if len(df_a) < min_points_for_asset:
                    continue
                c = colors[color_idx % len(colors)]
                ax1.plot(
                    df_a["year"].to_numpy(dtype=int),
                    df_a[asset_after_col].to_numpy(dtype=float),
                    lw=1.0,
                    alpha=0.45,
                    color=c,
                )
                color_idx += 1

            # Titles & labels
            title_bits = []
            for k in ["technology", "scenario_geography"] + (
                ["sector"] if "sector" in keys else []
            ):
                if k in combo:
                    title_bits.append(str(combo[k]))
            title_name = combo.get("company_name", np.nan)
            title_company = (
                title_name
                if pd.notna(title_name)
                else combo.get("company_id", "Unknown")
            )

            ax1.set_title(" • ".join(title_bits) + f" • {title_company}")
            ax1.set_xlabel("Year")
            ax1.set_ylabel("Activity")
            ax1.legend(loc="upper left")

            # Residual panel
            ax2 = fig.add_subplot(gs[1])
            bar_width = 0.7
            pos = [max(0.0, r) for r in residual]
            neg = [min(0.0, r) for r in residual]
            ax2.bar(
                years,
                pos,
                bar_width,
                label="Company > Assets (under-allocation)",
                alpha=0.8,
            )
            ax2.bar(
                years,
                neg,
                bar_width,
                label="Company < Assets (over-allocation)",
                alpha=0.8,
            )
            ax2.axhline(0.0, color="black", lw=1.0, alpha=0.4)
            ax2.set_xlabel("Year")
            ax2.set_ylabel("Residual")
            ax2.legend(loc="upper left")
            if debug:
                # annotate non-negligible residuals
                for y, r in zip(years, residual):
                    if abs(r) > 1e-8:
                        ax2.text(
                            y,
                            r,
                            f"{r:.2e}",
                            ha="center",
                            va="bottom" if r > 0 else "top",
                            fontsize=8,
                            alpha=0.75,
                        )

            # Save
            tech = combo.get("technology", "tech")
            geo = combo.get("scenario_geography", "geo")
            sector = combo.get("sector", None)
            tech_clean = _clean(tech)
            geo_clean = _clean(geo)
            comp_clean = _clean(title_company)
            sector_part = f"-{_clean(sector)}" if sector is not None else ""
            save_path = os.path.join(
                subdir, f"{tech_clean}{sector_part}-{comp_clean}-{geo_clean}.png"
            )
            plt.savefig(save_path, dpi=300, bbox_inches="tight")
            plt.close()
            total_plots += 1

    print(f"Saved {total_plots} plot(s) under {output_dir}")
