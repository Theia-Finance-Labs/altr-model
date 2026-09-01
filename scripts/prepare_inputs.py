"""Adapt the ALTR deliverables files to the schemas the pipeline consumes.

The deliverables drop and the model inputs are the same data under slightly
different column names. Rather than teach the pipeline a second schema -- which
would make results incomparable to the validated baseline -- this script
reshapes the inputs to the existing contract. Zero pipeline changes.

Usage
-----
Place the three deliverables files in ``data/01_raw/`` and run::

    python scripts/prepare_inputs.py            # or --source / --dest

    data/01_raw/assets_forecasts.csv      -> data/05_model_input/downloaded_assets.csv
    data/01_raw/companies_ownerships.csv  -> data/05_model_input/downloaded_companies.csv
    data/01_raw/scenarios.csv             -> data/05_model_input/downloaded_scenarios.csv

Transformations
---------------
assets_forecasts.csv        ``year`` -> ``production_year``; ``workforce_size``
                            added (NaN -- its only consumer is a sum agg in
                            ``inputs_postproc``).
companies_ownerships.csv    ``year`` -> ``production_year``;
                            ``sector`` / ``technology`` / ``asset_name`` dropped
                            (``filter_companies`` projects them away before the
                            merge, so they never reach the join).
scenarios.csv               ``scenario_name`` -> ``scenario`` (``filter_scenarios``
                            adds the ``AR6_<provider>_`` prefix only where it is
                            absent); ``year`` -> ``scenario_year``.

Everything is transformed and validated BEFORE anything is written, so a failed
check cannot leave the model inputs half-swapped.
"""

from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = REPO / "data" / "01_raw"
DEFAULT_DEST = REPO / "data" / "05_model_input"

# Column contract required by conf/base/catalog.yml and the consuming nodes.
ASSETS_REQUIRED = [
    "asset_id", "sector", "technology", "production_year", "capacity_unit",
    "capacity", "asset_age", "country_iso2", "country_name", "asset_name",
    "latitude", "longitude", "age_is_inferred", "workforce_size",
    "capacity_factor", "emission_factor",
]
COMPANIES_REQUIRED = [
    "asset_id", "company_name", "company_id", "production_year",
    "ownership_percentage",
]
# Ownership-tier check: an asset-year whose ownership sums above
# OVER_ALLOCATION_PCT is over-allocated, and the warning fires once more than
# OVER_ALLOCATION_SHARE of asset-years exceed it.
OVER_ALLOCATION_PCT = 105
OVER_ALLOCATION_SHARE = 0.01

#: The pipeline hard-indexes the cost columns below (lifetime_years onward), so
#: the bare prices/pathways extract fails deep inside inputs_processing rather
#: than here. Keep this cost block literally identical to the ``required`` set in
#: ``tests/fixtures/test_fixture_slice.py::test_fixture_scenarios_carry_cost_columns``.
SCENARIOS_REQUIRED = [
    "scenario_provider", "scenario", "scenario_type", "scenario_geography",
    "sector", "technology", "technology_type", "scenario_price",
    "scenario_pathway", "scenario_capacity_factor", "scenario_year",
    "country_iso2_list",
    "lifetime_years", "efficiency_decimal", "capital_cost_usd_per_mw",
    "om_cost_usd_per_mw_per_yr", "capacity_additions_mw_per_yr",
    "scrap_usd_per_mw", "carbon_price_usd_per_tco2", "fuel_price",
]


def require_columns(frame: pd.DataFrame, cols: list[str], label: str) -> None:
    """Raise ``ValueError`` naming every required column the frame lacks."""
    missing = [c for c in cols if c not in frame.columns]
    if missing:
        raise ValueError(f"{label}: missing required columns {missing}")


