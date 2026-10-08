"""PROPOSAL: natural retirement lands on its own date (decision #9).

An asset retires NATURALLY when its age passes its technology's lifetime.
That date has nothing to do with the policy shock - it is the same date in
the baseline world and in the shocked one.

Today both pathways clamp it:

    eff_retirement = max(retirement_year, alignment_year + 1)

so every natural retirement dated on or before the alignment year is deferred
and bunched into `alignment_year + 1`. With the shipped `alignment_year: 2038`
that is the 2039 cliff: decades of retirements arriving in one year, and every
one of those assets held at full capacity until then in BOTH pathways.

The clamp was reaching for isolation - keeping natural retirement from
contaminating the shock-minus-baseline difference. But applying the SAME
natural date in both pathways achieves that by construction: it cancels in the
difference, without inventing a cliff in either level.

Window logic keeps governing SHOCK-INDUCED capacity reduction: the staggering
and phase-out machinery runs off `shock_year` and the company's adjusted path,
untouched here. That separation is what `test_shock_induced_*` below pins.
"""

from __future__ import annotations

import pandas as pd
import pytest
from altr_model.pipelines.allocate_company_trajectories_to_assets._allocation_nodes import (
    RETIREMENT_TIMING_DEFERRED,
    RETIREMENT_TIMING_NATURAL,
    compute_asset_baseline_trajectories,
    stagger_decreasing_technologies,
)
from altr_model.pipelines.allocate_company_trajectories_to_assets.nodes import (
    create_frozen_capacity_at_retirement,
)

#: The shipped window. A natural retirement in 2030 is nine years inside it,
#: so the clamp defers it to 2039 - the cliff this proposal removes.
SHOCK_YEAR = 2033
ALIGNMENT_YEAR = 2038
DEFERRED_TO = ALIGNMENT_YEAR + 1

NATURAL_RETIREMENT = 2030
YEARS = list(range(2028, 2042))

GROUP = {
    "company_id": "company",
    "company_name": "Company",
    "scenario_geography": "World",
    "sector": "Power",
    "technology": "CoalCap",
}


def _company_path(trajectory_type: str, value: float = 20.0) -> pd.DataFrame:
    """A FLAT company path, so any zero in the output is retirement, not shock."""
    return pd.DataFrame(
        [
            {
                **GROUP,
                "year": year,
                "trajectory_type": trajectory_type,
                "company_trajectory": value,
                "late_sudden_phase": "transition",
                "alignment_type": "misaligned_high_carbon",
            }
            for year in YEARS
        ]
    )


def _assets() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                **GROUP,
                "asset_id": asset_id,
                "asset_name": asset_id,
                "year": year,
                "asset_activity": activity,
                "asset_age": 10.0 + year - YEARS[0],
                "asset_baseline_trajectory": activity,
            }
            for year in YEARS
            for asset_id, activity in [("retiring", 12.0), ("continuing", 8.0)]
        ]
    )


def _retirement_dates(year: int = NATURAL_RETIREMENT) -> pd.DataFrame:
    return pd.DataFrame([{**GROUP, "asset_id": "retiring", "retirement_year": year}])


def _baseline(retirement_timing: str) -> pd.Series:
    out = compute_asset_baseline_trajectories(
        companies_late_sudden_trajectories=_company_path("baseline"),
        allocated_assets_to_companies=_assets(),
        assets_retirement_dates=_retirement_dates(),
        apply_retirement_baseline=True,
        alignment_year=ALIGNMENT_YEAR,
        retirement_timing=retirement_timing,
    )
    retiring = out[out["asset_id"].eq("retiring")].set_index("year")
    return retiring["asset_baseline_trajectory"]


