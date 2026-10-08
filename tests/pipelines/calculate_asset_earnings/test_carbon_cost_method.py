"""`carbon_cost_method`, exercised against a non-zero marginal emission factor.

The switch chooses what an asset pays carbon on:

    "full_ef"         cost = Q x cp x EF                     (every tonne)
    "differential_ef" cost = Q x cp x max(EF - marginal_EF, 0)  (the excess only)

`marginal_emission_factor` is produced by the market-clearing-price adjustment,
which this tree does not carry, so on today's inputs the column is absent, the
marginal EF defaults to 0 and the two methods coincide exactly. That is why the
switch had no test: nothing reachable could tell the branches apart.

Owner ruling 14 deleted `dynamic_marginal_ef` - a knob that scaled that same
always-zero value - and kept this one. A kept switch that no test distinguishes
is the next inert-knob defect waiting to happen, so these tests INJECT a
marginal EF column and pin the arithmetic of both arms, including the clip that
stops a cleaner-than-marginal generator from being paid to emit.
"""

import pandas as pd
import pytest
from altr_model.pipelines.calculate_asset_earnings.nodes import (
    HOURS_PER_YEAR,
    compute_ops_block,
)

CAPACITY = 100.0
CAPACITY_FACTOR = 0.5
CARBON_PRICE = 50.0
POWER_PRICE = 60.0

#: A coal-like asset against a gas-like price-setting generator.
ASSET_EF = 0.9
MARGINAL_EF = 0.4

#: Charged in full, not netted down by a passthrough, so the two arms differ by
#: exactly the marginal EF's worth of tonnes.
NO_PASSTHROUGH = 0.0

PRODUCTION = CAPACITY * CAPACITY_FACTOR * HOURS_PER_YEAR


def _panel(marginal_emission_factor: float | None = None) -> pd.DataFrame:
    row = {
        "company_id": "C1",
        "asset_id": "A1",
        "scenario_geography": "EU",
        "sector": "Power",
        "technology": "CoalCap - w/o CCS",
        "trajectory_type": "baseline",
        "alignment_type": "misaligned_high_carbon",
        "year": 2030,
        "asset_trajectory": CAPACITY,
        "capacity_factor": CAPACITY_FACTOR,
        "emission_factor": ASSET_EF,
        "carbon_price_usd_per_tco2": CARBON_PRICE,
        "power_price_excarbon_usd_per_mwh": POWER_PRICE,
        "fuel_price_usd_per_mwh_fuel": 0.0,
        "efficiency_decimal": 1.0,
        "fom_usd_per_mw_yr": 0.0,
    }
    if marginal_emission_factor is not None:
        row["marginal_emission_factor"] = marginal_emission_factor
    return pd.DataFrame([row])


def _carbon_cost(panel: pd.DataFrame, method: str) -> float:
    out = compute_ops_block(
        panel,
        market_passthrough=NO_PASSTHROUGH,
        apply_continued_om_baseline=False,
        apply_continued_om_shock=False,
        carbon_cost_method=method,
    )
    return float(out["carbon_cost_net"].iloc[0])


def test_the_differential_method_charges_less_than_the_full_method():
    """The switch is live once a marginal EF is present, and in which direction.

    This is the assertion the surviving switch did not have: with a non-zero
    marginal EF the differential arm charges strictly LESS, because the asset
    pays only for what it emits ABOVE the generator that sets the price.
    """
    panel = _panel(marginal_emission_factor=MARGINAL_EF)

    full = _carbon_cost(panel, "full_ef")
    differential = _carbon_cost(panel, "differential_ef")

    assert differential < full
    assert full == pytest.approx(PRODUCTION * CARBON_PRICE * ASSET_EF)
    assert differential == pytest.approx(
        PRODUCTION * CARBON_PRICE * (ASSET_EF - MARGINAL_EF)
    )
    # The difference is exactly the marginal generator's tonnes.
    assert full - differential == pytest.approx(
        PRODUCTION * CARBON_PRICE * MARGINAL_EF
    )


def test_a_cleaner_than_marginal_asset_is_not_paid_to_emit():
    """The excess is clipped at zero, so a credit can never become revenue."""
    panel = _panel(marginal_emission_factor=ASSET_EF * 2)

    assert _carbon_cost(panel, "differential_ef") == pytest.approx(0.0)


def test_without_the_column_the_two_methods_coincide():
    """Today's inputs: no marginal EF column, so the switch cannot bite.

    This is the state the codebase actually runs in, and the reason the switch
    is inert rather than wrong.
    """
    panel = _panel()

    assert _carbon_cost(panel, "differential_ef") == pytest.approx(
        _carbon_cost(panel, "full_ef")
    )


def test_the_full_method_ignores_a_marginal_ef_that_is_present():
    """`"full_ef"` means every tonne, even where a marginal EF is available."""
    with_marginal = _panel(marginal_emission_factor=MARGINAL_EF)
    without = _panel()

    assert _carbon_cost(with_marginal, "full_ef") == pytest.approx(
        _carbon_cost(without, "full_ef")
    )
