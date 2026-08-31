"""Regression: the transition anchor must not crash when the scenario grid
starts at (or after) the shock year.

The builders looked up baseline[years == shock_year - 1][0]; on a grid that
starts at shock_year that selection is empty and raised IndexError. The
clamp anchors on the last grid year <= shock_year - 1, falling back to the
first grid year.
"""
import pandas as pd

from altr_model.pipelines.calculate_company_trajectories._late_sudden_nodes import (
    late_sudden_misaligned_high_carbon_companies,
)

KEY = dict(
    company_id="C1",
    company_name="c",
    scenario_geography="EU",
    sector="Power",
    technology="CoalCap",
)


def _traj(years):
    return pd.DataFrame(
        [
            {
                **KEY,
                "year": y,
                "company_activity": 100.0 if y == years[0] else None,
                "company_trajectory_baseline": 100.0,
                "company_trajectory_target": 50.0,
            }
            for y in years
        ]
    )


def test_grid_starting_at_shock_year_does_not_crash():
    years = list(range(2030, 2036))
    out = late_sudden_misaligned_high_carbon_companies(
        _traj(years), shock_year=2030, alignment_year=2033
    )
    assert len(out) == len(years)
    ls = out.set_index("year")["company_trajectory_latesudden"]
    # anchor fell back to the first grid value (baseline 100), path ends on target
    assert ls.loc[2033] == 50.0
    assert ls.notna().all()


def test_normal_grid_anchor_unchanged():
    years = list(range(2025, 2036))
    out = late_sudden_misaligned_high_carbon_companies(
        _traj(years), shock_year=2030, alignment_year=2033
    )
    ls = out.set_index("year")["company_trajectory_latesudden"]
    # pre-shock years follow forecast/baseline; alignment year hits target
    assert ls.loc[2033] == 50.0
    assert ls.notna().all()
