"""Batch-run the crispy-kedro model across named parameter configurations.

This is the script form of the loop in ``notebooks/generate_results.ipynb``:
each entry of a "run configurations" mapping becomes one ``kedro run`` (via
``KedroSession.create(extra_params=...)``), optionally restricted to a fixed
subset of companies, and each run's outputs are copied into
``workspace_dir/<run_name>/`` (plus a ``run_params.csv`` recording exactly
which parameters produced them) so runs never overwrite each other.

CLI usage::

    python notebooks/run_kedro_batch.py \\
        --run-configurations notebooks/example_run_configurations.yml \\
        --company-ids notebooks/example_company_selection.csv \\
        --workspace-dir workspace/results_batch \\
        --tags altrisk

Library usage (this is how ``notebooks/streamlit_app.py`` drives it, so
progress can be streamed into the UI instead of only printed)::

    from run_kedro_batch import run_batch, load_run_configurations

    run_configurations = load_run_configurations("notebooks/example_run_configurations.yml")
    summary = run_batch(run_configurations, workspace_dir="workspace/results_batch")
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_OUTPUT_DIR = PROJECT_ROOT / "data" / "07_model_output"
REPORTING_DIR = PROJECT_ROOT / "data" / "08_reporting"

# Mirrors the set of tables notebooks/generate_results.ipynb copies out of
# data/07_model_output/ after each run. asset_earnings.csv and
# asset_trajectories.csv are deliberately excluded here too - at full
# (non-company-restricted) scale they run into the hundreds of MB per run,
# which is exactly the kind of thing this workspace-copy step exists to
# avoid duplicating for every configuration.
MODEL_OUTPUT_FILES = [
    "company_trajectories.csv",
    "asset_trajectories.csv",
    "asset_npv.csv",
    "company_technology_npv.csv",
    "company_npv.csv",
    "yearly_npv_trajectories.csv",
]

REPORTING_FOLDERS = [
    "companies_trajectories_plots",
    "companies_staggered_shock_plots",
    "asset_financial_trajectories",
]


class ScenarioProviderMismatch(ValueError):
    """Raised when a run's baseline/target scenarios come from different providers."""


def load_run_configurations(path: Path | str) -> dict[str, dict]:
    """Load a ``{run_name: {param: value, ...}}`` mapping from YAML or JSON."""
    path = Path(path)
    with path.open("r") as f:
        if path.suffix.lower() == ".json":
            data = json.load(f)
        else:
            data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(
            f"{path} must contain a mapping of run_name -> parameter overrides, "
            f"got {type(data).__name__}"
        )
    return data


