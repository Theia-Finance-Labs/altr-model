# outputs.py
import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Define base reporting directory and sub-folders.
REPORTING_DIR = "data/08_reporting"

ASSETS_BASELINE_TARGET_DIR = os.path.join(REPORTING_DIR, "assets", "baseline_target")
ASSETS_SHOCKS_COMPENSATED_DIR = os.path.join(
    REPORTING_DIR, "assets", "shocks", "compensated"
)
ASSETS_SHOCKS_SIMPLY_DIR = os.path.join(REPORTING_DIR, "assets", "shocks", "simply")
COMPANIES_NET_PROFITS_DIR = os.path.join(REPORTING_DIR, "companies", "net_profits")

# Ensure all sub-folders exist.
for folder in [
    ASSETS_BASELINE_TARGET_DIR,
    ASSETS_SHOCKS_COMPENSATED_DIR,
    ASSETS_SHOCKS_SIMPLY_DIR,
    COMPANIES_NET_PROFITS_DIR,
]:
    os.makedirs(folder, exist_ok=True)


def plot_assets_baseline_target(
    traj_assets_baseline_clean: pd.DataFrame, traj_assets_target_clean: pd.DataFrame
) -> dict:
    """
    For each asset_id, create a single plot that overlays the baseline and target trajectories
    for all technologies.

    Expected inputs:
      - traj_assets_baseline_clean: DataFrame with columns:
          asset_id, sector, technology, year, asset_trajectory_baseline
      - traj_assets_target_clean: DataFrame with columns:
          asset_id, sector, technology, year, asset_trajectory_target

    Each technology's baseline trajectory is plotted with a solid line (marker "o") and
    target trajectory with a dashed line (marker "x"). The legend shows "Tech <name> Baseline"
    and "Tech <name> Target".

    The plot is saved as:
      {ASSETS_BASELINE_TARGET_DIR}/asset_{asset_id}_baseline_target.png

    Returns:
      A dictionary mapping each asset_id to its saved file path.
    """
    file_paths = {}
    asset_ids = sorted(
        set(traj_assets_baseline_clean["asset_id"].unique()).union(
            traj_assets_target_clean["asset_id"].unique()
        )
    )

    for asset in asset_ids:
        fig, ax = plt.subplots(figsize=(8, 6))
        baseline_data = traj_assets_baseline_clean[
            traj_assets_baseline_clean["asset_id"] == asset
        ]
        target_data = traj_assets_target_clean[
            traj_assets_target_clean["asset_id"] == asset
        ]
        # Determine unique technologies for this asset.
        techs = sorted(
            set(baseline_data["technology"].unique()).union(
                target_data["technology"].unique()
            )
        )
        # Plot each technology.
        for tech in techs:
            bdata = baseline_data[baseline_data["technology"] == tech]
            tdata = target_data[target_data["technology"] == tech]
            if not bdata.empty:
                ax.plot(
                    bdata["year"],
                    bdata["asset_trajectory_baseline"],
                    linestyle="-",
                    marker="o",
                    label=f"{tech} Baseline",
                )
            if not tdata.empty:
                ax.plot(
                    tdata["year"],
                    tdata["asset_trajectory_target"],
                    linestyle="--",
                    marker="x",
                    label=f"{tech} Target",
                )

        # Use sector info if available.
        if not baseline_data.empty:
            sector = baseline_data["sector"].iloc[0]
        elif not target_data.empty:
            sector = target_data["sector"].iloc[0]
        else:
            sector = ""
        ax.set_title(f"Asset {asset} - Sector: {sector}")
        ax.set_xlabel("Year")
        ax.set_ylabel("Trajectory Value")
        ax.legend()

        file_path = os.path.join(
            ASSETS_BASELINE_TARGET_DIR, f"asset_{asset}_baseline_target.png"
        )
        fig.tight_layout()
        fig.savefig(file_path)
        plt.close(fig)


