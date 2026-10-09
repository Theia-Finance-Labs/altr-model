"""Optional company NPV floor (`company_npv_floor`, owner rulings 2026-09-29 and
2026-10-07): when on, a company can lose at most everything, so a carbon-price
shock cannot push npv_change below -100%. OFF by default: summed across
companies the floor is asymmetric (a negative baseline goes to 0 while the
shock-case gain still counts) and flipped the WITCH headline from -27.2% to
+30.7%. Asset and company-technology NPVs stay raw either way; the unfloored
company sums are always kept so company totals rebuild from the assets."""

import numpy as np
import pandas as pd
from altr_model.pipelines.calculate_asset_and_company_npv.nodes import (
    aggregate_to_company_npv,
)


def _company_tech(company_id, rows):
    return [
        {
            "company_id": company_id,
            "company_name": company_id,
            "sector": "Power",
            "technology": tech,
            "scenario_geography": "EU",
            "baseline_npv": base,
            "latesudden_npv": shock,
            "baseline_discount_rate": 0.08,
            "latesudden_discount_rate": 0.08,
            "asset_count": 1,
        }
        for tech, base, shock in rows
    ]


def _frame():
    return pd.DataFrame(
        _company_tech("DEEP_LOSS", [("CoalCap", 100.0, -900.0)])
        + _company_tech("OFFSET", [("CoalCap", 100.0, -50.0), ("HydroCap", 50.0, 80.0)])
        + _company_tech("NEG_BASE", [("GasCap", -20.0, -60.0)])
    )


def _out(floor=True):
    return aggregate_to_company_npv(_frame(), floor).set_index("company_id")


def test_shock_loss_capped_at_total_loss():
    row = _out().loc["DEEP_LOSS"]
    assert row["latesudden_npv"] == 0.0
    assert row["npv_change"] == -1.0


def test_floor_applies_after_netting_technologies():
    row = _out().loc["OFFSET"]
    assert row["latesudden_npv"] == 30.0
    assert row["baseline_npv"] == 150.0


def test_negative_baseline_gives_no_percentage():
    row = _out().loc["NEG_BASE"]
    assert row["baseline_npv"] == 0.0 and row["latesudden_npv"] == 0.0
    assert np.isnan(row["npv_change"])


def test_unfloored_sums_are_kept():
    out = _out()
    assert out.loc["DEEP_LOSS", "latesudden_npv_unfloored"] == -900.0
    assert out.loc["NEG_BASE", "baseline_npv_unfloored"] == -20.0


def test_floor_is_off_by_default():
    out = aggregate_to_company_npv(_frame()).set_index("company_id")
    assert out.loc["DEEP_LOSS", "latesudden_npv"] == -900.0
    assert out.loc["DEEP_LOSS", "npv_change"] == -10.0
    assert out.loc["NEG_BASE", "baseline_npv"] == -20.0
    assert out.loc["NEG_BASE", "npv_change"] == -2.0


def test_unfloored_columns_exist_with_the_floor_off():
    out = aggregate_to_company_npv(_frame(), False)
    assert (out["baseline_npv_unfloored"] == out["baseline_npv"]).all()
    assert (out["latesudden_npv_unfloored"] == out["latesudden_npv"]).all()


def test_the_switch_is_wired_to_conf():
    from altr_model.pipelines.calculate_asset_and_company_npv.pipeline import (
        PIPELINE_PARAMETERS,
    )

    assert "company_npv_floor" in PIPELINE_PARAMETERS
