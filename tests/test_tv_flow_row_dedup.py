"""Regression: flow-split duplicate (asset, year) rows must not corrupt the
terminal-value anchor.

compute_capacity_flows emits separate component rows per asset-year (operating,
decom, rollover). Their FCFFs sum correctly for PV, but the TV anchor,
normalization window and stranding check index by ROW. The valuation node must
therefore collapse to one row per asset-year first: a frame with flow-split
rows and its pre-aggregated equivalent must produce identical NPVs and
terminal values.
"""
import pandas as pd

from crispy_kedro.pipelines.valuation_model.nodes import (
    compute_yearly_npv_trajectories,
)

META = dict(
    asset_name="a1", asset_id="A1", company_id="C1", company_name="c",
    scenario_geography="EU", sector="Power", technology="GasCap - w/o CCS",
    is_synthetic=False, alignment_type="misaligned_high_carbon",
    trajectory_type="baseline", scenario_type="baseline",
)


def _frame(rows):
    return pd.DataFrame([{**META, "year": y, "FCFF": f} for y, f in rows])


def _totals(df):
    out = compute_yearly_npv_trajectories(df)
    return round(out.yearly_npv.sum(), 6), round(out.terminal_value.sum(), 6)


def test_flow_split_rows_match_aggregated_rows():
    # Final year 2050 split into an operating row (+100) and a decom row (-30):
    # economically identical to a single 70 row. Under row-indexed anchoring the
    # split frame used to anchor the perpetuity on the -30 component row.
    dup = _frame([(2046, 50.0), (2047, 60.0), (2048, 65.0), (2049, 68.0),
                  (2050, 100.0), (2050, -30.0)])
    agg = _frame([(2046, 50.0), (2047, 60.0), (2048, 65.0), (2049, 68.0),
                  (2050, 70.0)])
    assert _totals(dup) == _totals(agg)
