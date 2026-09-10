"""Adapt the 2026-08-25 Dropbox extract to the schemas the ALTR pipeline expects.

The new upstream drop ("ALTR deliverables") renames a few columns and drops
others, but is otherwise the same data the pipeline already consumes. Rather
than change pipeline code -- which would make results incomparable to the
validated v3 baseline -- this script reshapes the inputs to the existing
contract. Zero pipeline changes.

Deltas handled
--------------
assets_forecasts.csv        year -> production_year; workforce_size added (NaN,
                            its only consumer is a sum agg at
                            inputs_postproc/nodes.py:41).
companies_ownerships.csv    year -> production_year; sector/technology/asset_name
                            dropped. (Inert either way: filter_companies projects
                            to [asset_id, company_id, company_name, year,
                            ownership_level, ownership_percentage] at
                            inputs_processing/nodes.py:199-205 before the merge,
                            so extra columns never reach the join.)
                            *** BLOCKED as of 2026-08-25: see check_ownership_tier.
scenarios.csv               scenario_name -> scenario (AR6_<provider>_ prefix
                            stripped, since the batch runner re-adds it);
                            year -> scenario_year. Sliced to the manifest pairs
                            so the runner reads ~50MB instead of 2GB per pair.

Everything is transformed and validated BEFORE anything is written, so a failed
check cannot leave the model inputs half-swapped. Existing inputs are renamed to
*.bak-<stamp>, never deleted.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
# Default source: the BigQuery marts download (src/altr_model/bigquery_marts_downloader.py
# on origin/main). The 2026-08-25 Dropbox drop has the same shape but lacks
# ownership_type; override with --source if reading that instead.
SOURCE = Path("data/05_model_input/bq_20260831")
MODEL_INPUT = REPO / "data" / "05_model_input"

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
SCENARIOS_REQUIRED = [
    "scenario_provider", "scenario", "scenario_type", "scenario_geography",
    "sector", "technology", "technology_type", "scenario_price",
    "scenario_pathway", "scenario_capacity_factor", "scenario_year",
    "country_iso2_list",
]


def require_columns(df: pd.DataFrame, cols: list[str], label: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise SystemExit(f"{label}: missing required columns {missing}")


def check_ownership_tier(df: pd.DataFrame, ownership_type: str = "direct") -> None:
    """Validate the tier the PIPELINE WILL ACTUALLY SELECT sums to ~100%.

    allocate_assets_to_companies does a bare `capacity * ownership_percentage`
    (inputs_processing/nodes.py:567-568), so the rows reaching it must partition
    the asset. filter_companies (nodes.py:152-177) picks them in this order:
      1. ownership_type == params:ownership_type   ("direct")
      2. ownership_level == 1                       (legacy; note level 1 is the
         PARENT of the operator, level 0 is the operator itself)
      3. neither column -> keep ALL rows
    Branch 3 is the trap: the 2026-08-25 extract had no tier column and zero
    duplicate (asset_id, company_id, year) keys, yet flattened all 18 tiers of
    the ownership chain, so a median asset-year summed to 227.5%. Uniqueness is
    necessary but NOT sufficient -- different companies on different rungs each
    claim the same capacity. Mirror the pipeline's choice and check the sum.
    """
    if "ownership_type" in df.columns:
        sel, how = df[df.ownership_type == ownership_type], f"ownership_type=='{ownership_type}'"
        if sel.empty:
            raise SystemExit(
                f"companies: ownership_type present but no rows match "
                f"'{ownership_type}'. Values: {sorted(df.ownership_type.dropna().unique())}"
            )
    elif "ownership_level" in df.columns:
        sel, how = df[df.ownership_level == 1], "ownership_level==1"
    else:
        sel, how = df, "ALL ROWS (no tier column)"

    s = sel.groupby(["asset_id", "production_year"]).ownership_percentage.sum()
    over = float((s > 105).mean())
    print(f"  tier check [{how}]: {len(sel):,} rows, {s.index.get_level_values(0).nunique():,} assets, "
          f"sum p50={s.median():.1f}% max={s.max():.1f}%, within 99-101%={100*s.between(99,101).mean():.1f}%")
    if over > 0.01:
        raise SystemExit(
            f"companies: {over:.1%} of asset-years sum to >105% under {how} "
            f"(median {s.median():.1f}%). Capacity would be over-allocated silently.\n"
            "Fix upstream: the selected tier must partition the asset (sum to 100%)."
        )


def build_assets() -> pd.DataFrame:
    df = pd.read_csv(SOURCE / "assets_forecasts.csv", low_memory=False)
    df = df.rename(columns={"year": "production_year"})
    df["workforce_size"] = pd.NA
    require_columns(df, ASSETS_REQUIRED, "assets")
    return df


def build_companies() -> pd.DataFrame:
    df = pd.read_csv(SOURCE / "companies_ownerships.csv", low_memory=False)
    df = df.rename(columns={"year": "production_year"})
    df = df.drop(columns=[c for c in ("sector", "technology", "asset_name")
                          if c in df.columns])
    require_columns(df, COMPANIES_REQUIRED, "companies")
    check_ownership_tier(df)
    return df


def rebuild_carbon_prices_from_ar6(df: pd.DataFrame, ar6_path: Path) -> pd.DataFrame:
    """Replace carbon_price_usd_per_tco2 with values interpolated from AR6.

    WHY: as of 2026-08-31 the upstream mart
    (cloud-1in1000.bertrand2_marts.altr_scenarios) has a defective carbon price
    column -- the join that attaches it lost its `year` key, so the value is
    frozen at the series' earliest year. Measured at the (scenario, geography,
    technology) grain it varies across years in 0.0% of groups, while
    scenario_price varies in 98.9% and scenario_pathway in 96.1%; it also
    differs between technologies in 29.8% of (scenario, geography, year) groups,
    which it must never do -- a carbon price is per tonne of CO2, not per
    technology. Colleague is fixing it upstream.

    THIS IS A RECONSTRUCTION, NOT SOURCE DATA. AR6 reports carbon prices at
    5-year steps (2025, 2030, ..., 2050); the model needs annual values, so we
    interpolate linearly within each (provider, scenario, geography) series and
    hold the end values flat outside the reported range. Series with fewer than
    two reported points get 0.0 -- that is correct, not a gap: baselines
    (e.g. WITCH EN_NoPolicy, 0/120 points) and the eight providers that publish
    no carbon price at all genuinely have none, and the baseline-vs-target
    carbon differential IS the shock channel.

    Drop this once the mart is fixed; the pipeline's own inject_carbon_prices
    node then stands down on its own because the column arrives populated.
    """
    ar6 = pd.read_csv(ar6_path)
    key = ["scenario_provider", "scenario", "scenario_geography"]
    years = np.arange(int(df.scenario_year.min()), int(df.scenario_year.max()) + 1)

    rebuilt, n_interp = [], 0
    for k, grp in ar6.dropna(subset=["carbon_price_usd_per_tco2"]).groupby(key):
        grp = grp.sort_values("scenario_year")
        if len(grp) < 2:
            continue
        # np.interp holds the endpoints flat outside the reported range.
        vals = np.interp(years, grp.scenario_year.to_numpy(),
                         grp.carbon_price_usd_per_tco2.to_numpy())
        rebuilt.append(pd.DataFrame({
            "scenario_provider": k[0], "scenario": k[1], "scenario_geography": k[2],
            "scenario_year": years, "_cp": vals}))
        n_interp += 1

    if not rebuilt:
        raise SystemExit(f"no interpolable carbon-price series found in {ar6_path}")
    lookup = pd.concat(rebuilt, ignore_index=True)

    before = len(df)
    df = df.merge(lookup, on=key + ["scenario_year"], how="left")
    if len(df) != before:
        raise SystemExit(f"carbon-price merge changed row count {before:,} -> {len(df):,}")
    # Interpolation can emit tiny negatives (~-3e-11) on all-zero baselines;
    # a negative carbon price is meaningless, so floor at 0.
    df["carbon_price_usd_per_tco2"] = df["_cp"].fillna(0.0).clip(lower=0.0)
    df = df.drop(columns=["_cp"])

    matched = 100 * (df.carbon_price_usd_per_tco2 > 0).mean()
    print(f"  carbon prices REBUILT from {ar6_path.name}: {n_interp:,} series interpolated "
          f"to annual, {matched:.1f}% of rows now have a positive price")

    # The two defects this exists to fix must be gone.
    # NB: group on scenario_provider too -- AR6 protocol names like
    # "EN_NPi2020_500" are shared by up to 5 providers in this file (the runner
    # re-adds the AR6_<provider>_ prefix later), so omitting provider conflates
    # unrelated series and makes a correct rebuild look broken.
    gt = df.groupby(["scenario_provider", "scenario", "scenario_geography", "technology"]).agg(
        ny=("scenario_year", "nunique"), nu=("carbon_price_usd_per_tco2", "nunique"),
        mx=("carbon_price_usd_per_tco2", "max"))
    gt = gt[(gt.ny > 1) & (gt.mx > 0)]
    varies = 100 * (gt.nu > 1).mean() if len(gt) else float("nan")
    gy = df.groupby(["scenario_provider", "scenario", "scenario_geography", "scenario_year"]).agg(
        nt=("technology", "nunique"), ncp=("carbon_price_usd_per_tco2", "nunique"),
        mx=("carbon_price_usd_per_tco2", "max"))
    gy = gy[(gy.nt > 1) & (gy.mx > 0)]
    by_tech = 100 * (gy.ncp > 1).mean() if len(gy) else 0.0
    print(f"  validation: varies across years {varies:.1f}% (want ~100) | "
          f"differs by technology {by_tech:.1f}% (want 0)")
    if varies < 95 or by_tech > 0.01:
        raise SystemExit("carbon-price rebuild failed its own validation")
    return df


def build_scenarios(manifest_path: Path, carbon_prices: str = "source",
                    ar6_path: Path | None = None) -> pd.DataFrame:
    src = SOURCE / "scenarios.csv"
    if not src.exists():
        raise SystemExit(f"{src} not found")

    pairs = json.load(open(manifest_path))["scenario_pairs"]
    wanted = {e["baseline_scenario"] for e in pairs} | {e["target_scenario"] for e in pairs}

    # 6.7M x 23 need not be resident; slice while streaming.
    keep = [c[c.scenario_name.isin(wanted)] for c in pd.read_csv(src, chunksize=500_000)]
    df = pd.concat(keep, ignore_index=True)

    # The batch runner strips "AR6_<provider>_" to match, then re-adds it.
    prefix = "AR6_" + df.scenario_provider.astype(str).str.strip() + "_"
    df["scenario"] = [n[len(p):] if n.startswith(p) else n
                      for n, p in zip(df.scenario_name.astype(str), prefix)]
    df = df.rename(columns={"year": "scenario_year"}).drop(columns=["scenario_name"])
    require_columns(df, SCENARIOS_REQUIRED, "scenarios")

    broken = {}
    for e in pairs:
        have = set(df[df.scenario_provider == e["provider"]].scenario)
        pfx = f"AR6_{e['provider']}_"
        b = e["baseline_scenario"].removeprefix(pfx) in have
        t = e["target_scenario"].removeprefix(pfx) in have
        if not (b and t):
            broken[e["provider"]] = {"baseline": b, "target": t}
    if broken:
        raise SystemExit(f"scenarios: manifest pairs unresolvable after reshape: {broken}")

    if carbon_prices == "ar6":
        df = rebuild_carbon_prices_from_ar6(df, ar6_path)
    return df


def write(df: pd.DataFrame, out: Path, stamp: str) -> None:
    if out.exists():
        dest = out.with_suffix(out.suffix + f".bak-{stamp}")
        shutil.move(str(out), str(dest))
        print(f"  backed up {out.name} -> {dest.name}")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)


def main() -> None:
    global SOURCE
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stamp", default="20260831")
    ap.add_argument("--source", type=Path, default=SOURCE,
                    help="Directory holding assets_forecasts.csv / companies_ownerships.csv / scenarios.csv")
    ap.add_argument("--manifest", type=Path,
                    default=REPO / "workspace" / "scenario_manifest.json")
    ap.add_argument("--scenarios-out", type=Path,
                    default=REPO / "ar6_scenarios_20260825.csv")
    ap.add_argument("--carbon-prices", choices=["source", "ar6"], default="source",
                    help="'source' uses the mart's own column; 'ar6' rebuilds it by "
                         "interpolating the AR6 reference to annual (workaround for the "
                         "frozen-carbon-price defect -- a reconstruction, label it as such)")
    ap.add_argument("--ar6-ref", type=Path, default=REPO / "data/01_raw/ar6_carbon_prices.csv")
    ap.add_argument("--skip", nargs="*", default=[],
                    choices=["assets", "companies", "scenarios"],
                    help="Datasets to leave untouched (e.g. --skip assets companies)")
    args = ap.parse_args()
    SOURCE = args.source

    # Build and validate everything first; write nothing until all checks pass.
    built: list[tuple[str, pd.DataFrame, Path]] = []
    if "assets" not in args.skip:
        built.append(("assets", build_assets(), MODEL_INPUT / "downloaded_assets.csv"))
    if "companies" not in args.skip:
        built.append(("companies", build_companies(), MODEL_INPUT / "downloaded_companies.csv"))
    if "scenarios" not in args.skip:
        built.append(("scenarios", build_scenarios(args.manifest, args.carbon_prices,
                                                   args.ar6_ref), args.scenarios_out))

    names = [n for n, _, _ in built]
    if {"assets", "companies"} <= set(names):
        a = next(d for n, d, _ in built if n == "assets")
        c = next(d for n, d, _ in built if n == "companies")
        overlap = set(a.asset_id) & set(c.asset_id)
        if not overlap:
            raise SystemExit("no asset overlap between assets and companies")
        print(f"asset/company overlap: {len(overlap):,} "
              f"({100 * len(overlap) / a.asset_id.nunique():.1f}% of assets)")

    for name, df, out in built:
        print(f"{name}:")
        write(df, out, args.stamp)
        print(f"  wrote {out.name}: {len(df):,} rows")


if __name__ == "__main__":
    main()
