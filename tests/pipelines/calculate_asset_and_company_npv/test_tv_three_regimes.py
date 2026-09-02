"""The three terminal-value tiers: each one fires, and hands off to the next.

`compute_yearly_npv_trajectories` picks one of three terminal values per
asset-trajectory group (Gourdel 2024), in this order:

    1. STRANDED    - loss-making for `stranding_consecutive_years` consecutive
                     OBSERVED years at the end of the horizon: TV = 0, and no
                     terminal row is emitted at all.
    2. ANNUITY     - declining but still profitable carbontech: a finite
                     annuity over `brown_remaining_life_years`, not a
                     perpetuity, because a fossil asset in transition has a
                     finite remaining economic life.
    3. PERPETUITY  - everything else: Gordon Growth at the technology's own
                     terminal growth rate.

The tests below hand-build small frames and assert the EXACT arithmetic each
tier produces, from closed forms written out independently of the
implementation (which sums the annuity factor in a Python loop and computes
the discounting inline). A tier that silently stopped firing, or that fired on
the wrong group, changes these numbers.

All of them run the SHIPPED configuration from
`conf/base/parameters_calculate_asset_and_company_npv.yml`, not the node's
signature defaults - the two disagree (`stranding_aware_tv` is False in the
signature and True in the shipped config), so neither is used bare. That also
means the discount rate carries the shipped technology spreads: 8.0% on
carbontech (7% + 100 bps) and 6.5% on greentech (7% - 50 bps).

TWO THINGS THIS PINS THAT ARE WORTH THE OWNERS' ATTENTION
    - `g_real_brown: 0.0` is very nearly INERT under the shipped config. A
      profitable carbontech asset is caught by the annuity tier before the
      perpetuity is reached, and inside the annuity the rate enters only as
      `final_fcff * (1 + g)` - which is `x 1.0` at g = 0. It therefore changes
      a number only for carbontech that reaches the perpetuity tier, i.e.
      carbontech with a NEGATIVE terminal FCFF that escapes stranding. See
      `test_healthy_carbontech_never_reaches_the_perpetuity_tier`.
    - A negative terminal FCFF that escapes the stranding test takes a
      negative perpetuity, unbounded below. That is decision clash D3
      (`docs/superpowers/plans/decision-ablations.md`), still open: the
      perpetuity anchor is `final_fcff != 0` (Jakub) rather than
      `final_fcff > 0` (Bertrand). 2,699 groups, 5.18% of the golden run, take
      one today. The behaviour is CHARACTERIZED here, not endorsed - see
      `test_negative_terminal_fcff_without_stranding_takes_a_negative_perpetuity`.
"""

import pandas as pd
import pytest
from altr_model.pipelines.calculate_asset_and_company_npv.nodes import (
    compute_yearly_npv_trajectories,
)

#: One physical asset, one trajectory. `alignment_type` is overridden per frame:
#: `*_high_carbon` is carbontech, `*_low_carbon` is not (CARBONTECH_ALIGNMENTS).
META = dict(
    asset_name="a1",
    asset_id="A1",
    company_id="C1",
    company_name="c",
    scenario_geography="EU",
    sector="Power",
    technology="GasCap - w/o CCS",
    is_synthetic=False,
    trajectory_type="baseline",
    scenario_type="baseline",
)

CARBONTECH = "misaligned_high_carbon"
GREENTECH = "aligned_low_carbon"

#: `conf/base/parameters_calculate_asset_and_company_npv.yml`, verbatim.
SHIPPED = dict(
    discount_rate_baseline=0.07,
    discount_rate_shock=0.07,
    terminal_method="perpetuity",
    terminal_growth_rate=0.02,
    terminal_growth_rate_brown=0.0,
    terminal_growth_rate_green=0.02,
    terminal_normalization_window=3,
    brown_discount_spread=0.01,
    green_discount_spread=0.005,
    stranding_aware_tv=True,
    stranding_consecutive_years=3,
    brown_remaining_life_years=10,
)

#: The discount rates the shipped spreads produce off the 7% baseline rate.
R_BROWN = 0.08
R_GREEN = 0.065

#: Last forecast year of every frame below; the terminal row lands at +1.
FINAL_YEAR = 2050


