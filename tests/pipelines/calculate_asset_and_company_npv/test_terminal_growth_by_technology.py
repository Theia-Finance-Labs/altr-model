"""PROPOSAL: the terminal growth rate is chosen by TECHNOLOGY (owner ruling 13).

`g_real_brown` / `g_real_green` used to be selected by `alignment_type`, the
carrier owner ruling 12 had already taken the discount spread off. Ruling 13
puts them on the same carrier: membership of the `dcf.brown_technologies` list
decides the growth rate, and `alignment_type` no longer enters it.

The carrier matters more here than it does for the spread. The spread moves the
perpetuity denominator by 100 bps; g moves it by 200, and on the shipped rates
the two ends are 1/(0.08 - 0.00) = 12.5x and 1/(0.07 - 0.02) = 20x. For the
assets this ruling actually moves - offshore wind and nuclear, off the list but
routinely classed `misaligned_high_carbon` - the rate stays at 7% and the
multiple goes 14.3x -> 20x.

STILL ON `alignment_type`: the tier-2 annuity ("declining but profitable
carbontech"). That is the one remaining `alignment_type` consumer in the
valuation stage, outside this ruling, and pinned unchanged below.
"""

import pandas as pd
import pytest
from altr_model.pipelines.calculate_asset_and_company_npv.nodes import (
    compute_yearly_npv_trajectories,
)

#: The shipped list, without the CCS variants the fixture never builds.
BROWN_TECHNOLOGIES = ["CoalCap - w/o CCS", "GasCap - w/o CCS", "OilCap - w/o CCS"]

G_BROWN = 0.0
G_GREEN = 0.02

#: The shipped rates. Ruling 12 removed the greenium, so anything off the list
#: sits at the 7% base rate and only list members carry the +100 bps.
R_BROWN = 0.08
R_GREEN = 0.07

FINAL_YEAR = 2050

SHIPPED = dict(
    discount_rate=0.07,
    terminal_method="perpetuity",
    terminal_growth_rate=0.02,
    terminal_growth_rate_brown=G_BROWN,
    terminal_growth_rate_green=G_GREEN,
    terminal_normalization_window=3,
    brown_discount_spread=0.01,
    brown_technologies=BROWN_TECHNOLOGIES,
    stranding_aware_tv=True,
    stranding_consecutive_years=3,
    brown_remaining_life_years=10,
    negative_tv_method="bounded_annuity",
)

META = dict(
    asset_name="a1",
    asset_id="A1",
    company_id="C1",
    company_name="c",
    scenario_geography="EU",
    sector="Power",
    is_synthetic=False,
    trajectory_type="baseline",
    scenario_type="baseline",
)

ALIGNMENTS = [
    "misaligned_high_carbon",
    "aligned_high_carbon",
    "misaligned_low_carbon",
    "aligned_low_carbon",
]


def _frame(technology: str, alignment_type: str, fcff: list[float]) -> pd.DataFrame:
    """One asset-trajectory, `len(fcff)` consecutive years ending at FINAL_YEAR."""
    first_year = FINAL_YEAR - len(fcff) + 1
    return pd.DataFrame(
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


def _growth_rate(technology: str, alignment_type: str, **overrides) -> float:
    """The terminal growth rate a one-asset frame is valued at."""
    out = compute_yearly_npv_trajectories(
        _frame(technology, alignment_type, [100.0, 100.0, 100.0]),
        **{**SHIPPED, **overrides},
    )
    rates = out["terminal_growth_rate"].unique()
    assert len(rates) == 1, f"one asset must have one growth rate, got {rates}"
    return float(rates[0])


# ── the list decides ────────────────────────────────────────────────────────


@pytest.mark.parametrize("technology", BROWN_TECHNOLOGIES)
def test_the_listed_technologies_do_not_grow(technology):
    assert _growth_rate(technology, "misaligned_high_carbon") == G_BROWN


def test_offshore_wind_returns_to_the_clean_growth_rate():
    """The misfire case, and the one with the money in it.

    `WindCap - Offshore` classed `misaligned_high_carbon` was growing at the
    fossil 0% - a 14.3x terminal multiple at its own 7% rate, where the clean
    rate gives 20x. Alignment says its build-out is behind its scenario; it
    says nothing about whether the turbine's cash flows can grow.
    """
    assert _growth_rate("WindCap - Offshore", "misaligned_high_carbon") == G_GREEN


def test_nuclear_returns_to_the_clean_growth_rate():
    assert _growth_rate("NuclearCap", "misaligned_high_carbon") == G_GREEN


def test_a_listed_technology_that_is_aligned_still_does_not_grow():
    """The carrier is the list, not the alignment - in both directions.

    Gas on an `aligned_low_carbon` trajectory is still gas. It used to collect
    the 2% clean growth rate for running ahead of its scenario.
    """
    assert _growth_rate("GasCap - w/o CCS", "aligned_low_carbon") == G_BROWN


def test_alignment_type_does_not_move_the_growth_rate_at_all():
    """One technology, every alignment it appears with: one growth rate."""
    assert {_growth_rate("GasCap - w/o CCS", a) for a in ALIGNMENTS} == {G_BROWN}
    assert {_growth_rate("WindCap - Offshore", a) for a in ALIGNMENTS} == {G_GREEN}


def test_an_empty_technology_list_grows_everything_at_the_clean_rate():
    """No members, no brown leg - including for coal."""
    assert (
        _growth_rate(
            "CoalCap - w/o CCS", "misaligned_high_carbon", brown_technologies=[]
        )
        == G_GREEN
    )


# ── what this ruling deliberately did NOT move ──────────────────────────────


def test_the_tier_2_annuity_now_selects_on_the_technology_carrier():
    """Owner ruling 2026-09-05: tier 2 rides the same carrier as rulings 12/13.

    `WindCap - Offshore` classed `misaligned_high_carbon` used to take the
    CARBONTECH annuity off its alignment label. It is not on the brown list, so
    it now takes the 2%-growth perpetuity like every other clean asset.
    """
    out = compute_yearly_npv_trajectories(
        _frame(
            "WindCap - Offshore",
            "misaligned_high_carbon",
            [500.0, 400.0, 300.0, 200.0, 100.0],
        ),
        **SHIPPED,
    )

    normalised_fcff = (300.0 + 200.0 + 100.0) / 3.0
    expected = (
        normalised_fcff
        * (1.0 + G_GREEN)
        / (R_GREEN - G_GREEN)
        * (1.0 + R_GREEN) ** -5  # base 2046 -> final 2050, perpetuity at final+1
    )

    assert float(out["terminal_value"].sum()) == pytest.approx(expected)
