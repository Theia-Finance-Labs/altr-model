"""
Batch runner for ALTR model: all IAM scenario pairs x parameter configurations.

Reads a scenario manifest (JSON), iterates over each scenario pair and each
config variant, writes temporary overrides to conf/local/, shells out to Kedro,
and collects results into workspace/comparison_results/.

Usage:
    # Dry run — prints what would execute without running anything
    python notebooks/run_all_scenarios_comparison.py --dry-run

    # Full run
    python notebooks/run_all_scenarios_comparison.py

    # Custom manifest and AR6 path
    python notebooks/run_all_scenarios_comparison.py \
        --manifest workspace/scenario_manifest.json \
        --ar6-path 6_final_AR6_viable_scenarios.csv

    # Run only a subset of configs
    python notebooks/run_all_scenarios_comparison.py --configs vanilla adjusted

    # Run only a subset of providers
    python notebooks/run_all_scenarios_comparison.py --providers "WITCH 5.0" "COFFEE 1.1"
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("batch_runner")


# ---------------------------------------------------------------------------
# Parameter configuration definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConfigVariant:
    """A named parameter configuration for the ALTR model."""

    name: str
    earnings_params: dict[str, Any]
    valuation_params: dict[str, Any]


def _vanilla_earnings() -> dict[str, Any]:
    return {
        "enable_mcpr": False,
        "price_ramp": False,
        "dynamic_marginal_ef": False,
        "apply_continued_om_shock": False,
        "include_replacement_capex": False,
        "include_decom_costs": False,
        "market_passthrough": 0,
        "carbon_cost_method": "differential_ef",
    }


def _vanilla_valuation() -> dict[str, Any]:
    """Complete valuation params — must include ALL keys the pipeline references."""
    return {
        "dcf": {
            "discount_rate_baseline": 0.07,
            "discount_rate_shock": 0.07,
            "brown_discount_spread": 0.0,
            "green_discount_spread": 0.0,
            "stranding_aware_tv": False,
            "stranding_consecutive_years": 3,
            "brown_remaining_life_years": 10,
            "terminal_value": {
                "method": "perpetuity",
                "g_real_default": 0.02,
                "g_real_brown": 0.02,
                "g_real_green": 0.02,
                "normalization_window": 1,
            },
        }
    }


def _adjusted_earnings() -> dict[str, Any]:
    return {
        "enable_mcpr": True,
        "price_ramp": True,
        "dynamic_marginal_ef": True,
        "apply_continued_om_shock": True,
        "include_replacement_capex": True,
        "include_decom_costs": True,
        "market_passthrough": 0,
        "carbon_cost_method": "full_ef",
    }


def _adjusted_valuation() -> dict[str, Any]:
    """Complete valuation params — must include ALL keys the pipeline references."""
    return {
        "dcf": {
            "discount_rate_baseline": 0.07,
            "discount_rate_shock": 0.07,
            "brown_discount_spread": 0.01,
            "green_discount_spread": 0.005,
            "stranding_aware_tv": True,
            "stranding_consecutive_years": 3,
            "brown_remaining_life_years": 10,
            "terminal_value": {
                "method": "perpetuity",
                "g_real_default": 0.02,
                "g_real_brown": 0.0,
                "g_real_green": 0.02,
                "normalization_window": 3,
            },
        }
    }


# Build the six config variants
CONFIG_VARIANTS: dict[str, ConfigVariant] = {}

# 1. vanilla — all adjustments OFF
CONFIG_VARIANTS["vanilla"] = ConfigVariant(
    name="vanilla",
    earnings_params=_vanilla_earnings(),
    valuation_params=_vanilla_valuation(),
)

# 2. adjusted — all adjustments ON (current model)
CONFIG_VARIANTS["adjusted"] = ConfigVariant(
    name="adjusted",
    earnings_params=_adjusted_earnings(),
    valuation_params=_adjusted_valuation(),
)

# 3. iso_mcpr — vanilla + MCPR only
_iso_mcpr_earn = _vanilla_earnings()
_iso_mcpr_earn["enable_mcpr"] = True
CONFIG_VARIANTS["iso_mcpr"] = ConfigVariant(
    name="iso_mcpr",
    earnings_params=_iso_mcpr_earn,
    valuation_params=_vanilla_valuation(),
)

# 4. iso_stranding_tv — vanilla + stranding-aware TV only
_iso_tv_val = _vanilla_valuation()
_iso_tv_val["dcf"]["stranding_aware_tv"] = True
_iso_tv_val["dcf"]["terminal_value"]["g_real_brown"] = 0.0
_iso_tv_val["dcf"]["terminal_value"]["normalization_window"] = 3
CONFIG_VARIANTS["iso_stranding_tv"] = ConfigVariant(
    name="iso_stranding_tv",
    earnings_params=_vanilla_earnings(),
    valuation_params=_iso_tv_val,
)

# 5. iso_dynamic_ef — vanilla + dynamic marginal EF only
_iso_ef_earn = _vanilla_earnings()
_iso_ef_earn["dynamic_marginal_ef"] = True
CONFIG_VARIANTS["iso_dynamic_ef"] = ConfigVariant(
    name="iso_dynamic_ef",
    earnings_params=_iso_ef_earn,
    valuation_params=_vanilla_valuation(),
)

# 6. iso_full_ef — vanilla + full_ef carbon cost method only
_iso_fullef_earn = _vanilla_earnings()
_iso_fullef_earn["carbon_cost_method"] = "full_ef"
CONFIG_VARIANTS["iso_full_ef"] = ConfigVariant(
    name="iso_full_ef",
    earnings_params=_iso_fullef_earn,
    valuation_params=_vanilla_valuation(),
)

# 7. iso_d1 — vanilla + D1 discount rate spread only
# Tests the hypothesis that the discount spread is the dominant driver
# of the +19.5pp interaction term in the full adjusted config.
_iso_d1_val = _vanilla_valuation()
_iso_d1_val["dcf"]["brown_discount_spread"] = 0.01   # +100bps for carbontech
_iso_d1_val["dcf"]["green_discount_spread"] = 0.005  # -50bps for greentech
CONFIG_VARIANTS["iso_d1"] = ConfigVariant(
    name="iso_d1",
    earnings_params=_vanilla_earnings(),
    valuation_params=_iso_d1_val,
)

# 8. mcpr_v2_carbon — MCPR carbon_explicit mode (forces full_ef)
# For IAMs with carbon price data: MCPR sets clearing price,
# full_ef carbon costs create the asymmetric fossil penalty.
_mcpr_v2c_earn = _vanilla_earnings()
_mcpr_v2c_earn["enable_mcpr"] = True
_mcpr_v2c_earn["carbon_cost_method"] = "full_ef"
_mcpr_v2c_earn["mcpr_mode"] = "carbon_explicit"
CONFIG_VARIANTS["mcpr_v2_carbon"] = ConfigVariant(
    name="mcpr_v2_carbon",
    earnings_params=_mcpr_v2c_earn,
    valuation_params=_vanilla_valuation(),
)

# 9. mcpr_v2_merit — MCPR merit_order_decline mode
# For IAMs without carbon prices: clearing price declines with VRE share.
_mcpr_v2m_earn = _vanilla_earnings()
_mcpr_v2m_earn["enable_mcpr"] = True
_mcpr_v2m_earn["enable_dynamic_capture_ratios"] = True
_mcpr_v2m_earn["mcpr_mode"] = "merit_order_decline"
CONFIG_VARIANTS["mcpr_v2_merit"] = ConfigVariant(
    name="mcpr_v2_merit",
    earnings_params=_mcpr_v2m_earn,
    valuation_params=_vanilla_valuation(),
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScenarioPair:
    """A single baseline+target scenario pair from the manifest."""

    provider: str
    baseline_scenario: str
    target_scenario: str


@dataclass
class RunResult:
    """Outcome of a single pipeline run."""

    provider: str
    config_name: str
    success: bool
    duration_seconds: float = 0.0
    error_message: str = ""
    output_dir: str = ""
    stats: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def load_manifest(manifest_path: Path) -> list[ScenarioPair]:
    """Load scenario pairs from the JSON manifest.

    Expected manifest format:
    {
        "scenario_pairs": [
            {
                "provider": "WITCH 5.0",
                "baseline_scenario": "AR6_WITCH 5.0_CO_CurPol",
                "target_scenario": "AR6_WITCH 5.0_EN_NPi2020_600"
            },
            ...
        ]
    }
    """
    with open(manifest_path) as f:
        data = json.load(f)

    pairs = []
    for entry in data["scenario_pairs"]:
        pairs.append(ScenarioPair(
            provider=entry["provider"],
            baseline_scenario=entry["baseline_scenario"],
            target_scenario=entry["target_scenario"],
        ))
    log.info("Loaded %d scenario pairs from %s", len(pairs), manifest_path)
    return pairs


def write_scenario_csv(
    ar6_path: Path,
    provider: str,
    baseline_scenario: str,
    target_scenario: str,
    output_path: Path,
) -> int:
    """Extract a scenario pair from the AR6 file and write it as a pipeline-ready CSV.

    The AR6 file has scenario names WITHOUT the AR6_ prefix (e.g. "CO_CurPol").
    The pipeline expects scenario names WITH the AR6_ prefix (e.g. "AR6_WITCH 5.0_CO_CurPol").

    The baseline_scenario and target_scenario arguments already include the AR6_ prefix.
    We strip the prefix to match against the AR6 file, then add it back for the output.

    Returns the number of rows written.
    """
    df = pd.read_csv(ar6_path)

    # Filter to this provider
    provider_mask = df["scenario_provider"] == provider
    provider_df = df[provider_mask].copy()
    if provider_df.empty:
        raise ValueError(f"Provider '{provider}' not found in AR6 file. "
                         f"Available: {sorted(df['scenario_provider'].unique())}")

    # Strip the AR6_<provider>_ prefix to get raw scenario names for matching
    prefix = f"AR6_{provider}_"
    baseline_raw = baseline_scenario.removeprefix(prefix)
    target_raw = target_scenario.removeprefix(prefix)

    # Filter to the two scenarios
    baseline_mask = provider_df["scenario"] == baseline_raw
    target_mask = provider_df["scenario"] == target_raw

    baseline_df = provider_df[baseline_mask].copy()
    target_df = provider_df[target_mask].copy()

    if baseline_df.empty:
        available = sorted(provider_df["scenario"].unique())
        raise ValueError(
            f"Baseline scenario '{baseline_raw}' not found for provider '{provider}'. "
            f"Available: {available[:20]}..."
        )
    if target_df.empty:
        available = sorted(provider_df["scenario"].unique())
        raise ValueError(
            f"Target scenario '{target_raw}' not found for provider '{provider}'. "
            f"Available: {available[:20]}..."
        )

    # Assign scenario_type
    baseline_df = baseline_df.assign(scenario_type="baseline")
    target_df = target_df.assign(scenario_type="target")

    # Combine
    combined = pd.concat([baseline_df, target_df], ignore_index=True)

    # Add AR6_ prefix to scenario names (filter_scenarios in the pipeline expects it)
    combined["scenario"] = "AR6_" + combined["scenario_provider"] + "_" + combined["scenario"]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_path, index=False)
    log.info(
        "Wrote %d rows for %s (%s vs %s) to %s",
        len(combined), provider, baseline_raw, target_raw, output_path.name,
    )
    return len(combined)


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def write_param_overrides(
    config: ConfigVariant,
    conf_local_dir: Path,
    conf_base_dir: Path | None = None,
) -> list[Path]:
    """Write YAML override files to conf/local/ by deep-merging config params
    into the full base parameter files.

    Kedro's conf/local/ completely replaces conf/base/ for the same filename,
    so we must include ALL parameters — not just the ones we're changing.

    Returns list of paths written (for cleanup).
    """
    if conf_base_dir is None:
        conf_base_dir = conf_local_dir.parent / "base"

    conf_local_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # Earnings model: load base, merge overrides
    earnings_base_path = conf_base_dir / "parameters_earnings_model.yml"
    with open(earnings_base_path) as f:
        earnings_base = yaml.safe_load(f) or {}
    earnings_merged = _deep_merge(earnings_base, config.earnings_params)
    earnings_path = conf_local_dir / "parameters_earnings_model.yml"
    with open(earnings_path, "w") as f:
        yaml.dump(earnings_merged, f, default_flow_style=False)
    written.append(earnings_path)

    # Valuation model: load base, merge overrides
    valuation_base_path = conf_base_dir / "parameters_valuation_model.yml"
    with open(valuation_base_path) as f:
        valuation_base = yaml.safe_load(f) or {}
    valuation_merged = _deep_merge(valuation_base, config.valuation_params)
    valuation_path = conf_local_dir / "parameters_valuation_model.yml"
    with open(valuation_path, "w") as f:
        yaml.dump(valuation_merged, f, default_flow_style=False)
    written.append(valuation_path)

    log.info("Wrote param overrides for config '%s' to %s", config.name, conf_local_dir)
    return written


def write_catalog_override(
    scenario_csv_path: Path,
    baseline_scenario: str,
    target_scenario: str,
    conf_local_dir: Path,
) -> Path:
    """Write a catalog override to point downloaded_scenarios at the extracted CSV,
    and override the scenario parameters (baseline_scenario, target_scenario).

    Returns path to the override file.
    """
    conf_local_dir.mkdir(parents=True, exist_ok=True)

    # Catalog override — point downloaded_scenarios at the extracted scenario file
    catalog_override = {
        "downloaded_scenarios": {
            "type": "pandas.CSVDataset",
            "filepath": str(scenario_csv_path),
        }
    }
    catalog_path = conf_local_dir / "catalog.yml"
    with open(catalog_path, "w") as f:
        yaml.dump(catalog_override, f, default_flow_style=False)

    # Inputs processing parameter override — deep merge scenario names into base
    conf_base_dir = conf_local_dir.parent / "base"
    inputs_base_path = conf_base_dir / "parameters_inputs_processing.yml"
    with open(inputs_base_path) as f:
        inputs_base = yaml.safe_load(f) or {}
    inputs_base["baseline_scenario"] = baseline_scenario
    inputs_base["target_scenario"] = target_scenario
    inputs_params_path = conf_local_dir / "parameters_inputs_processing.yml"
    with open(inputs_params_path, "w") as f:
        yaml.dump(inputs_base, f, default_flow_style=False)

    log.info(
        "Wrote catalog override: downloaded_scenarios -> %s",
        scenario_csv_path.name,
    )
    return catalog_path


def run_kedro_pipeline(
    project_dir: Path,
    timeout_seconds: int = 1800,
) -> tuple[bool, str, str]:
    """Shell out to kedro run --tags altrisk, capture stdout/stderr.

    Returns (success, stdout, stderr).
    """
    kedro_bin = project_dir / ".venv" / "bin" / "kedro"
    if not kedro_bin.exists():
        return False, "", f"Kedro binary not found at {kedro_bin}"

    cmd = [str(kedro_bin), "run", "--tags", "altrisk"]
    log.info("Running: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        success = result.returncode == 0
        if not success:
            log.error("Kedro run failed (exit code %d)", result.returncode)
            # Log last 30 lines of stderr for diagnostics
            stderr_lines = result.stderr.strip().split("\n")
            for line in stderr_lines[-30:]:
                log.error("  stderr: %s", line)
        return success, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", f"Kedro run timed out after {timeout_seconds}s"
    except Exception as e:
        return False, "", f"Kedro run failed with exception: {e}"


def collect_outputs(
    project_dir: Path,
    output_dir: Path,
    provider: str,
    config_name: str,
) -> Path:
    """Copy pipeline output files to workspace/comparison_results/{provider}/{config_name}/.

    Returns the destination directory.
    """
    # Sanitize provider name for filesystem (replace spaces, slashes)
    safe_provider = provider.replace(" ", "_").replace("/", "_")
    dest_dir = output_dir / safe_provider / config_name
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Only collect small summary files (not asset_earnings/yearly_npv which are ~500MB each)
    output_files = [
        "data/07_model_output/company_technology_npv.csv",
        "data/07_model_output/company_npv.csv",
    ]

    copied = 0
    for rel_path in output_files:
        src = project_dir / rel_path
        if src.exists():
            shutil.copy2(src, dest_dir / src.name)
            copied += 1
        else:
            log.warning("Output file not found: %s", src)

    log.info("Collected %d/%d output files to %s", copied, len(output_files), dest_dir)
    return dest_dir


def validate_run(output_dir: Path) -> tuple[bool, dict[str, Any]]:
    """Check outputs exist, are non-empty, and have no all-NaN value columns.

    Returns (pass/fail, stats dict).
    """
    stats: dict[str, Any] = {}
    all_ok = True

    for csv_name in ["company_technology_npv.csv", "company_npv.csv"]:
        csv_path = output_dir / csv_name
        if not csv_path.exists():
            stats[csv_name] = {"status": "MISSING"}
            all_ok = False
            continue

        try:
            df = pd.read_csv(csv_path)
        except Exception as e:
            stats[csv_name] = {"status": f"READ_ERROR: {e}"}
            all_ok = False
            continue

        if df.empty:
            stats[csv_name] = {"status": "EMPTY", "rows": 0}
            all_ok = False
            continue

        # Check for all-NaN in value columns (skip string/ID columns)
        numeric_cols = df.select_dtypes(include="number").columns
        all_nan_cols = [c for c in numeric_cols if df[c].isna().all()]

        file_stats: dict[str, Any] = {
            "status": "OK",
            "rows": len(df),
            "columns": len(df.columns),
            "numeric_columns": len(numeric_cols),
        }

        if all_nan_cols:
            file_stats["status"] = "WARN_ALL_NAN"
            file_stats["all_nan_columns"] = all_nan_cols
            # Not a hard failure — some scenarios may legitimately have no data
            # for certain aggregation levels

        stats[csv_name] = file_stats

    stats["overall"] = "PASS" if all_ok else "FAIL"
    return all_ok, stats


def cleanup_overrides(conf_local_dir: Path) -> None:
    """Remove all override files written to conf/local/.

    Only removes files we know we wrote — does not delete the directory
    or any pre-existing files.
    """
    override_files = [
        "parameters_earnings_model.yml",
        "parameters_valuation_model.yml",
        "parameters_inputs_processing.yml",
        "catalog.yml",
    ]
    for filename in override_files:
        fpath = conf_local_dir / filename
        if fpath.exists():
            fpath.unlink()
            log.debug("Removed override: %s", fpath)


def print_summary(results: list[RunResult]) -> None:
    """Print a human-readable summary table of all run results."""
    total = len(results)
    passed = sum(1 for r in results if r.success)
    failed = total - passed

    print("\n" + "=" * 80)
    print("BATCH RUN SUMMARY")
    print("=" * 80)
    print(f"Total runs: {total}  |  Passed: {passed}  |  Failed: {failed}")
    print("-" * 80)
    print(f"{'Provider':<25} {'Config':<20} {'Status':<8} {'Duration':<10} {'Rows'}")
    print("-" * 80)

    for r in results:
        status = "OK" if r.success else "FAIL"
        duration = f"{r.duration_seconds:.1f}s"
        rows = r.stats.get("company_npv.csv", {}).get("rows", "?")
        print(f"{r.provider:<25} {r.config_name:<20} {status:<8} {duration:<10} {rows}")

    print("=" * 80)

    if failed > 0:
        print(f"\nFailed runs ({failed}):")
        for r in results:
            if not r.success:
                print(f"  - {r.provider} [{r.config_name}]: {r.error_message[:120]}")
        print()


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def main(
    manifest_path: Path,
    ar6_path: Path,
    project_dir: Path,
    output_dir: Path,
    dry_run: bool = False,
    config_filter: list[str] | None = None,
    provider_filter: list[str] | None = None,
    timeout_seconds: int = 1800,
) -> list[RunResult]:
    """Main loop: for each scenario x config, extract -> configure -> run -> collect -> validate."""

    # Resolve paths
    manifest_path = manifest_path.resolve()
    ar6_path = ar6_path.resolve()
    project_dir = project_dir.resolve()
    output_dir = output_dir.resolve()
    conf_local_dir = project_dir / "conf" / "local"
    temp_scenarios_dir = project_dir / "workspace" / "_temp_scenario_csvs"

    # Validate inputs
    if not manifest_path.exists():
        log.error("Manifest not found: %s", manifest_path)
        sys.exit(1)
    if not ar6_path.exists():
        log.error("AR6 file not found: %s", ar6_path)
        sys.exit(1)
    if not project_dir.exists():
        log.error("Project directory not found: %s", project_dir)
        sys.exit(1)

    # Load scenario pairs
    scenario_pairs = load_manifest(manifest_path)

    # Apply provider filter
    if provider_filter:
        scenario_pairs = [
            p for p in scenario_pairs if p.provider in provider_filter
        ]
        log.info("Filtered to %d scenario pairs (providers: %s)", len(scenario_pairs), provider_filter)

    # Select config variants
    if config_filter:
        configs = {k: v for k, v in CONFIG_VARIANTS.items() if k in config_filter}
        if not configs:
            log.error("No matching configs for filter: %s", config_filter)
            sys.exit(1)
    else:
        configs = CONFIG_VARIANTS

    total_runs = len(scenario_pairs) * len(configs)
    log.info(
        "Batch plan: %d scenario pairs x %d configs = %d total runs",
        len(scenario_pairs), len(configs), total_runs,
    )

    if dry_run:
        print("\n=== DRY RUN — nothing will be executed ===\n")
        run_num = 0
        for pair in scenario_pairs:
            for config_name, config in configs.items():
                run_num += 1
                print(
                    f"  [{run_num:3d}/{total_runs}] {pair.provider:<25} "
                    f"[{config_name:<20}] "
                    f"baseline={pair.baseline_scenario}  "
                    f"target={pair.target_scenario}"
                )
        print(f"\nTotal: {total_runs} runs")
        print(f"Configs: {', '.join(configs.keys())}")
        print(f"Output: {output_dir}")
        return []

    # Execute runs
    results: list[RunResult] = []
    run_num = 0
    batch_start = time.time()

    for pair_idx, pair in enumerate(scenario_pairs):
        # Extract scenario CSV once per provider pair (shared across configs)
        safe_provider = pair.provider.replace(" ", "_").replace("/", "_")
        scenario_csv_path = temp_scenarios_dir / f"{safe_provider}_scenarios.csv"

        try:
            row_count = write_scenario_csv(
                ar6_path=ar6_path,
                provider=pair.provider,
                baseline_scenario=pair.baseline_scenario,
                target_scenario=pair.target_scenario,
                output_path=scenario_csv_path,
            )
            log.info("Extracted %d scenario rows for %s", row_count, pair.provider)
        except Exception as e:
            log.error("Failed to extract scenarios for %s: %s", pair.provider, e)
            # Record failure for all configs of this provider
            for config_name in configs:
                run_num += 1
                results.append(RunResult(
                    provider=pair.provider,
                    config_name=config_name,
                    success=False,
                    error_message=f"Scenario extraction failed: {e}",
                ))
            continue

        for config_name, config in configs.items():
            run_num += 1
            log.info(
                "\n>>> Running scenario %d/%d: %s [%s] <<<",
                run_num, total_runs, pair.provider, config_name,
            )
            run_start = time.time()

            try:
                # 1. Write parameter overrides to conf/local/
                write_param_overrides(config, conf_local_dir)

                # 2. Write catalog override pointing at extracted scenario CSV
                write_catalog_override(
                    scenario_csv_path=scenario_csv_path,
                    baseline_scenario=pair.baseline_scenario,
                    target_scenario=pair.target_scenario,
                    conf_local_dir=conf_local_dir,
                )

                # 3. Run the pipeline
                success, stdout, stderr = run_kedro_pipeline(
                    project_dir=project_dir,
                    timeout_seconds=timeout_seconds,
                )

                duration = time.time() - run_start

                if success:
                    # 4. Collect outputs
                    dest_dir = collect_outputs(
                        project_dir=project_dir,
                        output_dir=output_dir,
                        provider=pair.provider,
                        config_name=config_name,
                    )

                    # 5. Validate
                    valid, stats = validate_run(dest_dir)

                    results.append(RunResult(
                        provider=pair.provider,
                        config_name=config_name,
                        success=True,
                        duration_seconds=duration,
                        output_dir=str(dest_dir),
                        stats=stats,
                    ))
                    log.info(
                        "PASS: %s [%s] completed in %.1fs — %s",
                        pair.provider, config_name, duration,
                        "validation OK" if valid else "validation WARN",
                    )
                else:
                    # Extract last meaningful error from stderr
                    error_lines = [
                        line for line in stderr.strip().split("\n")
                        if line.strip() and not line.startswith("INFO")
                    ]
                    error_msg = error_lines[-1] if error_lines else "Unknown error"

                    results.append(RunResult(
                        provider=pair.provider,
                        config_name=config_name,
                        success=False,
                        duration_seconds=duration,
                        error_message=error_msg,
                    ))
                    log.error(
                        "FAIL: %s [%s] failed after %.1fs",
                        pair.provider, config_name, duration,
                    )

            except Exception as e:
                duration = time.time() - run_start
                results.append(RunResult(
                    provider=pair.provider,
                    config_name=config_name,
                    success=False,
                    duration_seconds=duration,
                    error_message=str(e),
                ))
                log.error(
                    "ERROR: %s [%s] raised exception: %s",
                    pair.provider, config_name, e,
                )

            finally:
                # 6. Clean up overrides after each run
                cleanup_overrides(conf_local_dir)

    batch_duration = time.time() - batch_start

    # Print summary
    print_summary(results)
    log.info("Batch completed in %.1f minutes", batch_duration / 60)

    # Write results index
    results_index_path = output_dir / "batch_results_index.json"
    results_index = {
        "total_runs": total_runs,
        "passed": sum(1 for r in results if r.success),
        "failed": sum(1 for r in results if not r.success),
        "duration_minutes": round(batch_duration / 60, 1),
        "runs": [
            {
                "provider": r.provider,
                "config": r.config_name,
                "success": r.success,
                "duration_s": round(r.duration_seconds, 1),
                "error": r.error_message if not r.success else None,
                "output_dir": r.output_dir if r.success else None,
                "stats": r.stats if r.success else None,
            }
            for r in results
        ],
    }
    results_index_path.parent.mkdir(parents=True, exist_ok=True)
    with open(results_index_path, "w") as f:
        json.dump(results_index, f, indent=2)
    log.info("Results index written to %s", results_index_path)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch runner for ALTR model: all IAM scenarios x parameter configs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("workspace/scenario_manifest.json"),
        help="Path to scenario manifest JSON (default: workspace/scenario_manifest.json)",
    )
    parser.add_argument(
        "--ar6-path",
        type=Path,
        default=Path("6_final_AR6_viable_scenarios.csv"),
        help="Path to the AR6 viable scenarios CSV (default: 6_final_AR6_viable_scenarios.csv)",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path("."),
        help="Kedro project root directory (default: current directory)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("workspace/comparison_results"),
        help="Output directory for collected results (default: workspace/comparison_results)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned runs without executing",
    )
    parser.add_argument(
        "--configs",
        nargs="+",
        choices=list(CONFIG_VARIANTS.keys()),
        help="Run only these config variants (default: all 5)",
    )
    parser.add_argument(
        "--providers",
        nargs="+",
        help="Run only these providers (e.g. 'WITCH 5.0' 'COFFEE 1.1')",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Timeout per Kedro run in seconds (default: 1800)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(
        manifest_path=args.manifest,
        ar6_path=args.ar6_path,
        project_dir=args.project_dir,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
        config_filter=args.configs,
        provider_filter=args.providers,
        timeout_seconds=args.timeout,
    )
