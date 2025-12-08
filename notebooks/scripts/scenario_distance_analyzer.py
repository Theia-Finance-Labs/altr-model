#!/usr/bin/env python3
"""
Scenario Distance Analyzer
===========================

Interactive script to analyze and compare scenario trajectories within providers.
Finds scenarios that should be different but have similar trajectories.

Usage:
    python scenario_distance_analyzer.py

The script will:
1. Load and filter the AR6 scenarios data
2. Calculate trajectory distances between scenario pairs
3. Allow interactive selection of interesting scenario pairs
4. Generate comparison plots
5. Save results to workspace/scenarios_distance/
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from itertools import combinations
from tqdm import tqdm
from pathlib import Path
from joblib import Parallel, delayed
import multiprocessing


# Set up plotting style
sns.set_style("whitegrid")
plt.rcParams["figure.figsize"] = (16, 10)

# Configuration
DATA_PATH = "data/05_model_input/AR6_scenarios_carbon_price_fixed.csv"
OUTPUT_DIR = "workspace/scenarios_distance"
RESULTS_DIR = "results"
PLOTS_DIR = "plots"

# Variables to compare
VARIABLES_TO_COMPARE = [
    "scenario_price",
    "fuel_price",
    "scenario_pathway",
    "scenario_capacity_factor",
    "efficiency_decimal",
]


def setup_directories():
    """Create necessary directories and clean plot folder."""
    Path(OUTPUT_DIR).mkdir(exist_ok=True)
    Path(f"{OUTPUT_DIR}/{RESULTS_DIR}").mkdir(exist_ok=True)
    Path(f"{OUTPUT_DIR}/{PLOTS_DIR}").mkdir(exist_ok=True)

    # Clean plots directory
    plots_path = Path(f"{OUTPUT_DIR}/{PLOTS_DIR}")
    if plots_path.exists():
        plot_files = list(plots_path.glob("*.png"))
        if plot_files:
            print(f"Cleaning {len(plot_files)} existing plot files...")
            for plot_file in plot_files:
                plot_file.unlink()

    print(
        f"Created directories: {OUTPUT_DIR}/{RESULTS_DIR} and {OUTPUT_DIR}/{PLOTS_DIR}"
    )


def load_and_filter_data():
    """Load and filter the AR6 scenarios data."""
    print("Loading data...")
    df = pd.read_csv(DATA_PATH, low_memory=False)

    print("Filtering for years 2023-2030 and Power sector...")
    df_filtered = df[
        (df["scenario_year"] >= 2023)
        & (df["scenario_year"] <= 2030)
        & (df["sector"] == "Power")
    ].copy()

    print(f"Filtered data shape: {df_filtered.shape}")
    print(f"Years: {sorted(df_filtered['scenario_year'].unique())}")
    print(f"Number of scenario providers: {df_filtered['scenario_provider'].nunique()}")

    return df, df_filtered


def calculate_trajectory_distance(series1, series2):
    """
    Calculate distance between two time series.
    Returns multiple metrics: RMSE, mean absolute difference, and correlation.
    """
    # Remove NaN values where both series have valid data
    valid_mask = ~(pd.isna(series1) | pd.isna(series2))
    s1 = series1[valid_mask]
    s2 = series2[valid_mask]

    if len(s1) < 2:
        return np.nan, np.nan, np.nan

    # Calculate RMSE (root mean squared error)
    rmse = np.sqrt(np.mean((s1 - s2) ** 2))

    # Calculate mean absolute difference
    mad = np.mean(np.abs(s1 - s2))

    # Fast correlation calculation using numpy
    # Check for constant arrays (std == 0) which cause correlation issues
    if np.std(s1) == 0 or np.std(s2) == 0:
        corr = np.nan
    else:
        # Use numpy's corrcoef which is faster than scipy's pearsonr
        corr = np.corrcoef(s1, s2)[0, 1]

    return rmse, mad, corr


def calculate_normalized_distance(group1, group2, variables):
    """
    Calculate normalized distance across multiple variables.
    Returns a dict with distances for each variable and an overall score.
    """
    distances = {}
    valid_norm_mads = []

    for var in variables:
        # Get values as numpy arrays once
        v1 = group1[var].values
        v2 = group2[var].values

        # Remove NaN values where both series have valid data
        valid_mask = ~(pd.isna(v1) | pd.isna(v2))
        s1 = v1[valid_mask]
        s2 = v2[valid_mask]

        if len(s1) < 2:
            distances[f"{var}_rmse"] = np.nan
            distances[f"{var}_mad"] = np.nan
            distances[f"{var}_normalized_mad"] = np.nan
            distances[f"{var}_correlation"] = np.nan
            continue

        # Calculate all metrics in one pass
        diff = s1 - s2
        rmse = np.sqrt(np.mean(diff**2))
        mad = np.mean(np.abs(diff))

        # Normalize by mean to make comparable across variables
        mean_val = (s1.mean() + s2.mean()) / 2
        if mean_val != 0 and not np.isnan(mean_val):
            normalized_mad = mad / abs(mean_val)
        else:
            normalized_mad = mad

        # Fast correlation calculation
        if np.std(s1) == 0 or np.std(s2) == 0:
            corr = np.nan
        else:
            corr = np.corrcoef(s1, s2)[0, 1]

        distances[f"{var}_rmse"] = rmse
        distances[f"{var}_mad"] = mad
        distances[f"{var}_normalized_mad"] = normalized_mad
        distances[f"{var}_correlation"] = corr

        if not np.isnan(normalized_mad):
            valid_norm_mads.append(normalized_mad)

    # Overall distance: average of normalized MADs (lower is better)
    distances["overall_distance"] = (
        np.mean(valid_norm_mads) if valid_norm_mads else np.nan
    )

    return distances


def process_group(group_key, group_data, variables_to_compare):
    """Process a single geography+technology group."""
    provider, geography, technology = group_key
    scenarios = group_data["scenario"].unique()

    if len(scenarios) < 2:
        return []

    results = []

    # Compare all pairs of scenarios
    for scenario1, scenario2 in combinations(scenarios, 2):
        # Get data for each scenario (sorted by year)
        data1 = group_data[group_data["scenario"] == scenario1].sort_values(
            "scenario_year"
        )
        data2 = group_data[group_data["scenario"] == scenario2].sort_values(
            "scenario_year"
        )

        # Make sure they have the same years
        common_years = set(data1["scenario_year"]) & set(data2["scenario_year"])
        if len(common_years) < 2:  # Need at least 2 years to compare
            continue

        data1 = data1[data1["scenario_year"].isin(common_years)]
        data2 = data2[data2["scenario_year"].isin(common_years)]

        # Calculate distances
        distances = calculate_normalized_distance(data1, data2, variables_to_compare)

        # Store result
        result = {
            "scenario_provider": provider,
            "scenario_geography": geography,
            "technology": technology,
            "scenario_1": scenario1,
            "scenario_2": scenario2,
            "n_years_compared": len(common_years),
            **distances,
        }
        results.append(result)

    return results


def calculate_pairwise_distances(df_filtered, n_jobs=-1):
    """
    Calculate pairwise distances for all scenario pairs using parallel processing.

    Args:
        df_filtered: Filtered dataframe with scenario data
        n_jobs: Number of parallel jobs (-1 uses all CPU cores)
    """
    print("Calculating pairwise distances...")

    # Group by provider, geography, and technology
    grouped = df_filtered.groupby(
        ["scenario_provider", "scenario_geography", "technology"]
    )

    total_groups = len(grouped)

    # Estimate number of comparisons
    n_scenarios = df_filtered["scenario"].nunique()
    estimated_pairs = (n_scenarios * (n_scenarios - 1)) // 2
    print(f"Processing {total_groups} provider+geography+technology combinations...")
    print(f"Number of unique scenarios: {n_scenarios}")
    print(f"Estimated pairwise comparisons: ~{estimated_pairs * total_groups:,}")

    # Determine number of cores
    if n_jobs == -1:
        n_jobs = multiprocessing.cpu_count()
    print(f"Using {n_jobs} CPU cores for parallel processing")

    # Process groups in parallel
    results_nested = Parallel(n_jobs=n_jobs, backend="loky")(
        delayed(process_group)(group_key, group_data, VARIABLES_TO_COMPARE)
        for group_key, group_data in tqdm(
            grouped, total=total_groups, desc="Processing groups"
        )
    )

    # Flatten results
    results = [item for sublist in results_nested for item in sublist]

    # Convert to DataFrame
    df_distances = pd.DataFrame(results)

    print(f"\nCompleted! Generated {len(df_distances):,} pairwise comparisons.")
    if len(df_distances) > 0:
        print(f"Scenario providers: {df_distances['scenario_provider'].nunique()}")

    return df_distances


def find_closest_pairs(df_distances):
    """Find the closest scenario pair for each provider."""
    print("Finding closest scenario pairs per provider...")

    closest_pairs = []
    for provider in df_distances["scenario_provider"].unique():
        provider_data = df_distances[df_distances["scenario_provider"] == provider]

        # Group by scenario pair and calculate average distance across all geo+tech
        pair_distances = (
            provider_data.groupby(["scenario_1", "scenario_2"])
            .agg({"overall_distance": "mean", "n_years_compared": "mean"})
            .reset_index()
        )

        # Find the pair with minimum average distance
        if len(pair_distances) > 0:
            closest = pair_distances.loc[pair_distances["overall_distance"].idxmin()]
            closest_pairs.append(
                {
                    "scenario_provider": provider,
                    "scenario_1": closest["scenario_1"],
                    "scenario_2": closest["scenario_2"],
                    "avg_overall_distance": closest["overall_distance"],
                    "avg_n_years": closest["n_years_compared"],
                }
            )

    df_closest_pairs = pd.DataFrame(closest_pairs).sort_values("avg_overall_distance")

    print(f"Found {len(df_closest_pairs)} providers with comparable scenarios")
    print("\nTop 10 providers with most similar scenario pairs:")
    print(df_closest_pairs.head(10))

    return df_closest_pairs


def plot_scenario_comparison(
    provider,
    scenario_1,
    scenario_2,
    variable="scenario_pathway",
    df_source=None,
    df_full=None,
    save_path=None,
):
    """
    Plot comparison of two scenarios - creates separate plots for each technology.
    Uses full dataset for plotting (not just filtered years).
    """
    if df_source is None:
        print("Error: df_source is required")
        return None

    # Use full dataset for plotting if available, otherwise use filtered dataset
    plot_df = df_full if df_full is not None else df_source

    # Filter data for the two scenarios
    data = plot_df[
        (plot_df["scenario_provider"] == provider)
        & (plot_df["scenario"].isin([scenario_1, scenario_2]))
        & (plot_df["sector"] == "Power")  # Ensure we only plot Power sector
    ].copy()

    if len(data) == 0:
        print(
            f"No data found for provider={provider}, scenarios={scenario_1}, {scenario_2}"
        )
        return None

    # Get unique technologies and geographies
    technologies = sorted(data["technology"].unique())
    geographies = sorted(data["scenario_geography"].unique())

    figures = []

    # Create a separate plot for each technology
    for tech in technologies:
        # Filter data for this technology
        tech_data = data[data["technology"] == tech].copy()

        if len(tech_data) == 0:
            continue

        # Create subplots for geographies - one row, multiple columns
        n_geos = len(geographies)
        ncols = min(4, n_geos)  # Limit to 4 columns max
        nrows = (n_geos + ncols - 1) // ncols  # Calculate rows needed

        figsize = (6 * ncols, 4 * nrows)
        fig, axes = plt.subplots(nrows, ncols, figsize=figsize, squeeze=False)

        # Plot data for each geography
        for plot_idx, geo in enumerate(geographies):
            row = plot_idx // ncols
            col = plot_idx % ncols
            ax = axes[row, col]

            # Filter data for this tech and geo
            subset = tech_data[tech_data["scenario_geography"] == geo].sort_values(
                "scenario_year"
            )

            if len(subset) > 0:
                # Plot each scenario
                for scenario in [scenario_1, scenario_2]:
                    scenario_data = subset[subset["scenario"] == scenario]
                    if len(scenario_data) > 0:
                        ax.plot(
                            scenario_data["scenario_year"],
                            scenario_data[variable],
                            marker="o",
                            label=scenario,
                            linewidth=2,
                            markersize=6,
                        )

                # Formatting
                ax.set_xlabel("Year", fontsize=10)
                ax.set_ylabel(variable.replace("_", " ").title(), fontsize=10)
                ax.set_title(f"{geo}", fontsize=11, fontweight="bold")
                ax.legend(fontsize=8, loc="best")
                ax.grid(True, alpha=0.3)
            else:
                ax.text(
                    0.5,
                    0.5,
                    "No data",
                    ha="center",
                    va="center",
                    transform=ax.transAxes,
                )
                ax.set_title(f"{geo}", fontsize=11)

        # Hide unused subplots
        for idx in range(len(geographies), nrows * ncols):
            row = idx // ncols
            col = idx % ncols
            axes[row, col].axis("off")

        # Main title for this technology
        title = f"{provider}\n{tech}\nComparing: {scenario_1} vs {scenario_2}"
        fig.suptitle(title, fontsize=14, fontweight="bold", y=0.995)

        plt.tight_layout()

        # Save plot with technology-specific filename
        if save_path:
            # Modify save path to include technology
            base_path = save_path.rsplit(".", 1)[0]  # Remove extension
            extension = save_path.rsplit(".", 1)[1] if "." in save_path else "png"
            safe_tech = tech.replace("/", "_").replace(" ", "_")
            tech_save_path = f"{base_path}_{safe_tech}.{extension}"

            plt.savefig(tech_save_path, dpi=150, bbox_inches="tight")
            print(f"Plot saved to: {tech_save_path}")

        figures.append(fig)

    return figures


def interactive_pair_selector(provider, df_distances, df_filtered, df_full=None):
    """
    Interactive selector to find the best pair by iteratively rejecting scenarios.

    Options:
    - Keep one scenario, reject the other
    - Reject both scenarios in the current pair
    - Accept the current pair and generate plots
    """
    # Track rejected scenarios
    rejected_scenarios = []

    # Get initial closest pair for this provider
    provider_data = df_distances[df_distances["scenario_provider"] == provider]

    if len(provider_data) == 0:
        print(f"No data found for provider: {provider}")
        return None

    # Calculate average distance for all pairs (across all geo+tech)
    pair_distances = (
        provider_data.groupby(["scenario_1", "scenario_2"])
        .agg({"overall_distance": "mean", "n_years_compared": "mean"})
        .reset_index()
        .sort_values("overall_distance")
    )

    if len(pair_distances) == 0:
        print(f"No scenario pairs found for provider: {provider}")
        return None

    # Start with the closest pair
    current_pair = pair_distances.iloc[0]
    scenario_1 = current_pair["scenario_1"]
    scenario_2 = current_pair["scenario_2"]
    distance = current_pair["overall_distance"]

    iteration = 1

    while True:
        print(f"\n{'='*80}")
        print(f"ITERATION {iteration} - Provider: {provider}")
        print(f"{'='*80}")
        print(f"\nCurrent best pair (avg distance: {distance:.4f}):")
        print(f"  [1] {scenario_1}")
        print(f"  [2] {scenario_2}")

        # Show distance breakdown per technology (averaged across geographies)
        pair_data = provider_data[
            (
                (provider_data["scenario_1"] == scenario_1)
                & (provider_data["scenario_2"] == scenario_2)
            )
            | (
                (provider_data["scenario_1"] == scenario_2)
                & (provider_data["scenario_2"] == scenario_1)
            )
        ]

        if len(pair_data) > 0:
            tech_distances = (
                pair_data.groupby("technology")["overall_distance"].mean().sort_values()
            )

            print(f"\nDistance by technology (averaged across geographies):")
            print(f"{'Technology':<35} {'Distance':>10}")
            print(f"{'-'*35} {'-'*10}")
            for tech, dist in tech_distances.items():
                print(f"{tech:<35} {dist:>10.4f}")
            print(f"{'-'*35} {'-'*10}")
            print(f"{'Overall average':<35} {distance:>10.4f}")

        print(f"\nOptions:")
        print(f"  1 - Keep scenario [1], find next best match")
        print(f"  2 - Keep scenario [2], find next best match")
        print(f"  3 - Reject both scenarios, find new pair")
        print(f"  4 - Accept this pair and plot comparison")
        print(f"  q - Quit without plotting")

        if len(rejected_scenarios) > 0:
            print(f"\nRejected scenarios so far: {len(rejected_scenarios)}")
            print(
                f"  {', '.join(rejected_scenarios[:5])}"
                + (
                    f" ... and {len(rejected_scenarios)-5} more"
                    if len(rejected_scenarios) > 5
                    else ""
                )
            )

        choice = input("\nYour choice: ").strip().lower()

        if choice == "q":
            print("Cancelled.")
            return None

        if choice == "4":
            print(f"\n✓ Final selection: {scenario_1} vs {scenario_2}")
            print(f"  Distance: {distance:.4f}")
            print("\nGenerating plot...")

            # Create safe filename
            safe_provider = provider.replace("/", "_").replace(" ", "_")
            safe_scenario1 = scenario_1.replace("/", "_").replace(" ", "_")[:30]
            safe_scenario2 = scenario_2.replace("/", "_").replace(" ", "_")[:30]
            plot_filename = f"{safe_provider}_{safe_scenario1}_vs_{safe_scenario2}.png"
            plot_path = f"{OUTPUT_DIR}/{PLOTS_DIR}/{plot_filename}"

            figures = plot_scenario_comparison(
                provider=provider,
                scenario_1=scenario_1,
                scenario_2=scenario_2,
                variable="scenario_pathway",
                df_source=df_filtered,
                df_full=df_full,
                save_path=plot_path,
            )

            if figures:
                # Close figures after saving to avoid memory issues
                for fig in figures:
                    plt.close(fig)

            return {
                "provider": provider,
                "scenario_1": scenario_1,
                "scenario_2": scenario_2,
                "distance": distance,
                "iterations": iteration,
                "rejected": rejected_scenarios,
                "plot_path": plot_path,
            }

        elif choice == "3":
            # Reject both scenarios
            rejected_scenarios.append(scenario_1)
            rejected_scenarios.append(scenario_2)
            print(f"\n→ Rejecting both: {scenario_1} and {scenario_2}")
            print(f"→ Finding next best pair...")

            # Filter out all pairs involving rejected scenarios
            available_pairs = pair_distances[
                ~pair_distances["scenario_1"].isin(rejected_scenarios)
                & ~pair_distances["scenario_2"].isin(rejected_scenarios)
            ].copy()

            if len(available_pairs) == 0:
                print(f"\n⚠ No more scenario pairs available")
                print("All remaining scenarios have been rejected.")
                return None

            # Get the best available pair
            best_pair = available_pairs.iloc[0]
            scenario_1 = best_pair["scenario_1"]
            scenario_2 = best_pair["scenario_2"]
            distance = best_pair["overall_distance"]
            iteration += 1

        elif choice in ["1", "2"]:
            # Keep the chosen scenario, reject the other
            if choice == "1":
                keep_scenario = scenario_1
                reject_scenario = scenario_2
            else:
                keep_scenario = scenario_2
                reject_scenario = scenario_1

            rejected_scenarios.append(reject_scenario)
            print(f"\n→ Keeping: {keep_scenario}")
            print(f"→ Rejecting: {reject_scenario}")
            print(f"→ Finding next best match for '{keep_scenario}'...")

            # Find pairs involving the kept scenario
            relevant_pairs = provider_data[
                (provider_data["scenario_1"] == keep_scenario)
                | (provider_data["scenario_2"] == keep_scenario)
            ].copy()

            # Get the "other" scenario
            relevant_pairs["other_scenario"] = relevant_pairs.apply(
                lambda row: (
                    row["scenario_2"]
                    if row["scenario_1"] == keep_scenario
                    else row["scenario_1"]
                ),
                axis=1,
            )

            # Filter out rejected scenarios
            relevant_pairs = relevant_pairs[
                ~relevant_pairs["other_scenario"].isin(rejected_scenarios)
            ]

            if len(relevant_pairs) == 0:
                print(f"\n⚠ No more scenarios available to pair with '{keep_scenario}'")
                print("Returning to previous state...")
                rejected_scenarios.remove(reject_scenario)
                continue

            # Calculate average distance for each candidate
            candidate_distances = (
                relevant_pairs.groupby("other_scenario")
                .agg({"overall_distance": "mean", "n_years_compared": "mean"})
                .reset_index()
                .sort_values("overall_distance")
            )

            # Get the best match
            best_match = candidate_distances.iloc[0]
            new_scenario = best_match["other_scenario"]
            new_distance = best_match["overall_distance"]

            # Update current pair
            scenario_1 = keep_scenario
            scenario_2 = new_scenario
            distance = new_distance
            iteration += 1

        else:
            print("Invalid choice. Please enter 1, 2, 3, 4, or q.")


def show_available_providers(df_source):
    """Show all available providers from the source data."""
    print("Available scenario providers:")
    print("=" * 80)
    providers = sorted(df_source["scenario_provider"].unique())
    for i, provider in enumerate(providers, 1):
        n_scenarios = df_source[df_source["scenario_provider"] == provider][
            "scenario"
        ].nunique()
        print(f"{i:2d}. {provider} ({n_scenarios} scenarios)")
    return providers


def show_providers(df_distances):
    """Show all available providers."""
    print("Available scenario providers:")
    print("=" * 80)
    for i, provider in enumerate(sorted(df_distances["scenario_provider"].unique()), 1):
        n_scenarios = len(
            set(
                df_distances[df_distances["scenario_provider"] == provider][
                    "scenario_1"
                ].unique()
            )
            | set(
                df_distances[df_distances["scenario_provider"] == provider][
                    "scenario_2"
                ].unique()
            )
        )
        print(f"{i:2d}. {provider} ({n_scenarios} scenarios)")


def get_cached_distances_path(provider):
    """Get the path for cached distances for a specific provider."""
    safe_provider = provider.replace("/", "_").replace(" ", "_")
    return f"{OUTPUT_DIR}/{RESULTS_DIR}/distances_{safe_provider}.csv"


def load_cached_distances(provider):
    """Load cached distances for a specific provider if they exist."""
    cached_path = get_cached_distances_path(provider)
    if Path(cached_path).exists():
        print(f"Loading cached distances for {provider}...")
        return pd.read_csv(cached_path)
    return None


def save_cached_distances(df_distances, provider):
    """Save distances for a specific provider to cache."""
    cached_path = get_cached_distances_path(provider)
    df_distances.to_csv(cached_path, index=False)
    print(f"✓ Cached distances for {provider}: {cached_path}")


def save_results(df_distances, df_closest_pairs, provider=None):
    """Save analysis results to files."""
    if provider:
        # Save provider-specific results
        safe_provider = provider.replace("/", "_").replace(" ", "_")
        distances_path = f"{OUTPUT_DIR}/{RESULTS_DIR}/scenario_trajectory_distances_{safe_provider}.csv"
        closest_path = (
            f"{OUTPUT_DIR}/{RESULTS_DIR}/closest_scenario_pairs_{safe_provider}.csv"
        )
        summary_path = (
            f"{OUTPUT_DIR}/{RESULTS_DIR}/summary_statistics_{safe_provider}.txt"
        )
    else:
        # Save combined results
        distances_path = f"{OUTPUT_DIR}/{RESULTS_DIR}/scenario_trajectory_distances.csv"
        closest_path = f"{OUTPUT_DIR}/{RESULTS_DIR}/closest_scenario_pairs.csv"
        summary_path = f"{OUTPUT_DIR}/{RESULTS_DIR}/summary_statistics.txt"

    print(f"\nSaving results to {OUTPUT_DIR}/{RESULTS_DIR}/...")

    # Save pairwise distances
    df_distances.to_csv(distances_path, index=False)
    print(f"✓ Saved pairwise distances: {distances_path}")

    # Save closest pairs
    df_closest_pairs.to_csv(closest_path, index=False)
    print(f"✓ Saved closest pairs: {closest_path}")

    # Save summary statistics
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("Scenario Distance Analysis Summary\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"Total pairwise comparisons: {len(df_distances)}\n")
        f.write(f"Number of providers: {df_distances['scenario_provider'].nunique()}\n")
        f.write(
            f"Average overall distance: {df_distances['overall_distance'].mean():.4f}\n"
        )
        f.write(
            f"Median overall distance: {df_distances['overall_distance'].median():.4f}\n\n"
        )

        f.write("Top 10 most similar scenario pairs:\n")
        f.write("-" * 40 + "\n")
        for _, row in df_closest_pairs.head(10).iterrows():
            f.write(
                f"{row['scenario_provider']}: {row['scenario_1']} vs {row['scenario_2']} (distance: {row['avg_overall_distance']:.4f})\n"
            )

    print(f"✓ Saved summary: {summary_path}")


def main():
    """Main function to run the scenario distance analysis."""
    print("Scenario Distance Analyzer")
    print("=" * 50)

    # Setup
    setup_directories()

    # Load and process data
    df, df_filtered = load_and_filter_data()

    # Show available providers and let user select one
    print("\n" + "=" * 80)
    print("PROVIDER SELECTION")
    print("=" * 80)

    available_providers = show_available_providers(df_filtered)

    while True:
        print("\n" + "-" * 50)
        provider = input("\nEnter provider name (or 'quit' to exit): ").strip()

        if provider.lower() in ["quit", "q", "exit"]:
            return

        if provider not in available_providers:
            print(f"Provider '{provider}' not found. Please check the list above.")
            continue

        break

    # Filter data for selected provider
    print(f"\nFiltering data for provider: {provider}")
    df_provider = df_filtered[df_filtered["scenario_provider"] == provider].copy()

    if len(df_provider) == 0:
        print(f"No data found for provider: {provider}")
        return

    print(f"Found {len(df_provider)} records for {provider}")
    print(f"Number of scenarios: {df_provider['scenario'].nunique()}")
    print(f"Technologies: {sorted(df_provider['technology'].unique())}")
    print(f"Geographies: {sorted(df_provider['scenario_geography'].unique())}")

    # Check for cached distances
    df_distances = load_cached_distances(provider)

    if df_distances is None:
        print(f"\nCalculating pairwise distances for {provider}...")
        df_distances = calculate_pairwise_distances(df_provider)
        df_closest_pairs = find_closest_pairs(df_distances)

        # Save results
        save_cached_distances(df_distances, provider)
        save_results(df_distances, df_closest_pairs, provider)
    else:
        print(f"Using cached distances for {provider}")
        df_closest_pairs = find_closest_pairs(df_distances)

    # Interactive selection
    print("\n" + "=" * 80)
    print("INTERACTIVE SCENARIO PAIR SELECTION")
    print("=" * 80)

    while True:
        result = interactive_pair_selector(provider, df_distances, df_provider, df)

        if result:
            print(f"\n✓ Analysis completed for {provider}")
            print(f"  Final pair: {result['scenario_1']} vs {result['scenario_2']}")
            print(f"  Distance: {result['distance']:.4f}")
            print(f"  Plot saved: {result['plot_path']}")

            # Ask if user wants to continue with same provider
            continue_choice = (
                input("\nAnalyze another pair for this provider? (y/n): ")
                .strip()
                .lower()
            )
            if continue_choice not in ["y", "yes"]:
                break
        else:
            break

    print("\n" + "=" * 80)
    print("Analysis complete!")
    print(f"Results saved to: {OUTPUT_DIR}/")
    print("=" * 80)


if __name__ == "__main__":
    main()
