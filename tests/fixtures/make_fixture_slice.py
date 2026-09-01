"""Build a small, schema-identical slice of the model inputs for fast regression runs.

Reads the FULL inputs from the main working tree (source of truth for current
data) and writes the slice into tests/fixtures/data/, which is committed.

Selection: the N companies that span the most technologies with the fewest
assets, restricted to companies that own assets *directly* — the pipeline runs
with ``ownership_type: "direct"``, so equity-only companies never reach the
outputs and make for a useless fixture. All ownership rows of the chosen
companies are kept so the filter itself stays exercised.

Scenarios: the pipeline consumes the EXTENDED scenario table (cost columns:
lifetime_years, capital_cost_usd_per_mw, carbon_price_usd_per_tco2, ...), which
is NOT ``<source>/downloaded_scenarios.csv``. Point ``--scenarios`` at the file
the catalog actually resolves to (internally, the per-provider extract under
``workspace/_temp_scenario_csvs/``); it defaults to the source directory's
``downloaded_scenarios.csv`` for setups where that file is already the extended
one. The scenario pair used by ``conf/fixture`` must be present in it.

Carbon prices: ``--carbon-prices`` points at the AR6 reference extract named by
the ``ar6_carbon_prices`` catalog entry; it is copied verbatim (it is small).

Re-run whenever upstream inputs change, then re-pin
``tests/integration/test_fixture_run.py``.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "data"
N_COMPANIES = 5
MIN_TECHNOLOGIES = 3
DIRECT_OWNERSHIP = "direct"


def pick_companies(companies: pd.DataFrame, assets: pd.DataFrame) -> list[str]:
    direct = companies[companies["ownership_type"] == DIRECT_OWNERSHIP]
    merged = direct.merge(
        assets[["asset_id", "technology"]].drop_duplicates(), on="asset_id"
    )
    stats = merged.groupby("company_id").agg(
        n_assets=("asset_id", "nunique"), n_tech=("technology", "nunique")
    )
    eligible = stats[stats["n_tech"] >= MIN_TECHNOLOGIES]
    ranked = eligible.sort_values(["n_tech", "n_assets"], ascending=[False, True])
    return ranked.head(N_COMPANIES).index.tolist()


def build(source: Path, scenarios: Path, carbon_prices: Path | None) -> None:
    assets = pd.read_csv(source / "downloaded_assets.csv", low_memory=False)
    companies = pd.read_csv(source / "downloaded_companies.csv", low_memory=False)
    chosen = pick_companies(companies, assets)
    comp_slice = companies[companies["company_id"].isin(chosen)]
    asset_slice = assets[assets["asset_id"].isin(comp_slice["asset_id"])]

    scen = pd.read_csv(scenarios, low_memory=False)
    col = "scenario" if "scenario" in scen.columns else "scenario_name"

    OUT.mkdir(parents=True, exist_ok=True)
    asset_slice.to_csv(OUT / "downloaded_assets.csv", index=False)
    comp_slice.to_csv(OUT / "downloaded_companies.csv", index=False)
    scen.to_csv(OUT / "downloaded_scenarios.csv", index=False)
    if carbon_prices is not None:
        shutil.copyfile(carbon_prices, OUT / "ar6_carbon_prices.csv")

    print(
        f"fixture: {comp_slice['company_id'].nunique()} companies, "
        f"{asset_slice['asset_id'].nunique()} assets, {scen[col].nunique()} scenarios"
    )


if __name__ == "__main__":
    import os

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--source",
        type=Path,
        default=os.environ.get("ALTR_FULL_INPUTS"),
        help="Directory with full downloaded_* inputs (or set ALTR_FULL_INPUTS)",
    )
    ap.add_argument(
        "--scenarios",
        type=Path,
        default=None,
        help="Extended scenario table the catalog resolves to "
        "(default: <source>/downloaded_scenarios.csv)",
    )
    ap.add_argument(
        "--carbon-prices",
        type=Path,
        default=None,
        help="AR6 carbon-price extract named by the ar6_carbon_prices catalog entry",
    )
    args = ap.parse_args()
    if not args.source:
        raise SystemExit("pass --source or set ALTR_FULL_INPUTS")
    src = Path(args.source)
    build(src, args.scenarios or src / "downloaded_scenarios.csv", args.carbon_prices)
