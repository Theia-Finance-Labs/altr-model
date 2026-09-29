"""Company NPV is floored at zero (owner ruling 2026-09-29): a company can lose
at most everything, so a carbon-price shock cannot push npv_change below -100%.
Asset and company-technology NPVs stay raw; the unfloored company sums are kept
so company totals still rebuild from the assets."""

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


def _out():
    frame = pd.DataFrame(
        _company_tech("DEEP_LOSS", [("CoalCap", 100.0, -900.0)])
        + _company_tech("OFFSET", [("CoalCap", 100.0, -50.0), ("HydroCap", 50.0, 80.0)])
        + _company_tech("NEG_BASE", [("GasCap", -20.0, -60.0)])
    )
    return aggregate_to_company_npv(frame).set_index("company_id")


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
