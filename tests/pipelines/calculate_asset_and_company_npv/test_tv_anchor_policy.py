"""PROPOSAL: the terminal anchor takes operating cash flow (owner ruling 11).

A perpetuity capitalises whatever the anchor holds. Two things were getting in
that should never have been capitalised, and the golden-run investigation put a
number on each:

  * DECOMMISSIONING, a one-off charge for LEAVING, booked into `capex_total`.
    An asset shedding capacity through the transition books one every year, and
    `r - g` turns each exit bill into an infinite series of itself. Measured:
    -1.26 tn of negative terminal value traceable to decom at the horizon.
  * A RETIRED ASSET, resurrected by the normalization WINDOW. At window 3 a
    plant that retired two years before the horizon still has live years inside
    the window, so it was handed a terminal value off cash flows it can no
    longer earn. Measured: -615 bn fabricated on assets already retired.

Both are fixed under `tv_anchor_policy: "operating"`; `"raw"` reaches the
pre-proposal behaviour for the ablation batch. The two frames below are
hand-built equivalents of the two assets the investigation named - a solar
asset retiring AT the horizon, and a CSP park retired in 2049, one year before
it. Their arithmetic is written out from closed forms, independently of the
implementation.
"""

import pandas as pd
import pytest
from altr_model.pipelines.calculate_asset_and_company_npv.nodes import (
    HORIZON_ATTRIBUTE_KEYS,
    compute_yearly_npv_trajectories,
)

from .test_tv_three_regimes import (
    FINAL_YEAR,
    GREENTECH,
    META,
    NO_TERMINAL_VALUE,
    R_GREEN,
    SHIPPED,
    _gordon,
    _terminal_rows,
    _terminal_value,
)

#: The proposal's shipped default on this branch, and the ablation's switch.
OPERATING = dict(tv_anchor_policy="operating")
RAW = dict(tv_anchor_policy="raw")

#: Capacity in MW while the plant is running, and after it retires.
RUNNING = 250.0
RETIRED = 0.0

#: A decommissioning charge large enough to dominate the operating cash flow -
#: which is the whole point: it is what dragged these anchors negative.
DECOM = 400.0
OPERATING_FCFF = 20.0

#: A charge SMALLER than the operating cash flow, so a window carrying it still
#: averages positive. This is how a retired asset gets a POSITIVE perpetuity.
SMALL_DECOM = 5.0


