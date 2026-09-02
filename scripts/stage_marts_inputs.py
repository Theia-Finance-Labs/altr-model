"""Stage a BigQuery-marts drop into the deliverables contract `prepare_inputs` reads.

The marts export and the "ALTR deliverables" drop are the same data under two
naming conventions. `scripts/prepare_inputs.py` speaks the deliverables one
(`year`, `scenario_name`); the marts export speaks its own (`production_year`,
`scenario_year`, `scenario`). This script is the adapter between them, so a
marts drop can go through the same validated conversion path as a deliverables
drop rather than being hand-copied into `data/05_model_input/`.

It writes ONLY into `data/01_raw/`. Nothing here touches model code, and
`scripts/prepare_inputs.py` still performs every validation afterwards.

Transformations
---------------
assets      `production_year` -> `year`. Nothing else; `workforce_size` and the
            other extra marts columns ride along untouched.
companies   `production_year` -> `year`, plus `asset_name` / `sector` /
            `technology` joined on `asset_id` from the assets file. The marts
            companies export omits those three, but `_consolidate_ownership_
            stakes` groups on `sector`/`technology` and carries `asset_name`,
            so `prepare_inputs.COMPANIES_REQUIRED` demands them. They are
            constant per `asset_id` (asserted below), so the join is a pure
            widening -- it cannot change the row count, which is checked.
scenarios   `scenario_year` -> `year`, and the `AR6_<provider>_` prefix is
            RESTORED onto the scenario name, which is then emitted as
            `scenario_name` (`prepare_inputs.build_scenarios` renames it back to
            `scenario`; the round-trip is kept so the marts drop enters through
            the same validated door as every other drop).

            The prefix matters. Several comments in this repo claim
            `filter_scenarios` prepends `AR6_<provider>_` automatically -- it
            does NOT. `_input_nodes.filter_scenarios` asserts the configured
            scenario name is present in the `scenario` column verbatim and
            performs no prefixing, and the committed fixture
            (`tests/fixtures/data/scenarios.csv`) accordingly stores the FULL
            name `AR6_WITCH 5.0_EN_NoPolicy`. The upstream marts extract strips
            the prefix because crispy-kedro's batch runner re-added it; nothing
            in this repo does, so staging must. Prefixing is idempotent: a name
            that already carries its provider prefix is left alone.

Usage
-----
    python scripts/stage_marts_inputs.py \
        --assets   /path/to/downloaded_assets.csv \
        --companies /path/to/downloaded_companies.csv \
        --scenarios /path/to/ar6_scenarios_<stamp>.csv

then the normal conversion::

    python scripts/prepare_inputs.py
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DEST = REPO / "data" / "01_raw"

#: Columns the marts companies export omits but `prepare_inputs` requires.
#: Constant per `asset_id`, so they can be recovered from the assets file.
ASSET_ATTRIBUTES = ["asset_name", "sector", "technology"]


def sha256(path: Path) -> str:
    """Hash a file in chunks -- these inputs are ~130MB."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stage_assets(source: Path) -> pd.DataFrame:
    frame = pd.read_csv(source, low_memory=False)
    return frame.rename(columns={"production_year": "year"})


def stage_companies(source: Path, assets: pd.DataFrame) -> pd.DataFrame:
    frame = pd.read_csv(source, low_memory=False)
    frame = frame.rename(columns={"production_year": "year"})

    missing = [c for c in ASSET_ATTRIBUTES if c not in frame.columns]
    if not missing:
        return frame

    lookup = assets[["asset_id", *missing]].drop_duplicates()
    ambiguous = int((lookup.groupby("asset_id").size() > 1).sum())
    if ambiguous:
        raise SystemExit(
            f"companies: cannot recover {missing} -- {ambiguous:,} asset_ids "
            "carry more than one value in the assets file, so the join would "
            "duplicate ownership rows and over-allocate capacity."
        )

    before = len(frame)
    frame = frame.merge(lookup, on="asset_id", how="left")
    if len(frame) != before:
        raise SystemExit(
            f"companies: attribute join changed row count {before:,} -> {len(frame):,}"
        )
    unmatched = int(frame[missing[0]].isna().sum())
    if unmatched:
        print(  # noqa: T201
            f"  warning: {unmatched:,} ownership rows have no matching asset"
        )
    print(f"  recovered {missing} from the assets file")  # noqa: T201
    return frame


def stage_scenarios(source: Path) -> pd.DataFrame:
    frame = pd.read_csv(source, low_memory=False)
    frame = frame.rename(columns={"scenario_year": "year"})

    prefix = "AR6_" + frame.scenario_provider.astype(str).str.strip() + "_"
    names = frame.scenario.astype(str)
    prefixed = [n if n.startswith(p) else p + n for n, p in zip(names, prefix)]
    restored = sum(n != o for n, o in zip(prefixed, names))

    frame["scenario_name"] = prefixed
    frame = frame.drop(columns=["scenario"])
    print(  # noqa: T201
        f"  AR6_<provider>_ prefix: restored on {restored:,} rows, "
        f"already present on {len(frame) - restored:,}"
    )
    return frame


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--assets", type=Path, required=True)
    ap.add_argument("--companies", type=Path, required=True)
    ap.add_argument("--scenarios", type=Path, required=True)
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    args = ap.parse_args()

    for label, path in (
        ("assets", args.assets),
        ("companies", args.companies),
        ("scenarios", args.scenarios),
    ):
        print(f"{label}: {path}")  # noqa: T201
        print(f"  sha256 {sha256(path)}")  # noqa: T201

    assets = stage_assets(args.assets)
    built = [
        ("assets", assets, "assets_forecasts.csv"),
        ("companies", stage_companies(args.companies, assets), "companies_ownerships.csv"),
        ("scenarios", stage_scenarios(args.scenarios), "scenarios.csv"),
    ]

    args.dest.mkdir(parents=True, exist_ok=True)
    for label, frame, name in built:
        out = args.dest / name
        frame.to_csv(out, index=False)
        print(f"{label}: wrote {out} ({len(frame):,} rows)")  # noqa: T201


if __name__ == "__main__":
    main()
