"""Equivalence guard for the vectorised rewrite of compute_yearly_npv_trajectories.

`_reference_compute` below is a verbatim transcription of the ORIGINAL per-group
Python loop (nodes.py before the vectorisation), with one deliberate change:
the main `groupby(group_keys)` carries `dropna=False`. That is the separately
tested dropna fix (see test_npv_dropna_keys.py); folding it into the reference
isolates this file to the vectorisation change alone.

Every branch of the terminal-value ladder is exercised: perpetuity, r <= g,
final_fcff == 0, negative final FCFF, single-row groups,
terminal_method != "perpetuity", and a NaN group key.
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
    terminal_method: str = "perpetuity",
) -> pd.DataFrame:
    npv_data = asset_earnings.copy()

    unresolved_mask = npv_data["scenario_type"].isna()
    if unresolved_mask.any():
        unresolved_asset_ids = sorted(
            npv_data.loc[unresolved_mask, "asset_id"].unique()
        )
        raise ValueError(
            f"{len(unresolved_asset_ids)} asset(s) have no scenario_type resolved "
            f"and cannot be included in NPV: {unresolved_asset_ids}"
        )

    def get_discount_rate(scenario_type):
        if scenario_type == "baseline":
            return discount_rate_baseline
        elif scenario_type == "target":
            return discount_rate_shock
        else:
            raise ValueError(f"Invalid scenario type: {scenario_type}")

    npv_data["discount_rate"] = npv_data.apply(
        lambda row: get_discount_rate(row["scenario_type"]), axis=1
    )

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

        if (terminal_method == "perpetuity") and (len(g) > 0):
            final_fcff = float(g["FCFF"].iloc[-1])
            final_year = int(g["year"].iloc[-1])

            if final_fcff > 0:
                terminal_cf = final_fcff * (1 + terminal_growth_rate)
                final_discount_rate = g.iloc[-1]["discount_rate"]
                if final_discount_rate > terminal_growth_rate:
                    terminal_value_nominal = terminal_cf / (
                        final_discount_rate - terminal_growth_rate
                    )
                    years_to_terminal = (final_year + 1) - base_year
                    terminal_discount_factor = (1 + final_discount_rate) ** (
                        -years_to_terminal
                    )
                    terminal_value = float(
                        terminal_value_nominal * terminal_discount_factor
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
        g["terminal_growth_rate"] = terminal_growth_rate

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
    # A9 two-row group with a mixed-sign run
    rows += _asset("A9", "misaligned_high_carbon", [(2029, -5.0), (2030, 12.0)])
    return pd.DataFrame(rows)


PARAMS = [
    pytest.param({}, id="defaults"),
    pytest.param({"terminal_growth_rate": 0.10}, id="r_le_g"),
    pytest.param({"terminal_growth_rate": 0.0}, id="zero_growth"),
    pytest.param({"terminal_method": "none"}, id="terminal_method_none"),
    pytest.param(
        {"discount_rate_baseline": 0.05, "discount_rate_shock": 0.12},
        id="split_discount_rates",
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
    assert set(tv["asset_id"]) >= {"A1", "A3", "A5", "A9"}
    # A4 is loss-making throughout, A7 has final_fcff == 0 -> no terminal row
    assert "A4" not in set(tv["asset_id"])
    assert "A7" not in set(tv["asset_id"])


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
