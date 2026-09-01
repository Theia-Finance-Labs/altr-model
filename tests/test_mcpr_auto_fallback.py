"""OP9 regression guard: mcpr_mode='auto' must never resolve to merit_order_decline.

The 2026 single-vintage rebuild (30/30 runs) showed merit_order_decline reverses
the stress-test direction (carbon expected-negative 43.9% vs 72.6% for
carbon_explicit). Merit stays available only as an explicit, paper-track setting;
auto must fall back to carbon_explicit even when carbon-price coverage is low.
"""
import logging

import pandas as pd

from crispy_kedro.pipelines.earnings_model.nodes import apply_mcpr_adjustment


def _surfaces(cp_value: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "scenario_type": ["target", "target", "baseline", "baseline"],
            "technology": ["GasCap - w/o CCS", "SolarCap - PV"] * 2,
            "scenario_geography": ["EU"] * 4,
            "year": [2030] * 4,
            "power_price_usd_per_mwh": [80.0, 60.0, 70.0, 55.0],
            "carbon_price_usd_per_tco2": [cp_value] * 4,
        }
    )


def test_auto_low_coverage_falls_back_to_carbon_explicit(caplog):
    """Zero carbon-price coverage used to route auto into merit_order_decline."""
    with caplog.at_level(logging.INFO):
        apply_mcpr_adjustment(_surfaces(cp_value=0.0), mcpr_mode="auto")
    # "mode=<resolved>" appears in the definitive "Applying MCPR adjustment"
    # log line; the warning text may *mention* merit without selecting it.
    assert "mode=merit_order_decline" not in caplog.text
    assert "mode=carbon_explicit" in caplog.text


def test_explicit_merit_still_selectable(caplog):
    """Paper-track use stays possible: explicit merit_order_decline is honored."""
    with caplog.at_level(logging.INFO):
        apply_mcpr_adjustment(_surfaces(cp_value=0.0), mcpr_mode="merit_order_decline")
    assert "mode=merit_order_decline" in caplog.text
