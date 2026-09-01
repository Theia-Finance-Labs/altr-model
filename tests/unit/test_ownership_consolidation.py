"""Multi-stake ownership consolidation in ``filter_companies``.

A company can hold more than one stake in the same asset (a direct holding and
an equity holding, or two rungs of the ownership tree), recorded as separate
rows for the same ``(company_id, asset_id, year)``. Those rows must collapse to
one total-stake row before the ownership table is merged onto the assets,
otherwise the duplicate keys survive into the per-asset pivot in
``valuation_model`` and it fails with "Index contains duplicate entries".

Ported from upstream commit 63f5b59; see ``_consolidate_ownership_stakes``.
"""

import pandas as pd

from crispy_kedro.pipelines.inputs_processing.nodes import (
    _consolidate_ownership_stakes,
    filter_companies,
)

KEY = ["company_id", "asset_id", "year"]


def _multi_stake_frame() -> pd.DataFrame:
    """One company holding two stake types in one asset-year, plus controls."""
    return pd.DataFrame(
        [
            # Acme holds A1 twice in 2030: 50.00 direct + 0.45 equity.
            ("A1", "C1", "Acme", 2030, "direct", 50.00),
            ("A1", "C1", "Acme", 2030, "equity", 0.45),
            # Controls that must pass through untouched.
            ("A2", "C1", "Acme", 2030, "direct", 30.00),
            ("A1", "C1", "Acme", 2031, "direct", 50.00),
            ("A1", "C2", "Beta", 2030, "direct", 20.00),
        ],
        columns=[
            "asset_id",
            "company_id",
            "company_name",
            "year",
            "ownership_type",
            "ownership_percentage",
        ],
    )


def test_multi_stake_rows_collapse_to_one_summed_row():
    frame = _multi_stake_frame()

    out = _consolidate_ownership_stakes(frame)

    assert len(out) == 4, "the two A1/C1/2030 stake rows should become one"
    assert set(out.columns) == set(frame.columns), "column set must be unchanged"

    merged = out.set_index(KEY).loc[("C1", "A1", 2030)]
    assert merged["ownership_percentage"] == 50.45

    # The tier column survives consolidation: inputs_postproc's
    # apply_reduce_granularity_from_asset_to_company_level groups by it.
    assert merged["ownership_type"] == "direct"

    # Every other row is untouched.
    others = out.set_index(KEY)["ownership_percentage"]
    assert others.loc[("C1", "A2", 2030)] == 30.00
    assert others.loc[("C1", "A1", 2031)] == 50.00
    assert others.loc[("C2", "A1", 2030)] == 20.00


def test_consolidation_preserves_the_asset_year_ownership_total():
    """Consolidation merges rows; it must never change how much of an asset is
    owned. ``allocate_assets_to_companies`` multiplies capacity by this column
    (0-100 scale, divided by 100), so a shifted total would silently move
    allocated capacity."""
    frame = _multi_stake_frame()

    before = frame.groupby(["asset_id", "year"]).ownership_percentage.sum()
    after = _consolidate_ownership_stakes(frame).groupby(
        ["asset_id", "year"]
    ).ownership_percentage.sum()

    pd.testing.assert_series_equal(before, after)


def test_filter_companies_is_duplicate_free_on_the_indirect_tier():
    """``ownership_type="indirect"`` selects ``ownership_level >= 2``, so more
    than one rung reaches the groupby. Both rungs are the same parent company's
    stake in the same asset and must total into one row."""
    frame = pd.DataFrame(
        [
            ("A1", "C1", "Acme", 2030, 2, 30.0),
            ("A1", "C1", "Acme", 2030, 3, 12.0),
            ("A1", "C2", "Beta", 2030, 2, 58.0),
            # Level 1 is the direct tier; the indirect filter must drop it.
            ("A1", "C3", "Gamma", 2030, 1, 100.0),
        ],
        columns=[
            "asset_id",
            "company_id",
            "company_name",
            "production_year",
            "ownership_level",
            "ownership_percentage",
        ],
    )

    out = filter_companies(frame, [], "indirect")

    assert not out.duplicated(KEY).any(), "duplicate (company, asset, year) keys"
    assert len(out) == 2
    assert "C3" not in set(out.company_id), "direct tier leaked into indirect"

    stakes = out.set_index(KEY)["ownership_percentage"]
    assert stakes.loc[("C1", "A1", 2030)] == 42.0
    assert stakes.loc[("C2", "A1", 2030)] == 58.0


def test_filter_companies_is_duplicate_free_on_the_direct_tier():
    """The configured tier (``ownership_type: "direct"``). The tier filter runs
    first, so the equity rows never reach consolidation and cannot inflate the
    direct stake."""
    frame = _multi_stake_frame().rename(columns={"year": "production_year"})

    out = filter_companies(frame, [], "direct")

    assert not out.duplicated(KEY).any()
    assert out.set_index(KEY)["ownership_percentage"].loc[("C1", "A1", 2030)] == 50.00
