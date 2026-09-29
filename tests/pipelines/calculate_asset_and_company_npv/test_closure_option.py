"""EXPERIMENTAL: the year-by-year closure option (spec 2026-09-29-closure-option).

An owner closes a plant in the first year that paying to decommission it beats
the value of running on. Solved exactly by backward induction in present-value
terms:

    V[T+1] = terminal value from the existing tiers
    V[t]   = max(-|scrap| * capacity[t-1] * df[t],  pv_fcff[t] + V[t+1])

Frames are five years (2046-2050) of a solar asset, so the rate is a flat 7%
with no technology spread, and every expected value below is a closed form.
"""

import numpy as np
import pandas as pd
import pytest
from altr_model.pipelines.calculate_asset_and_company_npv.nodes import (
    HORIZON_ATTRIBUTE_KEYS,
    compute_yearly_npv_trajectories,
)

from .test_tv_three_regimes import FINAL_YEAR, GREENTECH, META, SHIPPED, TECHNOLOGY_FOR

R = 0.07
YEARS = list(range(FINAL_YEAR - 4, FINAL_YEAR + 1))  # 2046..2050
SCRAP = -20.0  # USD per MW; exit = 20 per MW of standing capacity
SHOCK_YEAR = 2048
LATESUDDEN = dict(trajectory_type="latesudden", scenario_type="target")

CLOSURE_ON = dict(closure_option=True, shock_year=SHOCK_YEAR)


def df(k: int) -> float:
    return (1.0 + R) ** -k


def _series(fcff, capacity=None, **meta):
    capacity = capacity or [1.0] * len(fcff)
    base = {**META, **meta, "technology": TECHNOLOGY_FOR[GREENTECH], "alignment_type": GREENTECH}
    return [
        base | {"year": y, "FCFF": f, "asset_trajectory": c}
        for y, f, c in zip(YEARS, fcff, capacity)
    ]


def _horizon(scrap=SCRAP, trajectories=("baseline",)):
    rows = []
    for traj in trajectories:
        row = {key: META[key] for key in HORIZON_ATTRIBUTE_KEYS}
        row |= {"technology": TECHNOLOGY_FOR[GREENTECH], "trajectory_type": traj}
        row |= {"asset_trajectory": 1.0, "asset_age": 5.0, "lifetime_years": 40.0}
        if scrap is not None:
            row["scrap_usd_per_mw"] = scrap
        rows.append(row)
    return pd.DataFrame(rows)


def _run(rows, horizon, **overrides):
    return compute_yearly_npv_trajectories(
        pd.DataFrame(rows), horizon, **{**SHIPPED, **overrides}
    )


def _npv(out, trajectory="baseline"):
    return out.loc[out["trajectory_type"] == trajectory, "yearly_npv"].sum()


def _closure_year(out, trajectory="baseline"):
    years = out.loc[out["trajectory_type"] == trajectory, "closure_year"].unique()
    assert len(years) == 1
    return years[0]


def test_permanent_loss_closes_in_the_first_year():
    out = _run(_series([-10.0] * 5), _horizon(), **CLOSURE_ON)
    assert _closure_year(out) == 2046
    assert _npv(out) == pytest.approx(SCRAP * df(0))
    assert (out.loc[out["year"] > 2046, "yearly_npv"] == 0.0).all()


def test_temporary_loss_runs_through_to_the_profits():
    rows = _series([-10.0, -10.0, 50.0, 50.0, 50.0])
    on = _run(rows, _horizon(), **CLOSURE_ON)
    off = _run(rows, _horizon())
    assert np.isnan(_closure_year(on))
    assert _npv(on) == pytest.approx(_npv(off))


def test_profitable_plant_closes_mid_life_when_losses_start():
    out = _run(_series([50.0, 50.0, -10.0, -10.0, -10.0]), _horizon(), **CLOSURE_ON)
    assert _closure_year(out) == 2048
    assert _npv(out) == pytest.approx(50.0 + 50.0 * df(1) + SCRAP * df(2))
    closed = out.loc[out["year"] == 2048].iloc[0]
    assert closed["FCFF"] == pytest.approx(SCRAP)


def test_no_scrap_quote_means_no_closure():
    rows = _series([-10.0] * 5)
    on = _run(rows, _horizon(scrap=None), **CLOSURE_ON)
    off = _run(rows, _horizon(scrap=None))
    assert np.isnan(_closure_year(on))
    assert _npv(on) == pytest.approx(_npv(off))


def test_shock_series_cannot_close_before_the_shock_year():
    rows = _series([-10.0] * 5, **LATESUDDEN)
    out = _run(rows, _horizon(trajectories=("latesudden",)), **CLOSURE_ON)
    assert _closure_year(out, "latesudden") == SHOCK_YEAR
    assert _npv(out, "latesudden") == pytest.approx(-10.0 - 10.0 * df(1) + SCRAP * df(2))


def test_shock_series_inherits_a_pre_shock_baseline_closure():
    rows = _series([-10.0] * 5) + _series([-10.0] * 5, **LATESUDDEN)
    out = _run(rows, _horizon(trajectories=("baseline", "latesudden")), **CLOSURE_ON)
    assert _closure_year(out, "baseline") == 2046
    assert _closure_year(out, "latesudden") == 2046
    assert _npv(out, "latesudden") == pytest.approx(SCRAP * df(0))


def test_retirement_year_decom_bill_cannot_be_dodged():
    """Pathway retires the plant in 2048 and books its decom (-8) that year.
    Exit in 2048 is priced on the capacity entering the year (1 MW, cost 20),
    so the owner pays the cheaper booked bill instead of exiting for free."""
    rows = _series([5.0, 5.0, -8.0, -3.0, -3.0], capacity=[1.0, 1.0, 0.0, 0.0, 0.0])
    out = _run(rows, _horizon(), **CLOSURE_ON)
    assert out.loc[out["year"] == 2048, "FCFF"].iloc[0] == pytest.approx(-8.0)
    assert _closure_year(out) == 2049


def test_flag_off_leaves_the_output_unchanged():
    rows = _series([50.0, 50.0, -10.0, -10.0, -10.0])
    off = _run(rows, _horizon())
    assert "closure_year" not in off.columns
    explicit = _run(rows, _horizon(), closure_option=False, shock_year=SHOCK_YEAR)
    pd.testing.assert_frame_equal(off, explicit)