def plot_assets_shocks(
    assets_compensated_shocked: pd.DataFrame, assets_simply_shocked: pd.DataFrame
) -> dict:
    """
    For each asset_id, create separate plots for compensated and simply shocked data, each showing
    all technologies in a single plot.

    Expected inputs:
      - assets_compensated_shocked: DataFrame with columns:
          asset_id, sector, technology, year, late_sudden
      - assets_simply_shocked: DataFrame with columns:
          asset_id, sector, technology, year, late_sudden

    In the compensated shock plot, trajectories for each technology are plotted with a solid line
    (marker "o"). In the simply shocked plot, they are plotted with a dashed line (marker "x").

    The plots are saved as:
      {ASSETS_SHOCKS_COMPENSATED_DIR}/asset_{asset_id}_compensated_shock.png
      {ASSETS_SHOCKS_SIMPLY_DIR}/asset_{asset_id}_simply_shock.png

    Returns:
      A dictionary with keys "compensated" and "simply", each mapping asset_ids to their saved file path.
    """
    shock_file_paths = {"compensated": {}, "simply": {}}

    # Compensated shock plots.
    for asset, group in assets_compensated_shocked.groupby("asset_id"):
        fig, ax = plt.subplots(figsize=(8, 6))
        techs = sorted(group["technology"].unique())
        for tech in techs:
            tech_grp = group[group["technology"] == tech]
            ax.plot(
                tech_grp["year"],
                tech_grp["late_sudden"],
                linestyle="-",
                marker="o",
                label=f"{tech}",
            )
        sector = group["sector"].iloc[0] if not group.empty else ""
        ax.set_title(f"Asset {asset} - Sector: {sector} - Compensated Shock")
        ax.set_xlabel("Year")
        ax.set_ylabel("Shock Value")
        ax.legend()

        file_path = os.path.join(
            ASSETS_SHOCKS_COMPENSATED_DIR, f"asset_{asset}_compensated_shock.png"
        )
        fig.tight_layout()
        fig.savefig(file_path)
        plt.close(fig)
        shock_file_paths["compensated"][asset] = file_path

    # Simply shock plots.
    for asset, group in assets_simply_shocked.groupby("asset_id"):
        fig, ax = plt.subplots(figsize=(8, 6))
        techs = sorted(group["technology"].unique())
        for tech in techs:
            tech_grp = group[group["technology"] == tech]
            ax.plot(
                tech_grp["year"],
                tech_grp["late_sudden"],
                linestyle="--",
                marker="x",
                label=f"{tech}",
            )
        sector = group["sector"].iloc[0] if not group.empty else ""
        ax.set_title(f"Asset {asset} - Sector: {sector} - Simply Shocked")
        ax.set_xlabel("Year")
        ax.set_ylabel("Shock Value")
        ax.legend()

        file_path = os.path.join(
            ASSETS_SHOCKS_SIMPLY_DIR, f"asset_{asset}_simply_shock.png"
        )
        fig.tight_layout()
        fig.savefig(file_path)
        plt.close(fig)


def merge_companies_net_profits(
    traj_companies_net_profits_baseline: pd.DataFrame,
    traj_companies_net_profits_shock: pd.DataFrame,
) -> pd.DataFrame:
    """
    Merge the baseline and shock net profits by company_id, sector, technology, and year.

    Expected columns in traj_companies_net_profits_baseline:
      - company_id, sector, technology, year,
        company_trajectory_baseline, net_profits_baseline, discounted_net_profit_baseline

    Expected columns in traj_companies_net_profits_shock:
      - company_id, sector, technology, year,
        company_trajectory_shock, net_profits_shock, discounted_net_profit_shock

    Returns:
      A merged DataFrame that can be saved via the Kedro catalog.
    """
    merged = pd.merge(
        traj_companies_net_profits_baseline,
        traj_companies_net_profits_shock,
        on=["company_id", "sector", "technology", "year"],
        suffixes=("_baseline", "_shock"),
    )
    return merged


def plot_companies_net_profits(merged_net_profits: pd.DataFrame) -> dict:
    """
    For each company_id, create a single plot that overlays baseline and shock net profits
    for all technologies.

    Expected columns in merged_net_profits:
      - company_id, technology, year, net_profits_baseline, net_profits_shock

    For each technology, the baseline line is plotted with a solid line (marker "o") and the shock
    line with a dashed line (marker "x").

    The plot is saved as:
      {COMPANIES_NET_PROFITS_DIR}/company_{company_id}_net_profits.png

    Returns:
      A dictionary mapping each company_id to its saved file path.
    """
    file_paths = {}
    for company, group in merged_net_profits.groupby("company_id"):
        fig, ax = plt.subplots(figsize=(8, 6))
        techs = sorted(group["technology"].unique())
        for tech in techs:
            tech_grp = group[group["technology"] == tech]
            if not tech_grp.empty:
                ax.plot(
                    tech_grp["year"],
                    tech_grp["net_profits_baseline"],
                    linestyle="-",
                    marker="o",
                    label=f"{tech} Baseline",
                )
                ax.plot(
                    tech_grp["year"],
                    tech_grp["net_profits_shock"],
                    linestyle="--",
                    marker="x",
                    label=f"{tech} Shock",
                )
        ax.set_title(f"Company {company} Net Profits")
        ax.set_xlabel("Year")
        ax.set_ylabel("Net Profit")
        ax.legend()

        file_path = os.path.join(
            COMPANIES_NET_PROFITS_DIR, f"company_{company}_net_profits.png"
        )
        fig.tight_layout()
        fig.savefig(file_path)
        plt.close(fig)


def plot_companies_npvs_kde(companies_npvs: pd.DataFrame) -> str:
    """
    Create a KDE distribution plot overlaying the NPVs for companies using both baseline and shock values.

    Expects the companies_npvs DataFrame to contain:
      - net_present_value_baseline
      - net_present_value_shock

    The plot is saved using the data catalog

    Returns:
      matplotlib fig
    """
    fig, ax = plt.subplots(figsize=(8, 6))
    sns.kdeplot(
        companies_npvs["net_present_value_baseline"], fill=True, label="Baseline", ax=ax
    )
    sns.kdeplot(
        companies_npvs["net_present_value_shock"], fill=True, label="Shock", ax=ax
    )
    ax.set_title("KDE Distribution of Companies NPVs")
    ax.set_xlabel("NPV")
    ax.set_ylabel("Density")
    ax.legend()
    fig.tight_layout()
    return fig
