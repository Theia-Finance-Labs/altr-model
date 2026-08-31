"""Characterization tests for the DCF core (valuation_model + FCFF).

Pinned behaviors — current behavior, computed by hand in each test body:

* `compute_fcff`: FCFF = EBITDA - capex_total (tax-neutral, no working-capital
  term), input frame left unmutated.
* `compute_yearly_npv_trajectories`:
  - discount rate is `discount_rate_baseline` for `scenario_type == "baseline"`
    rows and `discount_rate_shock` otherwise;
  - base year = the group's earliest year; discount factor = (1+r)^-(year-base);
    `pv_fcff` = FCFF * discount factor and `yearly_npv` = `pv_fcff` on real rows;
  - CapEx flow-split rows are collapsed (financial columns summed) to one row
    per asset-year before any terminal-value logic runs;
  - `terminal_method != "perpetuity"` adds no terminal row;
  - Gordon-Growth terminal row is appended at final_year + 1 with `pv_fcff` 0,
    `yearly_npv` = terminal value and financial columns zeroed;
  - no terminal row when r <= g;
  - `stranding_aware_tv` zeroes the terminal value of a group whose last N rows
    are all loss-making (Gourdel 2024), which otherwise carries a negative
    perpetuity;
  - rows with a missing `scenario_type` are dropped (loudly);
  - a NaN year raises `ValueError`.
"""

import numpy as np
import pandas as pd
import pytest

from crispy_kedro.pipelines.earnings_model.nodes import compute_fcff
from crispy_kedro.pipelines.valuation_model.nodes import (
    compute_yearly_npv_trajectories,
)

META = dict(
    asset_name="a1",
    asset_id="A1",
    company_id="C1",
    company_name="c",
    scenario_geography="EU",
    sector="Power",
    technology="GasCap",
    is_synthetic=False,
    alignment_type="aligned_low_carbon",
    trajectory_type="baseline",
    scenario_type="baseline",
)


def _earnings(rows, **overrides):
    """rows: list of (year, FCFF)."""
    meta = {**META, **overrides}
    return pd.DataFrame([{**meta, "year": year, "FCFF": fcff} for year, fcff in rows])


def test_fcff_is_ebitda_minus_capex():
    ops = pd.DataFrame(
        {
            "asset_id": ["A1", "A2"],
            "year": [2025, 2025],
            "EBITDA": [100.0, -20.0],
            "capex_total": [30.0, 5.0],
        }
    )

    out = compute_fcff(ops)

    assert list(out["FCFF"]) == [70.0, -25.0]
    # Source frame untouched, other columns carried through.
    assert "FCFF" not in ops.columns
    assert list(out["EBITDA"]) == [100.0, -20.0]


def test_discount_factors_and_pv_use_group_base_year():
    # r = 0.10, base year 2025: df = 1.0 and 1/1.1; pv = 100 and 110/1.1 = 100.
    out = compute_yearly_npv_trajectories(
        _earnings([(2025, 100.0), (2026, 110.0)]),
        discount_rate_baseline=0.10,
        terminal_method="none",
    )

    assert len(out) == 2
    assert list(out["base_year"]) == [2025, 2025]
    assert list(out["years_from_base"]) == [0, 1]
    assert out["discount_rate"].tolist() == [0.10, 0.10]
    assert out["discount_factor"].round(9).tolist() == [1.0, round(1 / 1.1, 9)]
    assert out["pv_fcff"].round(6).tolist() == [100.0, 100.0]
    assert out["yearly_npv"].round(6).tolist() == [100.0, 100.0]
    assert (out["terminal_value"] == 0.0).all()


def test_shock_rows_use_the_shock_discount_rate():
    baseline = _earnings([(2025, 100.0)])
    shock = _earnings(
        [(2025, 100.0)], scenario_type="target", trajectory_type="latesudden"
    )

    out = compute_yearly_npv_trajectories(
        pd.concat([baseline, shock], ignore_index=True),
        discount_rate_baseline=0.07,
        discount_rate_shock=0.09,
        terminal_method="none",
    )

    assert dict(zip(out["trajectory_type"], out["discount_rate"].round(6))) == {
        "baseline": 0.07,
        "latesudden": 0.09,
    }


