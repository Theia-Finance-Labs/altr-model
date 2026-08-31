"""Reporting stage: earnings, valuation and per-asset financial plots.

Stage 8 of the ALTR pipeline. Renders the engineering explainability pack, the
regulator-facing authority pack, and the per-asset financial component
trajectories built from the DCF outputs. See the ALTR Documentation, valuation
and reporting sections.
"""
# ruff: noqa: PLR0912, PLR0915 — long matplotlib routines, kept whole
# ruff: noqa: PLC0415, PLW2901 — deferred import and loop rebinds left as written
# ruff: noqa: F841 — unused locals kept; removing them is a code change (see handover notes)

import logging
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import _style  # noqa: F401  (applies the shared plotting style on import)

logger = logging.getLogger(__name__)


def plot_earnings_inner_workings(
    view_asset_explain: pd.DataFrame,
    view_asset_npv_decomp: pd.DataFrame,
    reporting_params: dict,
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
        # Slice by the full owner key: co-owned assets carry one row set per
        # owning company, and an asset_id-only slice would stack both owners'
        # series into one panel.
        owner_slice_keys = [
            k
            for k in ("asset_id", "company_id", "scenario_geography", "sector", "technology")
            if k in view_asset_explain.columns and k in asset.index
        ]
        slice_mask = pd.Series(True, index=view_asset_explain.index)
        for k in owner_slice_keys:
            slice_mask &= view_asset_explain[k] == asset[k]
        asset_data = view_asset_explain[slice_mask].sort_values("year")

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
    reporting_params: dict,
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


def plot_asset_financial_trajectories(
    yearly_npv_trajectories: pd.DataFrame,
    asset_level_staggered_shock_melted: pd.DataFrame,
    reporting_params: dict,
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

    # Merge in melted asset trajectories to bring company_name/asset_name and production series
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
    melted_use = asset_level_staggered_shock_melted[melted_cols].copy()
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
        merged[["asset_id", "company_id"]].drop_duplicates().shape[0]
    )

    logger.info(
        f"Creating trajectory plots for {total_asset_company_pairs} asset-company pairs..."
    )

    for i, ((asset_id, company_id), asset_data) in enumerate(
        merged.groupby(["asset_id", "company_id"])
    ):
        if i % 50 == 0:  # Log progress every 50 asset-company pairs
            logger.info(
                f"Progress: {i}/{total_asset_company_pairs} asset-company pairs processed"
            )

        # Get asset metadata
        first_row = asset_data.iloc[0]
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
