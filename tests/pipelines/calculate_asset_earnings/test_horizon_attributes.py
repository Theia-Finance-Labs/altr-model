"""PROPOSAL: `asset_horizon_attributes`, the valuation stage's second input.

The bounded negative terminal value (decision #5 / clash D3) prices an exit off
four scalars measured at the LAST forecast year: `lifetime_years`, `asset_age`,
`scrap_usd_per_mw` and the `asset_trajectory` capacity still standing. They are
per-series constants, so they travel in their own one-row-per-series table
rather than repeated down every row of `asset_earnings`.

The table is built from the panel BEFORE the CapEx flow split, where one
asset-year is still one row - so "the horizon" is the last row of a year-sorted
group, with no aggregation choice to make.
"""

import numpy as np
import pandas as pd
from altr_model.pipelines.calculate_asset_earnings.nodes import (
    ASSET_SERIES_KEYS,
    write_asset_horizon_attributes,
)

META = dict(
    company_id="C1",
    asset_id="A1",
    scenario_geography="EU",
    sector="Power",
    technology="GasCap - w/o CCS",
    trajectory_type="baseline",
)

#: The horizon year of every panel below, and the values standing in it.
HORIZON_CAPACITY = 100.0
HORIZON_AGE = 30.0
LIFETIME = 45.0
SCRAP = -100.0

#: An earlier year, deliberately different in every column, so a reduction that
#: reached back for it would be visible rather than coincidentally right.
EARLIER_CAPACITY = 500.0
EARLIER_AGE = 29.0
EARLIER_SCRAP = -100.0

#: The second series, on the shock trajectory.
SHOCK_CAPACITY = 30.0
SHOCK_AGE = 10.0

EXPECTED_COLUMNS = ASSET_SERIES_KEYS + [
    "lifetime_years",
    "asset_age",
    "scrap_usd_per_mw",
    "asset_trajectory",
]


def _panel(rows: list[dict], **overrides) -> pd.DataFrame:
    return pd.DataFrame([{**META, **overrides, **row} for row in rows])


def test_one_row_per_asset_series_carrying_the_final_years_values():
    """Two series, each reduced to its OWN last year - not the panel's."""
    panel = pd.concat(
        [
            _panel(
                [
                    {
                        "year": 2049,
                        "asset_trajectory": EARLIER_CAPACITY,
                        "asset_age": EARLIER_AGE,
                    },
                    {
                        "year": 2050,
                        "asset_trajectory": HORIZON_CAPACITY,
                        "asset_age": HORIZON_AGE,
                    },
                ],
                lifetime_years=LIFETIME,
                scrap_usd_per_mw=SCRAP,
            ),
            _panel(
                [
                    {"year": 2049, "asset_trajectory": 20.0, "asset_age": 9.0},
                    {
                        "year": 2050,
                        "asset_trajectory": SHOCK_CAPACITY,
                        "asset_age": SHOCK_AGE,
                    },
                ],
                trajectory_type="latesudden",
                lifetime_years=25.0,
                scrap_usd_per_mw=-40.0,
            ),
        ],
        ignore_index=True,
    )

    horizon = write_asset_horizon_attributes(panel)

    assert len(horizon) == len(panel["trajectory_type"].unique())
    assert list(horizon.columns) == EXPECTED_COLUMNS

    baseline = horizon[horizon["trajectory_type"] == "baseline"].iloc[0]
    assert baseline["asset_trajectory"] == HORIZON_CAPACITY
    assert baseline["asset_age"] == HORIZON_AGE
    assert baseline["lifetime_years"] == LIFETIME
    assert baseline["scrap_usd_per_mw"] == SCRAP

    shock = horizon[horizon["trajectory_type"] == "latesudden"].iloc[0]
    assert shock["asset_trajectory"] == SHOCK_CAPACITY
    assert shock["asset_age"] == SHOCK_AGE


def test_a_year_out_of_order_still_reduces_to_the_highest_year():
    """The horizon is the maximum year, not the last row as it arrives."""
    panel = _panel(
        [
            {"year": 2050, "asset_trajectory": HORIZON_CAPACITY, "asset_age": HORIZON_AGE},
            {"year": 2048, "asset_trajectory": 900.0, "asset_age": 28.0},
            {
                "year": 2049,
                "asset_trajectory": EARLIER_CAPACITY,
                "asset_age": EARLIER_AGE,
            },
        ],
        lifetime_years=LIFETIME,
        scrap_usd_per_mw=SCRAP,
    )

    horizon = write_asset_horizon_attributes(panel)

    assert len(horizon) == 1
    assert horizon.iloc[0]["asset_trajectory"] == HORIZON_CAPACITY
    assert horizon.iloc[0]["asset_age"] == HORIZON_AGE


def test_a_missing_value_at_the_horizon_stays_missing():
    """The last ROW, never the last non-null value per column.

    A group reduced with `groupby.last()` would reach back for 2049's scrap
    price and report it as the horizon's - a silently wrong exit quote. The
    valuation stage has a fallback for a MISSING scrap price and none for a
    wrong one, so the missingness has to survive this node.
    """
    panel = _panel(
        [
            {
                "year": 2049,
                "asset_trajectory": EARLIER_CAPACITY,
                "scrap_usd_per_mw": EARLIER_SCRAP,
            },
            {
                "year": 2050,
                "asset_trajectory": HORIZON_CAPACITY,
                "scrap_usd_per_mw": np.nan,
            },
        ],
        asset_age=HORIZON_AGE,
        lifetime_years=LIFETIME,
    )

    horizon = write_asset_horizon_attributes(panel)

    assert len(horizon) == 1
    assert pd.isna(horizon.iloc[0]["scrap_usd_per_mw"])


def test_a_panel_without_lifetime_still_produces_the_columns_it_has():
    """A column the panel does not carry is simply absent, not fatal.

    `lifetime_years` is not in `validate_asset_trajectories`' required set, so a
    panel can legitimately arrive without it; the valuation stage then falls
    back to the tier-2 annuity horizon.
    """
    panel = _panel(
        [{"year": 2050, "asset_trajectory": HORIZON_CAPACITY, "asset_age": HORIZON_AGE}],
        scrap_usd_per_mw=SCRAP,
    )

    horizon = write_asset_horizon_attributes(panel)

    assert "lifetime_years" not in horizon.columns
    assert horizon.iloc[0]["asset_trajectory"] == HORIZON_CAPACITY


def test_a_text_valued_column_is_coerced_to_a_number():
    """CSV round-trips arrive as strings; the valuation stage does float maths."""
    panel = _panel(
        [{"year": 2050, "asset_trajectory": "100.0", "asset_age": "30"}],
        lifetime_years="45",
        scrap_usd_per_mw="-100.0",
    )

    horizon = write_asset_horizon_attributes(panel)

    assert horizon["asset_trajectory"].dtype.kind == "f"
    assert horizon.iloc[0]["lifetime_years"] == LIFETIME
