"""compute_capacity_flows must not shift capacity across a scenario_geography seam.

An asset that appears in two geographies used to be grouped only by
(trajectory_type, company_id, asset_id, technology), so shift(1) carried the last
row of one geography into the first row of the next -- inventing a capacity change
(and a phantom retirement) at each geography's first year. The canonical
ASSET_SERIES_KEYS grain includes scenario_geography; these tests pin that.
"""

import pandas as pd
import pytest
from altr_model.pipelines.calculate_asset_earnings.nodes import compute_capacity_flows

EU_CAPACITY_2030 = 100.0
US_CAPACITY_2030 = 500.0
EU_DELTA = -10.0
US_DELTA = -20.0


def test_missing_scenario_geography_fails_loudly():
    panel = pd.DataFrame(
        {
            "trajectory_type": ["baseline"],
            "company_id": ["C1"],
            "asset_id": ["A"],
            "sector": ["Power"],
            "technology": ["GasCap"],
            "year": [2030],
            "asset_trajectory": [100.0],
        }
    )
    with pytest.raises(KeyError, match="scenario_geography"):
        compute_capacity_flows(panel)


def _panel() -> pd.DataFrame:
    """One asset, two geographies, interleaved so a geography-blind shift leaks."""
    rows = [
        ("EU", 2030, EU_CAPACITY_2030),
        ("US", 2030, US_CAPACITY_2030),
        ("EU", 2031, EU_CAPACITY_2030 + EU_DELTA),
        ("US", 2031, US_CAPACITY_2030 + US_DELTA),
    ]
    return pd.DataFrame(
        {
            "trajectory_type": ["target"] * 4,
            "company_id": ["C1"] * 4,
            "asset_id": ["A1"] * 4,
            "sector": ["Power"] * 4,
            "technology": ["GasCap - w/o CCS"] * 4,
            "scenario_geography": [r[0] for r in rows],
            "year": [r[1] for r in rows],
            "asset_trajectory": [r[2] for r in rows],
        }
    )


def _change(result: pd.DataFrame, geography: str, year: int) -> float:
    row = result[
        (result["scenario_geography"] == geography) & (result["year"] == year)
    ]
    assert len(row) == 1, f"expected exactly one flow row for {geography}/{year}"
    return float(row["capacity_change"].iloc[0])


def test_first_year_per_geography_has_no_capacity_change():
    result = compute_capacity_flows(_panel())

    assert _change(result, "EU", 2030) == 0.0
    assert _change(result, "US", 2030) == 0.0


def test_subsequent_years_use_same_geography_predecessor():
    result = compute_capacity_flows(_panel())

    assert _change(result, "EU", 2031) == EU_DELTA
    assert _change(result, "US", 2031) == US_DELTA


def test_no_phantom_retirement_at_geography_seam():
    result = compute_capacity_flows(_panel())

    retirements = result[result["capex_indicator"] == "retired_max_cap"]
    assert set(zip(retirements["scenario_geography"], retirements["year"])) == {
        ("EU", 2031),
        ("US", 2031),
    }
