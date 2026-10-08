"""`decom_cost_fraction_of_capex` recalibrates the delivered scrap value.

The marts drop carries ``scrap_usd_per_mw = -capital_cost/2``: retiring a plant
is charged half of what building it cost. That one column feeds BOTH the
in-window decommissioning charge (calculate_asset_earnings) and the terminal
value's decommissioning floor (calculate_asset_and_company_npv), so the
calibration is applied once, where the column enters, and every consumer
sees the same number.
"""

import numpy as np
import pandas as pd
import pytest
from altr_model.pipelines.prepare_scenario_asset_and_company_inputs._input_nodes import (
    apply_decom_cost_fraction,
)


def _scenarios() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "technology": ["CoalCap - w/o CCS", "SolarCap - PV", "GasCap - w/o CCS"],
            "capex_usd_per_mw": [2_000_000.0, 800_000.0, 1_000_000.0],
            "scrap_usd_per_mw": [-1_000_000.0, -400_000.0, -500_000.0],
        }
    )


def test_none_keeps_the_delivered_scrap_value():
    scenarios = _scenarios()
    out = apply_decom_cost_fraction(scenarios, None)
    pd.testing.assert_frame_equal(out, scenarios)


def test_a_fraction_rewrites_scrap_as_a_negative_share_of_capex():
    out = apply_decom_cost_fraction(_scenarios(), 0.15)
    np.testing.assert_allclose(
        out["scrap_usd_per_mw"], [-300_000.0, -120_000.0, -150_000.0]
    )
    assert (
        out["scrap_usd_per_mw"] < 0
    ).all(), "scrap stays negative: the charge site takes abs()"


def test_the_input_frame_is_not_mutated():
    scenarios = _scenarios()
    before = scenarios.copy()
    apply_decom_cost_fraction(scenarios, 0.15)
    pd.testing.assert_frame_equal(scenarios, before)


@pytest.mark.parametrize("fraction", [1.5, -0.1, float("nan")])
def test_a_fraction_outside_the_unit_interval_is_rejected(fraction):
    with pytest.raises(ValueError, match="decom_cost_fraction_of_capex"):
        apply_decom_cost_fraction(_scenarios(), fraction)


def test_a_missing_capex_column_is_rejected_by_name():
    with pytest.raises(ValueError, match="capex_usd_per_mw"):
        apply_decom_cost_fraction(_scenarios().drop(columns="capex_usd_per_mw"), 0.15)
