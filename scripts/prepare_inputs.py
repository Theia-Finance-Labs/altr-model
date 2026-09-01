"""Adapt the ALTR deliverables files to the schemas the pipeline consumes.

The deliverables drop and the model inputs are the same data under slightly
different column names. Rather than teach the pipeline a second schema -- which
would make results incomparable to the validated baseline -- this script
reshapes the inputs to the existing contract. Zero pipeline changes.

Usage
-----
Place the three deliverables files in ``data/01_raw/`` and run::

    python scripts/prepare_inputs.py            # or --source / --dest

    data/01_raw/assets_forecasts.csv      -> data/05_model_input/assets_forecasts.csv
    data/01_raw/companies_ownerships.csv  -> data/05_model_input/companies_ownerships.csv
    data/01_raw/scenarios.csv             -> data/05_model_input/scenarios.csv

Transformations
---------------
assets_forecasts.csv        none -- the deliverables schema is already the one
                            ``conf/base/catalog.yml`` declares. Validated, not
                            reshaped.
companies_ownerships.csv    none. ``sector`` / ``technology`` / ``asset_name``
                            are KEPT: ``_consolidate_ownership_stakes`` groups
                            on them, so dropping them breaks the roll-up.
scenarios.csv               ``scenario_name`` -> ``scenario`` (``filter_scenarios``
                            adds the ``AR6_<provider>_`` prefix only where it is
                            absent). ``year`` is left alone -- the pipeline
                            indexes the scenario frame on ``year``.

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
    "asset_id", "sector", "technology", "year", "capacity_unit",
    "capacity", "asset_age", "country_iso2", "country_name", "asset_name",
    "latitude", "longitude", "age_is_inferred",
    "capacity_factor", "emission_factor",
]
# company_name / asset_name / sector / technology are in `_consolidate_ownership
# _stakes`'s group_cols; without them the roll-up raises.
COMPANIES_REQUIRED = [
    "asset_id", "asset_name", "company_id", "company_name", "sector",
    "technology", "year", "ownership_percentage",
]
# Ownership check: an asset-year whose CONSOLIDATED ownership sums above
# OVER_ALLOCATION_PCT is over-allocated, and the warning fires once more than
# OVER_ALLOCATION_SHARE of asset-years exceed it.
OVER_ALLOCATION_PCT = 105
OVER_ALLOCATION_SHARE = 0.01

#: The pipeline hard-indexes the cost columns below (lifetime_years onward), so
#: the bare prices/pathways extract fails deep inside input preparation rather
#: than here. Keep this cost block literally identical to the ``required`` set in
#: ``tests/fixtures/test_fixture_slice.py::test_fixture_scenarios_carry_cost_columns``.
SCENARIOS_REQUIRED = [
    "scenario_provider", "scenario", "scenario_type", "scenario_geography",
    "sector", "technology", "technology_type", "scenario_price",
    "scenario_pathway", "scenario_capacity_factor", "year",
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


def check_ownership_allocation(frame: pd.DataFrame) -> None:
    """Warn if consolidated ownership does not partition the asset.

    ``allocate_assets_to_companies`` does a bare ``capacity *
    ownership_percentage``, so the rows reaching it must partition the asset.
    On this tree ``filter_companies`` does NOT select an ownership tier: it
    calls ``_consolidate_ownership_stakes``, which sums every stake a company
    holds in one asset-year into a single row. That merge is sum-preserving, so
    the question is whether the ownership rows as delivered already sum to
    ~100% per asset-year -- consolidation cannot bring an over-allocated
    universe back under it.

    An extract that flattens every rung of an ownership chain passes a
    duplicate-key check and still over-allocates, because different companies
    on different rungs each claim the same capacity. Uniqueness is necessary
    but not sufficient, which is why this sums instead of counting.

    Warning only: some universes legitimately hold partial ownership.
    """
    sums = frame.groupby(["asset_id", "year"]).ownership_percentage.sum()
    over = float((sums > OVER_ALLOCATION_PCT).mean())
    print(  # noqa: T201
        f"  allocation check: {len(frame):,} rows, "
        f"{sums.index.get_level_values(0).nunique():,} assets, "
        f"sum p50={sums.median():.1f}% max={sums.max():.1f}%, "
        f"within 99-101%={100 * sums.between(99, 101).mean():.1f}%"
    )
    if over > OVER_ALLOCATION_SHARE:
        warnings.warn(
            f"companies: {over:.1%} of asset-years sum to "
            f">{OVER_ALLOCATION_PCT}% (median {sums.median():.1f}%). Capacity "
            "would be over-allocated silently. The delivered ownership rows "
            "must partition the asset (sum to 100%) -- fix this upstream. Note "
            "this is NOT about duplicate stake rows: `_consolidate_ownership_"
            "stakes` totals every stake a company holds in one asset-year into "
            "a single row automatically, and that merge is sum-preserving, so "
            "it cannot bring an over-allocated universe back under 100%.",
            stacklevel=2,
        )


def build_assets(source: Path) -> pd.DataFrame:
    frame = pd.read_csv(source / "assets_forecasts.csv", low_memory=False)
    require_columns(frame, ASSETS_REQUIRED, "assets")
    return frame


def build_companies(source: Path) -> pd.DataFrame:
    frame = pd.read_csv(source / "companies_ownerships.csv", low_memory=False)
    require_columns(frame, COMPANIES_REQUIRED, "companies")
    check_ownership_allocation(frame)
    return frame


def build_scenarios(source: Path) -> pd.DataFrame:
    frame = pd.read_csv(source / "scenarios.csv", low_memory=False)
    require_columns(frame, ["scenario_provider", "scenario_name"], "scenarios")

    # `filter_scenarios` prefixes "AR6_<provider>_" only where it is absent, so
    # names pass through either way — no strip needed, just the rename.
    frame = frame.rename(columns={"scenario_name": "scenario"})
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
        ("assets", build_assets(source), dest / "assets_forecasts.csv"),
        ("companies", build_companies(source), dest / "companies_ownerships.csv"),
        ("scenarios", build_scenarios(source), dest / "scenarios.csv"),
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
