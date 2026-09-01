"""Equivalence guard for the vectorised rewrite of compute_yearly_npv_trajectories.

`_reference_compute` below is a verbatim transcription of the ORIGINAL per-group
Python loop (nodes.py before the vectorisation), with two deliberate changes:
the main `groupby(group_keys)` carries `dropna=False`, and the flow-split
collapse runs ahead of the loop. Both are separately tested fixes (see
test_npv_dropna_keys.py and test_tv_flow_row_dedup.py); folding them into the
reference isolates this file to the vectorisation change alone.

The reference now carries the terminal-value ladder ported from the handover
branch under the 2026-09-01 owner ruling (Q2): stranding-aware tiers, the
terminal-FCFF normalization window, technology-differentiated growth rates and
discount spreads. It is still an independent per-group transcription, so it
still isolates the vectorisation.

Every branch of that ladder is exercised: stranded, finite annuity, perpetuity,
r <= g, final_fcff == 0, negative final FCFF with stranding off, single-row
groups, normalisation windows 1 and 3, terminal_method != "perpetuity",
flow-split duplicate years, and a NaN group key.
"""

import os
import time

import numpy as np
import pandas as pd
import pytest
from altr_model.pipelines.calculate_asset_and_company_npv.nodes import (
    compute_yearly_npv_trajectories,
)

GROUP_KEYS = [
    "asset_name",
    "asset_id",
    "company_id",
    "company_name",
    "scenario_geography",
    "sector",
    "technology",
    "is_synthetic",
    "alignment_type",
    "trajectory_type",
]

_NUMERIC = {
    "year",
    "discount_rate",
    "base_year",
    "terminal_growth_rate",
    "years_from_base",
    "discount_factor",
    "pv_fcff",
    "terminal_value",
    "yearly_npv",
    "FCFF",
    "EBITDA",
    "revenue",
    "var_cost",
    "fixed_cost",
    "carbon_cost_net",
    "capex_total",
}


