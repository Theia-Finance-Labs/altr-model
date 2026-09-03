"""PROPOSAL: the bounded negative terminal value (decision #5).

Today a non-stranded group whose terminal FCFF is NEGATIVE is handed a Gordon
Growth perpetuity, which for a negative cash flow is an UNBOUNDED negative
value: the asset is worth less than nothing, forever. That is decision clash
D3, characterized (not endorsed) in `test_tv_three_regimes.py`.

The proposal replaces it with the economic story a real owner faces. A
loss-maker does not run at a loss in perpetuity - it exits. So the terminal
value is the LEAST BAD of the two choices actually available:

    run it out   = final_fcff * annuity_factor(r, N_remaining)   (negative)
    exit now     = -decom_cost                                    (negative)
    TV           = max(run_out, exit_now)

both candidates being negative, `max` picks the smaller loss. `r` is the same
rate the group already uses (technology spreads included), `N_remaining` is
the asset's remaining lifetime at the horizon, and `decom_cost` is priced off
the same `scrap_usd_per_mw` the `include_decom_costs` charge uses.

Nothing else moves: a positive terminal FCFF keeps the perpetuity/annuity
ladder it has today, a zero one still gets no terminal value, and the
stranding tier still wins before any of this is reached.

The tests below hand-build small frames and assert EXACT arithmetic, from
closed forms written independently of the implementation.
"""

import pandas as pd
import pytest
from altr_model.pipelines.calculate_asset_and_company_npv.nodes import (
    HORIZON_ATTRIBUTE_KEYS,
    compute_yearly_npv_trajectories,
)

from .test_tv_three_regimes import (
    CARBONTECH,
    FINAL_YEAR,
    GREENTECH,
    META,
    NO_TERMINAL_VALUE,
    R_GREEN,
    SHIPPED,
    TECHNOLOGY_FOR,
    _annuity_factor,
    _gordon,
    _terminal_value,
)

#: The proposal's shipped default on this branch.
BOUNDED = dict(negative_tv_method="bounded_annuity")

#: Today's behaviour, kept reachable by the config switch.
UNBOUNDED = dict(negative_tv_method="perpetuity")

#: A window of (-30, +5, +5) averages NEGATIVE but is not a run of losses, so
#: the group escapes the stranding tier and reaches the negative branch. This
#: is exactly the frame the D3 characterization test uses.
ESCAPES_STRANDING = [-30.0, 5.0, 5.0]

#: `lifetime_years - asset_age` at the horizon = the annuity's N_remaining.
#: Deliberately NOT equal to the shipped `brown_remaining_life_years` (10), so
#: a test that passes on the fallback horizon cannot pass on this one too.
LIFETIME = 45.0
AGE_AT_HORIZON = 30.0
N_REMAINING = 15

#: Capacity still standing at the horizon, in MW.
CAPACITY = 1.0

#: Two scrap prices, on either side of the ~63 run-out loss the frames below
#: produce, so each one selects a different arm of the max().
SCRAP_DEARER_THAN_RUNNING_ON = -100.0
SCRAP_CHEAPER_THAN_RUNNING_ON = -10.0


