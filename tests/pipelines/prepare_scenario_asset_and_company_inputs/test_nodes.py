"""Focused tests for scenario, asset, and company input preparation."""

import pandas as pd
from altr_model.pipelines.prepare_scenario_asset_and_company_inputs._asset_preparation import (
    apply_reduce_granularity_from_asset_to_company_level,
)
from altr_model.pipelines.prepare_scenario_asset_and_company_inputs.nodes import (
    FINANCIAL_SURFACE_COLUMNS,
    prepare_company_projection_inputs,
)


def test_reduced_granularity_creates_one_synthetic_company_asset():
    shared = {
        "company_id": "company",
        "company_name": "Company",
        "scenario_geography": "World",
        "sector": "Power",
        "technology": "CoalCap",
        "year": 2030,
        "capacity_unit": "MW",
        "asset_age": 10.0,
        "age_is_inferred": False,
        "ownership_percentage": 1.0,
        "capacity_factor": 0.5,
        "emission_factor": 0.9,
    }
    assets = pd.DataFrame(
        [
            {**shared, "asset_id": "a", "asset_activity": 3.0},
            {**shared, "asset_id": "b", "asset_activity": 4.0},
        ]
    )

    reduced = apply_reduce_granularity_from_asset_to_company_level(assets, True)

    assert len(reduced) == 1
    assert reduced.loc[0, "asset_activity"] == 7.0
    assert reduced.loc[0, "asset_id"].startswith("unique_company_asset_")


# ── an unnamed company survives to the company projection inputs ─────────────
# `_consolidate_ownership_stakes` keeps a stake whose `company_name` is blank.
# That is worth nothing on its own: every company-grain aggregation between it
# and the projection inputs used to group ON `company_name`, so pandas deleted
# the row again one or two stages later — the fix was undone downstream and no
# row count said so. This is the end-to-end pin.

_PANEL_YEARS = [2030, 2031]


def _asset_panel() -> pd.DataFrame:
    """Two companies in one geography/sector/technology. C1 has NO name."""
    shared = {
        "scenario_geography": "World",
        "sector": "Power",
        "technology": "CoalCap",
        "capacity_unit": "MW",
        "asset_age": 10.0,
        "age_is_inferred": False,
        "ownership_percentage": 100.0,
        "capacity_factor": 0.5,
        "emission_factor": 0.9,
    }
    rows = []
    for year in _PANEL_YEARS:
        rows += [
            # The unnamed company, holding two assets so the roll-up has work.
            {
                **shared,
                "company_id": "C1",
                "company_name": pd.NA,
                "asset_id": "a",
                "year": year,
                "asset_activity": 3.0,
            },
            {
                **shared,
                "company_id": "C1",
                "company_name": pd.NA,
                "asset_id": "b",
                "year": year,
                "asset_activity": 4.0,
            },
            # A named control, to prove the drop is about the blank name.
            {
                **shared,
                "company_id": "C2",
                "company_name": "Beta",
                "asset_id": "c",
                "year": year,
                "asset_activity": 5.0,
            },
        ]
    return pd.DataFrame(rows)


def _scenario_pathways() -> pd.DataFrame:
    """The narrowest frame `prepare_company_projection_inputs` can consume."""
    pathways = pd.DataFrame(
        {
            "scenario_geography": "World",
            "sector": "Power",
            "technology": "CoalCap",
            "year": _PANEL_YEARS,
            "scenario_type": "baseline",
            "tmsr": [0.0, -0.1],
            "increasing": False,
        }
    )
    for column in FINANCIAL_SURFACE_COLUMNS:
        pathways[column] = "AR6_baseline" if column == "scenario" else 1.0
    return pathways


def test_a_company_with_no_name_reaches_the_company_projection_inputs():
    projection = prepare_company_projection_inputs(_asset_panel(), _scenario_pathways())

    assert set(projection["company_id"]) == {"C1", "C2"}, (
        "the unnamed company was dropped between the asset panel and the "
        "company projection inputs"
    )
    unnamed = projection.loc[projection.company_id == "C1"]
    # Both of C1's assets are in the total: the roll-up summed, not filtered.
    assert set(unnamed["company_activity"]) == {7.0}
    assert unnamed["company_name"].isna().all(), "it is unnamed, not renamed"


def test_the_unnamed_company_survives_the_reduced_granularity_path_too():
    """The other company-grain roll-up, on the `reduce_granularity` mode: it
    collapses a company's assets into one synthetic company-asset BEFORE the
    panel reaches the projection inputs, so it can delete the same row."""
    reduced = apply_reduce_granularity_from_asset_to_company_level(_asset_panel(), True)

    assert set(reduced["company_id"]) == {"C1", "C2"}
    assert set(reduced.loc[reduced.company_id == "C1", "asset_activity"]) == {7.0}

    projection = prepare_company_projection_inputs(reduced, _scenario_pathways())

    assert set(projection["company_id"]) == {"C1", "C2"}
    assert set(projection.loc[projection.company_id == "C1", "company_activity"]) == {
        7.0
    }