# --------------------------------------------------------------------------
# Reference implementation: the original per-group loop, verbatim.
# --------------------------------------------------------------------------
def _reference_compute(
    asset_earnings: pd.DataFrame,
    discount_rate_baseline: float = 0.07,
    discount_rate_shock: float = 0.08,
    terminal_growth_rate: float = 0.02,
    terminal_growth_rate_brown: float = None,
    terminal_growth_rate_green: float = None,
    terminal_method: str = "perpetuity",
    terminal_normalization_window: int = 1,
    brown_discount_spread: float = 0.0,
    green_discount_spread: float = 0.0,
    stranding_aware_tv: bool = False,
    stranding_consecutive_years: int = 3,
    brown_remaining_life_years: int = 10,
) -> pd.DataFrame:
    g_brown = (
        terminal_growth_rate_brown
        if terminal_growth_rate_brown is not None
        else terminal_growth_rate
    )
    g_green = (
        terminal_growth_rate_green
        if terminal_growth_rate_green is not None
        else terminal_growth_rate
    )

    npv_data = asset_earnings.copy()
    if npv_data["scenario_type"].isna().any():
        raise ValueError("asset(s) have no scenario_type resolved")

    carbontech_alignments = {"misaligned_high_carbon", "aligned_high_carbon"}

    def get_discount_rate(row):
        if row.get("scenario_type") == "baseline":
            base = discount_rate_baseline
        else:
            base = discount_rate_shock
        alignment = row.get("alignment_type", "")
        if alignment in carbontech_alignments:
            return base + brown_discount_spread
        elif green_discount_spread > 0:
            return base - green_discount_spread
        return base

    npv_data["discount_rate"] = npv_data.apply(get_discount_rate, axis=1)

    need_cols = ["asset_id", "year", "FCFF", "trajectory_type"]
    missing = [c for c in need_cols if c not in npv_data.columns]
    if missing:
        raise ValueError(f"asset_earnings missing required columns for NPV: {missing}")

    financial_cols = [
        "FCFF",
        "EBITDA",
        "revenue",
        "var_cost",
        "fixed_cost",
        "carbon_cost_net",
        "capex_total",
    ]
    available_financial_cols = [c for c in financial_cols if c in npv_data.columns]

    group_keys = list(GROUP_KEYS)

    agg_map = {col: "sum" for col in available_financial_cols}
    agg_map["discount_rate"] = "first"
    # Mirrors the production collapse: an all-NaN FCFF cell sums to 0.0, so the
    # observation count travels alongside it for the stranding test.
    npv_data = npv_data.assign(_fcff_observed=npv_data["FCFF"].notna())
    agg_map["_fcff_observed"] = "sum"
    npv_data = npv_data.groupby(
        group_keys + ["year"], dropna=False, as_index=False
    ).agg(agg_map)

    yearly_results = []

    for _key, g in npv_data.groupby(group_keys, dropna=False):
        g = g.sort_values("year").copy()
        first_row = g.iloc[0]
        base_year = int(g["year"].min())

        g["years_from_base"] = g["year"] - base_year
        g["discount_factor"] = (1 + g["discount_rate"]) ** (-g["years_from_base"])
        g["pv_fcff"] = g["FCFF"] * g["discount_factor"]

        g["terminal_value"] = 0.0
        g["yearly_npv"] = g["pv_fcff"]

        g_effective = terminal_growth_rate

        if (terminal_method == "perpetuity") and (len(g) > 0):
            n_window = min(terminal_normalization_window, len(g))
            final_fcff = float(g["FCFF"].iloc[-n_window:].mean())
            final_year = int(g["year"].iloc[-1])
            final_discount_rate = g.iloc[-1]["discount_rate"]

            alignment = first_row.get("alignment_type", "")
            is_carbontech = alignment in carbontech_alignments
            if is_carbontech:
                g_effective = g_brown
            else:
                g_effective = g_green

            tv_tier = "perpetuity"
            terminal_value = 0.0

            if stranding_aware_tv and final_fcff != 0:
                # A group with fewer than N OBSERVED years cannot show N
                # consecutive loss years, and a missing year is not a loss —
                # mirrors the production guard. The trailing window must be
                # complete: "loss, gap, loss" is not a run of three.
                tail = g.iloc[-stranding_consecutive_years:]
                is_stranded = bool(
                    g["_fcff_observed"].gt(0).sum() >= stranding_consecutive_years
                    and tail["_fcff_observed"].gt(0).all()
                    and (tail["FCFF"] <= 0).all()
                )

                if is_stranded:
                    tv_tier = "stranded"
                    terminal_value = 0.0
                elif is_carbontech and final_fcff > 0:
                    tv_tier = "finite_annuity"
                    annuity_factor = sum(
                        1 / (1 + final_discount_rate) ** t
                        for t in range(1, brown_remaining_life_years + 1)
                    )
                    terminal_cf = final_fcff * (1 + g_effective)
                    terminal_value_nominal = terminal_cf * annuity_factor
                    years_from_base_to_final = final_year - base_year
                    terminal_discount_factor = (1 + final_discount_rate) ** (
                        -years_from_base_to_final
                    )
                    terminal_value = float(
                        terminal_value_nominal * terminal_discount_factor
                    )
                else:
                    tv_tier = "perpetuity"
            elif not stranding_aware_tv:
                tv_tier = "perpetuity"

            if tv_tier == "perpetuity" and final_fcff != 0:
                if final_discount_rate > g_effective:
                    terminal_cf = final_fcff * (1 + g_effective)
                    terminal_value_nominal = terminal_cf / (
                        final_discount_rate - g_effective
                    )
                    years_to_terminal = (final_year + 1) - base_year
                    terminal_discount_factor = (1 + final_discount_rate) ** (
                        -years_to_terminal
                    )
                    terminal_value = float(
                        terminal_value_nominal * terminal_discount_factor
                    )

            if terminal_value != 0:
                years_to_terminal = (final_year + 1) - base_year
                terminal_discount_factor = (1 + final_discount_rate) ** (
                    -years_to_terminal
                )
                terminal_row = g.iloc[-1].copy()
                terminal_row["year"] = final_year + 1
                terminal_row["years_from_base"] = years_to_terminal
                terminal_row["discount_factor"] = terminal_discount_factor
                terminal_row["pv_fcff"] = 0.0
                terminal_row["terminal_value"] = terminal_value
                terminal_row["yearly_npv"] = terminal_value

                for fin_col in available_financial_cols:
                    if fin_col in terminal_row.index:
                        terminal_row[fin_col] = 0.0

                g = pd.concat([g, terminal_row.to_frame().T], ignore_index=True)

        for col in group_keys:
            if col not in g.columns:
                g[col] = first_row.get(col)

        g["base_year"] = base_year
        g["terminal_method"] = terminal_method
        g["terminal_growth_rate"] = g_effective

        output_cols = (
            group_keys
            + [
                "year",
                "discount_rate",
                "base_year",
                "terminal_method",
                "terminal_growth_rate",
                "years_from_base",
                "discount_factor",
                "pv_fcff",
                "terminal_value",
                "yearly_npv",
            ]
            + available_financial_cols
        )
        output_cols = [col for col in output_cols if col in g.columns]

        yearly_results.append(g[output_cols])

    return pd.concat(yearly_results, ignore_index=True)


