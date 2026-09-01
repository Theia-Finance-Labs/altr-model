"""Retirement and replacement capacity-flow masks (Q1).

Ported from the handover branch under the 2026-09-01 owner ruling. Three
behaviours separate the ported semantics from what this tree did before:

* **synthetic assets never retire.** A synthetic asset is an accounting
  construct carrying the shock's incremental growth; its capacity falling is
  not a physical decommissioning event, so it must not be charged decom costs.
* **replacement CapEx is charged on installed capacity, not on growth.**
  Routine capital maintenance is an annual fraction of what is standing
  (``replacement_capex_rate``), which is why a flat asset — the common case —
  still carries it. Charging it on the year-on-year *change* meant an asset
  that never grew paid no maintenance at all.
* **a retiring asset does not also pay replacement CapEx** in the same year;
  it is already charged decommissioning.

The rate is this tree's ``replacement_capex_rate`` parameter, whose default is
set to the handover branch's hardcoded 2% (EPRI / Lazard LCOE benchmark for
annual capital maintenance).
"""

import pandas as pd
from altr_model.pipelines.calculate_asset_earnings.nodes import compute_capacity_flows

YEARS = [2025, 2026, 2027]


def _panel(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["scenario_geography"] = "EU"
    frame["sector"] = "Power"
    frame["trajectory_type"] = "latesudden"
    return frame


def _series(asset_id: str, technology: str, capacities: list[float], synthetic: bool):
    return [
        {
            "asset_id": asset_id,
            "company_id": "C1",
            "technology": technology,
            "year": year,
            "asset_trajectory": capacity,
            "is_synthetic": synthetic,
        }
        for year, capacity in zip(YEARS, capacities)
    ]


def _flows(panel: pd.DataFrame, rate: float = 0.02) -> pd.DataFrame:
    return compute_capacity_flows(panel, replacement_capex_rate=rate)


def test_declining_real_asset_retires_and_is_not_also_charged_replacement():
    panel = _panel(_series("real", "CoalCap", [100.0, 80.0, 60.0], synthetic=False))

    flows = _flows(panel)
    by_year = flows.set_index("year")

    assert by_year.loc[2026, "capex_indicator"] == "retired_max_cap"
    assert by_year.loc[2026, "capex_capacity"] == 20.0
    assert by_year.loc[2027, "capex_indicator"] == "retired_max_cap"
    assert "roll_over_cap" not in set(flows.loc[flows["year"] > 2025, "capex_indicator"])


def test_declining_synthetic_asset_never_retires():
    panel = _panel(
        _series("synthetic", "WindCap - Onshore", [100.0, 80.0, 60.0], synthetic=True)
    )

    flows = _flows(panel)

    assert "retired_max_cap" not in set(flows["capex_indicator"])
    assert set(flows["capex_indicator"]) == {"none"}


def test_flat_real_asset_still_pays_replacement_on_installed_capacity():
    panel = _panel(_series("real", "CoalCap", [100.0, 100.0, 100.0], synthetic=False))

    flows = _flows(panel)

    assert set(flows["capex_indicator"]) == {"roll_over_cap"}
    assert list(flows["capex_capacity"]) == [2.0, 2.0, 2.0]


def test_replacement_capacity_scales_with_the_configured_rate():
    panel = _panel(_series("real", "CoalCap", [100.0, 100.0, 100.0], synthetic=False))

    flows = _flows(panel, rate=0.05)

    assert list(flows["capex_capacity"]) == [5.0, 5.0, 5.0]


def test_growing_synthetic_asset_still_books_new_buildout():
    panel = _panel(
        _series("synthetic", "SolarCap - PV", [0.0, 40.0, 90.0], synthetic=True)
    )

    flows = _flows(panel)
    by_year = flows.set_index("year")

    assert by_year.loc[2026, "capex_indicator"] == "new_buildout_cap"
    assert by_year.loc[2026, "capex_capacity"] == 40.0
    assert by_year.loc[2027, "capex_capacity"] == 50.0


def test_every_asset_year_produces_exactly_one_flow_row():
    panel = _panel(
        _series("real", "CoalCap", [100.0, 80.0, 80.0], synthetic=False)
        + _series("synthetic", "SolarCap - PV", [0.0, 40.0, 40.0], synthetic=True)
    )

    flows = _flows(panel)

    assert len(flows) == len(panel)
    assert not flows.duplicated(["asset_id", "company_id", "year"]).any()
