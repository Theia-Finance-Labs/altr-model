"""Build a small, schema-identical slice of the model inputs for fast regression runs.

Reads the FULL inputs from the main working tree (source of truth for current
data) and writes the slice into tests/fixtures/data/, which is committed.

Selection: the N companies that span the most technologies with the fewest
assets. Unlike the pre-migration builder there is no ``ownership_type ==
"direct"`` restriction: ``filter_companies`` no longer selects a tier, it calls
``_consolidate_ownership_stakes`` and SUMS every stake a company holds in an
asset-year, so equity-only companies do reach the outputs and are legitimate
fixture material. All ownership rows of the chosen companies are kept.

Licensing: candidates are intersected with the deliverables drop named by
``ALTR_DELIVERABLES_DIR`` when it is set, so the builder cannot mint a slice
holding an identifier the recipient is not licensed for. That is belt-and-braces
for ``test_fixture_ids_licensed.py``, which is the actual gate.

Scenarios: the pipeline consumes the EXTENDED scenario table (cost columns:
lifetime_years, capital_cost_usd_per_mw, carbon_price_usd_per_tco2, ...), which
is not the bare prices/pathways extract. Point ``--scenarios`` at the file the
catalog resolves to (``scenarios.csv``, as produced by
``scripts/prepare_inputs.py``); it is copied verbatim after the slice's scenario
pair is confirmed present. The scenario pair used by ``conf/fixture`` must be in
it.

Company selection can be pinned explicitly with ``--company-ids``. The committed
slice uses that path: its five ids are the ones the handover branch's committed
slice holds, so the two branches' fixture outputs are comparable company for
company (the behaviour-equivalence bar in the 2026-09-01 owner ruling).

Re-run whenever upstream inputs change, then re-pin
``tests/integration/test_fixture_run.py``.
"""
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "data"
N_COMPANIES = 5
MIN_TECHNOLOGIES = 3

#: The committed slice's companies. Pinned rather than ranked so this tree's
#: fixture outputs line up company-for-company with the handover branch's
#: committed slice, which the behaviour-equivalence gate compares against.
COMMITTED_COMPANY_IDS = [
    "CN_3371785431787292505",
    "CN_6166477550945836346",
    "CN_6488161088428600082",
    "CN_8676642915009364747",
    "CP_3685197042895689972",
]


def licensed_company_ids(deliverables: Path | None) -> set[str] | None:
    """The licensed company universe, or None when no drop is mounted."""
    if deliverables is None:
        return None
    path = deliverables / "companies_ownerships.csv"
    if not path.is_file():
        return None
    return set(
        pd.read_csv(path, usecols=["company_id"], low_memory=False)["company_id"].dropna()
    )


def pick_companies(
    companies: pd.DataFrame,
    assets: pd.DataFrame,
    licensed: set[str] | None,
) -> list[str]:
    """The N companies spanning the most technologies with the fewest assets."""
    candidates = companies
    if licensed is not None:
        candidates = candidates[candidates["company_id"].isin(licensed)]
    # Both frames carry `technology` on main; keep the asset's, not the stake's.
    merged = candidates[["company_id", "asset_id"]].drop_duplicates().merge(
        assets[["asset_id", "technology"]].drop_duplicates(), on="asset_id"
    )
    stats = merged.groupby("company_id").agg(
        n_assets=("asset_id", "nunique"), n_tech=("technology", "nunique")
    )
    eligible = stats[stats["n_tech"] >= MIN_TECHNOLOGIES]
    ranked = eligible.sort_values(["n_tech", "n_assets"], ascending=[False, True])
    return ranked.head(N_COMPANIES).index.tolist()


def build(
    source: Path,
    scenarios: Path,
    deliverables: Path | None,
    company_ids: list[str] | None = None,
) -> None:
    assets = pd.read_csv(source / "assets_forecasts.csv", low_memory=False)
    companies = pd.read_csv(source / "companies_ownerships.csv", low_memory=False)

    chosen = company_ids or pick_companies(
        companies, assets, licensed_company_ids(deliverables)
    )
    comp_slice = companies[companies["company_id"].isin(chosen)]
    asset_slice = assets[assets["asset_id"].isin(comp_slice["asset_id"])]

    OUT.mkdir(parents=True, exist_ok=True)
    asset_slice.to_csv(OUT / "assets_forecasts.csv", index=False)
    comp_slice.to_csv(OUT / "companies_ownerships.csv", index=False)
    if scenarios.resolve() != (OUT / "scenarios.csv").resolve():
        shutil.copyfile(scenarios, OUT / "scenarios.csv")

    scen = pd.read_csv(OUT / "scenarios.csv", usecols=["scenario"], low_memory=False)
    print(  # noqa: T201
        f"fixture: {comp_slice['company_id'].nunique()} companies, "
        f"{asset_slice['asset_id'].nunique()} assets, "
        f"{scen['scenario'].nunique()} scenarios"
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--source",
        type=Path,
        default=os.environ.get("ALTR_FULL_INPUTS"),
        help="Directory with full assets_forecasts.csv / companies_ownerships.csv "
        "(or set ALTR_FULL_INPUTS)",
    )
    ap.add_argument(
        "--scenarios",
        type=Path,
        default=None,
        help="Extended scenario table the catalog resolves to "
        "(default: the committed tests/fixtures/data/scenarios.csv)",
    )
    ap.add_argument(
        "--deliverables",
        type=Path,
        default=os.environ.get("ALTR_DELIVERABLES_DIR") or None,
        help="Licensed universe to restrict candidates to "
        "(or set ALTR_DELIVERABLES_DIR)",
    )
    ap.add_argument(
        "--company-ids",
        nargs="*",
        default=COMMITTED_COMPANY_IDS,
        help="Company ids to slice on (default: the committed slice's five). "
        "Pass with no values to rank candidates instead.",
    )
    args = ap.parse_args()
    if not args.source:
        raise SystemExit("pass --source or set ALTR_FULL_INPUTS")
    build(
        Path(args.source),
        args.scenarios or OUT / "scenarios.csv",
        Path(args.deliverables) if args.deliverables else None,
        list(args.company_ids) or None,
    )
