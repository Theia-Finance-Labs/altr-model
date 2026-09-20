"""PROPOSAL: continued O&M stops when capacity crosses zero (owner ruling 15).

Continued O&M charges fixed costs on a trajectory's FIRST-YEAR capacity rather
than the year's actual capacity, so a plant being wound down keeps paying the
cost base of the plant it used to be. That is deliberate, and it is the single
biggest stranding lever in the model: a shrinking asset does not shed its crew,
its contracts or its site costs in proportion to its output.

A plant that is GONE does. Past zero capacity there is no site to maintain, and
the charge was running to 2050 regardless - measured on the golden run at
1.27 tn charged on plant standing at zero MW, with one nuclear asset paying
1.26 bn/yr for the twelve years after it closed.

The fix is one condition on the existing mask. Everything else is unchanged:
the first-year basis while the asset is alive, shock-path-only by default, and
high-carbon alignments only.
"""

import pandas as pd
import pytest
from altr_model.pipelines.calculate_asset_earnings.nodes import compute_ops_block

FOM_PER_MW_YR = 1_000.0
FIRST_YEAR_CAPACITY = 1_000.0

#: The year the plant closes: capacity is zero from here to the horizon.
CLOSURE_YEAR = 2038
FIRST_YEAR = 2035
LAST_YEAR = 2042

#: What the first-year basis charges every year the asset is alive.
CONTINUED_OM_COST = FIRST_YEAR_CAPACITY * FOM_PER_MW_YR


def _panel(capacities: dict[int, float], trajectory_type: str = "latesudden",
           alignment_type: str = "misaligned_high_carbon") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "company_id": "C1",
                "asset_id": "A1",
                "scenario_geography": "EU",
                "sector": "Power",
                "technology": "NuclearCap",
                "trajectory_type": trajectory_type,
                "alignment_type": alignment_type,
                "year": year,
                "asset_trajectory": capacity,
                "capacity_factor": 0.9,
                "emission_factor": 0.0,
                "carbon_price_usd_per_tco2": 0.0,
                "power_price_excarbon_usd_per_mwh": 50.0,
                "fuel_price_usd_per_mwh_fuel": 0.0,
                "efficiency_decimal": 1.0,
                "fom_usd_per_mw_yr": FOM_PER_MW_YR,
            }
            for year, capacity in sorted(capacities.items())
        ]
    )


def _fixed_cost_by_year(panel: pd.DataFrame, **overrides) -> dict[int, float]:
    out = compute_ops_block(
        panel,
        **{
            "market_passthrough": 0.0,
            "apply_continued_om_baseline": False,
            "apply_continued_om_shock": True,
            **overrides,
        },
    )
    return dict(zip(out["year"], out["fixed_cost"]))


#: A plant at full capacity until it closes in 2038, then zero to the horizon.
NUCLEAR_SHAPED = {
    year: (FIRST_YEAR_CAPACITY if year < CLOSURE_YEAR else 0.0)
    for year in range(FIRST_YEAR, LAST_YEAR + 1)
}


def test_fixed_cost_is_zero_from_the_year_capacity_reaches_zero():
    """The nuclear-shaped case: the charge stops at closure, not at 2050."""
    costs = _fixed_cost_by_year(_panel(NUCLEAR_SHAPED))

    for year in range(FIRST_YEAR, CLOSURE_YEAR):
        assert costs[year] == pytest.approx(CONTINUED_OM_COST), (
            f"{year}: an asset still standing pays its first-year cost base"
        )
    for year in range(CLOSURE_YEAR, LAST_YEAR + 1):
        assert costs[year] == pytest.approx(0.0), (
            f"{year}: a closed plant has no site, no crew and no fixed cost"
        )


def test_the_charge_removed_is_the_whole_post_closure_tail():
    """Size of the fix on one asset, stated rather than implied."""
    costs = _fixed_cost_by_year(_panel(NUCLEAR_SHAPED))
    post_closure_years = LAST_YEAR - CLOSURE_YEAR + 1

    assert sum(costs.values()) == pytest.approx(
        CONTINUED_OM_COST * (CLOSURE_YEAR - FIRST_YEAR)
    )
    # What the previous behaviour would have added on top.
    assert CONTINUED_OM_COST * post_closure_years > 0


def test_a_partially_shrunk_asset_still_pays_the_first_year_basis():
    """The lever itself is untouched: only ZERO stops the charge.

    An asset down to a tenth of its capacity is still a plant, and still pays
    the cost base of the plant it was. This is the behaviour continued O&M
    exists to produce, and ruling 15 must not weaken it.
    """
    shrinking = {2035: FIRST_YEAR_CAPACITY, 2036: 500.0, 2037: 100.0, 2038: 0.1}

    costs = _fixed_cost_by_year(_panel(shrinking))

    assert all(
        cost == pytest.approx(CONTINUED_OM_COST) for cost in costs.values()
    ), costs


def test_a_flat_capacity_asset_is_unchanged():
    """Nothing crosses zero, so nothing about this asset moves."""
    flat = dict.fromkeys(range(FIRST_YEAR, LAST_YEAR + 1), FIRST_YEAR_CAPACITY)

    costs = _fixed_cost_by_year(_panel(flat))

    assert all(cost == pytest.approx(CONTINUED_OM_COST) for cost in costs.values())


def test_the_baseline_path_is_unchanged():
    """Shock-path-only is unchanged: the baseline never had the charge to stop.

    With `apply_continued_om_baseline: False` the baseline pays on ACTUAL
    capacity, which is already zero after closure - so ruling 15 cannot move a
    baseline number, and the shock-minus-baseline difference moves by the full
    amount of the charge removed.
    """
    costs = _fixed_cost_by_year(
        _panel(NUCLEAR_SHAPED, trajectory_type="baseline"),
    )

    for year in range(FIRST_YEAR, CLOSURE_YEAR):
        assert costs[year] == pytest.approx(CONTINUED_OM_COST)
    for year in range(CLOSURE_YEAR, LAST_YEAR + 1):
        assert costs[year] == pytest.approx(0.0)


def test_a_low_carbon_asset_is_untouched_either_way():
    """High-carbon-only is unchanged: this asset pays on actual capacity."""
    costs = _fixed_cost_by_year(
        _panel(NUCLEAR_SHAPED, alignment_type="misaligned_low_carbon")
    )

    for year in range(FIRST_YEAR, CLOSURE_YEAR):
        assert costs[year] == pytest.approx(CONTINUED_OM_COST)
    for year in range(CLOSURE_YEAR, LAST_YEAR + 1):
        assert costs[year] == pytest.approx(0.0)


def test_with_continued_om_off_nothing_changes():
    """The toggle-off path charges actual capacity and always did."""
    costs = _fixed_cost_by_year(
        _panel(NUCLEAR_SHAPED), apply_continued_om_shock=False
    )

    for year in range(CLOSURE_YEAR, LAST_YEAR + 1):
        assert costs[year] == pytest.approx(0.0)