# --------------------------------------------------------------------------
# Normalisation: the reference emits object-dtype columns wherever a terminal
# row was concatenated (Series.to_frame().T). Compare observable VALUES.
# --------------------------------------------------------------------------
def _norm(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in df.columns:
        if col in _NUMERIC:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
        else:
            df[col] = df[col].astype(str)
    sort_keys = [c for c in GROUP_KEYS if c in df.columns] + ["year"]
    return df.sort_values(sort_keys, ignore_index=True)


def _assert_equivalent(frame, **kwargs):
    expected = _norm(_reference_compute(frame, **kwargs))
    actual = _norm(compute_yearly_npv_trajectories(frame, **kwargs))
    assert len(actual) == len(
        expected
    ), f"row count {len(actual)} != reference {len(expected)}"
    pd.testing.assert_frame_equal(
        actual, expected, check_like=True, check_dtype=False, rtol=1e-9, atol=1e-9
    )


# --------------------------------------------------------------------------
# Synthetic fixture
# --------------------------------------------------------------------------
def _asset(
    asset_id,
    alignment,
    years_fcff,
    trajectory="baseline",
    scenario_type="baseline",
    company_name=None,
):
    carbon = str(alignment).endswith("high_carbon")
    return [
        {
            "asset_name": f"name_{asset_id}",
            "asset_id": asset_id,
            "company_id": f"CO_{asset_id}",
            "company_name": company_name
            if company_name is not None
            else f"co_{asset_id}",
            "scenario_geography": "EU",
            "sector": "Power",
            "technology": "GasCap - w/o CCS" if carbon else "WindCap - Onshore",
            "is_synthetic": False,
            "alignment_type": alignment,
            "trajectory_type": trajectory,
            "scenario_type": scenario_type,
            "year": int(y),
            "FCFF": float(f),
        }
        for y, f in years_fcff
    ]


def _fixture_frame() -> pd.DataFrame:
    rows = []
    # A1 profitable carbontech, multi-year -> perpetuity terminal value
    rows += _asset(
        "A1",
        "misaligned_high_carbon",
        [
            (2025, 100.0),
            (2026, 110.0),
            (2027, 120.0),
            (2028, 130.0),
            (2029, 140.0),
            (2030, 150.0),
        ],
    )
    # A1 shock trajectory (target scenario_type -> shock discount rate),
    # negative final FCFF -> no terminal value
    rows += _asset(
        "A1",
        "misaligned_high_carbon",
        [
            (2025, 100.0),
            (2026, 90.0),
            (2027, 70.0),
            (2028, 40.0),
            (2029, 10.0),
            (2030, -5.0),
        ],
        trajectory="latesudden",
        scenario_type="target",
    )
    # A2 trailing losses -> negative final FCFF, no terminal value
    rows += _asset(
        "A2",
        "aligned_high_carbon",
        [
            (2025, 80.0),
            (2026, 40.0),
            (2027, 5.0),
            (2028, -10.0),
            (2029, -20.0),
            (2030, -30.0),
        ],
    )
    # A3 greentech, growing -> perpetuity
    rows += _asset(
        "A3",
        "misaligned_low_carbon",
        [
            (2025, 50.0),
            (2026, 60.0),
            (2027, 70.0),
            (2028, 80.0),
            (2029, 90.0),
            (2030, 100.0),
        ],
    )
    # A4 all-negative greentech
    rows += _asset(
        "A4",
        "aligned_low_carbon",
        [
            (2025, -10.0),
            (2026, -20.0),
            (2027, -30.0),
            (2028, -40.0),
            (2029, -50.0),
            (2030, -60.0),
        ],
    )
    # A5 single-row group
    rows += _asset("A5", "misaligned_high_carbon", [(2030, 250.0)])
    # A6 NaN group key (company_name)
    rows += _asset(
        "A6",
        "misaligned_low_carbon",
        [(2025, 30.0), (2026, 35.0), (2027, 40.0)],
        company_name=np.nan,
    )
    # A7 final FCFF exactly zero -> no terminal value
    rows += _asset(
        "A7", "aligned_high_carbon", [(2025, 90.0), (2026, 60.0), (2027, 0.0)]
    )
    # A8 flow-split duplicate years (must collapse before anchoring)
    rows += _asset(
        "A8",
        "misaligned_high_carbon",
        [(2028, 60.0), (2029, 65.0), (2030, 100.0), (2030, -30.0)],
    )
    # A9 two-row group with a mixed-sign run
    rows += _asset("A9", "misaligned_high_carbon", [(2029, -5.0), (2030, 12.0)])
    return pd.DataFrame(rows)


PARAMS = [
    pytest.param({}, id="defaults"),
    pytest.param({"stranding_aware_tv": True}, id="stranding_on"),
    pytest.param({"terminal_normalization_window": 3}, id="window3"),
    pytest.param(
        {"stranding_aware_tv": True, "terminal_normalization_window": 3,
         "terminal_growth_rate_brown": 0.0, "terminal_growth_rate_green": 0.03},
        id="stranding_window3_split_g",
    ),
    pytest.param(
        {"stranding_aware_tv": True, "stranding_consecutive_years": 2,
         "brown_remaining_life_years": 15},
        id="stranding_2yr_life15",
    ),
    pytest.param({"terminal_growth_rate_green": 0.10}, id="r_le_g_green"),
    pytest.param(
        {"terminal_growth_rate_brown": 0.20, "terminal_growth_rate_green": 0.20},
        id="r_le_g_all",
    ),
    pytest.param({"terminal_method": "none"}, id="terminal_method_none"),
    pytest.param(
        {"brown_discount_spread": 0.015, "green_discount_spread": 0.005},
        id="both_spreads",
    ),
    pytest.param({"brown_discount_spread": 0.015}, id="brown_spread_only"),
    pytest.param(
        {"stranding_aware_tv": True, "brown_discount_spread": 0.015,
         "green_discount_spread": 0.005, "terminal_normalization_window": 3,
         "terminal_growth_rate_brown": -0.01, "terminal_growth_rate_green": 0.025},
        id="kitchen_sink",
    ),
]


@pytest.mark.parametrize("kwargs", PARAMS)
def test_vectorized_matches_reference_loop(kwargs):
    _assert_equivalent(_fixture_frame(), **kwargs)


def test_terminal_rows_are_added_for_the_expected_groups():
    """Guard the fixture itself: if no terminal rows exist the equivalence
    parametrisation would be vacuous for the TV branches."""
    out = compute_yearly_npv_trajectories(_fixture_frame())
    tv = out.loc[pd.to_numeric(out["terminal_value"], errors="coerce") != 0]
    assert set(tv["asset_id"]) >= {"A1", "A3", "A5", "A8", "A9"}
    # A4 is loss-making throughout: with stranding off it still takes a
    # perpetuity, now on a NEGATIVE terminal cash flow (the ported rule anchors
    # on final_fcff != 0, not final_fcff > 0).
    assert "A4" in set(tv["asset_id"])
    # A7's final FCFF is exactly zero -> no terminal row, either way.
    assert "A7" not in set(tv["asset_id"])

    stranded = compute_yearly_npv_trajectories(_fixture_frame(), stranding_aware_tv=True)
    stranded_tv = stranded.loc[
        pd.to_numeric(stranded["terminal_value"], errors="coerce") != 0
    ]
    # A4 and A2 close their horizon with three loss-making years -> TV = 0.
    assert "A4" not in set(stranded_tv["asset_id"])
    assert "A2" not in set(stranded_tv["asset_id"])


# --------------------------------------------------------------------------
# Real-data equivalence + timing
# --------------------------------------------------------------------------
_REAL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "data",
    "07_model_output",
    "asset_earnings.csv",
)


