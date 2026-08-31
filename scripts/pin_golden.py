"""Pin a full model run as the golden baseline.

Snapshots the key output tables of a completed run to parquet under
`tests/golden/snapshots/` plus a `manifest.json`, so `tests/golden/test_golden.py`
can compare later runs against them with a numeric tolerance.

Usage (from the repo root of the tree that holds the run):

    python scripts/pin_golden.py --run-dir data/07_model_output

Copy the resulting `tests/golden/snapshots/` directory into any other checkout
that should be gated on the same baseline. Re-pin whenever the inputs change
(e.g. when the carbon-price data fix lands).
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# Filenames from conf/base/catalog.yml: the earnings series plus the four
# valuation tables the model is judged on.
KEY_TABLES = (
    "asset_earnings.csv",
    "yearly_npv_trajectories.csv",
    "asset_npv.csv",
    "company_technology_npv.csv",
    "company_npv.csv",
)

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "tests" / "golden" / "snapshots"


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _as_source_path(csv: Path) -> str:
    """Path recorded in the manifest: relative to cwd when possible."""
    try:
        return str(csv.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(csv.resolve())


def pin(run_dir: Path, out_dir: Path) -> list[dict[str, str]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pinned_at = datetime.now(timezone.utc).isoformat()
    sha = _git_sha()
    tables: list[dict[str, str]] = []
    for name in KEY_TABLES:
        matches = sorted(run_dir.rglob(name))
        if not matches:
            print(f"skip: {name} not found under {run_dir}")  # noqa: T201
            continue
        csv = matches[0]
        snapshot = f"{csv.stem}.parquet"
        frame = pd.read_csv(csv, low_memory=False)
        frame.to_parquet(out_dir / snapshot, index=False)
        tables.append(
            {
                "source": _as_source_path(csv),
                "snapshot": snapshot,
                "pinned_at": pinned_at,
                "git_sha": sha,
                "rows": str(len(frame)),
            }
        )
        print(f"pinned: {csv} -> {snapshot} ({len(frame)} rows)")  # noqa: T201
    if not tables:
        raise SystemExit(f"no key output tables found under {run_dir}")
    (out_dir / "manifest.json").write_text(
        json.dumps({"pinned_at": pinned_at, "git_sha": sha, "tables": tables}, indent=2)
    )
    return tables


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--run-dir",
        type=Path,
        required=True,
        help="Directory holding a completed run's outputs (e.g. data/07_model_output)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="Where to write snapshots (default: tests/golden/snapshots)",
    )
    args = ap.parse_args()
    if not args.run_dir.is_dir():
        raise SystemExit(f"--run-dir does not exist: {args.run_dir}")
    tables = pin(args.run_dir, args.out)
    print(f"manifest: {args.out / 'manifest.json'} ({len(tables)} tables)")  # noqa: T201


if __name__ == "__main__":
    main()
