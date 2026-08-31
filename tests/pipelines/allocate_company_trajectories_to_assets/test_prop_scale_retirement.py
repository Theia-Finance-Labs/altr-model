"""Regression: proportional scaling must apply a retiring asset's share once.

_prop_scale_decreasing_fast used to both pre-reduce C_adj by the retiring
share AND zero the retired columns after allocation, so surviving capacity
came out as (1 - r)^2 * C instead of (1 - r) * C.
"""

import pandas as pd
from altr_model.pipelines.allocate_company_trajectories_to_assets._allocation_nodes import (
    _prop_scale_decreasing_fast,
)

KEY = dict(
    company_id="C1",
    scenario_geography="EU",
    sector="Power",
    technology="CoalCap",
)
YEARS = [2030, 2031, 2032, 2033]
SHOCK_YEAR = 2031
ALIGNMENT_YEAR = 2029
RETIREMENT_YEAR = 2032
C = 100.0


def _lsc():
    return pd.DataFrame(
        [
            {
                **KEY,
                "company_name": "c",
                "year": y,
                "trajectory_type": "latesudden",
                "company_trajectory": C,
                "late_sudden_phase": "shock",
                "alignment_type": "misaligned_high_carbon",
            }
            for y in YEARS
        ]
    )


def _assets():
    return pd.DataFrame(
        [
            {
                **KEY,
                "asset_id": a,
                "asset_name": a,
                "year": y,
                # Pre-shock activity (2030) deliberately differs from C so the
                # adjusted-series splice is observable: asset totals are 120
                # in 2030 while the company series is 100.
                "asset_activity": 60.0 if y == 2030 else 50.0,
                "asset_age": 5.0,
                "asset_baseline_trajectory": 50.0,
            }
            for a in ("A", "B")
            for y in YEARS
        ]
    )


def _retirement():
    return pd.DataFrame([{**KEY, "asset_id": "A", "retirement_year": RETIREMENT_YEAR}])


def _run():
    return _prop_scale_decreasing_fast(
        _lsc(),
        _assets(),
        SHOCK_YEAR,
        assets_retirement_dates=_retirement(),
        alignment_year=ALIGNMENT_YEAR,
        apply_retirement=True,
    )


def test_retired_share_is_applied_once():
    assets_df, _ = _run()
    cap = assets_df.set_index(["asset_id", "year"])["capacity_after_shock"]

    for year in (RETIREMENT_YEAR, RETIREMENT_YEAR + 1):
        assert cap.loc[("A", year)] == 0.0
        # surviving asset keeps w * C, not w * (1 - w) * C
        assert cap.loc[("B", year)] == 0.5 * C

    totals = assets_df.groupby("year")["capacity_after_shock"].sum()
    assert totals.loc[SHOCK_YEAR] == C
    assert totals.loc[RETIREMENT_YEAR] == 0.5 * C
    assert totals.loc[RETIREMENT_YEAR + 1] == 0.5 * C


def test_adjusted_corrections_track_asset_totals():
    assets_df, corrections_df = _run()

    totals = assets_df.groupby("year")["capacity_after_shock"].sum()
    adjusted = (
        corrections_df[corrections_df["trajectory_type"] == "latesudden_adjusted"]
        .set_index("year")["company_trajectory"]
        .sort_index()
    )

    # Pre-shock: adjusted keeps the original company series (NOT the asset
    # totals, which are 120 here) so the reporting residual stays informative.
    assert adjusted.loc[2030] == C
    # From the shock year on: adjusted tracks the capacity assets actually hold.
    for year in YEARS[1:]:
        assert adjusted.loc[year] == totals.loc[year]
    assert adjusted.loc[RETIREMENT_YEAR] == 0.5 * C

    original = (
        corrections_df[corrections_df["trajectory_type"] == "latesudden_original"]
        .set_index("year")["company_trajectory"]
        .sort_index()
    )
    assert original.tolist() == [C] * len(YEARS)