def _frame(fcff: list[float], alignment_type: str) -> pd.DataFrame:
    """One asset-trajectory, `len(fcff)` consecutive years ending at FINAL_YEAR."""
    first_year = FINAL_YEAR - len(fcff) + 1
    return pd.DataFrame(
        [
            {**META, "alignment_type": alignment_type, "year": year, "FCFF": value}
            for year, value in zip(range(first_year, FINAL_YEAR + 1), fcff)
        ]
    )


def _run(frame: pd.DataFrame, **overrides) -> pd.DataFrame:
    """The node under the shipped configuration, with explicit overrides."""
    return compute_yearly_npv_trajectories(frame, **{**SHIPPED, **overrides})


def _terminal_value(out: pd.DataFrame) -> float:
    return float(out["terminal_value"].sum())


def _terminal_rows(out: pd.DataFrame) -> pd.DataFrame:
    """The emitted terminal row(s), if any. One tier emits none: STRANDED."""
    return out[out["year"] == FINAL_YEAR + 1]


def _annuity_factor(rate: float, years: int) -> float:
    """Ordinary-annuity factor, closed form.

    The implementation accumulates `sum(1 / (1 + r) ** t)` over `t = 1..N` in a
    Python loop; this is the same quantity written as
    `(1 - (1 + r) ** -N) / r`, so agreement is a real check rather than a
    transcription of the code under test.
    """
    return (1.0 - (1.0 + rate) ** -years) / rate


def _gordon(terminal_cf: float, rate: float, growth: float, years: int) -> float:
    """Gordon Growth value discounted `years` back to the group's base year."""
    return terminal_cf / (rate - growth) * (1.0 + rate) ** -years


# ---------------------------------------------------------------------------
# Tier 1 - STRANDED
# ---------------------------------------------------------------------------


def test_three_consecutive_final_losses_are_stranded_with_no_terminal_value():
    """Three observed loss years at the horizon end: TV is exactly zero.

    A profitable history first, so nothing but the trailing run can be doing
    the work, and so the minimum-history guard is comfortably satisfied.
    """
    out = _run(_frame([100.0, 100.0, 100.0, -10.0, -10.0, -10.0], CARBONTECH))

    assert _terminal_value(out) == 0.0
    assert _terminal_rows(out).empty, (
        "a stranded group must emit no terminal row at all - a zero-valued one "
        "would still be a phantom year in the yearly trajectories"
    )


def test_stranding_is_what_zeroes_it_not_the_missing_terminal_fcff_gate():
    """Hand-off proof for tier 1: the same frame, tiering off, is not zero.

    TV = 0 is also what a group with no terminal FCFF gets, so "zero" alone
    does not show the stranded tier fired. Switching `stranding_aware_tv` off
    sends the identical frame to the perpetuity tier, where its negative
    terminal FCFF produces a large negative value - which is exactly the
    unbounded exposure the stranding tiers exist to bound (ablation A5).
    """
    frame = _frame([100.0, 100.0, 100.0, -10.0, -10.0, -10.0], CARBONTECH)

    without_tiers = _terminal_value(_run(frame, stranding_aware_tv=False))

    # window = 3 -> normalised terminal FCFF is the mean of the three -10s.
    # carbontech g = 0, so terminal_cf = -10; base 2045 -> terminal 2051.
    assert without_tiers == pytest.approx(_gordon(-10.0, R_BROWN, 0.0, 6))
    assert _terminal_value(_run(frame)) == 0.0


# ---------------------------------------------------------------------------
# Tier 2 - ANNUITY
# ---------------------------------------------------------------------------


def test_declining_but_profitable_carbontech_takes_the_finite_annuity():
    """Tier 2 fires, and pays exactly the 10-year annuity, not a perpetuity.

    FCFF declines 500 -> 100 but never turns negative, so the group is not
    stranded; it is carbontech with a positive normalised terminal FCFF, which
    is precisely the annuity tier's condition.

    The annuity factor discounts t = 1..10 back to the FINAL year, so the
    outer discounting runs from the final year (2050 - 2046 = 4 periods), not
    from the terminal year - one period fewer than the perpetuity below.
    """
    out = _run(_frame([500.0, 400.0, 300.0, 200.0, 100.0], CARBONTECH))

    normalised_fcff = (300.0 + 200.0 + 100.0) / 3.0
    expected = (
        normalised_fcff  # x (1 + g_brown), and g_brown is 0
        * _annuity_factor(R_BROWN, SHIPPED["brown_remaining_life_years"])
        * (1.0 + R_BROWN) ** -4
    )

    assert _terminal_value(out) == pytest.approx(expected)
    assert len(_terminal_rows(out)) == 1


