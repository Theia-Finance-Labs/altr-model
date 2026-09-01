"""Emission-factor forward-fill: vectorized groupby().ffill() == the old apply form.

validate_and_standardize_inputs used to forward-fill EF with
    .groupby([...], group_keys=False).apply(lambda g: g.assign(ef=g["ef"].ffill()))
which is ~13-17x slower than the equivalent groupby column ffill (and trips a
pandas 2.x FutureWarning about operating on the grouping columns).

The swap is behaviour-preserving by construction, so these tests are
characterization guards, not red-then-green tests: they pin the values, the row
order and the dtype the old form produced, so a future edit cannot drift.
"""
import warnings

import numpy as np
import pandas as pd

from crispy_kedro.pipelines.earnings_model.nodes import validate_and_standardize_inputs

ASSET_A = "L100000000001"
ASSET_B = "L100000000002"
TECH_A = "GasCap - w/o CCS"
TECH_B = "CoalCap"
YEARS = [2030, 2031, 2032, 2033, 2034]

# Interleaved NaNs: A has a leading gap (must stay NaN - ffill never backfills),
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


def _old_apply_ffill(frame: pd.DataFrame) -> pd.DataFrame:
    """The replaced implementation, kept here as the equivalence reference."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        return (
            frame.sort_values(["asset_id", "technology", "year"])
            .groupby(["asset_id", "technology"], group_keys=False)
            .apply(lambda g: g.assign(emission_factor=g["emission_factor"].ffill()))
        )


def _staggered_shock() -> pd.DataFrame:
    """Deliberately shuffled rows so the node's sort is load-bearing."""
    rows = [
        (asset, year)
        for asset in (ASSET_B, ASSET_A)
        for year in reversed(YEARS)
    ]
    return pd.DataFrame(
        {
            "asset_id": [a for a, _ in rows],
            "company_id": ["C1"] * len(rows),
            "scenario_geography": ["EU"] * len(rows),
            "sector": ["Power"] * len(rows),
            "technology": [TECH_BY_ASSET[a] for a, _ in rows],
            "year": [y for _, y in rows],
            "asset_age": [10] * len(rows),
            "asset_trajectory": [100.0] * len(rows),
            "trajectory_type": ["target"] * len(rows),
        }
    )


def _assets_data() -> pd.DataFrame:
    rows = [(asset, year) for asset in EF_BY_ASSET for year in YEARS]
    return pd.DataFrame(
        {
            "asset_id": [a for a, _ in rows],
            "technology": [TECH_BY_ASSET[a] for a, _ in rows],
            "scenario_geography": ["EU"] * len(rows),
            "year": [y for _, y in rows],
            "emission_factor": [
                EF_BY_ASSET[a][YEARS.index(y)] for a, y in rows
            ],
        }
    )


def _scenarios() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "scenario_geography": ["EU"],
            "sector": ["Power"],
            "technology": [TECH_A],
            "scenario_year": [2030],
            "scenario_price": [80.0],
        }
    )


def _alignments() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "company_id": ["C1"],
            "scenario_geography": ["EU"],
            "sector": ["Power"],
            "technology": [TECH_A],
            "aligned": [True],
            "increasing": [False],
        }
    )


def _validated_assets() -> pd.DataFrame:
    return validate_and_standardize_inputs(
        asset_level_staggered_shock=_staggered_shock(),
        downloaded_scenarios=_scenarios(),
        all_alignment_classifications=_alignments(),
        assets_data=_assets_data(),
    )["assets_validated"]


def test_ffill_values_and_row_order():
    assets = _validated_assets()

    assert list(assets["asset_id"]) == [ASSET_A] * 5 + [ASSET_B] * 5
    assert list(assets["year"]) == YEARS * 2
    np.testing.assert_array_equal(
        assets["emission_factor"].to_numpy(),
        np.array(EXPECTED_FFILLED[ASSET_A] + EXPECTED_FFILLED[ASSET_B]),
    )
    assert assets["emission_factor"].dtype == np.float64


def test_matches_old_apply_reference():
    """Same frame, both implementations: values, order and dtype must agree."""
    assets = _validated_assets()
    pre_ffill = assets.assign(
        emission_factor=[
            EF_BY_ASSET[a][YEARS.index(y)]
            for a, y in zip(assets["asset_id"], assets["year"])
        ]
    )

    reference = _old_apply_ffill(pre_ffill)
    vectorized = pre_ffill.sort_values(["asset_id", "technology", "year"])
    vectorized["emission_factor"] = vectorized.groupby(
        ["asset_id", "technology"]
    )["emission_factor"].ffill()

    pd.testing.assert_frame_equal(reference, vectorized)
    pd.testing.assert_series_equal(
        assets["emission_factor"], reference["emission_factor"]
    )
