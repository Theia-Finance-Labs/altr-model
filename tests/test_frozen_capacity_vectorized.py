"""create_frozen_capacity_at_retirement: the vectorized extension must match
the original row-by-row construction exactly (rows, columns, order).
"""
import pandas as pd
from pandas.testing import assert_frame_equal

from crispy_kedro.pipelines.distribute_impacts_to_asset_level.nodes import (
    create_frozen_capacity_at_retirement,
)

KEY_COLS = ["asset_id", "company_id", "scenario_geography", "sector", "technology"]
KEY = dict(
    company_id="C1",
    scenario_geography="EU",
    sector="Power",
    technology="CoalCap",
)
YEARS = [2030, 2031, 2032, 2033, 2034]
RETIREMENT = {"A": 2032, "B": 2034}


def _assets():
    return pd.DataFrame(
        [
            {
                **KEY,
                "asset_id": a,
                "year": y,
                "capacity_after_shock": float(y - 2000) * (1.0 if a == "A" else 2.0),
            }
            for a in ("A", "B")
            for y in YEARS
        ]
    )


def _retirement():
    return pd.DataFrame(
        [{**KEY, "asset_id": a, "retirement_year": r} for a, r in RETIREMENT.items()]
    )


def _reference_row_by_row(assets, retirement):
    """Original implementation, kept here as the behavioural oracle."""
    merged = assets.merge(
        retirement[KEY_COLS + ["retirement_year"]], on=KEY_COLS, how="inner"
    )
    capacity = merged[merged["year"] == (merged["retirement_year"] - 1)].copy()
    capacity["frozen_capacity_at_retirement"] = capacity["capacity_after_shock"]
    capacity = capacity[
        KEY_COLS + ["frozen_capacity_at_retirement"]
    ].drop_duplicates()

    all_years = sorted(assets["year"].unique())
    records = []
    for _, row in capacity.iterrows():
        retirement_year = retirement[
            (retirement["asset_id"] == row["asset_id"])
            & (retirement["company_id"] == row["company_id"])
            & (retirement["scenario_geography"] == row["scenario_geography"])
            & (retirement["sector"] == row["sector"])
            & (retirement["technology"] == row["technology"])
        ]["retirement_year"].iloc[0]
        for year in all_years:
            if year >= retirement_year:
                records.append(
                    {
                        "asset_id": row["asset_id"],
                        "company_id": row["company_id"],
                        "scenario_geography": row["scenario_geography"],
                        "sector": row["sector"],
                        "technology": row["technology"],
                        "year": year,
                        "frozen_capacity_at_retirement": row[
                            "frozen_capacity_at_retirement"
                        ],
                    }
                )
    return (
        pd.DataFrame(records)
        .sort_values(
            [
                "company_id",
                "scenario_geography",
                "sector",
                "technology",
                "asset_id",
                "year",
            ]
        )
        .reset_index(drop=True)
    )


def test_matches_row_by_row_reference():
    assets, retirement = _assets(), _retirement()
    got = create_frozen_capacity_at_retirement(assets, retirement)
    expected = _reference_row_by_row(assets, retirement)
    assert_frame_equal(got, expected)


def test_freezes_capacity_from_the_year_before_retirement():
    got = create_frozen_capacity_at_retirement(_assets(), _retirement())
    frozen = got.set_index(["asset_id", "year"])["frozen_capacity_at_retirement"]

    # A retires in 2032 -> frozen at its 2031 capacity, extended 2032..2034
    assert frozen.loc[("A", 2032)] == 31.0
    assert frozen.loc[("A", 2034)] == 31.0
    assert ("A", 2031) not in frozen.index
    # B retires in 2034 -> frozen at its 2033 capacity, single row
    assert frozen.loc[("B", 2034)] == 66.0
    assert ("B", 2033) not in frozen.index


def test_empty_inputs_return_empty_frames():
    cols = [
        "asset_id",
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
        "year",
        "frozen_capacity_at_retirement",
    ]
    empty_retirement = create_frozen_capacity_at_retirement(
        _assets(), pd.DataFrame(columns=KEY_COLS + ["retirement_year"])
    )
    assert empty_retirement.empty and list(empty_retirement.columns) == cols

    # no asset-year matches retirement_year - 1 -> no records
    late = _retirement().assign(retirement_year=2100)
    assert create_frozen_capacity_at_retirement(_assets(), late).empty
