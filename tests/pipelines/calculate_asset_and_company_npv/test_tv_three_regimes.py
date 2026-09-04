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

PROPOSAL BRANCH: a fourth outcome sits between 1 and 3. A non-stranded group
with a NEGATIVE terminal FCFF no longer takes a negative perpetuity; it takes
the least bad of running its remaining life out at a loss and paying to
decommission. That is decision D3, resolved - see `test_tv_bounded_negative.py`
for the arithmetic, and `negative_tv_method` in the shipped config for the
switch back.

The tests below hand-build small frames and assert the EXACT arithmetic each
tier produces, from closed forms written out independently of the
implementation (which sums the annuity factor in a Python loop and computes
the discounting inline). A tier that silently stopped firing, or that fired on
the wrong group, changes these numbers.

All of them run the SHIPPED configuration from
`conf/base/parameters_calculate_asset_and_company_npv.yml`, not the node's
signature defaults - the two disagree (`stranding_aware_tv` is False in the
signature and True in the shipped config), so neither is used bare. That also
means the discount rate carries the shipped technology spread: 8.0% on a
`brown_technologies` member (7% + 100 bps) and the 7.0% base rate on everything
else (owner ruling 12 removed the greenium).

TWO THINGS THIS PINS THAT ARE WORTH THE OWNERS' ATTENTION
    - `g_real_brown: 0.0` is very nearly INERT under the shipped config. A
      profitable carbontech asset is caught by the annuity tier before the
      perpetuity is reached, and inside the annuity the rate enters only as
      `final_fcff * (1 + g)` - which is `x 1.0` at g = 0. It therefore changes
      a number only for carbontech that reaches the perpetuity tier, i.e.
      carbontech with a NEGATIVE terminal FCFF that escapes stranding. See
      `test_healthy_carbontech_never_reaches_the_perpetuity_tier`.
    - A negative terminal FCFF that escapes the stranding test USED TO take a
      negative perpetuity, unbounded below - decision clash D3
      (`docs/superpowers/plans/decision-ablations.md`), where the perpetuity
      anchor is `final_fcff != 0` (Jakub) rather than `final_fcff > 0`
      (Bertrand). 2,699 groups, 5.18% of the golden run, took one. This branch
      resolves it a third way, bounding rather than zeroing the loss - see
      `test_negative_terminal_fcff_without_stranding_takes_a_bounded_negative`.

AND ONE THAT SURFACED WHILE WRITING THESE (reported, not fixed)
    A missing FCFF year is read two different ways in the same function. The
    stranding test excludes it, correctly - that is what
    `test_stranding_min_history.py` pins. The normalised terminal FCFF does
    NOT: the flow-row collapse sums an all-missing cell to 0.0 before the
    window mean, so a gap enters the terminal anchor as a zero-cash-flow year
    and pulls it toward zero. With `normalization_window: 3`, one gap moves
    the anchor by a third. This is the documented intent at `nodes.py:179-184`
    rather than an oversight, and the `# NaN-skipping` comment on the window
    mean describes a NaN that has already been replaced by then - but the
    asymmetry is worth an owner decision, so it is pinned in
    `test_loss_gap_loss_is_not_a_run_of_consecutive_losses`.
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

#: Rulings 12 and 13: the discount SPREAD and the terminal GROWTH rate are both
#: keyed on `brown_technologies`, while the tier-2 annuity stays keyed on
#: `alignment_type`. Every frame below therefore carries a technology that
#: matches the tier it exercises, so `R_BROWN` / `R_GREEN` and the growth rates
#: alike remain what these tests were written against.
TECHNOLOGY_FOR = {
    CARBONTECH: "GasCap - w/o CCS",
    GREENTECH: "SolarCap - PV",
}

#: `conf/base/parameters_calculate_asset_and_company_npv.yml`, verbatim.
SHIPPED = dict(
    discount_rate=0.07,
    terminal_method="perpetuity",
    terminal_growth_rate=0.02,
    terminal_growth_rate_brown=0.0,
    terminal_growth_rate_green=0.02,
    terminal_normalization_window=3,
    brown_discount_spread=0.01,
    # PROPOSAL BRANCH (ruling 12): membership is by technology, and the -50 bps
    # `green_discount_spread` is gone — B&K measure no greenium.
    brown_technologies=["CoalCap - w/o CCS", "GasCap - w/o CCS", "OilCap - w/o CCS"],
    stranding_aware_tv=True,
    stranding_consecutive_years=3,
    brown_remaining_life_years=10,
    # PROPOSAL BRANCH: ships "bounded_annuity" here, "perpetuity" on main.
    # A non-stranded group with a negative terminal FCFF no longer takes an
    # unbounded negative perpetuity - see `test_tv_bounded_negative.py`.
    negative_tv_method="bounded_annuity",
)

