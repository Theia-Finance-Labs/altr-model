"""
Post-batch analysis: compare full_ef vs differential_ef across all IAM providers.

Reads results from workspace/comparison_results/{provider}/{config}/ and computes:
1. Narrative consistency (brown negative, green positive) per provider × config
2. Isolated effect of full_ef vs differential_ef
3. Summary statistics across all providers
4. Gas-specific RC5 resolution check

Usage:
    python notebooks/analyze_fullef_comparison.py
    python notebooks/analyze_fullef_comparison.py --output workspace/fullef_analysis_report.md
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fullef_analysis")

# Technology classification
BROWN_TECHS = {"CoalCap - w/o CCS", "GasCap - w/o CCS", "OilCap - w/o CCS"}
GREEN_TECHS = {
    "SolarCap - PV",
    "SolarCap - CSP",
    "WindCap - Onshore",
    "WindCap - Offshore",
    "HydroCap",
}
AMBIGUOUS_TECHS = {"NuclearCap", "BiomassCap - w/o CCS"}

ALL_CONFIGS = [
    "vanilla",
    "adjusted",
    "iso_mcpr",
    "iso_stranding_tv",
    "iso_dynamic_ef",
    "iso_full_ef",
]


def load_results(results_dir: Path) -> pd.DataFrame:
    """Load all company_technology_npv.csv files into a single DataFrame."""
    rows = []
    for provider_dir in sorted(results_dir.iterdir()):
        if not provider_dir.is_dir():
            continue
        provider = provider_dir.name
        for config_dir in sorted(provider_dir.iterdir()):
            if not config_dir.is_dir():
                continue
            config = config_dir.name
            csv_path = config_dir / "company_technology_npv.csv"
            if not csv_path.exists():
                log.warning("Missing: %s/%s", provider, config)
                continue
            try:
                df = pd.read_csv(csv_path)
                df["provider"] = provider
                df["config"] = config
                rows.append(df)
            except Exception as e:
                log.error("Error reading %s: %s", csv_path, e)

    if not rows:
        raise RuntimeError(f"No results found in {results_dir}")

    combined = pd.concat(rows, ignore_index=True)
    log.info(
        "Loaded %d rows across %d provider-config combinations",
        len(combined),
        len(rows),
    )
    return combined


def classify_tech(tech: str) -> str:
    if tech in BROWN_TECHS:
        return "brown"
    if tech in GREEN_TECHS:
        return "green"
    return "ambiguous"


def compute_narrative_consistency(df: pd.DataFrame) -> pd.DataFrame:
    """Compute narrative consistency per provider × config.

    Returns a DataFrame with columns:
        provider, config, brown_total, brown_correct, green_total, green_correct,
        brown_pct, green_pct, overall_pct
    """
    df = df.copy()
    df["tech_class"] = df["technology"].apply(classify_tech)

    # Aggregate to tech × geography level (mean NPV change)
    combos = (
        df.groupby(["provider", "config", "technology", "scenario_geography", "tech_class"])
        .agg(mean_npv_change=("npv_change", "mean"), n_companies=("company_id", "count"))
        .reset_index()
    )

    results = []
    for (provider, config), group in combos.groupby(["provider", "config"]):
        brown = group[group["tech_class"] == "brown"]
        green = group[group["tech_class"] == "green"]

        brown_total = len(brown)
        brown_correct = (brown["mean_npv_change"] < 0).sum()
        green_total = len(green)
        green_correct = (green["mean_npv_change"] > 0).sum()

        total = brown_total + green_total
        correct = brown_correct + green_correct

        results.append(
            {
                "provider": provider,
                "config": config,
                "brown_total": brown_total,
                "brown_correct": int(brown_correct),
                "green_total": green_total,
                "green_correct": int(green_correct),
                "brown_pct": brown_correct / brown_total * 100 if brown_total > 0 else 0,
                "green_pct": green_correct / green_total * 100 if green_total > 0 else 0,
                "overall_total": total,
                "overall_correct": int(correct),
                "overall_pct": correct / total * 100 if total > 0 else 0,
            }
        )

    return pd.DataFrame(results)


def compute_gas_rc5_check(df: pd.DataFrame) -> pd.DataFrame:
    """Check RC5: is gas NPV negative across configs and geographies?"""
    gas = df[df["technology"] == "GasCap - w/o CCS"].copy()

    results = []
    for (provider, config, geo), group in gas.groupby(
        ["provider", "config", "scenario_geography"]
    ):
        mean_npv = group["npv_change"].mean()
        pct_neg = (group["npv_change"] < 0).mean() * 100
        results.append(
            {
                "provider": provider,
                "config": config,
                "geography": geo,
                "mean_npv_change": mean_npv,
                "pct_negative": pct_neg,
                "n_companies": len(group),
                "direction": "negative" if mean_npv < 0 else "POSITIVE",
            }
        )

    return pd.DataFrame(results)


def compute_fullef_delta(consistency: pd.DataFrame) -> pd.DataFrame:
    """Compare full_ef effect: iso_full_ef vs vanilla (isolated effect)
    and adjusted vs iso_dynamic_ef (full_ef contribution within adjusted).
    """
    rows = []
    for provider in consistency["provider"].unique():
        prov = consistency[consistency["provider"] == provider]

        vanilla_row = prov[prov["config"] == "vanilla"]
        iso_fullef_row = prov[prov["config"] == "iso_full_ef"]
        adjusted_row = prov[prov["config"] == "adjusted"]

        if not vanilla_row.empty and not iso_fullef_row.empty:
            v_pct = vanilla_row.iloc[0]["overall_pct"]
            f_pct = iso_fullef_row.iloc[0]["overall_pct"]
            rows.append(
                {
                    "provider": provider,
                    "comparison": "iso_full_ef vs vanilla",
                    "baseline_pct": v_pct,
                    "treatment_pct": f_pct,
                    "delta_pct": f_pct - v_pct,
                }
            )

        if not vanilla_row.empty and not adjusted_row.empty:
            v_pct = vanilla_row.iloc[0]["overall_pct"]
            a_pct = adjusted_row.iloc[0]["overall_pct"]
            rows.append(
                {
                    "provider": provider,
                    "comparison": "adjusted vs vanilla",
                    "baseline_pct": v_pct,
                    "treatment_pct": a_pct,
                    "delta_pct": a_pct - v_pct,
                }
            )

    return pd.DataFrame(rows)


def generate_report(
    consistency: pd.DataFrame,
    gas_check: pd.DataFrame,
    fullef_delta: pd.DataFrame,
    output_path: Path | None = None,
) -> str:
    """Generate a markdown report."""
    lines: list[str] = []
    lines.append("# Full EF Batch Run Analysis Report")
    lines.append("")
    lines.append(f"**Providers**: {consistency['provider'].nunique()}")
    lines.append(f"**Configs**: {consistency['config'].nunique()}")
    lines.append("")

    # 1. Narrative consistency summary — adjusted config
    lines.append("## 1. Narrative Consistency by Provider (adjusted config)")
    lines.append("")
    adj = consistency[consistency["config"] == "adjusted"].sort_values(
        "overall_pct", ascending=False
    )
    lines.append(
        "| Provider | Brown OK | Green OK | Overall | Brown % | Green % | Overall % |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for _, row in adj.iterrows():
        lines.append(
            f"| {row['provider']} | {row['brown_correct']}/{row['brown_total']} "
            f"| {row['green_correct']}/{row['green_total']} "
            f"| {row['overall_correct']}/{row['overall_total']} "
            f"| {row['brown_pct']:.0f}% | {row['green_pct']:.0f}% "
            f"| {row['overall_pct']:.0f}% |"
        )
    lines.append("")

    # 2. full_ef isolated effect
    lines.append("## 2. Full EF Isolated Effect (iso_full_ef vs vanilla)")
    lines.append("")
    iso_comp = fullef_delta[fullef_delta["comparison"] == "iso_full_ef vs vanilla"].sort_values(
        "delta_pct", ascending=False
    )
    lines.append("| Provider | Vanilla % | iso_full_ef % | Delta |")
    lines.append("|---|---|---|---|")
    for _, row in iso_comp.iterrows():
        sign = "+" if row["delta_pct"] > 0 else ""
        lines.append(
            f"| {row['provider']} | {row['baseline_pct']:.0f}% "
            f"| {row['treatment_pct']:.0f}% | {sign}{row['delta_pct']:.1f}% |"
        )
    lines.append("")

    # 3. Full adjusted effect
    lines.append("## 3. Full Adjusted Effect (adjusted vs vanilla)")
    lines.append("")
    adj_comp = fullef_delta[fullef_delta["comparison"] == "adjusted vs vanilla"].sort_values(
        "delta_pct", ascending=False
    )
    lines.append("| Provider | Vanilla % | Adjusted % | Delta |")
    lines.append("|---|---|---|---|")
    for _, row in adj_comp.iterrows():
        sign = "+" if row["delta_pct"] > 0 else ""
        lines.append(
            f"| {row['provider']} | {row['baseline_pct']:.0f}% "
            f"| {row['treatment_pct']:.0f}% | {sign}{row['delta_pct']:.1f}% |"
        )
    lines.append("")

    # 4. Config comparison across all providers
    lines.append("## 4. Config Comparison (mean across all providers)")
    lines.append("")
    config_summary = (
        consistency.groupby("config")
        .agg(
            mean_overall_pct=("overall_pct", "mean"),
            mean_brown_pct=("brown_pct", "mean"),
            mean_green_pct=("green_pct", "mean"),
            n_providers=("provider", "nunique"),
        )
        .reset_index()
        .sort_values("mean_overall_pct", ascending=False)
    )
    lines.append("| Config | Mean Overall % | Mean Brown % | Mean Green % | N Providers |")
    lines.append("|---|---|---|---|---|")
    for _, row in config_summary.iterrows():
        lines.append(
            f"| {row['config']} | {row['mean_overall_pct']:.1f}% "
            f"| {row['mean_brown_pct']:.1f}% | {row['mean_green_pct']:.1f}% "
            f"| {int(row['n_providers'])} |"
        )
    lines.append("")

    # 5. RC5 Gas check — adjusted config, positive geographies
    lines.append("## 5. RC5 Gas Check (adjusted config — positive NPV geographies)")
    lines.append("")
    gas_adj = gas_check[
        (gas_check["config"] == "adjusted") & (gas_check["direction"] == "POSITIVE")
    ].sort_values("mean_npv_change", ascending=False)

    if gas_adj.empty:
        lines.append("**No gas-positive geographies under adjusted config.** RC5 fully resolved.")
    else:
        lines.append(
            f"**{len(gas_adj)} gas-positive geographies remaining under adjusted config:**"
        )
        lines.append("")
        lines.append("| Provider | Geography | Mean NPV Change | % Negative | N |")
        lines.append("|---|---|---|---|---|")
        for _, row in gas_adj.iterrows():
            lines.append(
                f"| {row['provider']} | {row['geography']} "
                f"| {row['mean_npv_change']:+.4f} | {row['pct_negative']:.0f}% "
                f"| {int(row['n_companies'])} |"
            )
    lines.append("")

    report = "\n".join(lines)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report)
        log.info("Report written to %s", output_path)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze full_ef batch run results")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("workspace/comparison_results"),
        help="Directory containing batch run results",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("workspace/fullef_analysis_report.md"),
        help="Output path for the markdown report",
    )
    args = parser.parse_args()

    # Load all results
    df = load_results(args.results_dir)

    # Compute analyses
    consistency = compute_narrative_consistency(df)
    gas_check = compute_gas_rc5_check(df)
    fullef_delta = compute_fullef_delta(consistency)

    # Generate report
    report = generate_report(consistency, gas_check, fullef_delta, args.output)

    # Also print summary to stdout
    print(report)

    # Save raw data
    consistency.to_csv(args.results_dir / "narrative_consistency.csv", index=False)
    gas_check.to_csv(args.results_dir / "gas_rc5_check.csv", index=False)
    fullef_delta.to_csv(args.results_dir / "fullef_delta.csv", index=False)
    log.info("Raw analysis CSVs saved to %s", args.results_dir)


if __name__ == "__main__":
    main()
