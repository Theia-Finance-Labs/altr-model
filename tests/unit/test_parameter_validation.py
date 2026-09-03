"""A misspelled switch must RAISE, never silently select the other branch.

Five parameters in this model select between behaviours that move published
numbers, and every one of them was reached by an ``if x == "a": ... else: ...``.
That shape has no failure mode: ``negative_tv_method: "bounded_anuity"`` (one
n) selected the unbounded perpetuity, ``retirement_timing: "Natural"`` deferred
every retirement to the window edge, and the run completed and wrote a
spreadsheet either way. The only signal was the number itself, which is exactly
the thing nobody can check by eye.

Each test below feeds one plausible misspelling and asserts the error names the
parameter as a reader finds it in ``conf/`` and lists the legal values.
"""

import numpy as np
import pandas as pd
import pytest
from altr_model._validation import validate_choice
from altr_model.pipelines.allocate_company_trajectories_to_assets._allocation_nodes import (  # noqa: E501
    effective_retirement_year,
)
from altr_model.pipelines.calculate_asset_and_company_npv.nodes import (
    compute_yearly_npv_trajectories,
)
from altr_model.pipelines.calculate_asset_earnings.nodes import compute_ops_block

META = dict(
    asset_name="a1",
    asset_id="A1",
    company_id="C1",
    company_name="c",
    scenario_geography="EU",
    sector="Power",
    technology="GasCap - w/o CCS",
    is_synthetic=False,
    alignment_type="misaligned_high_carbon",
    trajectory_type="baseline",
    scenario_type="baseline",
)


def _earnings_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [{**META, "year": year, "FCFF": 100.0} for year in (2048, 2049, 2050)]
    )


# ── the helper itself ───────────────────────────────────────────────────────


def test_validate_choice_names_the_parameter_and_every_legal_value():
    with pytest.raises(ValueError) as excinfo:
        validate_choice("dcf.some_switch", "typo", ("a", "b"))

    message = str(excinfo.value)
    assert "dcf.some_switch" in message
    assert "'a'" in message and "'b'" in message
    assert "'typo'" in message


def test_validate_choice_passes_a_legal_value_straight_through():
    assert validate_choice("dcf.some_switch", "b", ("a", "b")) == "b"


# ── one bad value per switch ────────────────────────────────────────────────


def test_a_misspelled_negative_tv_method_raises():
    """`bounded_anuity` (one n) used to select the unbounded perpetuity."""
    with pytest.raises(ValueError, match="dcf.negative_tv_method"):
        compute_yearly_npv_trajectories(
            _earnings_frame(), negative_tv_method="bounded_anuity"
        )


def test_a_misspelled_tv_anchor_policy_raises():
    """`Operating` used to select "raw" and lose both ruling-11 corrections."""
    with pytest.raises(ValueError, match="dcf.tv_anchor_policy"):
        compute_yearly_npv_trajectories(_earnings_frame(), tv_anchor_policy="Operating")


def test_a_misspelled_spread_carrier_raises():
    """`alignment` used to fall through to the technology carrier."""
    with pytest.raises(ValueError, match="dcf.spread_carrier"):
        compute_yearly_npv_trajectories(_earnings_frame(), spread_carrier="alignment")


def test_a_misspelled_carbon_cost_method_raises():
    """`differential` used to select the differential branch by accident.

    The `else` here is the differential path, so a typo did not fall back to
    the shipped `full_ef` - it selected the OTHER method.
    """
    panel = pd.DataFrame(
        [
            {
                **META,
                "year": 2050,
                "K_avg": 1.0,
                "Q": 1.0,
                "emission_factor": 0.5,
                "carbon_price_usd_per_tco2": 100.0,
                "power_price_excarbon_usd_per_mwh": 50.0,
                "fuel_price_usd_per_mwh_fuel": 10.0,
                "fom_usd_per_mw_yr": 1.0,
                "efficiency_decimal": 0.5,
                "capacity_factor": 0.5,
                "asset_trajectory": 1.0,
            }
        ]
    )
    with pytest.raises(ValueError, match="carbon_cost_method"):
        compute_ops_block(panel, carbon_cost_method="differential")


def test_a_misspelled_retirement_timing_raises():
    """`Natural` used to defer every retirement to the window edge."""
    with pytest.raises(ValueError, match="retirement_timing"):
        effective_retirement_year(2030, alignment_year=2038, retirement_timing="Natural")


# ── the legal values still work ─────────────────────────────────────────────


@pytest.mark.parametrize("timing", ["deferred_to_window", "natural"])
def test_both_legal_retirement_timings_are_accepted(timing):
    result = effective_retirement_year(2030, alignment_year=2038, retirement_timing=timing)
    expected = 2030 if timing == "natural" else 2039
    assert int(np.asarray(result)) == expected