def _frame_with_exit_data(
    fcff: list[float],
    alignment_type: str,
    scrap_usd_per_mw: float | None = SCRAP_DEARER_THAN_RUNNING_ON,
    lifetime_years: float | None = LIFETIME,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """An earnings frame, and the horizon table the exit floor is priced off.

    The horizon table is what the earnings stage now emits: ONE row per asset
    series, carrying the state of its last forecast year. `asset_age` there is
    AGE_AT_HORIZON, so the remaining life at the horizon is
    `LIFETIME - AGE_AT_HORIZON`. A `None` drops that column from the table
    entirely, which is how the fallbacks are exercised.
    """
    first_year = FINAL_YEAR - len(fcff) + 1
    technology = TECHNOLOGY_FOR[alignment_type]
    frame = pd.DataFrame(
        [
            {
                **META,
                "technology": technology,
                "alignment_type": alignment_type,
                "year": year,
                "FCFF": value,
            }
            for year, value in zip(range(first_year, FINAL_YEAR + 1), fcff)
        ]
    )

    attributes = {"asset_trajectory": CAPACITY, "asset_age": AGE_AT_HORIZON}
    if scrap_usd_per_mw is not None:
        attributes["scrap_usd_per_mw"] = scrap_usd_per_mw
    if lifetime_years is not None:
        attributes["lifetime_years"] = lifetime_years
    horizon = pd.DataFrame(
        [
            {key: META[key] for key in HORIZON_ATTRIBUTE_KEYS}
            | {"technology": technology}
            | attributes
        ]
    )
    return frame, horizon


def _run(frames: tuple[pd.DataFrame, pd.DataFrame], **overrides) -> pd.DataFrame:
    frame, horizon = frames
    return compute_yearly_npv_trajectories(
        frame, horizon, **{**SHIPPED, **overrides}
    )


def _run_out_value(fcff_window: list[float], rate: float, years_back: int) -> float:
    """`final_fcff * annuity_factor`, discounted back to the group's base year."""
    final_fcff = sum(fcff_window) / len(fcff_window)
    return (
        final_fcff * _annuity_factor(rate, N_REMAINING) * (1.0 + rate) ** -years_back
    )


def _discounted(value: float, rate: float, years_back: int) -> float:
    return value * (1.0 + rate) ** -years_back


# ── (a) the annuity is the least-bad option ─────────────────────────────────


def test_negative_fcff_takes_the_annuity_when_running_out_beats_exiting():
    """Decommissioning costs more than running the remaining life at a loss.

    scrap of -100/MW on 1 MW is a 100 exit bill, against a ~63 loss from
    running the last 15 years out. The owner runs it out, so the annuity is
    the terminal value.
    """
    out = _run(_frame_with_exit_data(ESCAPES_STRANDING, GREENTECH), **BOUNDED)

    expected = _run_out_value(ESCAPES_STRANDING, R_GREEN, years_back=2)

    assert (
        _run_out_value(ESCAPES_STRANDING, R_GREEN, years_back=0)
        > SCRAP_DEARER_THAN_RUNNING_ON * CAPACITY
    ), "frame must make the annuity the least-bad option"
    assert _terminal_value(out) == pytest.approx(expected)
    assert _terminal_value(out) < NO_TERMINAL_VALUE


# ── (b) exiting is the least-bad option ─────────────────────────────────────


def test_negative_fcff_is_floored_at_the_decommissioning_cost():
    """Running the remaining life at a loss costs more than decommissioning.

    scrap of -10/MW on 1 MW is a 10 exit bill, against the same ~63 running
    loss. The owner exits, so the terminal value is exactly `-decom_cost`,
    discounted back - never the deeper annuity, and never the unbounded
    perpetuity it takes today.
    """
    out = _run(
        _frame_with_exit_data(
            ESCAPES_STRANDING, GREENTECH, scrap_usd_per_mw=SCRAP_CHEAPER_THAN_RUNNING_ON
        ),
        **BOUNDED,
    )

    decom_cost = abs(SCRAP_CHEAPER_THAN_RUNNING_ON) * CAPACITY
    expected = _discounted(-decom_cost, R_GREEN, years_back=2)

    assert -decom_cost > _run_out_value(ESCAPES_STRANDING, R_GREEN, years_back=0), (
        "frame must make exiting the least-bad option"
    )
    assert _terminal_value(out) == pytest.approx(expected)


# ── (c) a positive terminal FCFF is untouched ───────────────────────────────


def test_positive_fcff_keeps_todays_perpetuity_exactly():
    """The proposal changes nothing for a profitable group."""
    frame = _frame_with_exit_data([5.0, 5.0, 5.0], GREENTECH)

    bounded = _terminal_value(_run(frame, **BOUNDED))
    today = _terminal_value(_run(frame, **UNBOUNDED))

    green_growth = SHIPPED["terminal_growth_rate_green"]
    expected = _gordon(5.0 * (1.0 + green_growth), R_GREEN, green_growth, 3)

    assert bounded == pytest.approx(expected)
    assert bounded == pytest.approx(today)


def test_positive_carbontech_keeps_todays_annuity_exactly():
    """The tier-2 carbontech annuity is untouched too."""
    frame = _frame_with_exit_data([5.0, 5.0, 5.0], CARBONTECH)

    bounded = _terminal_value(_run(frame, **BOUNDED))
    today = _terminal_value(_run(frame, **UNBOUNDED))

    assert bounded == pytest.approx(today)
    assert bounded > NO_TERMINAL_VALUE


def test_a_terminal_fcff_of_exactly_zero_still_gets_no_terminal_value():
    """The zero anchor is unchanged: no terminal row, no terminal value."""
    out = _run(_frame_with_exit_data([0.0, 0.0, 0.0], GREENTECH), **BOUNDED)

    assert _terminal_value(out) == pytest.approx(NO_TERMINAL_VALUE)


# ── (d) the stranding tier still wins first ─────────────────────────────────


def test_stranding_still_wins_before_the_bounded_negative_branch():
    """A genuine run of losses is stranded: TV = 0, not a bounded negative.

    The stranding tier pays ZERO - the abandonment option is already
    exercised - so it must be reached before the floor, which would otherwise
    charge this group a decommissioning bill it does not owe.
    """
    stranded = [-30.0, -30.0, -30.0]

    out = _run(_frame_with_exit_data(stranded, CARBONTECH), **BOUNDED)

    assert _terminal_value(out) == pytest.approx(NO_TERMINAL_VALUE)
    assert _run(_frame_with_exit_data(stranded, CARBONTECH), **UNBOUNDED)[
        "terminal_value"
    ].sum() == pytest.approx(NO_TERMINAL_VALUE)


# ── the switch, and the missing-data fallbacks ──────────────────────────────


def test_the_switch_still_reaches_todays_unbounded_perpetuity():
    """`negative_tv_method: perpetuity` keeps D3 behaviour, for the ablation."""
    out = _run(_frame_with_exit_data(ESCAPES_STRANDING, GREENTECH), **UNBOUNDED)

    final_fcff = sum(ESCAPES_STRANDING) / len(ESCAPES_STRANDING)
    green_growth = SHIPPED["terminal_growth_rate_green"]
    expected = _gordon(
        final_fcff * (1.0 + green_growth), R_GREEN, green_growth, 3
    )

    assert _terminal_value(out) == pytest.approx(expected)
    assert _terminal_value(out) < _run_out_value(
        ESCAPES_STRANDING, R_GREEN, years_back=2
    ), "the unbounded perpetuity must be the deeper loss it is today"


def test_without_scrap_the_annuity_stands_alone():
    """No scrap price means no exit quote, so there is no floor to apply."""
    out = _run(
        _frame_with_exit_data(
            ESCAPES_STRANDING, GREENTECH, scrap_usd_per_mw=None
        ),
        **BOUNDED,
    )

    expected = _run_out_value(ESCAPES_STRANDING, R_GREEN, years_back=2)

    assert _terminal_value(out) == pytest.approx(expected)


def test_without_the_horizon_table_at_all_the_annuity_stands_alone():
    """No `asset_horizon_attributes` input: every fallback at once.

    A direct caller that passes only an earnings frame - and any older run whose
    catalog has no such dataset - must still value, with no exit floor and the
    tier-2 annuity horizon.
    """
    frame, _ = _frame_with_exit_data(ESCAPES_STRANDING, GREENTECH)
    out = compute_yearly_npv_trajectories(frame, None, **{**SHIPPED, **BOUNDED})

    final_fcff = sum(ESCAPES_STRANDING) / len(ESCAPES_STRANDING)
    fallback_years = SHIPPED["brown_remaining_life_years"]
    expected = (
        final_fcff * _annuity_factor(R_GREEN, fallback_years) * (1.0 + R_GREEN) ** -2
    )

    assert _terminal_value(out) == pytest.approx(expected)


def test_a_horizon_row_that_does_not_match_the_group_is_not_used():
    """A table that misses this asset falls back rather than mis-pricing it."""
    frame, horizon = _frame_with_exit_data(ESCAPES_STRANDING, GREENTECH)
    out = _run((frame, horizon.assign(asset_id="SOMEONE_ELSE")), **BOUNDED)

    final_fcff = sum(ESCAPES_STRANDING) / len(ESCAPES_STRANDING)
    fallback_years = SHIPPED["brown_remaining_life_years"]
    expected = (
        final_fcff * _annuity_factor(R_GREEN, fallback_years) * (1.0 + R_GREEN) ** -2
    )

    assert _terminal_value(out) == pytest.approx(expected)


def test_without_lifetime_the_annuity_falls_back_to_the_brown_horizon():
    """Missing lifetime data falls back to the tier-2 annuity's own horizon."""
    out = _run(
        _frame_with_exit_data(ESCAPES_STRANDING, GREENTECH, lifetime_years=None),
        **BOUNDED,
    )

    final_fcff = sum(ESCAPES_STRANDING) / len(ESCAPES_STRANDING)
    fallback_years = SHIPPED["brown_remaining_life_years"]
    expected = (
        final_fcff
        * _annuity_factor(R_GREEN, fallback_years)
        * (1.0 + R_GREEN) ** -2
    )

    assert _terminal_value(out) == pytest.approx(expected)


def test_a_non_finite_scrap_price_is_not_an_exit_quote():
    """NaN and inf are missing data, not a free or infinite decommissioning.

    `abs(scrap) * capacity` is non-finite for either, and a non-finite exit
    bill is no quote at all: the floor drops out and the run-out annuity
    stands alone, exactly as it does when the column is absent.
    """
    frame, horizon = _frame_with_exit_data(ESCAPES_STRANDING, GREENTECH)
    expected = _run_out_value(ESCAPES_STRANDING, R_GREEN, years_back=2)

    for bad_scrap in (float("nan"), float("inf"), float("-inf")):
        out = _run((frame, horizon.assign(scrap_usd_per_mw=bad_scrap)), **BOUNDED)
        assert _terminal_value(out) == pytest.approx(expected), bad_scrap


# ── the n_remaining <= 0 boundary (owner ruling C2) ─────────────────────────
#
# An asset PAST its lifetime but still standing has no remaining life to run
# out, so the run-out arm does not exist and the exit arm binds. Clamping the
# remaining life to zero and keeping the arm gives `run_out_tv == 0`, which
# beats every negative `-decom_cost` and hands the asset a FREE EXIT.


def test_past_its_lifetime_and_still_standing_pays_the_exit_bill():
    """`lifetime - age == 0` with capacity standing: TV is exactly -decom.

    NOT zero. A zero-year annuity factor is 0, and `max(0, -decom)` would pick
    the 0 - valuing a plant that must still be decommissioned as though
    walking away were free.
    """
    out = _run(
        _frame_with_exit_data(
            ESCAPES_STRANDING, GREENTECH, lifetime_years=AGE_AT_HORIZON
        ),
        **BOUNDED,
    )

    decom_cost = abs(SCRAP_DEARER_THAN_RUNNING_ON) * CAPACITY
    expected = _discounted(-decom_cost, R_GREEN, years_back=2)

    assert _terminal_value(out) == pytest.approx(expected)
    assert _terminal_value(out) < NO_TERMINAL_VALUE, "a free exit is the bug"


def test_past_its_lifetime_with_no_exit_quote_takes_no_terminal_value():
    """Both arms unavailable: no life to run out, and no scrap price to exit at.

    There is no number to put on the group, so it takes none - the same "no
    quote, no floor" reading the missing-scrap fallback already uses, applied
    when the annuity is the arm that is missing.
    """
    out = _run(
        _frame_with_exit_data(
            ESCAPES_STRANDING,
            GREENTECH,
            scrap_usd_per_mw=None,
            lifetime_years=AGE_AT_HORIZON,
        ),
        **BOUNDED,
    )

    assert _terminal_value(out) == pytest.approx(NO_TERMINAL_VALUE)


def test_one_year_of_life_left_is_a_one_year_annuity():
    """The other side of the boundary is untouched: N=1 still runs out.

    The arm only disappears at `lifetime - age <= 0`; one year of remaining
    life is one year of annuity, and here that is the less-bad arm.
    """
    out = _run(
        _frame_with_exit_data(
            ESCAPES_STRANDING, GREENTECH, lifetime_years=AGE_AT_HORIZON + 1.0
        ),
        **BOUNDED,
    )

    final_fcff = sum(ESCAPES_STRANDING) / len(ESCAPES_STRANDING)
    run_out = final_fcff * _annuity_factor(R_GREEN, 1)
    decom_cost = abs(SCRAP_DEARER_THAN_RUNNING_ON) * CAPACITY

    assert run_out > -decom_cost, "frame must make the one-year run-out least bad"
    assert _terminal_value(out) == pytest.approx(
        _discounted(run_out, R_GREEN, years_back=2)
    )