def _shock(retirement_timing: str, staggered: bool = False) -> pd.Series:
    allocated, _ = stagger_decreasing_technologies(
        _company_path("latesudden"),
        _assets(),
        _retirement_dates(),
        shock_year=SHOCK_YEAR,
        alignment_year=ALIGNMENT_YEAR,
        apply_retirement_shock=True,
        apply_decreasing_staggered_shock=staggered,
        retirement_timing=retirement_timing,
    )
    retiring = allocated[allocated["asset_id"].eq("retiring")].set_index("year")
    return retiring["capacity_after_shock"]


def _first_zero_year(series: pd.Series) -> int:
    zeros = series[series.eq(0.0)]
    assert not zeros.empty, "asset never retires in this run"
    return int(zeros.index.min())


# ── (a) natural retirement lands on its own date, in BOTH pathways ──────────


@pytest.mark.parametrize("pathway", ["baseline", "shock"])
def test_natural_retirement_applies_at_its_actual_year_in_both_pathways(pathway):
    """2030 means 2030 - in the baseline trajectory and the shocked one alike.

    Both pathways must agree, because that is the whole isolation argument:
    a natural retirement that lands on the same year in both cancels out of
    the shock-minus-baseline difference by construction.
    """
    series = (_baseline if pathway == "baseline" else _shock)(
        RETIREMENT_TIMING_NATURAL
    )

    assert _first_zero_year(series) == NATURAL_RETIREMENT
    assert series.loc[NATURAL_RETIREMENT - 1] > 0.0, "still running the year before"
    assert (series.loc[NATURAL_RETIREMENT:] == 0.0).all(), "and zero from then on"


@pytest.mark.parametrize("pathway", ["baseline", "shock"])
def test_the_clamp_is_what_bunches_retirement_into_the_window_year(pathway):
    """The same frame under the old rule: capacity held to 2038, zero at 2039.

    This is the behaviour being proposed away, pinned here so the diff between
    the two rules is visible in one file rather than inferred.
    """
    series = (_baseline if pathway == "baseline" else _shock)(
        RETIREMENT_TIMING_DEFERRED
    )

    assert _first_zero_year(series) == DEFERRED_TO
    assert (series.loc[NATURAL_RETIREMENT:ALIGNMENT_YEAR] > 0.0).all(), (
        "the clamp keeps a retired asset at full capacity for nine more years"
    )


def test_both_pathways_agree_year_for_year_under_natural_timing():
    """The isolation property itself: baseline and shock retire identically."""
    baseline = _baseline(RETIREMENT_TIMING_NATURAL)
    shock = _shock(RETIREMENT_TIMING_NATURAL)

    assert _first_zero_year(baseline) == _first_zero_year(shock)


def test_natural_retirement_reaches_the_staggered_mode_too():
    """The staggered branch carries the same rule as the proportional one.

    `apply_decreasing_staggered_shock` ships False, so the proportional branch
    is the live one - but the staggered branch has its own copy of the clamp,
    and a switch flipped later must not silently restore the cliff.
    """
    series = _shock(RETIREMENT_TIMING_NATURAL, staggered=True)

    assert _first_zero_year(series) == NATURAL_RETIREMENT


# ── (b) shock-induced phase-out timing is untouched ─────────────────────────


def _declining_path() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                **GROUP,
                "year": year,
                "trajectory_type": "latesudden",
                "company_trajectory": value,
                "late_sudden_phase": "transition",
                "alignment_type": "misaligned_high_carbon",
            }
            for year, value in zip(range(2032, 2036), [10.0, 8.0, 6.0, 4.0])
        ]
    )


def _declining_assets() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                **GROUP,
                "asset_id": asset_id,
                "asset_name": asset_id,
                "year": year,
                "asset_activity": activity,
                "asset_age": initial_age + year - 2032,
                "asset_baseline_trajectory": activity,
            }
            for year in range(2032, 2036)
            for asset_id, activity, initial_age in [
                ("older", 6.0, 20.0),
                ("newer", 4.0, 5.0),
            ]
        ]
    )


