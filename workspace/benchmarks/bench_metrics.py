"""Extract per-run metrics, then compare two runs.

extract <label>          -- snapshot data/07_model_output into runs/<label>/
compare <label> <ref>    -- JSON comparison; ref is a label or "golden"
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[2]
OUTDIR = PROJECT / "data/07_model_output"
RUNS = Path(os.environ.get("ALTR_BENCH_RUNS", PROJECT / "data" / "09_benchmarks"))
GOLDEN = PROJECT / "tests/golden/snapshots"
BN = 1e9

# The valuation grain, minus the columns functionally determined by the ids.
GRAIN = ["asset_id", "company_id", "scenario_geography", "sector", "technology",
         "trajectory_type"]
COST_COLS = ["var_cost", "fixed_cost", "carbon_cost_net", "capex_total"]
NORM_WINDOW = 3


def earnings_diagnostics(path: Path) -> tuple[pd.DataFrame, dict]:
    """Q2 revenue-to-total-cost ratio per technology + all-NaN anchor windows."""
    use = GRAIN + ["year", "revenue", "FCFF"] + COST_COLS
    df = pd.read_csv(
        path,
        usecols=use,
        dtype={c: "category" for c in GRAIN},
    )

    g = df.groupby(["technology", "trajectory_type"], observed=True)[
        ["revenue", *COST_COLS]
    ].sum()
    g["total_cost"] = g[COST_COLS].sum(axis=1)
    g["ratio"] = g["revenue"] / g["total_cost"]
    ratio_df = (g / BN).assign(ratio=g["ratio"]).reset_index()
    ratio_df.columns = [
        c if c in ("technology", "trajectory_type", "ratio") else f"{c}_bn"
        for c in ratio_df.columns
    ]

    # Groups whose final NORM_WINDOW years carry NO observed FCFF: those take a
    # NaN window mean, which passes `final_fcff != 0` and would be handed a
    # perpetuity on a NaN anchor.
    df = df.sort_values(GRAIN + ["year"])
    tail = df.groupby(GRAIN, observed=True).tail(NORM_WINDOW)
    per = tail.groupby(GRAIN, observed=True)["FCFF"].count()
    win = {
        "valuation_groups": int(per.size),
        "all_nan_anchor_window_groups": int((per == 0).sum()),
        "earnings_rows": int(len(df)),
    }
    return ratio_df, win


def extract(label: str) -> None:
    dest = RUNS / label
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("company_npv.csv", "company_technology_npv.csv"):
        pd.read_csv(OUTDIR / name).to_parquet(dest / name.replace(".csv", ".parquet"))

    ratio_df, win = earnings_diagnostics(OUTDIR / "asset_earnings.csv")
    ratio_df.to_csv(dest / "tech_ratio.csv", index=False)

    cn = pd.read_csv(OUTDIR / "company_npv.csv")
    an = pd.read_csv(OUTDIR / "asset_npv.csv", usecols=["company_id"])
    metrics = {
        "companies": int(len(cn)),
        "asset_rows": int(len(an)),
        "sum_baseline_npv_bn": float(cn["baseline_npv"].sum() / BN),
        "sum_latesudden_npv_bn": float(cn["latesudden_npv"].sum() / BN),
        "headline_bn": float((cn["latesudden_npv"] - cn["baseline_npv"]).sum() / BN),
        "npv_change_mean": float(cn["npv_change"].mean()),
        "npv_change_median": float(cn["npv_change"].median()),
        "npv_change_nan": int(cn["npv_change"].isna().sum()),
        **win,
    }
    (dest / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))
    print("\n-- Q2 revenue / (var+fixed+carbon+capex), baseline trajectory --")
    b = ratio_df[ratio_df.trajectory_type == "baseline"].sort_values("ratio")
    print(b[["technology", "revenue_bn", "total_cost_bn", "ratio"]].to_string(index=False))
    below = b[b.ratio < 1.0]["technology"].tolist()
    print(f"BELOW 1 AT BASELINE: {below or 'none'}")


def load(label: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    if label == "golden":
        return (
            pd.read_parquet(GOLDEN / "company_npv.parquet"),
            pd.read_parquet(GOLDEN / "company_technology_npv.parquet"),
        )
    d = RUNS / label
    return (
        pd.read_parquet(d / "company_npv.parquet"),
        pd.read_parquet(d / "company_technology_npv.parquet"),
    )


def compare(label: str, ref_label: str) -> None:
    new_c, new_t = load(label)
    ref_c, ref_t = load(ref_label)
    for df in (new_c, ref_c):
        df["headline"] = df["latesudden_npv"] - df["baseline_npv"]

    m = ref_c.merge(new_c, on="company_id", how="inner", suffixes=("_ref", "_new"))
    rel = ((m["headline_new"] - m["headline_ref"]) / m["headline_ref"].abs()).replace(
        [np.inf, -np.inf], np.nan
    )
    moved10 = int((rel.abs() > 0.10).sum())
    s_ref, s_new = np.sign(m["headline_ref"]), np.sign(m["headline_new"])
    live = (s_ref != 0) & (s_new != 0)
    neg_pos = int((live & (s_ref < 0) & (s_new > 0)).sum())
    pos_neg = int((live & (s_ref > 0) & (s_new < 0)).sum())

    def agg_tech(df: pd.DataFrame) -> pd.Series:
        return (df["latesudden_npv"] - df["baseline_npv"]).groupby(df["technology"]).sum()

    t_new, t_ref = agg_tech(new_t), agg_tech(ref_t)
    idx = t_new.index.union(t_ref.index)
    tdelta = (t_new.reindex(idx).fillna(0) - t_ref.reindex(idx).fillna(0)).sort_values(
        key=lambda s: s.abs(), ascending=False
    )

    hb_ref = ref_c["headline"].sum() / BN
    hb_new = new_c["headline"].sum() / BN
    out = {
        "run": label,
        "reference": ref_label,
        "sum_baseline_bn": [ref_c["baseline_npv"].sum() / BN, new_c["baseline_npv"].sum() / BN],
        "sum_latesudden_bn": [ref_c["latesudden_npv"].sum() / BN, new_c["latesudden_npv"].sum() / BN],
        "headline_bn": [hb_ref, hb_new],
        "headline_delta_bn": hb_new - hb_ref,
        "headline_delta_pct": (hb_new - hb_ref) / abs(hb_ref) * 100 if hb_ref else None,
        "npv_change_mean": [ref_c["npv_change"].mean(), new_c["npv_change"].mean()],
        "npv_change_median": [ref_c["npv_change"].median(), new_c["npv_change"].median()],
        "npv_change_nan": [int(ref_c["npv_change"].isna().sum()), int(new_c["npv_change"].isna().sum())],
        "companies": [int(len(ref_c)), int(len(new_c))],
        "companies_compared": int(len(m)),
        "sign_flips": neg_pos + pos_neg,
        "sign_flips_neg_to_pos": neg_pos,
        "sign_flips_pos_to_neg": pos_neg,
        "moved_gt_10pct": moved10,
        "moved_gt_10pct_share_pct": moved10 / len(m) * 100 if len(m) else None,
        "median_rel_pct": float(rel.median() * 100),
        "top3_technology_delta_bn": [
            {
                "technology": t,
                "delta_bn": float(tdelta[t] / BN),
                "ref_bn": float(t_ref.get(t, 0.0) / BN),
                "pct": float(tdelta[t] / abs(t_ref[t]) * 100)
                if t in t_ref.index and t_ref[t]
                else None,
            }
            for t in tdelta.index[:3]
        ],
    }
    print(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    if sys.argv[1] == "extract":
        extract(sys.argv[2])
    else:
        compare(sys.argv[2], sys.argv[3])