def test_flow_split_rows_are_collapsed_to_one_row_per_year():
    # Two CapEx component rows for 2026 (+100 operating, -30 decom) become one
    # row of 70 before any terminal-value logic sees them.
    out = compute_yearly_npv_trajectories(
        _earnings([(2025, 50.0), (2026, 100.0), (2026, -30.0)]),
        discount_rate_baseline=0.10,
        terminal_method="none",
    )

    assert len(out) == 2
    assert out["FCFF"].round(6).tolist() == [50.0, 70.0]
    assert out["pv_fcff"].round(6).tolist() == [50.0, round(70.0 / 1.1, 6)]


def test_perpetuity_appends_terminal_row_after_the_final_year():
    out = compute_yearly_npv_trajectories(
        _earnings([(2025, 100.0), (2026, 110.0)]),
        discount_rate_baseline=0.10,
        terminal_growth_rate=0.02,
    )

    # TV = FCFF_final * (1 + g) / (r - g), discounted from final_year + 1:
    #   110 * 1.02 / (0.10 - 0.02) / 1.1**2 = 1159.090909...
    expected_tv = 110.0 * 1.02 / (0.10 - 0.02) / 1.1**2
    assert len(out) == 3
    terminal = out[out["year"] == 2027].squeeze()
    assert terminal["terminal_value"] == pytest.approx(expected_tv)
    assert terminal["yearly_npv"] == pytest.approx(expected_tv)
    assert terminal["pv_fcff"] == 0.0
    assert terminal["FCFF"] == 0.0
    assert terminal["years_from_base"] == 2
    assert terminal["discount_factor"] == pytest.approx(1 / 1.1**2)
    # Real rows keep their own present values.
    assert out[out["year"] < 2027]["terminal_value"].tolist() == [0.0, 0.0]


def test_no_terminal_row_when_growth_exceeds_discount_rate():
    out = compute_yearly_npv_trajectories(
        _earnings([(2025, 100.0), (2026, 110.0)]),
        discount_rate_baseline=0.10,
        terminal_growth_rate=0.15,
    )

    assert len(out) == 2
    assert (out["terminal_value"] == 0.0).all()


def test_stranding_aware_tv_zeroes_a_persistently_loss_making_group():
    losses = _earnings(
        [(2025, -5.0), (2026, -10.0)], alignment_type="misaligned_high_carbon"
    )

    stranded = compute_yearly_npv_trajectories(
        losses,
        discount_rate_baseline=0.10,
        terminal_growth_rate=0.02,
        stranding_aware_tv=True,
        stranding_consecutive_years=2,
    )
    assert len(stranded) == 2
    assert (stranded["terminal_value"] == 0.0).all()

    # Without the stranding rule the same group carries a negative perpetuity:
    #   -10 * 1.02 / (0.10 - 0.02) / 1.1**2 = -105.3719...
    unguarded = compute_yearly_npv_trajectories(
        losses, discount_rate_baseline=0.10, terminal_growth_rate=0.02
    )
    assert len(unguarded) == 3
    assert unguarded["terminal_value"].sum() == pytest.approx(
        -10.0 * 1.02 / (0.10 - 0.02) / 1.1**2
    )


def test_rows_without_scenario_type_are_dropped():
    frame = _earnings([(2025, 100.0), (2026, 110.0)])
    frame.loc[1, "scenario_type"] = None

    out = compute_yearly_npv_trajectories(
        frame, discount_rate_baseline=0.10, terminal_method="none"
    )

    assert out["year"].tolist() == [2025]


def test_nan_year_raises():
    frame = _earnings([(2025, 100.0), (2026, 110.0)])
    frame.loc[1, "year"] = np.nan

    with pytest.raises(ValueError, match="NaN year"):
        compute_yearly_npv_trajectories(frame, terminal_method="none")
