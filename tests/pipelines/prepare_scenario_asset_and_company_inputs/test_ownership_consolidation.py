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

``filter_companies`` selects an ownership TIER before consolidating, restored
from the handover branch under the 2026-09-01 owner ruling. The two operations
have to run in that order: a direct holding and the equity stakes rolling up
through subsidiaries are alternative views of the same capacity, not additive
ones, so summing across tiers allocates the same plant to the same company
twice. Consolidation then only ever sums within one rung — several stakes of
the same tier in one asset-year, which do add up.

``_consolidate_ownership_stakes`` is still tested on its own, on a frame that
mixes tiers, because its contract is "sum whatever you are given" and that is
what the ordering above relies on.

That ordering is the DEFAULT, not the only behaviour: the same ruling made it
the ``ownership_aggregation: "tier_filter"`` mode, alongside ``"sum"``, which
skips the tier selection so a company's direct and equity holdings are totalled
(TRISK's reading). The tests up to ``test_a_companies_input_with_no_tier_column…``
pin the default; the section after it pins the alternative.
"""

import pandas as pd
import pytest

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
    """The empty `company_ids` list keeps every company, and the tier selection
    plus consolidation run first, so no duplicate (company, asset, year) key can
    reach the merge."""
    out = filter_companies(_multi_stake_frame(), [])

    assert not out.duplicated(KEY).any(), "duplicate (company, asset, year) keys"
    assert set(out.company_id) == {"C1", "C2"}
    assert out.set_index(KEY)["ownership_percentage"].loc[("C1", "A1", 2030)] == 50.00


def test_filter_companies_selects_the_requested_companies():
    out = filter_companies(_multi_stake_frame(), ["C1"])

    assert set(out.company_id) == {"C1"}
    assert not out.duplicated(KEY).any()


def test_direct_tier_excludes_the_equity_stake_in_the_same_asset():
    """The 0.45 equity rung is a view of the same holding as the 50.00 direct
    one. Adding them to 50.45 would allocate that plant to Acme twice."""
    out = filter_companies(_multi_stake_frame(), [], ownership_type="direct")

    assert out.set_index(KEY)["ownership_percentage"].loc[("C1", "A1", 2030)] == 50.00


def test_equity_tier_selects_the_other_rung():
    """The named schema's other rung is "equity". Selecting it returns the
    equity rows — the direct 50.00 stake drops out and the 0.45 one remains."""
    out = filter_companies(_multi_stake_frame(), [], ownership_type="equity")

    assert out.set_index(KEY)["ownership_percentage"].loc[("C1", "A1", 2030)] == 0.45


def test_a_tier_the_data_does_not_carry_is_rejected():
    """"indirect" is the documented-but-wrong name for the equity rung. Under
    the named schema it matches nothing, and an empty panel takes every company
    out of the run silently — so it must raise, naming what is available."""
    with pytest.raises(ValueError, match="indirect") as excinfo:
        filter_companies(_multi_stake_frame(), [], ownership_type="indirect")

    assert "'direct'" in str(excinfo.value) and "'equity'" in str(excinfo.value)


def test_a_numbered_rung_that_maps_to_nothing_is_rejected():
    """The numbered schema keeps its rung semantics — "direct" is level 1, any
    other value is level 2+ — but a selection that maps to no row still raises
    rather than emptying the panel."""
    frame = _multi_stake_frame().rename(columns={"ownership_type": "ownership_level"})
    frame["ownership_level"] = 1

    with pytest.raises(ValueError, match="ownership_level"):
        filter_companies(frame, [], ownership_type="equity")


def test_ownership_level_schema_maps_onto_the_same_tiers():
    """The newer companies schema numbers the rungs instead of naming them."""
    frame = _multi_stake_frame().rename(columns={"ownership_type": "ownership_level"})
    frame["ownership_level"] = frame["ownership_level"].map({"direct": 1, "equity": 2})

    direct = filter_companies(frame, [], ownership_type="direct")
    indirect = filter_companies(frame, [], ownership_type="indirect")

    assert direct.set_index(KEY)["ownership_percentage"].loc[("C1", "A1", 2030)] == 50.00
    assert indirect.set_index(KEY)["ownership_percentage"].loc[("C1", "A1", 2030)] == 0.45


def test_a_companies_input_with_no_tier_column_keeps_every_row():
    """Older inputs carry neither column; the run warns rather than dropping
    every stake, and consolidation then sums what it is given."""
    frame = _multi_stake_frame().drop(columns="ownership_type")

    out = filter_companies(frame, [])

    assert out.set_index(KEY)["ownership_percentage"].loc[("C1", "A1", 2030)] == 50.45


# ── ownership_aggregation ────────────────────────────────────────────────────
# The owner ruling of 2026-09-01 made the tier-first ordering above a MODE
# rather than the only behaviour: `tier_filter` (default, the validated
# baseline) versus `sum` (total direct + equity per company-asset-year, the
# TRISK-comparable reading). The tests above pin `tier_filter`; these pin the
# alternative and the boundary between them.


def _with_an_equity_only_holder() -> pd.DataFrame:
    """The multi-stake frame plus a company whose ONLY stake is an equity one.

    It is the case that separates the modes at the company level, not just the
    percentage level: `tier_filter` on "direct" drops such a holder entirely,
    `sum` keeps it.
    """
    equity_only = pd.DataFrame(
        [("A3", "plant-3", "C3", "Gamma", 2030, "equity", 10.00)],
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
    return pd.concat([_multi_stake_frame(), equity_only], ignore_index=True)


def test_sum_mode_totals_the_direct_and_equity_stakes_into_one_row():
    """Sum semantics (TRISK-style): every holding enters, so Acme's 50.00 direct and
    0.45 equity stakes in plant-1 become a single 50.45 row."""
    out = filter_companies(_multi_stake_frame(), [], ownership_aggregation="sum")

    assert not out.duplicated(KEY).any(), "duplicate (company, asset, year) keys"
    assert out.set_index(KEY)["ownership_percentage"].loc[("C1", "A1", 2030)] == 50.45


def test_tier_filter_is_the_default_and_keeps_only_the_selected_rung():
    """The default is the validated baseline: the equity rung is not added in."""
    out = filter_companies(_multi_stake_frame(), [])

    assert out.set_index(KEY)["ownership_percentage"].loc[("C1", "A1", 2030)] == 50.00


def test_an_equity_only_holder_is_dropped_by_tier_filter_and_kept_by_sum():
    frame = _with_an_equity_only_holder()

    tiered = filter_companies(frame, [], ownership_aggregation="tier_filter")
    summed = filter_companies(frame, [], ownership_aggregation="sum")

    assert "C3" not in set(tiered.company_id)
    assert summed.set_index(KEY)["ownership_percentage"].loc[("C3", "A3", 2030)] == 10.00


def test_an_unknown_ownership_aggregation_names_both_options():
    with pytest.raises(ValueError, match="tier_filter"):
        filter_companies(_multi_stake_frame(), [], ownership_aggregation="average")
    with pytest.raises(ValueError, match="sum"):
        filter_companies(_multi_stake_frame(), [], ownership_aggregation="average")
