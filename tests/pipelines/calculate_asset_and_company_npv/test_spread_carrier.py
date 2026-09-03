"""PROPOSAL: `dcf.spread_carrier` makes rulings 12 and 13 MEASURABLE.

Rulings 12 and 13 moved the carbon risk premium and the terminal growth rate
off `alignment_type` and onto the `brown_technologies` list, and deleted the
greenium outright. The rulings are almost certainly right - alignment describes
an asset's trajectory against its scenario, not what its plant burns - but as
committed they were UNMEASURABLE: the pre-ruling behaviour was gone from the
tree, so the effect could only be quoted from a commit message, never
reproduced by a reader running the shipped code.

`dcf.spread_carrier` restores it as an ablation arm, and `green_discount_spread`
comes back as a parameter shipping at 0.0:

    spread_carrier: "technology"      + greenium 0      -> shipped, ruling 12/13
    spread_carrier: "alignment_type"  + greenium 0.005  -> pre-ruling behaviour

ONE switch governs BOTH the rate and the growth rate, because ruling 13 tied
them to one carrier on purpose: an asset must not be brown for its discount
rate and green for its growth rate. The tests below assert that property
directly, alongside the three misfires the alignment carrier brings back.

The tier-2 carbontech annuity is NOT governed by this switch - it still selects
on `alignment_type` under either carrier, pending its own ruling.
"""

import pandas as pd
import pytest
from altr_model.pipelines.calculate_asset_and_company_npv.nodes import (
    compute_yearly_npv_trajectories,
)

#: The shipped list, without the CCS variants the fixture never builds.
BROWN_TECHNOLOGIES = ["CoalCap - w/o CCS", "GasCap - w/o CCS", "OilCap - w/o CCS"]

BASE_RATE = 0.07
SPREAD = 0.01
GREENIUM = 0.005

BROWN_RATE = 0.08          # base + penalty
GREEN_RATE = BASE_RATE      # base, no greenium (shipped)
GREENIUM_RATE = 0.065       # base - greenium (pre-ruling-12)

G_BROWN = 0.0
G_GREEN = 0.02

TECHNOLOGY = "technology"
ALIGNMENT = "alignment_type"

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

SHIPPED = dict(
    discount_rate_baseline=BASE_RATE,
    discount_rate_shock=BASE_RATE,
    brown_discount_spread=SPREAD,
    brown_technologies=BROWN_TECHNOLOGIES,
    terminal_method="perpetuity",
    terminal_growth_rate_brown=G_BROWN,
    terminal_growth_rate_green=G_GREEN,
)


def _frame(technology: str, alignment_type: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                **META,
                "technology": technology,
                "alignment_type": alignment_type,
                "year": year,
                "FCFF": 100.0,
            }
            for year in (2048, 2049, 2050)
        ]
    )


def _rate_and_growth(
    technology: str, alignment_type: str, **overrides
) -> tuple[float, float]:
    """The discount rate AND terminal growth rate one asset is valued at."""
    out = compute_yearly_npv_trajectories(
        _frame(technology, alignment_type), **{**SHIPPED, **overrides}
    )
    rates = out["discount_rate"].unique()
    growths = out["terminal_growth_rate"].unique()
    assert len(rates) == 1, f"one asset must have one rate, got {rates}"
    assert len(growths) == 1, f"one asset must have one growth rate, got {growths}"
    return float(rates[0]), float(growths[0])


PRE_RULING = dict(spread_carrier=ALIGNMENT, green_discount_spread=GREENIUM)


# ── the three misfires the alignment carrier brings back ────────────────────


@pytest.mark.parametrize(
    ("technology", "alignment_type", "expected"),
    [
        # Offshore wind and nuclear are not fossil, but a scenario classing
        # them `misaligned_high_carbon` made them pay the coal rate AND grow at
        # the fossil 0%.
        ("WindCap - Offshore", "misaligned_high_carbon", (BROWN_RATE, G_BROWN)),
        ("NuclearCap", "misaligned_high_carbon", (BROWN_RATE, G_BROWN)),
        # Oil classed `misaligned_low_carbon` collected the greenium and grew
        # at the clean 2%.
        ("OilCap - w/o CCS", "misaligned_low_carbon", (GREENIUM_RATE, G_GREEN)),
    ],
)
def test_the_alignment_carrier_reproduces_the_pre_ruling_misfires(
    technology, alignment_type, expected
):
    """`alignment_type` + a 50 bps greenium IS the pre-ruling-12/13 selection."""
    assert _rate_and_growth(technology, alignment_type, **PRE_RULING) == expected


