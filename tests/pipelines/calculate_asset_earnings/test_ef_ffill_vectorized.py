"""Emission-factor forward-fill in ``validate_asset_trajectories``.

Ported from the handover branch's ``tests/test_ef_ffill_vectorized.py`` under
the 2026-09-01 owner ruling (Q3): the earnings stage forward-fills
``emission_factor`` along each asset series before the renewable zero-fill,
instead of leaving the gaps for ``compute_ops_block``'s ``fillna(0.0)`` to turn
into "this plant emits nothing".

Two behaviours are pinned:

* a leading gap stays NaN — a forward fill never backfills, so an asset whose
  EF is unknown in its first years does not inherit a later value;
* trailing gaps carry the last observed value forward, which is the case that
  matters in production: the EF series is shorter than the trajectory horizon.

The fill runs on ``ASSET_SERIES_KEYS`` (this tree's canonical asset-series
grain), not on the handover branch's ``(asset_id, technology)`` — see
docs/superpowers/plans/consolidation-clash-report.md, entry Q3-1.
"""

import numpy as np
import pandas as pd
from altr_model.pipelines.calculate_asset_earnings.nodes import (
    ASSET_SERIES_KEYS,
    validate_asset_trajectories,
)

ASSET_A = "L100000000001"
ASSET_B = "L100000000002"
TECH_A = "GasCap - w/o CCS"
TECH_B = "CoalCap"
YEARS = [2030, 2031, 2032, 2033, 2034]

# Interleaved NaNs: A has a leading gap (must stay NaN — ffill never backfills),
# B has trailing gaps (must carry the last observed value forward).
EF_BY_ASSET = {
    ASSET_A: [np.nan, 0.5, np.nan, np.nan, 0.7],
    ASSET_B: [1.2, np.nan, 0.9, np.nan, np.nan],
}
EXPECTED_FFILLED = {
    ASSET_A: [np.nan, 0.5, 0.5, 0.5, 0.7],
    ASSET_B: [1.2, 1.2, 0.9, 0.9, 0.9],
}
TECH_BY_ASSET = {ASSET_A: TECH_A, ASSET_B: TECH_B}

NUMERIC_DEFAULTS = {
    "asset_age": 10.0,
    "asset_trajectory": 100.0,
    "capacity_factor": 0.5,
    "power_price_excarbon_usd_per_mwh": 80.0,
    "fuel_price_usd_per_mwh_fuel": 20.0,
    "capex_usd_per_mw": 1.0e6,
    "fom_usd_per_mw_yr": 1.0e4,
    "carbon_price_usd_per_tco2": 50.0,
    "efficiency_decimal": 0.5,
    "scrap_usd_per_mw": -5.0e5,
}


def _asset_trajectories() -> pd.DataFrame:
    """Deliberately shuffled rows so the node's own year ordering is load-bearing."""
    rows = [
        (asset, year)
        for asset in (ASSET_B, ASSET_A)
        for year in reversed(YEARS)
    ]
    frame = pd.DataFrame(
        {
            "asset_id": [asset for asset, _ in rows],
            "company_id": ["C1"] * len(rows),
            "scenario_geography": ["EU"] * len(rows),
            "sector": ["Power"] * len(rows),
            "technology": [TECH_BY_ASSET[asset] for asset, _ in rows],
            "trajectory_type": ["latesudden"] * len(rows),
            "year": [year for _, year in rows],
            "scenario": ["AR6_TEST_target"] * len(rows),
            "scenario_type": ["target"] * len(rows),
            "emission_factor": [
                EF_BY_ASSET[asset][YEARS.index(year)] for asset, year in rows
            ],
        }
    )
    for column, value in NUMERIC_DEFAULTS.items():
        frame[column] = value
    return frame


def _validated() -> pd.DataFrame:
    return validate_asset_trajectories(_asset_trajectories())


def test_ffill_values_and_row_order():
    assets = _validated().sort_values(ASSET_SERIES_KEYS + ["year"])

    assert list(assets["asset_id"]) == [ASSET_A] * 5 + [ASSET_B] * 5
    assert list(assets["year"]) == YEARS * 2
    np.testing.assert_array_equal(
        assets["emission_factor"].to_numpy(),
        np.array(EXPECTED_FFILLED[ASSET_A] + EXPECTED_FFILLED[ASSET_B]),
    )
    assert assets["emission_factor"].dtype == np.float64


def test_leading_gap_is_not_backfilled():
    """The one case a fillna(0.0) and a ffill agree on must stay NaN here."""
    assets = _validated()
    leading = assets.loc[
        (assets["asset_id"] == ASSET_A) & (assets["year"] == YEARS[0]),
        "emission_factor",
    ]
    assert leading.isna().all()


def test_renewable_zero_fill_still_applies_after_the_ffill():
    """Renewables with no EF anywhere keep landing on 0.0, not on NaN."""
    frame = _asset_trajectories()
    frame.loc[frame["asset_id"] == ASSET_A, "technology"] = "SolarCap - PV"
    frame.loc[frame["asset_id"] == ASSET_A, "emission_factor"] = np.nan

    assets = validate_asset_trajectories(frame)
    solar = assets.loc[assets["technology"] == "SolarCap - PV", "emission_factor"]
    assert (solar == 0.0).all()


def test_fill_does_not_cross_asset_series():
    """B's leading value must not leak into A's leading gap."""
    assets = _validated().set_index(["asset_id", "year"])["emission_factor"]
    assert assets[(ASSET_A, 2030)] != assets[(ASSET_B, 2030)] or np.isnan(
        assets[(ASSET_A, 2030)]
    )
    assert np.isnan(assets[(ASSET_A, 2030)])
    assert assets[(ASSET_B, 2034)] == 0.9
