"""Carbon-price fill from peer scenarios (owner ruling 2026-10-01).

Six AR6 providers publish no regional carbon price, so their scenarios reach
the model at 0 USD/tCO2 and fossil plants pay nothing for carbon. ENGAGE-style
scenarios share one protocol across models, so the same scenario name in
another model is the closest available price. A scenario whose carbon price is
0 everywhere takes, per year, the median over peer providers of each peer's
median-across-geographies price. Scenarios with no priced peer stay at 0.
"""

import numpy as np
import pandas as pd
import pytest
from altr_model.pipelines.prepare_scenario_asset_and_company_inputs._carbon_price_fill import (
    fill_missing_carbon_prices,
)

PEER_FILL = "peer_scenario_median"


def _rows(provider, protocol, prices_by_geo, years=(2030, 2040)):
    """One row per geography x year x technology; price constant over techs."""
    return [
        {
            "scenario_provider": provider,
            "scenario": f"AR6_{provider}_{protocol}",
            "scenario_geography": geo,
            "technology": tech,
            "year": year,
            "carbon_price_usd_per_tco2": price * (1 + (year - 2030) / 10),
        }
        for geo, price in prices_by_geo.items()
        for year in years
        for tech in ("CoalCap", "GasCap")
    ]


def _frame():
    return pd.DataFrame(
        _rows("AIM", "EN_NPi2020_900f", {"R1": 0.0, "R2": 0.0})
        + _rows("POLES", "EN_NPi2020_900", {"EU": 100.0, "US": 120.0})  # median 110
        + _rows("WITCH", "EN_NPi2020_900", {"EU": 80.0})  # median 80
        + _rows("REMIND", "EN_NPi2020_900", {"EU": 0.0})  # unpriced: not a peer price
        + _rows("GCAM", "NGFS_Net-Zero", {"R1": 0.0})  # no peer at all
        + _rows("WITCH", "EN_NoPolicy", {"EU": 0.0, "US": 5.0})  # partly priced: kept
    )


def _price(out, scenario, year):
    rows = out[(out["scenario"] == scenario) & (out["year"] == year)]
    return rows["carbon_price_usd_per_tco2"].unique()


def test_none_returns_input_untouched():
    frame = _frame()
    pd.testing.assert_frame_equal(fill_missing_carbon_prices(frame, "none"), frame)


def test_zero_scenario_takes_median_of_peer_medians_per_year():
    out = fill_missing_carbon_prices(_frame(), PEER_FILL)
    # peers 110 and 80 -> 95 in 2030; prices scale x2 in 2040 -> 190
    assert _price(out, "AR6_AIM_EN_NPi2020_900f", 2030) == pytest.approx([95.0])
    assert _price(out, "AR6_AIM_EN_NPi2020_900f", 2040) == pytest.approx([190.0])


def test_filled_rows_are_flagged_and_nothing_else_is():
    out = fill_missing_carbon_prices(_frame(), PEER_FILL)
    filled = out[out["carbon_price_filled"]]
    # REMIND's 900 is all-zero too, so it is filled from the priced peers.
    assert set(filled["scenario"]) == {"AR6_AIM_EN_NPi2020_900f", "AR6_REMIND_EN_NPi2020_900"}


def test_scenario_without_priced_peer_stays_at_zero():
    out = fill_missing_carbon_prices(_frame(), PEER_FILL)
    assert _price(out, "AR6_GCAM_NGFS_Net-Zero", 2030) == [0.0]


def test_partly_priced_scenario_is_not_touched():
    frame = _frame()
    out = fill_missing_carbon_prices(frame, PEER_FILL)
    nopol = out["scenario"] == "AR6_WITCH_EN_NoPolicy"
    np.testing.assert_array_equal(
        out.loc[nopol, "carbon_price_usd_per_tco2"].to_numpy(),
        frame.loc[nopol, "carbon_price_usd_per_tco2"].to_numpy(),
    )


def test_input_frame_is_not_mutated():
    frame = _frame()
    before = frame.copy()
    fill_missing_carbon_prices(frame, PEER_FILL)
    pd.testing.assert_frame_equal(frame, before)


def test_unknown_method_is_rejected():
    with pytest.raises(ValueError, match="carbon_price_fill"):
        fill_missing_carbon_prices(_frame(), "global_median")