#: The discount rates the shipped spread produces off the 7% baseline rate.
#: Ruling 12 removed the greenium, so everything outside `brown_technologies`
#: sits at the base rate itself - `R_GREEN` is now a name for "no spread".
R_BROWN = 0.08
R_GREEN = 0.07

#: Last forecast year of every frame below; the terminal row lands at +1.
FINAL_YEAR = 2050

#: What the STRANDED tier pays, and what a group with no terminal anchor gets.
NO_TERMINAL_VALUE = 0.0


def _frame(fcff: list[float], alignment_type: str) -> pd.DataFrame:
    """One asset-trajectory, `len(fcff)` consecutive years ending at FINAL_YEAR."""
    first_year = FINAL_YEAR - len(fcff) + 1
    return pd.DataFrame(
        [
            {
                **META,
                "technology": TECHNOLOGY_FOR[alignment_type],
                "alignment_type": alignment_type,
                "year": year,
                "FCFF": value,
            }
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


@pytest.mark.parametrize(("rate", "years"), [(0.07, 10), (0.08, 15), (0.065, 1)])
def test_the_annuity_factor_helper_is_independent_of_the_implementation(rate, years):
    """The closed form above IS the explicit sum the implementation accumulates.

    Without this, `_annuity_factor` is only ASSERTED to be an independent
    check; every expected value in this directory rests on it, so the claim is
    pinned rather than believed.
    """
    assert _annuity_factor(rate, years) == pytest.approx(
        sum(1.0 / (1.0 + rate) ** t for t in range(1, years + 1))
    )


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

    assert _terminal_value(out) == NO_TERMINAL_VALUE
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

    This is a ONE-switch ablation of `stranding_aware_tv`, so the negative
    branch is pinned to "perpetuity" alongside it: on this proposal branch the
    shipped `bounded_annuity` would bound the same frame a second time, and
    the hand-off being demonstrated here is the stranding tier's, not that one.
    """
    frame = _frame([100.0, 100.0, 100.0, -10.0, -10.0, -10.0], CARBONTECH)

    without_tiers = _terminal_value(
        _run(frame, stranding_aware_tv=False, negative_tv_method="perpetuity")
    )

    # window = 3 -> normalised terminal FCFF is the mean of the three -10s.
    # carbontech g = 0, so terminal_cf = -10; base 2045 -> terminal 2051.
    assert without_tiers == pytest.approx(_gordon(-10.0, R_BROWN, 0.0, 6))
    assert _terminal_value(_run(frame)) == NO_TERMINAL_VALUE


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

    assert NO_TERMINAL_VALUE < annuity < perpetuity


# ---------------------------------------------------------------------------
# Tier 3 - PERPETUITY, and the growth rate it uses
# ---------------------------------------------------------------------------


def test_healthy_greentech_takes_the_perpetuity_at_the_green_growth_rate():
    """Tier 3 with `g_real_green` = 2%, discounted at the greentech 6.5%."""
    out = _run(_frame([100.0, 110.0, 120.0], GREENTECH))

    normalised_fcff = (100.0 + 110.0 + 120.0) / 3.0
    green_growth = SHIPPED["terminal_growth_rate_green"]
    # base 2048 -> terminal 2051 is 3 periods.
    expected = _gordon(normalised_fcff * (1.0 + green_growth), R_GREEN, green_growth, 3)

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


def test_two_losses_on_a_short_history_fall_through_to_the_bounded_negative():
    """Boundary: the minimum-history guard, and where the group lands.

    `test_stranding_min_history.py` already pins that a two-year history is
    not stranded. This adds the other half - WHICH tier catches it, and for
    how much. The annuity tier rejects it too (it screens on the raw loss run,
    before the history guard), so on this branch it lands on the BOUNDED
    NEGATIVE branch rather than the perpetuity it used to take.

    The frame carries no `scrap_usd_per_mw`, so there is no exit quote and no
    floor: the run-out annuity stands alone, over the fallback horizon.
    """
    out = _run(_frame([-10.0, -10.0], CARBONTECH))

    # Normalised over min(window, size) = 2 rows; base 2049, final 2050, and
    # the annuity factor discounts back to the FINAL year - so 1 period, not 2.
    expected = (
        -10.0
        * _annuity_factor(R_BROWN, SHIPPED["brown_remaining_life_years"])
        * (1.0 + R_BROWN) ** -1
    )

    assert _terminal_value(out) == pytest.approx(expected)
    assert expected < NO_TERMINAL_VALUE
    # Bounded, not unbounded: strictly less bad than the perpetuity it replaces.
    assert expected > _gordon(-10.0, R_BROWN, 0.0, 2)


def test_loss_gap_loss_is_not_a_run_of_consecutive_losses():
    """Boundary: an unobserved year breaks the run, on a LONG history.

    Five observed years clear the minimum-history guard, so the only thing
    standing between this group and the stranded tier is the completeness of
    the trailing window - and a gap inside it is not a loss year. It falls
    through to the perpetuity.

    NOTE the asymmetry in how the same gap is read, pinned by the expected
    value below. The stranding test excludes it (`_fcff_observed`), but the
    NORMALISED TERMINAL FCFF counts it as a zero-cash-flow year: the flow-row
    collapse sums an all-missing cell to 0.0 before the window mean runs, so
    the mean here is (-10 + 0 + -10) / 3 = -6.67, not the -10 that the two
    measured years say. This is the documented intent at
    `nodes.py:179-184` ("every present-value number keeps the summed 0.0 it
    has always had"), and the `# NaN-skipping` comment on the window mean is
    therefore about a NaN that can no longer be present. It is recorded, not
    changed: a gap pulls the terminal anchor toward zero, flattering a
    loss-making asset and penalising a profitable one, in proportion to how
    much of the window is missing.
    """
    out = _run(_frame([-5.0, -5.0, -5.0, -10.0, float("nan"), -10.0], CARBONTECH))

    # base 2045, final 2050: the bounded-negative annuity discounts back to the
    # FINAL year, so 5 periods. No scrap on this frame, so no exit floor.
    gap_counted_as_zero = (-10.0 + 0.0 + -10.0) / 3.0
    expected = (
        gap_counted_as_zero
        * _annuity_factor(R_BROWN, SHIPPED["brown_remaining_life_years"])
        * (1.0 + R_BROWN) ** -5
    )

    assert _terminal_value(out) == pytest.approx(expected)
    # The measured-years-only reading would be a third larger in magnitude.
    # This is the point of the test and it is UNCHANGED by the proposal: the
    # gap asymmetry lives in the terminal ANCHOR, upstream of every tier.
    assert expected == pytest.approx(
        -10.0
        * _annuity_factor(R_BROWN, SHIPPED["brown_remaining_life_years"])
        * (1.0 + R_BROWN) ** -5
        * 2
        / 3
    )


def test_a_terminal_fcff_of_exactly_zero_gets_no_terminal_value():
    """Boundary: `has_terminal_fcff` is `final_fcff != 0`, and it gates first.

    The window here averages to exactly zero while containing a PROFITABLE
    year, so the group is not stranded by any reading - the +10 breaks the
    loss run. Zero terminal value here is therefore the missing-anchor gate
    firing, a different route to TV = 0 than tier 1.
    """
    out = _run(_frame([50.0, 50.0, 10.0, 0.0, -10.0], GREENTECH))

    assert _terminal_value(out) == NO_TERMINAL_VALUE
    assert _terminal_rows(out).empty


def test_negative_terminal_fcff_without_stranding_takes_a_bounded_negative():
    """Boundary: D3, RESOLVED on this branch.

    A window of (-30, +5, +5) averages negative but is not a run of losses, so
    the group escapes the stranding tier. It USED to be handed a negative
    growing perpetuity - the asset valued at less than nothing, forever, off
    the `final_fcff != 0` anchor. That was decision clash D3 in
    `docs/superpowers/plans/decision-ablations.md`, characterized here rather
    than endorsed.

    The proposal resolves it: the group takes the least bad of running its
    remaining life out at a loss and paying to exit. Bertrand's
    `final_fcff > 0` alternative would have floored it at zero instead, which
    hands a loss-maker a free exit; this keeps the loss, but bounds it.

    The exact arithmetic of both bounds, including the exit floor, is pinned
    in `test_tv_bounded_negative.py`. This frame carries no scrap price, so
    here the run-out annuity stands alone.
    """
    out = _run(_frame([-30.0, 5.0, 5.0], GREENTECH))

    normalised_fcff = (-30.0 + 5.0 + 5.0) / 3.0
    # base 2048, final 2050 -> the annuity discounts back 2 periods.
    expected = (
        normalised_fcff
        * _annuity_factor(R_GREEN, SHIPPED["brown_remaining_life_years"])
        * (1.0 + R_GREEN) ** -2
    )

    assert _terminal_value(out) == pytest.approx(expected)
    assert expected < NO_TERMINAL_VALUE, (
        "the loss is kept, not floored away at zero - the asset really is "
        "worth less than nothing at the horizon"
    )

    green_growth = SHIPPED["terminal_growth_rate_green"]
    unbounded = _gordon(
        normalised_fcff * (1.0 + green_growth), R_GREEN, green_growth, 3
    )
    assert (
        expected > unbounded
    ), "D3 resolved: bounded above the unbounded perpetuity it replaces"


# ── tier 2 on the brown carrier, and its off-switch (owner ruling 2026-09-05) ─


def _profitable_group(technology, alignment_type):
    """A single asset with positive, flat FCFF to the horizon: tier 2 or tier 3."""
    years = list(range(2025, 2031))
    return pd.DataFrame(
        {
            "asset_id": "A",
            "asset_name": "A",
            "company_id": "C",
            "company_name": "C",
            "is_synthetic": False,
            "scenario_geography": "EU",
            "sector": "Power",
            "technology": technology,
            "alignment_type": alignment_type,
            "trajectory_type": "baseline",
            "scenario_type": "baseline",
            "year": years,
            "FCFF": 100.0,
            "EBITDA": 100.0,
            "decom_cost": 0.0,
            "capex_total": 0.0,
            "asset_trajectory": 10.0,
        }
    )


def _tv(frame, **overrides):
    kwargs = dict(
        discount_rate=0.07,
        terminal_growth_rate=0.02,
        terminal_method="perpetuity",
        terminal_growth_rate_brown=0.0,
        terminal_growth_rate_green=0.02,
        terminal_normalization_window=1,
        brown_technologies=["CoalCap - w/o CCS"],
        spread_carrier="technology",
        stranding_aware_tv=True,
        brown_remaining_life_years=10,
        negative_tv_method="bounded_annuity",
        tv_anchor_policy="raw",
    )
    kwargs.update(overrides)
    out = compute_yearly_npv_trajectories(frame, None, **kwargs)
    return float(out["terminal_value"].sum())


def test_a_brown_technology_takes_the_annuity_whatever_its_alignment_label():
    coal_aligned = _tv(_profitable_group("CoalCap - w/o CCS", "aligned_low_carbon"))
    coal_misaligned = _tv(
        _profitable_group("CoalCap - w/o CCS", "misaligned_high_carbon")
    )
    assert coal_aligned == pytest.approx(coal_misaligned)
    # a 10-year annuity at 7% is worth less than the 0%-growth perpetuity (1/0.07)
    perpetuity = _tv(
        _profitable_group("CoalCap - w/o CCS", "aligned_low_carbon"),
        carbontech_annuity=False,
    )
    assert coal_aligned < perpetuity


def test_a_green_technology_with_a_high_carbon_alignment_label_is_not_annuitised():
    """Offshore wind classed misaligned_high_carbon used to take the fossil annuity."""
    wind = _tv(_profitable_group("WindCap - Offshore", "misaligned_high_carbon"))
    wind_off = _tv(
        _profitable_group("WindCap - Offshore", "misaligned_high_carbon"),
        carbontech_annuity=False,
    )
    assert wind == pytest.approx(wind_off)  # the switch cannot touch a non-brown asset
    coal = _tv(_profitable_group("CoalCap - w/o CCS", "misaligned_high_carbon"))
    assert wind > coal  # 2% growth perpetuity vs 10-year annuity


def test_the_legacy_alignment_carrier_still_selects_tier_two_on_alignment():
    wind_legacy = _tv(
        _profitable_group("WindCap - Offshore", "misaligned_high_carbon"),
        spread_carrier="alignment_type",
    )
    wind_tech = _tv(_profitable_group("WindCap - Offshore", "misaligned_high_carbon"))
    assert wind_legacy < wind_tech