@pytest.mark.skipif(not os.path.exists(_REAL), reason="asset_earnings.csv not present")
def test_real_data_sample_equivalence(capsys):
    chunk = pd.read_csv(_REAL, nrows=200_000)
    keys = chunk[GROUP_KEYS].drop_duplicates().head(500)
    sample = chunk.merge(keys, on=GROUP_KEYS, how="inner")

    t0 = time.perf_counter()
    ref = _reference_compute(sample)
    t_ref = time.perf_counter() - t0

    t0 = time.perf_counter()
    new = compute_yearly_npv_trajectories(sample)
    t_new = time.perf_counter() - t0

    with capsys.disabled():
        print(
            f"\n[real-data sample] groups={len(keys)} rows={len(sample)} "
            f"reference={t_ref:.3f}s vectorized={t_new:.3f}s "
            f"speedup={t_ref / max(t_new, 1e-9):.1f}x"
        )

    ref_g = (
        _norm(ref)
        .groupby(GROUP_KEYS, dropna=False)[["yearly_npv", "terminal_value"]]
        .sum()
        .sort_index()
    )
    new_g = (
        _norm(new)
        .groupby(GROUP_KEYS, dropna=False)[["yearly_npv", "terminal_value"]]
        .sum()
        .sort_index()
    )
    assert list(ref_g.index) == list(new_g.index)
    np.testing.assert_allclose(new_g.to_numpy(), ref_g.to_numpy(), rtol=1e-6, atol=1e-6)
