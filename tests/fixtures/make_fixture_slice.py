"""Build a small, schema-identical slice of the model inputs for fast regression runs.

Reads the FULL inputs from the main working tree (source of truth for current
data) and writes the slice into tests/fixtures/data/, which is committed.
Selection: the N companies with the fewest assets that still span >=3
technologies, one scenario pair. Re-run whenever upstream inputs change.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "data"
SCENARIO_SUBSTRINGS = ("CO_CurPol", "CO_2Deg2030", "CO_BAU", "CO_2Deg2020")
N_COMPANIES = 5


def pick_companies(companies: pd.DataFrame, assets: pd.DataFrame) -> list[str]:
    merged = companies.merge(assets[["asset_id", "technology"]].drop_duplicates(), on="asset_id")
    stats = merged.groupby("company_id").agg(n_assets=("asset_id", "nunique"), n_tech=("technology", "nunique"))
    ranked = stats.sort_values(["n_tech", "n_assets"], ascending=[False, True])
    return ranked.head(N_COMPANIES).index.tolist()


def build(source: Path) -> None:
    assets = pd.read_csv(source / "downloaded_assets.csv", low_memory=False)
    companies = pd.read_csv(source / "downloaded_companies.csv", low_memory=False)
    chosen = pick_companies(companies, assets)
    comp_slice = companies[companies["company_id"].isin(chosen)]
    asset_slice = assets[assets["asset_id"].isin(comp_slice["asset_id"])]

    scen_path = source / "downloaded_scenarios.csv"
    scen = pd.read_csv(scen_path, low_memory=False)
    col = "scenario" if "scenario" in scen.columns else "scenario_name"
    mask = scen[col].apply(lambda n: any(s in str(n) for s in SCENARIO_SUBSTRINGS))
    scen_slice = scen[mask]

    OUT.mkdir(parents=True, exist_ok=True)
    asset_slice.to_csv(OUT / "downloaded_assets.csv", index=False)
    comp_slice.to_csv(OUT / "downloaded_companies.csv", index=False)
    scen_slice.to_csv(OUT / "downloaded_scenarios.csv", index=False)
    print(f"fixture: {comp_slice['company_id'].nunique()} companies, "
          f"{asset_slice['asset_id'].nunique()} assets, {scen_slice[col].nunique()} scenarios")


if __name__ == "__main__":
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path,
                    default=os.environ.get("ALTR_FULL_INPUTS"),
                    help="Directory with full downloaded_* inputs (or set ALTR_FULL_INPUTS)")
    args = ap.parse_args()
    if not args.source:
        raise SystemExit("pass --source or set ALTR_FULL_INPUTS")
    build(Path(args.source))
