"""Reporting stage: compliance-ready export tables.

Stage 8 of the ALTR pipeline. Writes the company, technology, top-asset and
methodology tables under ``data/08_reporting/tables/`` for downstream
regulatory reporting. See the ALTR Documentation, reporting section.
"""

import logging
from pathlib import Path
from typing import Dict

import pandas as pd

logger = logging.getLogger(__name__)


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