def _shock_induced(retirement_timing: str, staggered: bool) -> dict:
    """A declining company path with NO retirement anywhere in the frame."""
    allocated, _ = stagger_decreasing_technologies(
        _declining_path(),
        _declining_assets(),
        pd.DataFrame(columns=[*GROUP, "asset_id", "retirement_year"]),
        shock_year=SHOCK_YEAR,
        alignment_year=ALIGNMENT_YEAR,
        apply_retirement_shock=True,
        apply_decreasing_staggered_shock=staggered,
        retirement_timing=retirement_timing,
    )
    return {
        (row["asset_id"], int(row["year"])): round(row["capacity_after_shock"], 10)
        for _, row in allocated.iterrows()
    }


#: The proportional branch's shock-induced allocation, captured from the code
#: BEFORE this change and asserted unchanged after it. Shares are fixed at the
#: shock year, so each asset holds its 60/40 split of the declining path.
PROP_SCALE_PINNED = {
    ("older", 2032): 6.0,
    ("older", 2033): 4.8,
    ("older", 2034): 3.6,
    ("older", 2035): 2.4,
    ("newer", 2032): 4.0,
    ("newer", 2033): 3.2,
    ("newer", 2034): 2.4,
    ("newer", 2035): 1.6,
}


@pytest.mark.parametrize("staggered", [False, True])
def test_shock_induced_phase_out_is_identical_under_both_timing_rules(staggered):
    """Retirement timing must not touch the shock allocation at all.

    No asset in this frame ever retires, so the only thing moving capacity is
    the shock. Both rules must produce byte-identical allocations - in the
    proportional branch and the staggered one.
    """
    assert _shock_induced(RETIREMENT_TIMING_DEFERRED, staggered) == _shock_induced(
        RETIREMENT_TIMING_NATURAL, staggered
    )


#: The staggered branch's, likewise captured before the change. The logistic
#: age curve loads the cut onto the OLDER asset first: it takes the whole
#: reduction, 6 -> 4 -> 2 -> 0, while the newer one is never touched.
STAGGERED_PINNED = {
    ("older", 2032): 6.0,
    ("older", 2033): 4.0,
    ("older", 2034): 2.0,
    ("older", 2035): 0.0,
    ("newer", 2032): 4.0,
    ("newer", 2033): 4.0,
    ("newer", 2034): 4.0,
    ("newer", 2035): 4.0,
}


@pytest.mark.parametrize(
    ("staggered", "pinned"),
    [(False, PROP_SCALE_PINNED), (True, STAGGERED_PINNED)],
)
def test_shock_induced_phase_out_still_matches_its_pinned_values(staggered, pinned):
    """And the allocation itself is the same one the code produced before.

    Captured from the pre-change implementation, so a regression in the shock
    machinery cannot hide behind the two rules merely agreeing with each other.
    """
    assert _shock_induced(RETIREMENT_TIMING_NATURAL, staggered) == pinned


# ── the frozen-capacity anchor follows the natural year again ───────────────


def _wide_panel() -> pd.DataFrame:
    capacity = {2029: 50.0, 2030: 0.0, 2031: 0.0}
    return pd.DataFrame(
        [
            {
                **GROUP,
                "asset_id": "retiring",
                "retirement_year": float(NATURAL_RETIREMENT),
                "year": year,
                "capacity_after_shock": value,
            }
            for year, value in capacity.items()
        ]
    )


def test_frozen_capacity_anchors_on_the_natural_retirement_year():
    """The anchor reads the year before retirement, so it must use 2030 too.

    Under the clamp it would look for 2038's capacity - a year this asset has
    already been retired for - and freeze a zero, or nothing at all.
    """
    frozen = create_frozen_capacity_at_retirement(
        _wide_panel(),
        alignment_year=ALIGNMENT_YEAR,
        retirement_timing=RETIREMENT_TIMING_NATURAL,
    )

    assert set(frozen["year"]) == {2030, 2031}
    assert set(frozen["frozen_capacity_at_retirement"]) == {50.0}
