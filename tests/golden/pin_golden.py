"""Pin a full model run as the golden baseline.

Snapshots the key output tables of a completed run to parquet under
`tests/golden/snapshots/` plus a `manifest.json`, so `tests/golden/test_golden.py`
can compare later runs against them with a numeric tolerance.

Usage (from the repo root of the tree that holds the run):

    python tests/golden/pin_golden.py --run-dir data/07_model_output \
        --require-sha <the commit the run was produced by>

Copy the resulting `tests/golden/snapshots/` directory into any other checkout
that should be gated on the same baseline. Re-pin whenever the inputs change
(e.g. when the carbon-price data fix lands).

**The stale-pin rule.** `--require-sha` is mandatory and is NOT the working
tree's HEAD: it is the commit that actually produced the outputs being pinned.
Defaulting to HEAD is how a baseline gets relabelled instead of regenerated —
you fix a bug, forget to re-run, pin, and the manifest now claims outputs the
fixed code never produced. A pin is INVALID unless the outputs were produced by
the exact SHA stamped. If a fix lands after a run, repeat the run; do not
re-label it.
"""

from __future__ import annotations

import argparse
import json
import re
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


#: A git object name: 7-40 lowercase hex characters.
SHA_PATTERN = re.compile(r"\A[0-9a-f]{7,40}\Z")


def _head_sha() -> str:
    """HEAD of the working tree, recorded for information only.

    Never used as the model-run SHA: see the stale-pin rule in the module
    docstring. It is stamped alongside so a reviewer can see whether the tree
    that pinned matched the tree that ran.
    """
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def validate_run_sha(sha: str | None) -> str:
    """The explicit model-run SHA, or a refusal. Never falls back to HEAD."""
    if not sha:
        raise SystemExit(
            "--require-sha is mandatory: pass the commit that PRODUCED this "
            "run. It is not HEAD by default -- a pin is invalid unless the "
            "outputs were produced by the exact SHA stamped, and defaulting to "
            "HEAD relabels a stale run instead of regenerating it."
        )
    if not SHA_PATTERN.match(sha):
        raise SystemExit(
            f"--require-sha is not a git object name: {sha!r} "
            "(expected 7-40 lowercase hex characters)"
        )
    return sha


def _as_source_path(csv: Path, run_dir: Path) -> str:
    """Path recorded in the manifest: relative to the run directory.

    Relative to ``--run-dir`` rather than to the cwd so a snapshot directory
    copied into another checkout still resolves (the test joins these onto the
    manifest's ``run_dir``).
    """
    return str(csv.resolve().relative_to(run_dir.resolve()))


def pin(run_dir: Path, out_dir: Path, run_sha: str) -> list[dict[str, str]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pinned_at = datetime.now(timezone.utc).isoformat()
    head = _head_sha()
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
                "source": _as_source_path(csv, run_dir),
                "snapshot": snapshot,
                "pinned_at": pinned_at,
                "model_run_sha": run_sha,
                "rows": str(len(frame)),
            }
        )
        print(f"pinned: {csv} -> {snapshot} ({len(frame)} rows)")  # noqa: T201
    if not tables:
        raise SystemExit(f"no key output tables found under {run_dir}")
    (out_dir / "manifest.json").write_text(
        json.dumps(
            {
                "pinned_at": pinned_at,
                # The commit that PRODUCED these outputs, passed explicitly.
                "model_run_sha": run_sha,
                # HEAD of the tree that ran the pin, informational only.
                "pinned_from_tree_sha": head,
                # Table sources are relative to this; edit it if the run
                # directory moves rather than re-pinning.
                "run_dir": str(run_dir),
                "tables": tables,
            },
            indent=2,
        )
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
    ap.add_argument(
        "--require-sha",
        default=None,
        help="The commit that PRODUCED this run. Mandatory; never defaults to "
             "HEAD. See the stale-pin rule in this module's docstring.",
    )
    args = ap.parse_args()
    run_sha = validate_run_sha(args.require_sha)
    if not args.run_dir.is_dir():
        raise SystemExit(f"--run-dir does not exist: {args.run_dir}")
    tables = pin(args.run_dir, args.out, run_sha)
    print(f"manifest: {args.out / 'manifest.json'} ({len(tables)} tables)")  # noqa: T201


if __name__ == "__main__":
    main()