def test_the_annuity_is_strictly_smaller_than_the_perpetuity_it_replaces():
    """Hand-off proof for tier 2: it is a discount, not a relabelling.

    A finite 10-year annuity on the same cash flow must be worth less than the
    growing perpetuity the group would otherwise receive. If the tier were
    quietly falling through to tier 3, these two would be equal.
    """
    frame = _frame([500.0, 400.0, 300.0, 200.0, 100.0], CARBONTECH)

    annuity = _terminal_value(_run(frame))
    perpetuity = _terminal_value(_run(frame, stranding_aware_tv=False))

    assert 0.0 < annuity < perpetuity


# ---------------------------------------------------------------------------
# Tier 3 - PERPETUITY, and the growth rate it uses
# ---------------------------------------------------------------------------


def test_healthy_greentech_takes_the_perpetuity_at_the_green_growth_rate():
    """Tier 3 with `g_real_green` = 2%, discounted at the greentech 6.5%."""
    out = _run(_frame([100.0, 110.0, 120.0], GREENTECH))

    normalised_fcff = (100.0 + 110.0 + 120.0) / 3.0
    green_growth = SHIPPED["terminal_growth_rate_green"]
    # base 2048 -> terminal 2051 is 3 periods.
    expected = _gordon(
        normalised_fcff * (1.0 + green_growth), R_GREEN, green_growth, 3
    )

    assert _terminal_value(out) == pytest.approx(expected)
    assert _terminal_rows(out)["terminal_growth_rate"].eq(green_growth).all()


def test_healthy_carbontech_never_reaches_the_perpetuity_tier():
    """`g_real_brown` is unreachable for a profitable carbontech asset.

    Tier 2 catches it first. This is not a defect - the tiers are ordered
    deliberately - but it does mean `g_real_brown: 0.0` is close to inert
    under the shipped configuration, since inside the annuity it appears only
    as `x (1 + 0)`. Recorded so a future change to `g_real_brown` is not
    expected to move a healthy fossil asset's valuation: it will not.
    """
    frame = _frame([100.0, 110.0, 120.0], CARBONTECH)

    at_zero_growth = _terminal_value(_run(frame))
    at_five_percent_growth = _terminal_value(
        _run(frame, terminal_growth_rate_brown=0.05)
    )

    normalised_fcff = (100.0 + 110.0 + 120.0) / 3.0
    annuity = (
        normalised_fcff
        * _annuity_factor(R_BROWN, SHIPPED["brown_remaining_life_years"])
        * (1.0 + R_BROWN) ** -2
    )
    assert at_zero_growth == pytest.approx(annuity)
    # Not equal, because g still scales terminal_cf - but it is the ANNUITY
    # that moved, at 1.05x, not a Gordon denominator at 1 / (r - g).
    assert at_five_percent_growth == pytest.approx(annuity * 1.05)


def test_carbontech_takes_the_brown_growth_rate_once_the_tiers_are_off():
    """With tiering off, tier 3 is reachable by carbontech - at `g_real_brown`.

    The one configuration in which the brown rate actually drives a Gordon
    denominator. Pinned so the brown/green selection itself is covered, not
    just the green half of it.
    """
    out = _run(_frame([100.0, 110.0, 120.0], CARBONTECH), stranding_aware_tv=False)

    normalised_fcff = (100.0 + 110.0 + 120.0) / 3.0
    expected = _gordon(normalised_fcff, R_BROWN, 0.0, 3)

    assert _terminal_value(out) == pytest.approx(expected)
    assert _terminal_rows(out)["terminal_growth_rate"].eq(0.0).all()


