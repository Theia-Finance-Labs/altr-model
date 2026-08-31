"""Regression: ownership_percentage is on the 0-100 scale, not 0-1.

allocate_assets_to_companies used to do a bare `capacity * ownership_percentage`,
inflating every allocated capacity ~100x (a 466 MW asset held 50% became 23,300).
The extract convention is percent -- notebooks/prepare_new_inputs.py's
check_ownership_tier validates the selected tier sums to ~100 -- so the product
must be divided by 100.
"""
import pandas as pd
import pytest

from crispy_kedro.pipelines.inputs_processing.nodes import (
    allocate_assets_to_companies,
)

SCENARIOS = pd.DataFrame({"year": [2025, 2026]})


def _assets(capacity=466.0):
    return pd.DataFrame([{
        "asset_id": "A1", "technology": "GasCap - w/o CCS", "year": 2025,
        "capacity": capacity,
    }])


def _companies(stakes):
    return pd.DataFrame([{
        "asset_id": "A1", "company_id": cid, "year": 2025,
        "ownership_percentage": pct,
    } for cid, pct in stakes])


def test_single_owner_allocation_uses_percent_scale():
    out = allocate_assets_to_companies(_assets(), _companies([("C1", 50.0)]), SCENARIOS)
    assert out["asset_activity"].tolist() == [233.0]


def test_two_owners_split_the_asset_without_inflation():
    out = allocate_assets_to_companies(
        _assets(), _companies([("C1", 50.0), ("C2", 50.0)]), SCENARIOS
    )
    assert out["asset_activity"].tolist() == [233.0, 233.0]
    assert out["asset_activity"].sum() == 466.0


def test_fraction_scale_input_is_rejected():
    with pytest.raises(ValueError, match="ownership_percentage"):
        allocate_assets_to_companies(
            _assets(), _companies([("C1", 0.5), ("C2", 0.5)]), SCENARIOS
        )
