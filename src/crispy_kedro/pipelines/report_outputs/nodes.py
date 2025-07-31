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
    and company_trajectory_latesudden over time and saves them in organized folders.

    Parameters
    ----------
    late_sudden_trajectories : pd.DataFrame
        DataFrame containing trajectory data with columns:
        company_id, scenario_geography, technology, year,
        company_trajectory_target, company_trajectory_baseline, company_trajectory_latesudden
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

    # Group by company, technology, and geography
    group_cols = [
        "company_id",
        "company_name",
        "company_name_clean",
        "technology",
        "scenario_geography",
    ]

    # Create base directory
    base_dir = Path("data/08_reporting/companies_trajectories_plots")
    base_dir.mkdir(parents=True, exist_ok=True)

    # Plot for each group
    for group_keys, group in late_sudden_trajectories_with_company_name.groupby(
        group_cols
    ):
        # Extract values from the first row of the group instead of unpacking keys
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
        # Use the requested ordering: technology-company_name-geography
        filename = f"{tech_clean}-{company_name_clean}-{geo_clean}.png"
        filepath = base_dir / filename

        # Sort by year for plotting
        group_sorted = group.sort_values("year")

        # Check if we have the required trajectory columns
        required_cols = [
            "company_trajectory_target",
            "company_trajectory_baseline",
            "company_trajectory_latesudden",
        ]
        available_cols = [col for col in required_cols if col in group_sorted.columns]

        if not available_cols:
            print(
                f"Warning: No trajectory columns found for {company_name} - {technology} - {scenario_geography}"
            )
            continue

        # Create the plot
        plt.figure(figsize=(12, 8))

        years = group_sorted["year"]

        # Plot each available trajectory
        if "company_trajectory_target" in group_sorted.columns:
            target_data = group_sorted["company_trajectory_target"].dropna()
            if not target_data.empty:
                plt.plot(
                    years,
                    group_sorted["company_trajectory_target"],
                    label="Target Trajectory",
                    linewidth=2,
                    linestyle="--",
                    color="green",
                )

        if "company_trajectory_baseline" in group_sorted.columns:
            baseline_data = group_sorted["company_trajectory_baseline"].dropna()
            if not baseline_data.empty:
                plt.plot(
                    years,
                    group_sorted["company_trajectory_baseline"],
                    label="Baseline Trajectory",
                    linewidth=2,
                    linestyle="-.",
                    color="blue",
                )

        if "company_trajectory_latesudden" in group_sorted.columns:
            latesudden_data = group_sorted["company_trajectory_latesudden"].dropna()
            if not latesudden_data.empty:
                plt.plot(
                    years,
                    group_sorted["company_trajectory_latesudden"],
                    label="Late & Sudden Trajectory",
                    linewidth=2,
                    color="red",
                )

        # Customize the plot
        plt.xlabel("Year", fontsize=12)
        plt.ylabel("Production/Activity", fontsize=12)
        plt.title(
            f"{company_name}\n{technology} - {scenario_geography}",
            fontsize=14,
            fontweight="bold",
        )
        plt.legend(fontsize=10)
        plt.grid(True, alpha=0.3)

        # Format x-axis to show years nicely
        plt.xticks(rotation=45)

        # Adjust layout to prevent label cutoff
        plt.tight_layout()

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

    Files are saved to `output_dir` with names:
      {technology}-{scenario_geography}-{company_id}.png
      {technology}-{scenario_geography}-{company_id}-diff.png

    Parameters
    ----------
    late_sudden_trajectories : pd.DataFrame
        Columns:
          ['scenario_geography','company_id','sector','technology',
           'year','company_trajectory_latesudden']
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

    # identify all combos
    combos = (
        late_sudden_trajectories[["scenario_geography", "company_id", "technology"]]
        .drop_duplicates()
        .sort_values(["scenario_geography", "company_id", "technology"])
    )

    for _, (geo, cid, tech) in combos.iterrows():
        # filter company series
        comp = late_sudden_trajectories[
            (late_sudden_trajectories["scenario_geography"] == geo)
            & (late_sudden_trajectories["company_id"] == cid)
            & (late_sudden_trajectories["technology"] == tech)
        ].sort_values("year")
        if comp.empty:
            continue

        # --- Prepare cleaned identifiers for file naming ---
        tech_clean = _clean(tech)
        geo_clean = _clean(geo)
        comp_name_raw = (
            comp["company_name"].iloc[0] if "company_name" in comp.columns else str(cid)
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
        plt.title(f"{tech} • {geo} • {cid}\nCompany vs. Asset trajectories")
        plt.legend(bbox_to_anchor=(1.05, 1), loc="upper left")
        plt.tight_layout()

        # save first figure
        fname = f"{tech_clean}-{company_name_clean}-{geo_clean}.png"
        save_path = os.path.join(output_dir, fname)
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
        plt.title(f"{tech} • {geo} • {cid}\nDifference Over Time")
        plt.tight_layout()

        # save second figure
        fname_diff = f"{tech_clean}-{company_name_clean}-{geo_clean}-diff.png"
        save_diff_path = os.path.join(output_dir, fname_diff)
        plt.savefig(save_diff_path, dpi=300)
        print(f"Saved plot: {save_diff_path}")
        plt.close()
