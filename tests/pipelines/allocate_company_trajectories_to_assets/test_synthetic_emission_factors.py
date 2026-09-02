"""Synthetic top-up assets inherit the EF of the assets they were built out from."""

from __future__ import annotations

import logging

import pandas as pd
import pytest
from altr_model.pipelines.allocate_company_trajectories_to_assets.nodes import (
    combine_asset_allocation_branches,
)

YEARS = [2030, 2031, 2032]


def _allocation_rows(
    asset_id: str,
    company_id: str,
    technology: str,
    geography: str,
    capacity: float | dict[int, float],
) -> list[dict]:
    """Wide-panel allocation rows, one per year, for a single asset.

    Synthetic top-ups are the ones allocation names ``NEW_<company>_...``.
    """
    by_year = capacity if isinstance(capacity, dict) else dict.fromkeys(YEARS, capacity)
    return [
        {
            "asset_id": asset_id,
            "company_id": company_id,
            "scenario_geography": geography,
            "sector": "Power",
            "technology": technology,
            "year": year,
            "is_synthetic": asset_id.startswith("NEW_"),
            "capacity_after_shock": by_year[year],
            "asset_baseline_trajectory": by_year[year],
        }
        for year in YEARS
    ]


def _source_rows(
    asset_id: str,
    company_id: str,
    technology: str,
    geography: str,
    emission_factor: float,
) -> list[dict]:
    """`assets_with_baseline` metadata rows — the EF source for real assets."""
    return [
        {
            "asset_id": asset_id,
            "company_id": company_id,
            "scenario_geography": geography,
            "sector": "Power",
            "technology": technology,
            "year": year,
            "emission_factor": emission_factor,
            "retirement_year": pd.NA,
            "asset_lifetime_years": 40.0,
        }
        for year in YEARS
    ]


def _universe(
    extra_allocation: list[dict] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Real BiomassCap assets across two geographies, plus any synthetic rows.

    World: EF 0.8 at capacity 10 and EF 0.3 at capacity 30
        -> capacity-weighted World EF = (0.8*10 + 0.3*30) / 40 = 0.425
    EU:    EF 1.0 at capacity 10
        -> technology-wide EF = (8 + 9 + 10) / 50 = 0.54
    """
    allocation = (
        _allocation_rows("R1", "C1", "BiomassCap", "World", 10.0)
        + _allocation_rows("R2", "C1", "BiomassCap", "World", 30.0)
        + _allocation_rows("R3", "C3", "BiomassCap", "EU", 10.0)
        + (extra_allocation or [])
    )
    source = (
        _source_rows("R1", "C1", "BiomassCap", "World", 0.8)
        + _source_rows("R2", "C1", "BiomassCap", "World", 0.3)
        + _source_rows("R3", "C3", "BiomassCap", "EU", 1.0)
    )
    return pd.DataFrame(allocation), pd.DataFrame(source)


def _combine(allocation: pd.DataFrame, source: pd.DataFrame) -> pd.DataFrame:
    """Both branches are concatenated, so the split between them is immaterial."""
    return combine_asset_allocation_branches(
        allocation, allocation.iloc[0:0].copy(), source
    )


def _synthetic_ef(combined: pd.DataFrame, asset_id: str) -> list[float]:
    """The distinct emission factors one asset carries across the horizon."""
    return sorted(
        set(combined.loc[combined["asset_id"].eq(asset_id), "emission_factor"])
    )


def test_synthetic_inherits_its_own_companys_capacity_weighted_emission_factor():
    allocation, source = _universe(
        _allocation_rows("NEW_C1", "C1", "BiomassCap", "World", 5.0)
    )

    combined = _combine(allocation, source)

    assert _synthetic_ef(combined, "NEW_C1") == pytest.approx([0.425])


def test_synthetic_without_company_assets_falls_back_to_technology_and_geography():
    """C2 owns nothing in BiomassCap/World, so it inherits the whole group's EF."""
    allocation, source = _universe(
        _allocation_rows("NEW_C2", "C2", "BiomassCap", "World", 5.0)
    )

    combined = _combine(allocation, source)

    assert _synthetic_ef(combined, "NEW_C2") == pytest.approx([0.425])


def test_synthetic_in_an_unrepresented_geography_falls_back_to_technology_wide():
    """No real BiomassCap asset stands in US, so the technology-wide EF applies."""
    allocation, source = _universe(
        _allocation_rows("NEW_C4", "C4", "BiomassCap", "US", 5.0)
    )

    combined = _combine(allocation, source)

    assert _synthetic_ef(combined, "NEW_C4") == pytest.approx([0.54])


def test_technology_with_no_real_assets_anywhere_gets_zero_and_warns(caplog):
    allocation, source = _universe(
        _allocation_rows("NEW_C5", "C5", "OilCap", "World", 5.0)
    )

    with caplog.at_level(logging.WARNING):
        combined = _combine(allocation, source)

    assert _synthetic_ef(combined, "NEW_C5") == [0.0]
    assert any(
        record.levelno == logging.WARNING and "OilCap" in record.getMessage()
        for record in caplog.records
    )


def test_real_assets_keep_their_own_emission_factors():
    allocation, source = _universe(
        _allocation_rows("NEW_C1", "C1", "BiomassCap", "World", 5.0)
    )

    combined = _combine(allocation, source)

    assert _synthetic_ef(combined, "R1") == [0.8]
    assert _synthetic_ef(combined, "R2") == [0.3]
    assert _synthetic_ef(combined, "R3") == [1.0]


def test_year_without_weighting_capacity_reuses_the_nearest_available_year():
    """Both real assets stand down in 2032, so 2032 carries 2031's group EF."""
    standing_down = {2030: 10.0, 2031: 10.0, 2032: 0.0}
    allocation = pd.DataFrame(
        _allocation_rows("R1", "C1", "BiomassCap", "World", standing_down)
        + _allocation_rows(
            "R2", "C1", "BiomassCap", "World", {2030: 30.0, 2031: 30.0, 2032: 0.0}
        )
        + _allocation_rows("NEW_C1", "C1", "BiomassCap", "World", 5.0)
    )
    source = pd.DataFrame(
        _source_rows("R1", "C1", "BiomassCap", "World", 0.8)
        + _source_rows("R2", "C1", "BiomassCap", "World", 0.3)
    )

    combined = _combine(allocation, source)

    assert _synthetic_ef(combined, "NEW_C1") == pytest.approx([0.425])


def test_renewable_synthetics_still_take_zero():
    """The renewable rule runs first and is untouched by the inheritance rule."""
    allocation, source = _universe(
        _allocation_rows("NEW_C6", "C6", "SolarCap - PV", "World", 5.0)
    )

    combined = _combine(allocation, source)

    assert _synthetic_ef(combined, "NEW_C6") == [0.0]
