"""Multi-stake ownership consolidation in ``filter_companies``.

A company can hold more than one stake in the same asset (a direct holding and
an equity holding, or two rungs of the ownership tree), recorded as separate
rows for the same ``(company_id, asset_id, year)``. Those rows must collapse to
one total-stake row before the ownership table is merged onto the assets,
otherwise the duplicate keys survive into the per-asset pivot in
``calculate_asset_and_company_npv`` and it fails with "Index contains duplicate
entries".

The implementation is already here (``_consolidate_ownership_stakes``); this
regression test was not, so it is ported to pin the behaviour.

Two of the four pre-migration cases described a ``filter_companies`` that took
an ``ownership_type`` tier argument and selected ``direct`` or
``ownership_level >= 2`` rows. That function does not exist here: this
``filter_companies`` takes ``(companies_ownerships, company_ids)``, consolidates
FIRST and never selects a tier. Those two cases are re-derived against the real
signature rather than ported.
"""

import pandas as pd

from altr_model.pipelines.prepare_scenario_asset_and_company_inputs._input_nodes import (  # noqa: E501
    _consolidate_ownership_stakes,
    filter_companies,
)

KEY = ["company_id", "asset_id", "year"]

#: The columns `_consolidate_ownership_stakes` groups on, plus the summed one.
#: `ownership_type` is deliberately absent — see the assertion below.
CONSOLIDATED_COLUMNS = {
    "company_id",
    "company_name",
    "asset_id",
    "asset_name",
    "sector",
    "technology",
    "year",
    "ownership_percentage",
}


def _multi_stake_frame() -> pd.DataFrame:
    """One company holding two stake types in one asset-year, plus controls."""
    return pd.DataFrame(
        [
            # Acme holds A1 twice in 2030: 50.00 direct + 0.45 equity.
            ("A1", "plant-1", "C1", "Acme", 2030, "direct", 50.00),
            ("A1", "plant-1", "C1", "Acme", 2030, "equity", 0.45),
            # Controls that must pass through untouched.
            ("A2", "plant-2", "C1", "Acme", 2030, "direct", 30.00),
            ("A1", "plant-1", "C1", "Acme", 2031, "direct", 50.00),
            ("A1", "plant-1", "C2", "Beta", 2030, "direct", 20.00),
        ],
        columns=[
            "asset_id",
            "asset_name",
            "company_id",
            "company_name",
            "year",
            "ownership_type",
            "ownership_percentage",
        ],
    ).assign(sector="Power", technology="CoalCap")


def test_multi_stake_rows_collapse_to_one_summed_row():
    frame = _multi_stake_frame()

    out = _consolidate_ownership_stakes(frame)

    assert len(out) == 4, "the two A1/C1/2030 stake rows should become one"
    assert set(out.columns) == CONSOLIDATED_COLUMNS

    merged = out.set_index(KEY).loc[("C1", "A1", 2030)]
    assert merged["ownership_percentage"] == 50.45

    # Every other row is untouched.
    others = out.set_index(KEY)["ownership_percentage"]
    assert others.loc[("C1", "A2", 2030)] == 30.00
    assert others.loc[("C1", "A1", 2031)] == 50.00
    assert others.loc[("C2", "A1", 2030)] == 20.00


def test_consolidation_drops_the_tier_column():
    """`ownership_type` is not a group key and not summed, so it does not
    survive. That is the point: a company's total stake is direct + equity, and
    once they are added the tier of the merged row is meaningless. Nothing
    downstream may read it — the parameter of the same name is gone too."""
    out = _consolidate_ownership_stakes(_multi_stake_frame())
    assert "ownership_type" not in out.columns


def test_consolidation_preserves_the_asset_year_ownership_total():
    """Consolidation merges rows; it must never change how much of an asset is
    owned. ``allocate_assets_to_companies`` multiplies capacity by this column,
    so a shifted total would silently move allocated capacity."""
    frame = _multi_stake_frame()

    before = frame.groupby(["asset_id", "year"]).ownership_percentage.sum()
    after = _consolidate_ownership_stakes(frame).groupby(
        ["asset_id", "year"]
    ).ownership_percentage.sum()

    pd.testing.assert_series_equal(before, after)


def test_filter_companies_is_duplicate_free_with_no_company_filter():
    """The empty `company_ids` list keeps every company, and consolidation runs
    first, so no duplicate (company, asset, year) key can reach the merge."""
    out = filter_companies(_multi_stake_frame(), [])

    assert not out.duplicated(KEY).any(), "duplicate (company, asset, year) keys"
    assert set(out.company_id) == {"C1", "C2"}
    assert out.set_index(KEY)["ownership_percentage"].loc[("C1", "A1", 2030)] == 50.45


def test_filter_companies_selects_the_requested_companies_after_consolidating():
    """A company_ids filter narrows the CONSOLIDATED frame, so a selected
    company still carries its summed stake rather than one of its two rows."""
    out = filter_companies(_multi_stake_frame(), ["C1"])

    assert set(out.company_id) == {"C1"}
    assert not out.duplicated(KEY).any()
    assert out.set_index(KEY)["ownership_percentage"].loc[("C1", "A1", 2030)] == 50.45
