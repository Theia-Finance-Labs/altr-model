"""Retirement and build-out capacity-flow masks (Q1, minus replacement).

Ported from the handover branch under the 2026-09-01 owner ruling, then cut
down under the 2026-09-04 ruling that removed replacement CapEx altogether:
IAM O&M already bundles annualised capital costs (the same reasoning that keeps
growth CapEx off), so a 2%/yr roll-over charge on standing capacity was
double-counting. Two behaviours remain:

* **synthetic assets never retire.** A synthetic asset is an accounting
  construct carrying the shock's incremental growth; its capacity falling is
  not a physical decommissioning event, so it must not be charged decom costs.
* **a real asset's decline is a retirement, and nothing else is charged.**
  Standing capacity carries no annual capital charge of any kind; the only
  CapEx events are new build-out (synthetic growth) and retirement.
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


def test_declining_real_asset_retires_on_the_capacity_it_loses():
    panel = _panel(_series("real", "CoalCap", [100.0, 80.0, 60.0], synthetic=False))

    by_year = compute_capacity_flows(panel).set_index("year")

    assert by_year.loc[2026, "capex_indicator"] == "retired_max_cap"
    assert by_year.loc[2026, "capex_capacity"] == 20.0
    assert by_year.loc[2027, "capex_indicator"] == "retired_max_cap"
    assert by_year.loc[2027, "capex_capacity"] == 20.0


def test_declining_synthetic_asset_never_retires():
    panel = _panel(
        _series("synthetic", "WindCap - Onshore", [100.0, 80.0, 60.0], synthetic=True)
    )

    flows = compute_capacity_flows(panel)

    assert "retired_max_cap" not in set(flows["capex_indicator"])
    assert set(flows["capex_indicator"]) == {"none"}


def test_flat_real_asset_carries_no_capital_charge():
    """The replacement ruling: standing capacity is not a CapEx event."""
    panel = _panel(_series("real", "CoalCap", [100.0, 100.0, 100.0], synthetic=False))

    flows = compute_capacity_flows(panel)

    assert set(flows["capex_indicator"]) == {"none"}
    assert list(flows["capex_capacity"]) == [0.0, 0.0, 0.0]


def test_the_only_flow_kinds_are_buildout_retirement_and_none():
    panel = _panel(
        _series("real", "CoalCap", [100.0, 80.0, 80.0], synthetic=False)
        + _series("synthetic", "SolarCap - PV", [0.0, 40.0, 40.0], synthetic=True)
    )

    flows = compute_capacity_flows(panel)

    assert set(flows["capex_indicator"]) <= {
        "new_buildout_cap",
        "retired_max_cap",
        "none",
    }


def test_growing_synthetic_asset_still_books_new_buildout():
    panel = _panel(
        _series("synthetic", "SolarCap - PV", [0.0, 40.0, 90.0], synthetic=True)
    )

    by_year = compute_capacity_flows(panel).set_index("year")

    assert by_year.loc[2026, "capex_indicator"] == "new_buildout_cap"
    assert by_year.loc[2026, "capex_capacity"] == 40.0
    assert by_year.loc[2027, "capex_capacity"] == 50.0


def test_every_asset_year_produces_exactly_one_flow_row():
    panel = _panel(
        _series("real", "CoalCap", [100.0, 80.0, 80.0], synthetic=False)
        + _series("synthetic", "SolarCap - PV", [0.0, 40.0, 40.0], synthetic=True)
    )

    flows = compute_capacity_flows(panel)

    assert len(flows) == len(panel)
    assert not flows.duplicated(["asset_id", "company_id", "year"]).any()
