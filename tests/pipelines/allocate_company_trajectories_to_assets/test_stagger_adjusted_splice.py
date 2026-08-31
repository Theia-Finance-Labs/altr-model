"""Regression: the staggered path's adjusted corrections must match the
prop-scale convention — original series pre-shock, capacity actually held by
the assets from the shock year on — so retirement losses show at company
level in both modes.
"""
import pandas as pd

from altr_model.pipelines.allocate_company_trajectories_to_assets._allocation_nodes import (
    _stagger_decreasing_fast,
)

KEY = dict(
    company_id="C1",
    scenario_geography="EU",
    sector="Power",
    technology="CoalCap",
)
YEARS = [2030, 2031, 2032, 2033]
SHOCK_YEAR = 2031
ALIGNMENT_YEAR = 2031
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
                # pre-shock totals (120) deliberately differ from C (100) so
                # the pre-shock half of the splice is observable
                "asset_activity": 60.0 if y == 2030 else 50.0,
                "asset_age": age,
                "asset_baseline_trajectory": 50.0,
            }
            for a, age in (("A", 30.0), ("B", 5.0))
            for y in YEARS
        ]
    )


def _retirement():
    return pd.DataFrame(
        [{**KEY, "asset_id": "A", "retirement_year": RETIREMENT_YEAR}]
    )


def test_stagger_adjusted_tracks_asset_totals_post_shock():
    assets_df, corrections_df = _stagger_decreasing_fast(
        _lsc(),
        _assets(),
        _retirement(),
        SHOCK_YEAR,
        ALIGNMENT_YEAR,
        apply_retirement=True,
        g_k=1.0,
        n_quantiles=4,
    )

    totals = assets_df.groupby("year")["capacity_after_shock"].sum()
    adjusted = (
        corrections_df[corrections_df["trajectory_type"] == "latesudden_adjusted"]
        .set_index("year")["company_trajectory"]
        .sort_index()
    )

    # Pre-shock: original company series, not the 120 asset total.
    assert adjusted.loc[2030] == C
    # From the shock year on: what the assets actually hold, including the
    # retirement loss at and after RETIREMENT_YEAR.
    for year in YEARS[1:]:
        assert adjusted.loc[year] == totals.loc[year]
    assert adjusted.loc[RETIREMENT_YEAR] < adjusted.loc[SHOCK_YEAR]

    original = (
        corrections_df[corrections_df["trajectory_type"] == "latesudden_original"]
        .set_index("year")["company_trajectory"]
        .sort_index()
    )
    assert original.tolist() == [C] * len(YEARS)
