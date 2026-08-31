"""Regression: reporting views must key on the owner composite key, not asset_id.

Hundreds of production assets are owned by two companies (same asset_id, different
company_id). asset_npv is keyed by [asset_id, company_id, scenario_geography,
sector, technology], so an asset_id-only merge fans out k**2 rows and the
per-asset cumulative/aggregate loops mix the owners' cash flows together.
"""

import pandas as pd
import pytest
from altr_model.pipelines.plot_transition_risk_results.nodes import (
    build_reporting_views,
)


def _approx(value):
    return pytest.approx(value, rel=1e-9)


KEY = ["asset_id", "company_id", "scenario_geography", "sector", "technology"]

# Asset A1 is co-owned by C1 and C2; A2 has a single owner.
OWNERS = [
    ("A1", "C1", 100.0),
    ("A1", "C2", 10.0),
    ("A2", "C3", 7.0),
]
YEARS = [2025, 2026, 2027]


def _earnings() -> pd.DataFrame:
    rows = []
    for asset_id, company_id, scale in OWNERS:
        for i, year in enumerate(YEARS):
            rows.append(
                {
                    "asset_id": asset_id,
                    "company_id": company_id,
                    "scenario_geography": "EU",
                    "sector": "Power",
                    "technology": "GasCap",
                    "year": year,
                    "trajectory_type": "latesudden",
                    "revenue": scale * (i + 1),
                    "var_cost": scale * 0.1,
                    "fixed_cost": scale * 0.2,
                    "carbon_cost_net": scale * 0.05,
                    "EBITDA": scale * (i + 2),
                    "capex_total": scale * 0.3,
                    "FCFF": scale * (i + 1.5),
                }
            )
    # Baseline rows must be filtered out by the node.
    baseline = [{**r, "trajectory_type": "baseline", "FCFF": -1.0} for r in rows]
    return pd.DataFrame(rows + baseline)


def _asset_npv() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "asset_id": asset_id,
                "company_id": company_id,
                "scenario_geography": "EU",
                "sector": "Power",
                "technology": "GasCap",
                "latesudden_discount_rate": 0.0,  # discount factor == 1
                "latesudden_npv": scale,
                "baseline_npv": scale * 2,
            }
            for asset_id, company_id, scale in OWNERS
        ]
    )


def _views():
    return build_reporting_views(
        _earnings(),
        _asset_npv(),
        pd.DataFrame({"company_id": ["C1", "C2", "C3"]}),
        {},
    )


def test_object_dtype_npv_columns_still_aggregate():
    # calculate_npv_per_asset pivots to wide, which hands the reporting node
    # object-dtype numeric columns; groupby.cumsum rejects object dtype.
    npv = _asset_npv()
    npv["latesudden_discount_rate"] = npv["latesudden_discount_rate"].astype(object)
    npv["latesudden_npv"] = npv["latesudden_npv"].astype(object)

    views = build_reporting_views(
        _earnings(), npv, pd.DataFrame({"company_id": ["C1", "C2", "C3"]}), {}
    )
    explain = views["view_asset_explain"]
    assert explain["PV_FCFF"].dtype.kind == "f"
    assert explain["cum_PV_FCFF"].notna().all()


def test_merge_does_not_fan_out_co_owned_assets():
    earnings = _earnings()
    expected = len(earnings.query("trajectory_type == 'latesudden'"))
    explain = _views()["view_asset_explain"]
    assert len(explain) == expected  # asset_id-only fan-out would give 15, not 9


def test_cumulative_pv_is_per_owner_not_mixed():
    explain = _views()["view_asset_explain"]
    final = explain[explain["year"] == YEARS[-1]].set_index(["asset_id", "company_id"])

    for asset_id, company_id, scale in OWNERS:
        own = explain[
            (explain["asset_id"] == asset_id) & (explain["company_id"] == company_id)
        ]
        assert final.loc[(asset_id, company_id), "cum_PV_EBITDA"] == _approx(
            own["PV_EBITDA"].sum()
        )
        assert final.loc[(asset_id, company_id), "cum_PV_FCFF"] == _approx(
            own["PV_FCFF"].sum()
        )

    # C1's cumulative must not absorb C2's flows (mixed sum would be 110*...).
    c1 = final.loc[("A1", "C1"), "cum_PV_EBITDA"]
    c2 = final.loc[("A1", "C2"), "cum_PV_EBITDA"]
    assert c1 != _approx(c1 + c2)
    assert c1 == _approx(100.0 * (2 + 3 + 4))
    assert c2 == _approx(10.0 * (2 + 3 + 4))


def test_npv_decomp_one_row_per_owner_with_own_pv_revenue():
    decomp = _views()["view_asset_npv_decomp"]

    assert len(decomp) == len(OWNERS)
    assert not decomp.duplicated(subset=KEY).any()

    indexed = decomp.set_index(["asset_id", "company_id"])
    for asset_id, company_id, scale in OWNERS:
        # discount factor is 1 (rate 0), revenue = scale * (1, 2, 3)
        assert indexed.loc[(asset_id, company_id), "PV_Revenue"] == _approx(scale * 6)
        assert indexed.loc[(asset_id, company_id), "PV_VarCost"] == _approx(scale * 0.3)
        assert indexed.loc[(asset_id, company_id), "PV_FixedCost"] == _approx(
            scale * 0.6
        )
        assert indexed.loc[(asset_id, company_id), "NPV"] == _approx(scale)