@pytest.mark.parametrize(
    ("technology", "alignment_type", "expected"),
    [
        ("WindCap - Offshore", "misaligned_high_carbon", (GREEN_RATE, G_GREEN)),
        ("NuclearCap", "misaligned_high_carbon", (GREEN_RATE, G_GREEN)),
        ("OilCap - w/o CCS", "misaligned_low_carbon", (BROWN_RATE, G_BROWN)),
    ],
)
def test_the_technology_carrier_corrects_all_three(
    technology, alignment_type, expected
):
    """The shipped carrier prices what the plant burns, in both directions."""
    assert _rate_and_growth(technology, alignment_type) == expected


# ── the carriers agree where alignment happens to match the technology ──────


@pytest.mark.parametrize(
    "alignment_type", ["misaligned_high_carbon", "aligned_high_carbon"]
)
def test_coal_is_brown_under_either_carrier(alignment_type):
    """A fossil plant a scenario also calls high-carbon is brown either way."""
    shipped = _rate_and_growth("CoalCap - w/o CCS", alignment_type)
    pre_ruling = _rate_and_growth("CoalCap - w/o CCS", alignment_type, **PRE_RULING)

    assert shipped == (BROWN_RATE, G_BROWN)
    assert pre_ruling == (BROWN_RATE, G_BROWN)


# ── one carrier, one answer (the point of ruling 13) ────────────────────────


@pytest.mark.parametrize("carrier", [TECHNOLOGY, ALIGNMENT])
@pytest.mark.parametrize(
    ("technology", "alignment_type"),
    [
        ("WindCap - Offshore", "misaligned_high_carbon"),
        ("NuclearCap", "misaligned_high_carbon"),
        ("OilCap - w/o CCS", "misaligned_low_carbon"),
        ("CoalCap - w/o CCS", "misaligned_high_carbon"),
        ("SolarCap - PV", "aligned_low_carbon"),
    ],
)
def test_the_rate_and_the_growth_rate_never_disagree(
    carrier, technology, alignment_type
):
    """Ruling 13's whole point: one carrier decides both, so they cannot split.

    A group paying the carbon PENALTY must also grow at the BROWN rate, and a
    group at the base rate must grow at the GREEN rate - under either carrier.
    """
    rate, growth = _rate_and_growth(
        technology, alignment_type, spread_carrier=carrier
    )

    pays_penalty = rate == pytest.approx(BROWN_RATE)
    grows_brown = growth == pytest.approx(G_BROWN)
    assert pays_penalty == grows_brown, (
        f"{technology}/{alignment_type} under {carrier}: rate {rate}, g {growth}"
    )


# ── the shipped carrier is unchanged, bitwise ──────────────────────────────


def test_naming_the_technology_carrier_changes_nothing():
    """The switch's default IS the shipped behaviour, frame for frame."""
    frame = _frame("OilCap - w/o CCS", "misaligned_low_carbon")

    default = compute_yearly_npv_trajectories(frame, **SHIPPED)
    explicit = compute_yearly_npv_trajectories(
        frame, **{**SHIPPED, "spread_carrier": TECHNOLOGY}
    )

    pd.testing.assert_frame_equal(default, explicit)


def test_a_greenium_under_the_technology_carrier_is_ignored():
    """The greenium is retired, not merely defaulted to zero.

    Setting it under the shipped carrier must not quietly discount every clean
    asset - B&K find no such discount. It is ignored (with a warning), so the
    frame is identical to one that never named it.
    """
    frame = _frame("SolarCap - PV", "aligned_low_carbon")

    without = compute_yearly_npv_trajectories(frame, **SHIPPED)
    with_greenium = compute_yearly_npv_trajectories(
        frame, **{**SHIPPED, "green_discount_spread": GREENIUM}
    )

    pd.testing.assert_frame_equal(without, with_greenium)
    assert float(without["discount_rate"].iloc[0]) == pytest.approx(GREEN_RATE)


def test_the_greenium_is_live_under_the_alignment_carrier():
    """Under the ablation arm it does what it always did: -50 bps."""
    rate, _ = _rate_and_growth(
        "SolarCap - PV", "aligned_low_carbon", **PRE_RULING
    )
    assert rate == pytest.approx(GREENIUM_RATE)


def test_a_zero_greenium_under_the_alignment_carrier_is_just_the_base_rate():
    """The carrier and the greenium are independent switches."""
    rate, _ = _rate_and_growth(
        "SolarCap - PV", "aligned_low_carbon", spread_carrier=ALIGNMENT
    )
    assert rate == pytest.approx(BASE_RATE)


def test_a_negative_greenium_is_rejected_not_ignored():
    """Round-2 S1: the old `if greenium > 0` silently discarded a sign typo —
    under the alignment carrier that would report "rulings 12+13 moved
    nothing" as a completed, wrong result. It now raises."""
    with pytest.raises(ValueError, match="green_discount_spread"):
        _rate_and_growth(
            "SolarCap - PV",
            "aligned_low_carbon",
            spread_carrier="alignment_type",
            green_discount_spread=-0.005,
        )
