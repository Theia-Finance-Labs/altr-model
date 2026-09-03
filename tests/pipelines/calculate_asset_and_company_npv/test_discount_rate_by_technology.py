"""PROPOSAL: the carbon risk premium is charged by TECHNOLOGY (owner ruling 12).

Two changes, one ruling:

  * THE GREENIUM IS GONE. `green_discount_spread` subtracted 50 bps from every
    non-carbontech asset. Bolton & Kacperczyk (2021, 2023) - the source the
    spread cites - measure a penalty on high emitters and NO discount for clean
    firms, so the discount leg was financing a valuation uplift the literature
    does not support. Everything outside the brown list now sits at the base
    rate.
  * MEMBERSHIP IS BY TECHNOLOGY, not `alignment_type`. Alignment describes an
    asset's trajectory against its scenario; it is not a statement about what
    the plant burns. Keying the rate on it produced two visible misfires in the
    shipped fixture, both pinned below: offshore wind classed
    `misaligned_high_carbon` paid the fossil penalty at 8.0%, and oil classed
    `misaligned_low_carbon` collected the greenium at 6.5%.

Owner ruling 13 put the terminal growth rate on this same carrier - see
`test_terminal_growth_by_technology.py`. The tier-2 annuity still selects on
`alignment_type`, and is the last consumer in the valuation stage that does;
see `docs/superpowers/plans/consolidation-clash-report.md`, Q2-4.
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
BROWN_RATE = 0.08

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


def _rate(technology: str, alignment_type: str, **overrides) -> float:
    """The discount rate a one-asset frame is valued at."""
    frame = pd.DataFrame(
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
    out = compute_yearly_npv_trajectories(
        frame,
        **{
            "discount_rate_baseline": BASE_RATE,
            "discount_rate_shock": BASE_RATE,
            "brown_discount_spread": SPREAD,
            "brown_technologies": BROWN_TECHNOLOGIES,
            **overrides,
        },
    )
    rates = out["discount_rate"].unique()
    assert len(rates) == 1, f"one asset must have one rate, got {rates}"
    return float(rates[0])


# ── the penalty leg ─────────────────────────────────────────────────────────


def test_coal_pays_the_carbon_risk_premium():
    assert _rate("CoalCap - w/o CCS", "misaligned_high_carbon") == BROWN_RATE


@pytest.mark.parametrize(
    "technology",
    ["SolarCap - PV", "SolarCap - CSP", "WindCap - Onshore", "HydroCap", "NuclearCap"],
)
def test_clean_technologies_sit_at_the_base_rate_with_no_greenium(technology):
    """No greenium: 7.0%, not the 6.5% the deleted green leg produced."""
    assert _rate(technology, "misaligned_low_carbon") == BASE_RATE


# ── the misfires the alignment carrier produced ─────────────────────────────


def test_offshore_wind_no_longer_pays_the_fossil_penalty():
    """The misfire case. 1,560 fixture asset-years carry this exact pair.

    `WindCap - Offshore` classed `misaligned_high_carbon` was charged 8.0%, the
    coal rate, because the rate read the alignment rather than the turbine.
    """
    assert _rate("WindCap - Offshore", "misaligned_high_carbon") == BASE_RATE


def test_oil_no_longer_collects_the_greenium():
    """The mirror misfire: `OilCap` classed `misaligned_low_carbon` took 6.5%."""
    assert _rate("OilCap - w/o CCS", "misaligned_low_carbon") == BROWN_RATE


def test_alignment_type_does_not_move_the_rate_at_all():
    """One technology, every alignment it appears with: one rate."""
    alignments = [
        "misaligned_high_carbon",
        "aligned_high_carbon",
        "misaligned_low_carbon",
        "aligned_low_carbon",
    ]
    assert {_rate("GasCap - w/o CCS", a) for a in alignments} == {BROWN_RATE}
    assert {_rate("WindCap - Onshore", a) for a in alignments} == {BASE_RATE}


# ── configuration guards ────────────────────────────────────────────────────


def test_a_negative_spread_is_rejected():
    """The asymmetric guard, closed. It used to be applied unconditionally.

    A negative premium would make carbon-intensive assets CHEAPER to finance
    than everything else - the opposite of the effect the parameter names - and
    nothing said so.
    """
    frame = pd.DataFrame(
        [
            {
                **META,
                "technology": "CoalCap - w/o CCS",
                "alignment_type": "misaligned_high_carbon",
                "year": 2050,
                "FCFF": 100.0,
            }
        ]
    )
    with pytest.raises(ValueError, match="cannot be negative"):
        compute_yearly_npv_trajectories(
            frame,
            brown_discount_spread=-0.01,
            brown_technologies=BROWN_TECHNOLOGIES,
        )


def test_a_zero_spread_gives_every_technology_the_base_rate():
    assert _rate("CoalCap - w/o CCS", "misaligned_high_carbon", brown_discount_spread=0.0) == (
        BASE_RATE
    )


def test_an_empty_technology_list_charges_nobody(caplog):
    """A spread with no members is inert, and says so rather than passing quietly."""
    with caplog.at_level("WARNING"):
        rate = _rate(
            "CoalCap - w/o CCS", "misaligned_high_carbon", brown_technologies=[]
        )

    assert rate == BASE_RATE
    assert "brown_technologies" in caplog.text
