"""A misspelled retirement_timing must raise even on paths that never retire.

Round-2 review finding: the helper's guard was unreachable when the allocation
is empty, retirement is disabled, or no asset retires - those paths return
early. Since the review of #60 (2026-10-08) the value is checked once, before
any node runs, by `altr_model.parameter_checks`, so every run shape fails
loudly on a typo.
"""
import pytest
from altr_model.parameter_checks import check_parameters


@pytest.mark.parametrize("typo", ["defered", "natrual", "window"])
def test_a_bad_timing_is_rejected_before_any_node_runs(typo):
    with pytest.raises(ValueError, match="retirement_timing"):
        check_parameters({"retirement_timing": typo})
