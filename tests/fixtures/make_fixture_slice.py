"""Build a small, schema-identical slice of the model inputs for fast regression runs.

Reads the FULL inputs from the main working tree (source of truth for current
data) and writes the slice into tests/fixtures/data/, which is committed.

Selection (when ranking): the N companies that span the most technologies with
the fewest assets. Every ownership row of the chosen companies is kept, at every
tier — the tier is a RUN parameter (``ownership_type``), so a slice that pre-
filtered on one would stop the run's own tier selection from being exercised.

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

By default the builder re-cuts the slice on the companies ALREADY in the
committed slice, read off the committed CSV (see ``committed_company_ids``).
Those are the companies the handover branch's committed slice holds, so the two
branches' fixture outputs stay comparable company for company — the
behaviour-equivalence bar in the 2026-09-01 owner ruling. ``--company-ids``
overrides the selection; ``--company-ids`` with no values ranks candidates
instead.

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


def committed_company_ids() -> list[str] | None:
    """The companies already in the committed slice, or None if it is absent.

    Read off the slice rather than written down here: the ids are licensed
    identifiers, so the committed CSV is the one place they belong. Re-running
    the builder therefore reproduces the committed slice by default instead of
    re-ranking candidates and silently cutting a different one — which is what
    keeps this tree's fixture outputs comparable, company for company, with the
    handover branch's slice that the behaviour-equivalence gate measures
    against.
    """
    path = OUT / "companies_ownerships.csv"
    if not path.is_file():
        return None
    ids = pd.read_csv(path, usecols=["company_id"], low_memory=False)["company_id"]
    return sorted(ids.dropna().unique())


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
        default=None,
        help="Company ids to slice on. Default: the ids already in the "
        "committed slice. Pass with no values to rank candidates instead.",
    )
    args = ap.parse_args()
    if not args.source:
        raise SystemExit("pass --source or set ALTR_FULL_INPUTS")
    build(
        Path(args.source),
        args.scenarios or OUT / "scenarios.csv",
        Path(args.deliverables) if args.deliverables else None,
        (
            committed_company_ids()
            if args.company_ids is None
            else (list(args.company_ids) or None)
        ),
    )