def _build(
    years: list[tuple[int, float, float]],
    capacity_at_horizon: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(year, FCFF, decom_cost) rows, plus the horizon table for the series.

    `FCFF` is the AS-BOOKED cash flow, decom included, exactly as the earnings
    stage writes it: `FCFF = EBITDA - capex_total` and `capex_total` carries
    the decom charge as a positive outflow.
    """
    frame = pd.DataFrame(
        [
            {
                **META,
                "alignment_type": GREENTECH,
                "technology": "SolarCap - PV",
                "year": year,
                "FCFF": fcff,
                "decom_cost": decom,
            }
            for year, fcff, decom in years
        ]
    )
    horizon = pd.DataFrame(
        [
            {key: META[key] for key in HORIZON_ATTRIBUTE_KEYS}
            | {
                "technology": "SolarCap - PV",
                "asset_trajectory": capacity_at_horizon,
                "asset_age": 30.0,
                "lifetime_years": 45.0,
                "scrap_usd_per_mw": -100.0,
            }
        ]
    )
    return frame, horizon


def _run(frames, **overrides) -> pd.DataFrame:
    frame, horizon = frames
    return compute_yearly_npv_trajectories(frame, horizon, **{**SHIPPED, **overrides})


# ── (1) the retired asset: TV is exactly zero ───────────────────────────────


def test_solar_retiring_at_the_horizon_has_no_terminal_value():
    """The Xinjiang-shaped case: capacity reaches zero in the final year.

    The plant runs profitably, then retires at the horizon and books its exit
    bill. Under "raw" the window averages that bill into the anchor, the anchor
    goes negative, and the group is handed a terminal value off a plant that no
    longer exists. It has none: there is nothing left to run.
    """
    frames = _build(
        [
            (FINAL_YEAR - 2, OPERATING_FCFF, 0.0),
            (FINAL_YEAR - 1, OPERATING_FCFF, 0.0),
            (FINAL_YEAR, OPERATING_FCFF - DECOM, DECOM),
        ],
        capacity_at_horizon=RETIRED,
    )

    out = _run(frames, **OPERATING)

    assert _terminal_value(out) == NO_TERMINAL_VALUE
    assert _terminal_rows(out).empty, (
        "a retired group must emit no terminal row at all - a zero-valued one "
        "would still be a phantom year in the yearly trajectories"
    )

    # And it is not zero by accident. Against the behaviour the investigation
    # MEASURED - a raw anchor and an unbounded perpetuity, i.e. this branch's
    # own D3 proposal switched off - the same frame capitalises its exit bill
    # into a large negative perpetuity. That is the -1.26 tn class.
    measured = _terminal_value(
        _run(frames, tv_anchor_policy="raw", negative_tv_method="perpetuity")
    )
    assert measured < NO_TERMINAL_VALUE
    green_growth = SHIPPED["terminal_growth_rate_green"]
    anchor_with_decom = (OPERATING_FCFF + OPERATING_FCFF + OPERATING_FCFF - DECOM) / 3.0
    assert measured == pytest.approx(
        _gordon(anchor_with_decom * (1.0 + green_growth), R_GREEN, green_growth, 3)
    )


def test_a_park_retired_before_the_horizon_is_not_resurrected_by_the_window():
    """The CSP-shaped case: retired in 2049, valued as if alive in 2050.

    This is the window's own defect. The park retires one year before the
    horizon, so at window 3 the anchor still sees two live years and one dead
    one, averages to something POSITIVE, and hands a decommissioned park a
    positive perpetuity. Zeroing on capacity is what stops it.
    """
    frames = _build(
        [
            (FINAL_YEAR - 2, OPERATING_FCFF, 0.0),
            (FINAL_YEAR - 1, OPERATING_FCFF - SMALL_DECOM, SMALL_DECOM),
            (FINAL_YEAR, 0.0, 0.0),
        ],
        capacity_at_horizon=RETIRED,
    )

    # Two live years and one dead one average POSITIVE, so the park is handed a
    # growing perpetuity - no negative-branch bound involved, nothing but the
    # window keeping a decommissioned asset on the books.
    resurrected = _terminal_value(_run(frames, **RAW))
    green_growth = SHIPPED["terminal_growth_rate_green"]
    window_mean = (OPERATING_FCFF + (OPERATING_FCFF - SMALL_DECOM) + 0.0) / 3.0
    assert resurrected == pytest.approx(
        _gordon(window_mean * (1.0 + green_growth), R_GREEN, green_growth, 3)
    )
    assert resurrected > NO_TERMINAL_VALUE, (
        "the window must genuinely fabricate a value here, or this test is not "
        "pinning the defect it names"
    )

    assert _terminal_value(_run(frames, **OPERATING)) == NO_TERMINAL_VALUE
    assert _terminal_rows(_run(frames, **OPERATING)).empty


def test_capacity_still_standing_keeps_its_terminal_value():
    """The other side of the switch: a live plant is untouched by the zeroing."""
    frames = _build(
        [
            (FINAL_YEAR - 2, OPERATING_FCFF, 0.0),
            (FINAL_YEAR - 1, OPERATING_FCFF, 0.0),
            (FINAL_YEAR, OPERATING_FCFF, 0.0),
        ],
        capacity_at_horizon=RUNNING,
    )

    green_growth = SHIPPED["terminal_growth_rate_green"]
    expected = _gordon(
        OPERATING_FCFF * (1.0 + green_growth), R_GREEN, green_growth, 3
    )

    assert _terminal_value(_run(frames, **OPERATING)) == pytest.approx(expected)


# ── (2) the anchor excludes the decommissioning charge ──────────────────────


def test_the_anchor_excludes_decommissioning_from_a_still_standing_asset():
    """A plant shedding capacity every year, still standing at the horizon.

    This is the population the capacity zeroing does NOT catch: the asset is
    alive, so it has a terminal value - but its anchor must be what it earns
    from operating, not the exit bills it pays on the way down. The anchor is
    therefore the mean of the three OPERATING flows, not of the as-booked ones,
    and all three operating flows are equal here, so it is exactly one of them.

    The first window year books no charge deliberately. The STRANDING tier is
    unchanged by this ruling and still reads the as-booked FCFF, so a window
    that is a full run of as-booked losses is scored stranded (TV = 0) before
    the anchor is ever consulted - see
    `test_a_full_run_of_as_booked_losses_is_still_stranded`.
    """
    frames = _build(
        [
            (FINAL_YEAR - 2, OPERATING_FCFF, 0.0),
            (FINAL_YEAR - 1, OPERATING_FCFF - DECOM, DECOM),
            (FINAL_YEAR, OPERATING_FCFF - DECOM, DECOM),
        ],
        capacity_at_horizon=RUNNING,
    )

    green_growth = SHIPPED["terminal_growth_rate_green"]
    expected = _gordon(
        OPERATING_FCFF * (1.0 + green_growth), R_GREEN, green_growth, 3
    )

    assert _terminal_value(_run(frames, **OPERATING)) == pytest.approx(expected)


def test_a_full_run_of_as_booked_losses_is_still_stranded():
    """The interaction this ruling deliberately does NOT change.

    Ruling 11 is about the ANCHOR. The stranding tier is a different question -
    "is this asset burning cash?" - and an asset paying a decommissioning bill
    it cannot cover is burning cash, so it keeps reading the as-booked FCFF and
    keeps firing first. The effect is conservative: stranded pays zero, which is
    strictly better than the negative value the raw anchor would have produced,
    so no part of the -1.26 tn comes back through here. It does mean the anchor
    correction only reaches windows that are NOT a full run of booked losses.
    """
    frames = _build(
        [
            (FINAL_YEAR - 2, OPERATING_FCFF - DECOM, DECOM),
            (FINAL_YEAR - 1, OPERATING_FCFF - DECOM, DECOM),
            (FINAL_YEAR, OPERATING_FCFF - DECOM, DECOM),
        ],
        capacity_at_horizon=RUNNING,
    )

    assert _terminal_value(_run(frames, **OPERATING)) == NO_TERMINAL_VALUE
    assert _terminal_value(_run(frames, **RAW)) == NO_TERMINAL_VALUE


def test_the_raw_policy_capitalises_the_exit_bill_as_it_did_before():
    """The ablation arm, and the size of what ruling 11 removes.

    Same frame as the test above, `"raw"`: the anchor becomes the as-booked
    mean, which two exit bills drag well below zero, and the group is valued off
    cash flows dominated by a charge it pays once. The correction flips the SIGN
    of the terminal value - the asset goes from worth less than nothing to worth
    a perpetuity of its operating cash flow.
    """
    frames = _build(
        [
            (FINAL_YEAR - 2, OPERATING_FCFF, 0.0),
            (FINAL_YEAR - 1, OPERATING_FCFF - DECOM, DECOM),
            (FINAL_YEAR, OPERATING_FCFF - DECOM, DECOM),
        ],
        capacity_at_horizon=RUNNING,
    )

    raw = _terminal_value(_run(frames, **RAW))
    operating = _terminal_value(_run(frames, **OPERATING))

    assert raw < NO_TERMINAL_VALUE < operating
    # "raw" reaches the bounded-negative branch, since the as-booked anchor is
    # negative; the exact bound is pinned in test_tv_bounded_negative.py. What
    # matters here is the sign flip and its cause.
    assert operating > raw


def test_a_frame_without_a_decom_column_is_unchanged_by_the_policy():
    """Every hand-built frame without decom, and any older `asset_earnings`.

    The anchor correction is exactly a no-op where there is no charge to
    exclude, so the switch cannot move a frame that never booked one.
    """
    frame = pd.DataFrame(
        [
            {
                **META,
                "alignment_type": GREENTECH,
                "technology": "SolarCap - PV",
                "year": year,
                "FCFF": OPERATING_FCFF,
            }
            for year in range(FINAL_YEAR - 2, FINAL_YEAR + 1)
        ]
    )
    _, horizon = _build([], capacity_at_horizon=RUNNING)

    operating = compute_yearly_npv_trajectories(
        frame, horizon, **{**SHIPPED, **OPERATING}
    )
    raw = compute_yearly_npv_trajectories(frame, horizon, **{**SHIPPED, **RAW})

    assert _terminal_value(operating) == pytest.approx(_terminal_value(raw))


def test_without_a_horizon_table_the_capacity_zeroing_cannot_fire():
    """No capacity to read means no zeroing - the documented fallback."""
    frames = _build(
        [
            (FINAL_YEAR - 2, OPERATING_FCFF, 0.0),
            (FINAL_YEAR - 1, OPERATING_FCFF, 0.0),
            (FINAL_YEAR, OPERATING_FCFF, 0.0),
        ],
        capacity_at_horizon=RETIRED,
    )
    frame, _ = frames

    out = compute_yearly_npv_trajectories(frame, None, **{**SHIPPED, **OPERATING})

    assert _terminal_value(out) != NO_TERMINAL_VALUE