def test_the_default_growth_rate_is_used_when_neither_brown_nor_green_is_given():
    """Third growth rate: both technology rates fall back to `g_real_default`.

    `terminal_growth_rate_brown/green=None` is the node's own default, so a
    direct caller that passes only `terminal_growth_rate` gets 2% for every
    technology - including carbontech, which the shipped config gives 0%.
    """
    frame = _frame([100.0, 110.0, 120.0], CARBONTECH)
    out = _run(
        frame,
        stranding_aware_tv=False,
        terminal_growth_rate_brown=None,
        terminal_growth_rate_green=None,
    )

    normalised_fcff = (100.0 + 110.0 + 120.0) / 3.0
    default_growth = SHIPPED["terminal_growth_rate"]
    expected = _gordon(
        normalised_fcff * (1.0 + default_growth), R_BROWN, default_growth, 3
    )

    assert _terminal_value(out) == pytest.approx(expected)
    assert _terminal_rows(out)["terminal_growth_rate"].eq(default_growth).all()
    # And it is a different number from the shipped brown rate, so the
    # fallback is genuinely routing to `terminal_growth_rate`.
    assert expected != pytest.approx(_gordon(normalised_fcff, R_BROWN, 0.0, 3))


# ---------------------------------------------------------------------------
# Boundaries between the tiers
# ---------------------------------------------------------------------------


def test_two_losses_on_a_short_history_fall_through_to_the_perpetuity():
    """Boundary: the minimum-history guard, and where the group lands.

    `test_stranding_min_history.py` already pins that a two-year history is
    not stranded. This adds the other half - WHICH tier catches it, and for
    how much. The annuity tier rejects it too (it screens on the raw loss run,
    before the history guard), so it lands on the perpetuity at the exact
    value below.
    """
    out = _run(_frame([-10.0, -10.0], CARBONTECH))

    # Normalised over min(window, size) = 2 rows; base 2049 -> terminal 2051.
    expected = _gordon(-10.0, R_BROWN, 0.0, 2)

    assert _terminal_value(out) == pytest.approx(expected)
    assert expected < 0.0


def test_loss_gap_loss_is_not_a_run_of_consecutive_losses():
    """Boundary: an unobserved year breaks the run, on a LONG history.

    Five observed years clear the minimum-history guard, so the only thing
    standing between this group and the stranded tier is the completeness of
    the trailing window - and a gap inside it is not a loss year. It falls
    through to the perpetuity, priced off a terminal FCFF that skips the gap.
    """
    out = _run(_frame([-5.0, -5.0, -5.0, -10.0, float("nan"), -10.0], CARBONTECH))

    # Terminal FCFF is the NaN-skipping mean of the window: (-10 + -10) / 2.
    # base 2045 -> terminal 2051 is 6 periods.
    expected = _gordon(-10.0, R_BROWN, 0.0, 6)

    assert _terminal_value(out) == pytest.approx(expected)


def test_a_terminal_fcff_of_exactly_zero_gets_no_terminal_value():
    """Boundary: `has_terminal_fcff` is `final_fcff != 0`, and it gates first.

    The window here averages to exactly zero while containing a PROFITABLE
    year, so the group is not stranded by any reading - the +10 breaks the
    loss run. Zero terminal value here is therefore the missing-anchor gate
    firing, a different route to TV = 0 than tier 1.
    """
    out = _run(_frame([50.0, 50.0, 10.0, 0.0, -10.0], GREENTECH))

    assert _terminal_value(out) == 0.0
    assert _terminal_rows(out).empty


def test_negative_terminal_fcff_without_stranding_takes_a_negative_perpetuity():
    """Boundary, CHARACTERIZATION ONLY: the open D3 clash.

    A window of (-30, +5, +5) averages negative but is not a run of losses, so
    the group escapes the stranding tier and is handed a NEGATIVE growing
    perpetuity: the asset is valued at less than nothing, forever. That is the
    current behaviour of the `final_fcff != 0` anchor, and it is the subject
    of decision clash D3 in `docs/superpowers/plans/decision-ablations.md` -
    Bertrand's `final_fcff > 0` alternative would floor this at zero. This
    test asserts what the model does TODAY so the clash can be resolved
    deliberately; it is not an endorsement of either side.
    """
    out = _run(_frame([-30.0, 5.0, 5.0], GREENTECH))

    normalised_fcff = (-30.0 + 5.0 + 5.0) / 3.0
    green_growth = SHIPPED["terminal_growth_rate_green"]
    expected = _gordon(
        normalised_fcff * (1.0 + green_growth), R_GREEN, green_growth, 3
    )

    assert _terminal_value(out) == pytest.approx(expected)
    assert expected < 0.0, (
        "D3 characterization: an asset losing money at the horizon is being "
        "valued below zero in perpetuity, with no floor"
    )
