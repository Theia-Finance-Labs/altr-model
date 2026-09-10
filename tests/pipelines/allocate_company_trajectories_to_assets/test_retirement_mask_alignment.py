"""Regression: retirement zeroing in compute_asset_baseline_trajectories must
hit the retiring asset's rows, not label-aligned neighbours.

`out` is sorted in place before the groupby apply, so its index is a permuted
set of labels. Building the retirement mask on a merged frame (fresh
RangeIndex) and then applying it with `out.loc[mask]` makes pandas align by
LABEL, which displaces the zeroing onto unrelated asset-years.

The fix is present in this codebase (`_allocation_nodes.py`, the retirement
merge with `validate="many_to_one"`); this regression test was not, so it is
ported to pin the behaviour rather than to change it.
"""
import pandas as pd

from altr_model.pipelines.allocate_company_trajectories_to_assets.nodes import (
    compute_asset_baseline_trajectories,
)

KEY = dict(
    company_id="C1",
    scenario_geography="EU",
    sector="Power",
    technology="CoalCap",
)
YEARS = (2030, 2031)


def _companies():
    return pd.DataFrame(
        [
            {
                **KEY,
                "company_name": "c",
                "year": y,
                "trajectory_type": "baseline",
                "company_trajectory": 100.0,
            }
            for y in YEARS
        ]
    )


def _assets():
    # Input order is deliberately the reverse of the internal sort order
    # (company/geo/sector/tech/asset_id/year), so sorting permutes row labels.
    return pd.DataFrame(
        [
            {**KEY, "asset_id": a, "year": y, "asset_activity": 10.0, "asset_age": 5.0}
            for a in ("B", "A")
            for y in YEARS
        ]
    )


def _retirement():
    return pd.DataFrame([{**KEY, "asset_id": "A", "retirement_year": 2031}])


def test_retirement_zeroes_only_the_retiring_asset_years():
    out = compute_asset_baseline_trajectories(
        _companies(),
        _assets(),
        _retirement(),
        apply_retirement_baseline=True,
        alignment_year=2029,
    )

    got = out.set_index(["asset_id", "year"])[
        ["asset_baseline_trajectory", "asset_activity"]
    ]

    assert got.loc[("A", 2031)].tolist() == [0.0, 0.0]
    assert got.loc[("A", 2030)].tolist() == [10.0, 10.0]
    assert got.loc[("B", 2030)].tolist() == [10.0, 10.0]
    # The label-aligned bug zeroed B/2031 (label 1) instead of A/2031.
    assert got.loc[("B", 2031)].tolist() == [10.0, 10.0]