def check_ownership_tier(frame: pd.DataFrame, ownership_type: str = "direct") -> None:
    """Warn if the tier the PIPELINE WILL SELECT does not sum to ~100%.

    ``allocate_assets_to_companies`` does a bare ``capacity * ownership_percentage``,
    so the rows reaching it must partition the asset. ``filter_companies`` picks
    them in this order:

      1. ``ownership_type == params:ownership_type``  ("direct")
      2. ``ownership_level == 1``  (legacy; level 1 is the PARENT of the operator,
         level 0 is the operator itself)
      3. neither column -> keep ALL rows

    Branch 3 is the trap: an extract with no tier column and zero duplicate
    ``(asset_id, company_id, year)`` keys can still flatten every rung of the
    ownership chain, so a median asset-year sums well above 100%. Uniqueness is
    necessary but NOT sufficient -- different companies on different rungs each
    claim the same capacity. This mirrors the pipeline's choice and checks the sum.

    Duplicate stake rows are handled downstream and are not what this checks:
    ``filter_companies`` totals every stake a company holds in one asset-year
    into a single row. That merge is sum-preserving, so it changes the row count
    and never the sums below.

    Warning only: some universes legitimately hold partial ownership. See the
    `ownership_type` entry in `docs/handover/parameters.md` before ignoring it.
    """
    if "ownership_type" in frame.columns:
        selected = frame[frame.ownership_type == ownership_type]
        how = f"ownership_type=='{ownership_type}'"
        if selected.empty:
            warnings.warn(
                f"companies: ownership_type present but no rows match "
                f"'{ownership_type}'. Values: "
                f"{sorted(frame.ownership_type.dropna().unique())}",
                stacklevel=2,
            )
            return
    elif "ownership_level" in frame.columns:
        selected, how = frame[frame.ownership_level == 1], "ownership_level==1"
    else:
        selected, how = frame, "ALL ROWS (no tier column)"

    sums = selected.groupby(["asset_id", "production_year"]).ownership_percentage.sum()
    over = float((sums > OVER_ALLOCATION_PCT).mean())
    print(  # noqa: T201
        f"  tier check [{how}]: {len(selected):,} rows, "
        f"{sums.index.get_level_values(0).nunique():,} assets, "
        f"sum p50={sums.median():.1f}% max={sums.max():.1f}%, "
        f"within 99-101%={100 * sums.between(99, 101).mean():.1f}%"
    )
    if over > OVER_ALLOCATION_SHARE:
        warnings.warn(
            f"companies: {over:.1%} of asset-years sum to "
            f">{OVER_ALLOCATION_PCT}% under {how} "
            f"(median {sums.median():.1f}%). Capacity would be over-allocated "
            "silently. The selected tier must partition the asset (sum to 100%) "
            "-- fix this upstream; see `ownership_type` in "
            "docs/handover/parameters.md. Note this is NOT about duplicate stake "
            "rows: `filter_companies` now totals every stake a company holds in "
            "one asset-year into a single row automatically, and that merge is "
            "sum-preserving, so it cannot bring an over-allocated tier back "
            "under 100%.",
            stacklevel=2,
        )


def build_assets(source: Path) -> pd.DataFrame:
    frame = pd.read_csv(source / "assets_forecasts.csv", low_memory=False)
    frame = frame.rename(columns={"year": "production_year"})
    frame["workforce_size"] = pd.NA
    require_columns(frame, ASSETS_REQUIRED, "assets")
    return frame


def build_companies(source: Path) -> pd.DataFrame:
    frame = pd.read_csv(source / "companies_ownerships.csv", low_memory=False)
    frame = frame.rename(columns={"year": "production_year"})
    frame = frame.drop(
        columns=[c for c in ("sector", "technology", "asset_name") if c in frame.columns]
    )
    require_columns(frame, COMPANIES_REQUIRED, "companies")
    check_ownership_tier(frame)
    return frame


def build_scenarios(source: Path) -> pd.DataFrame:
    frame = pd.read_csv(source / "scenarios.csv", low_memory=False)
    require_columns(frame, ["scenario_provider", "scenario_name"], "scenarios")

    # `filter_scenarios` prefixes "AR6_<provider>_" only where it is absent, so
    # names pass through either way — no strip needed, just the rename.
    frame = frame.rename(
        columns={"scenario_name": "scenario", "year": "scenario_year"}
    )
    require_columns(frame, SCENARIOS_REQUIRED, "scenarios")
    return frame


def check_asset_overlap(assets: pd.DataFrame, companies: pd.DataFrame) -> None:
    """Fail before writing if no asset is owned by any company."""
    overlap = set(assets.asset_id) & set(companies.asset_id)
    if not overlap:
        raise ValueError("no asset overlap between assets and companies")
    print(  # noqa: T201
        f"asset/company overlap: {len(overlap):,} "
        f"({100 * len(overlap) / assets.asset_id.nunique():.1f}% of assets)"
    )


def prepare(source: Path, dest: Path) -> None:
    """Build and validate all three inputs, then write them."""
    built = [
        ("assets", build_assets(source), dest / "downloaded_assets.csv"),
        ("companies", build_companies(source), dest / "downloaded_companies.csv"),
        ("scenarios", build_scenarios(source), dest / "downloaded_scenarios.csv"),
    ]
    check_asset_overlap(built[0][1], built[1][1])

    dest.mkdir(parents=True, exist_ok=True)
    for name, frame, out in built:
        frame.to_csv(out, index=False)
        print(f"{name}: wrote {out.name}: {len(frame):,} rows")  # noqa: T201


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Adapt the ALTR deliverables files to the model input schemas."
    )
    parser.add_argument(
        "--source", type=Path, default=DEFAULT_SOURCE,
        help="Directory holding assets_forecasts.csv / companies_ownerships.csv "
             "/ scenarios.csv (default: data/01_raw)",
    )
    parser.add_argument(
        "--dest", type=Path, default=DEFAULT_DEST,
        help="Directory the pipeline reads its inputs from "
             "(default: data/05_model_input)",
    )
    args = parser.parse_args(argv)
    prepare(args.source, args.dest)


if __name__ == "__main__":
    main()