def load_company_ids(path: Path | str) -> list[str]:
    """Load a flat list of company ids from CSV, plain text, YAML, or JSON.

    - ``.csv``: uses a ``company_id`` column if present, otherwise the first
      column. Extra columns (company_name, capacity, ...) are ignored.
    - ``.txt``: one id per line; blank lines and lines starting with ``#``
      are skipped.
    - ``.yml``/``.yaml``/``.json``: a plain list of ids.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".csv":
        df = pd.read_csv(path)
        column = "company_id" if "company_id" in df.columns else df.columns[0]
        ids = df[column].dropna().astype(str).tolist()
    elif suffix in (".yml", ".yaml"):
        ids = yaml.safe_load(path.read_text())
    elif suffix == ".json":
        ids = json.loads(path.read_text())
    else:
        ids = [
            line.strip()
            for line in path.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    if not isinstance(ids, list):
        raise ValueError(f"{path} did not resolve to a list of company ids")
    return [str(i) for i in ids]


def _sanitize_run_name(run_name: str) -> str:
    """Run names become directory names under workspace_dir - keep them safe."""
    return run_name.replace("/", "-")


def _validate_scenario_pairing(
    run_name: str,
    run_params: Mapping,
    scenarios_csv: Path | str | None,
    allow_cross_provider: bool,
    log: Callable[[str], None],
) -> None:
    # scenarios_csv is only used as an opt-in switch here (pass None to skip
    # this check entirely) - the provider comparison itself is a pure string
    # operation on the scenario names, see scenario_utils.scenario_provider.
    baseline_scenario = run_params.get("baseline_scenario")
    target_scenario = run_params.get("target_scenario")
    if not baseline_scenario or not target_scenario or not scenarios_csv:
        return

    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    import scenario_utils

    if scenario_utils.scenarios_share_a_provider(baseline_scenario, target_scenario):
        return

    baseline_provider = scenario_utils.scenario_provider(baseline_scenario)
    target_provider = scenario_utils.scenario_provider(target_scenario)
    message = (
        f"[{run_name}] baseline_scenario provider '{baseline_provider}' "
        f"({baseline_scenario!r}) does not match target_scenario provider "
        f"'{target_provider}' ({target_scenario!r}). Mixing IAM providers "
        f"between baseline and target is not enforced by the pipeline itself "
        f"(it silently intersects geographies/technologies and warns), but "
        f"it is almost never intentional."
    )
    if allow_cross_provider:
        log(f"WARNING: {message} Proceeding because allow_cross_provider=True.")
        return
    raise ScenarioProviderMismatch(
        f"{message} Pass allow_cross_provider=True (CLI: "
        f"--allow-cross-provider-scenarios) to run it anyway."
    )


def run_batch(
    run_configurations: Mapping[str, Mapping],
    workspace_dir: Path | str,
    tags: Sequence[str] = ("altrisk",),
    company_ids: Iterable[str] | None = None,
    scenarios_csv: Path | str | None = None,
    allow_cross_provider: bool = False,
    project_path: Path | str | None = None,
    log: Callable[[str], None] = print,
) -> pd.DataFrame:
    """Run one ``kedro run`` per entry of ``run_configurations``.

    Parameters
    ----------
    run_configurations:
        ``{run_name: {param: value, ...}}``. Each entry is passed as
        ``extra_params`` to a fresh ``KedroSession`` and overrides
        ``conf/base`` for that run only.
    workspace_dir:
        Root folder each run's outputs are copied into, under
        ``workspace_dir/<run_name>/``.
    tags:
        Kedro tags to run, e.g. ``["altrisk"]`` or ``["altrisk", "reporting"]``.
    company_ids:
        If given, overrides ``company_ids`` on every run (this is how a
        single uploaded company selection gets applied across all
        configurations). If omitted, each run's own ``company_ids`` (or the
        ``conf/base`` default - all companies) is used.
    scenarios_csv:
        Path to ``scenarios.csv``, used only to validate that each run's
        baseline/target scenarios share a provider. Pass ``None`` to skip
        this check entirely.
    allow_cross_provider:
        If False (default), a run whose baseline/target scenarios come from
        different providers is skipped (recorded as ``failed``) instead of
        executed.
    project_path:
        Kedro project root. Defaults to the repo this script lives in.
    log:
        Called with one message string per line of progress. Defaults to
        ``print``; the Streamlit app passes a callback that renders into
        the page so progress streams live instead of appearing only at the
        end.

    Returns
    -------
    A DataFrame with one row per run: ``run_name``, ``status``
    (``"success"`` or ``"failed"``), ``output_dir``, ``error``,
    ``elapsed_seconds``.
    """
    from kedro.framework.session import KedroSession
    from kedro.framework.startup import bootstrap_project

    project_path = Path(project_path) if project_path else PROJECT_ROOT
    bootstrap_project(project_path=project_path)

    workspace_dir = Path(workspace_dir)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    company_ids = list(company_ids) if company_ids is not None else None
    tags = list(tags)

    records = []
    total_runs = len(run_configurations)

    for idx, (run_name, base_params) in enumerate(run_configurations.items(), start=1):
        run_params = dict(base_params)
        if company_ids is not None:
            run_params["company_ids"] = company_ids

        safe_run_name = _sanitize_run_name(run_name)
        run_workspace_dir = workspace_dir / safe_run_name

        log("=" * 60)
        log(f"Run {idx}/{total_runs}: {run_name}")
        log("=" * 60)

        start = time.monotonic()
        try:
            _validate_scenario_pairing(
                run_name, run_params, scenarios_csv, allow_cross_provider, log
            )

            with KedroSession.create(
                project_path=project_path,
                extra_params=run_params,
            ) as session:
                session.run(pipeline_name="__default__", tags=tags)

            run_id = uuid.uuid4()
            run_workspace_dir.mkdir(parents=True, exist_ok=True)

            for filename in MODEL_OUTPUT_FILES:
                src = MODEL_OUTPUT_DIR / filename
                if not src.exists():
                    continue
                df = pd.read_csv(src)
                df["run_id"] = run_id
                df.to_csv(run_workspace_dir / filename, index=False)

            run_params_df = pd.DataFrame([run_params])
            run_params_df["run_id"] = run_id
            run_params_df["run_name"] = run_name
            run_params_df.to_csv(run_workspace_dir / "run_params.csv", index=False)

            if "reporting" in tags:
                for folder in REPORTING_FOLDERS:
                    src_dir = REPORTING_DIR / folder
                    dst_dir = run_workspace_dir / folder
                    if not src_dir.exists():
                        continue
                    if dst_dir.exists():
                        shutil.rmtree(dst_dir)
                    shutil.copytree(src_dir, dst_dir)
                    log(f"Copied {folder} to {dst_dir}")

            elapsed = time.monotonic() - start
            log(f"Completed {run_name} in {elapsed:.1f}s -> {run_workspace_dir}")
            records.append(
                {
                    "run_name": run_name,
                    "status": "success",
                    "output_dir": str(run_workspace_dir),
                    "error": None,
                    "elapsed_seconds": round(elapsed, 1),
                }
            )
        except Exception as exc:
            elapsed = time.monotonic() - start
            error_msg = f"{exc}\n{traceback.format_exc()}"
            error_file = workspace_dir / f"{safe_run_name}_error.txt"
            error_file.write_text(error_msg)
            log(f"FAILED {run_name} after {elapsed:.1f}s - see {error_file}")
            records.append(
                {
                    "run_name": run_name,
                    "status": "failed",
                    "output_dir": None,
                    "error": str(exc),
                    "elapsed_seconds": round(elapsed, 1),
                }
            )
            continue

    summary = pd.DataFrame.from_records(records)
    summary.to_csv(workspace_dir / "run_manifest.csv", index=False)
    log("=" * 60)
    n_success = (summary["status"] == "success").sum() if len(summary) else 0
    log(f"Done: {n_success}/{total_runs} runs succeeded. Manifest: {workspace_dir / 'run_manifest.csv'}")
    return summary


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--run-configurations",
        required=True,
        type=Path,
        help="YAML or JSON file with a {run_name: {param: value, ...}} mapping.",
    )
    parser.add_argument(
        "--company-ids",
        type=Path,
        default=None,
        help="CSV/TXT/YAML/JSON file listing company ids to restrict every run to. "
        "Omit to use each run's own company_ids (default: all companies).",
    )
    parser.add_argument(
        "--workspace-dir",
        type=Path,
        default=PROJECT_ROOT / "workspace" / "results_batch",
        help="Root folder each run's outputs are copied into (default: %(default)s).",
    )
    parser.add_argument(
        "--tags",
        default="altrisk",
        help="Comma-separated kedro tags to run (default: altrisk). "
        "Use 'altrisk,reporting' to also produce plots.",
    )
    parser.add_argument(
        "--scenarios-csv",
        type=str,
        default=str(PROJECT_ROOT / "data" / "05_model_input" / "scenarios.csv"),
        help="Used to validate baseline/target scenarios share a provider "
        "(default: %(default)s). Pass an empty string to skip the check.",
    )
    parser.add_argument(
        "--allow-cross-provider-scenarios",
        action="store_true",
        help="Allow a run whose baseline/target scenarios come from different "
        "IAM providers instead of skipping it.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    run_configurations = load_run_configurations(args.run_configurations)
    company_ids = (
        load_company_ids(args.company_ids) if args.company_ids is not None else None
    )
    scenarios_csv = args.scenarios_csv or None
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    summary = run_batch(
        run_configurations,
        workspace_dir=args.workspace_dir,
        tags=tags,
        company_ids=company_ids,
        scenarios_csv=scenarios_csv,
        allow_cross_provider=args.allow_cross_provider_scenarios,
    )
    return 0 if (summary["status"] == "success").all() else 1


if __name__ == "__main__":
    sys.exit(main())
