"""A misspelled switch must RAISE, never silently select the other branch.

Several parameters in this model select between behaviours that move published
numbers, and every one of them was reached by an ``if x == "a": ... else: ...``.
That shape has no failure mode: ``negative_tv_method: "bounded_anuity"`` (one
n) selected the unbounded perpetuity, ``retirement_timing: "Natural"`` deferred
every retirement to the window edge, and the run completed and wrote a
spreadsheet either way. The only signal was the number itself, which is exactly
the thing nobody can check by eye.

Each test below feeds one plausible misspelling to the central check
(``altr_model.parameter_checks``, run before any node since the review of #60)
and asserts the error names the parameter as a reader finds it in ``conf/``.
"""

import numpy as np
import pytest
from altr_model._validation import validate_choice
from altr_model.parameter_checks import check_parameters
from altr_model.pipelines.allocate_company_trajectories_to_assets._allocation_nodes import (  # noqa: E501
    effective_retirement_year,
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
        check_parameters({"dcf": {"negative_tv_method": "bounded_anuity"}})


def test_a_misspelled_tv_anchor_policy_raises():
    """`Operating` used to select "raw" and lose both ruling-11 corrections."""
    with pytest.raises(ValueError, match="dcf.tv_anchor_policy"):
        check_parameters({"dcf": {"tv_anchor_policy": "Operating"}})


def test_a_misspelled_spread_carrier_raises():
    """`alignment` used to fall through to the technology carrier."""
    with pytest.raises(ValueError, match="dcf.spread_carrier"):
        check_parameters({"dcf": {"spread_carrier": "alignment"}})


def test_a_misspelled_carbon_cost_method_raises():
    """`differential` used to select the differential branch by accident.

    The `else` here is the differential path, so a typo did not fall back to
    the shipped `full_ef` - it selected the OTHER method.
    """
    with pytest.raises(ValueError, match="carbon_cost_method"):
        check_parameters({"carbon_cost_method": "differential"})


def test_a_misspelled_retirement_timing_raises():
    """`Natural` used to defer every retirement to the window edge."""
    with pytest.raises(ValueError, match="retirement_timing"):
        check_parameters({"retirement_timing": "Natural"})


def test_a_misspelled_terminal_method_raises():
    """`perpetutiy` used to fall silently into the "none" (zero-TV) arm.

    `terminal_method` selects `if terminal_method == "perpetuity": ...`; a typo
    took the else, which writes no terminal value at all -- every asset's NPV
    quietly collapsed to the forecast-window sum. It was the one behaviour switch
    the node did not validate.
    """
    with pytest.raises(ValueError, match=r"dcf\.terminal_value\.method"):
        check_parameters({"dcf": {"terminal_value": {"method": "perpetutiy"}}})


# ── the legal values still work ─────────────────────────────────────────────


@pytest.mark.parametrize("timing", ["deferred_to_window", "natural"])
def test_both_legal_retirement_timings_are_accepted(timing):
    result = effective_retirement_year(2030, alignment_year=2038, retirement_timing=timing)
    expected = 2030 if timing == "natural" else 2039
    assert int(np.asarray(result)) == expected
