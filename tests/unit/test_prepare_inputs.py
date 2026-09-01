"""Unit tests for the deliverables -> model-input ingestion script.

Pinned behaviours:

* the three transforms emit every column in ``ASSETS_REQUIRED`` /
  ``COMPANIES_REQUIRED`` / ``SCENARIOS_REQUIRED``. On this tree only the
  scenario frame is reshaped (``scenario_name`` -> ``scenario``); the assets
  and companies deliverables already carry the pipeline's contract, and
  ``year`` is left alone in all three;
* ``sector`` / ``technology`` / ``asset_name`` SURVIVE on companies -- they are
  in ``_consolidate_ownership_stakes``'s group_cols;
* a missing required column raises ``ValueError`` naming the column;
* a companies input with no ownership TIER column (``ownership_type`` or
  ``ownership_level``) is refused outright -- owner ruling of 2026-09-01 that a
  tier-less export is a data defect, not a run-time mode;
* the ownership check warns (it does not raise) when consolidated ownership
  over-allocates an asset;
* nothing is written until every dataset has been built and validated.
"""

from pathlib import Path

import pandas as pd
import pytest

from scripts.prepare_inputs import (
    ASSETS_REQUIRED,
    COMPANIES_REQUIRED,
    SCENARIOS_REQUIRED,
    build_assets,
    build_companies,
    build_scenarios,
    check_ownership_allocation,
    main,
)

YEARS = [2025, 2026, 2027, 2028, 2029]


def deliverables_assets() -> pd.DataFrame:
    """Five rows in the deliverables schema, which is main's contract as-is."""
    return pd.DataFrame(
        {
            "asset_id": [f"A{i}" for i in range(5)],
            "sector": "Power",
            "technology": "CoalCap",
            "year": YEARS,
            "capacity_unit": "MW",
            "capacity": [100.0, 110.0, 120.0, 130.0, 140.0],
            "asset_age": [10, 11, 12, 13, 14],
            "country_iso2": "DE",
            "country_name": "Germany",
            "asset_name": [f"plant-{i}" for i in range(5)],
            "latitude": 51.0,
            "longitude": 9.0,
            "age_is_inferred": False,
            "capacity_factor": 0.5,
            "emission_factor": 0.9,
        }
    )


def deliverables_companies(ownership_percentage=None) -> pd.DataFrame:
    """Five rows in the deliverables schema, incl. the group_cols columns."""
    return pd.DataFrame(
        {
            "asset_id": [f"A{i}" for i in range(5)],
            "asset_name": [f"plant-{i}" for i in range(5)],
            "company_name": [f"co-{i}" for i in range(5)],
            "company_id": [f"C{i}" for i in range(5)],
            "year": YEARS,
            "ownership_type": "direct",
            "ownership_percentage": ownership_percentage or [100.0] * 5,
            "sector": "Power",
            "technology": "CoalCap",
        }
    )


def deliverables_scenarios() -> pd.DataFrame:
    """Five rows in the deliverables schema: `scenario_name` prefixed, `year`."""
    return pd.DataFrame(
        {
            "scenario_provider": "WITCH 5.0",
            "scenario_name": "AR6_WITCH 5.0_EN_NoPolicy",
            "scenario_type": "baseline",
            "scenario_geography": "Global",
            "sector": "Power",
            "technology": "CoalCap",
            "technology_type": "carbontech",
            "scenario_price": [1.0, 2.0, 3.0, 4.0, 5.0],
            "scenario_pathway": [10.0, 9.0, 8.0, 7.0, 6.0],
            "scenario_capacity_factor": 0.5,
            "year": YEARS,
            "country_iso2_list": "DE",
            # Cost columns the pipeline hard-indexes; see SCENARIOS_REQUIRED.
            "lifetime_years": 30.0,
            "efficiency_decimal": 0.4,
            "capital_cost_usd_per_mw": 1_000_000.0,
            "om_cost_usd_per_mw_per_yr": 30_000.0,
            "capacity_additions_mw_per_yr": 5.0,
            "scrap_usd_per_mw": 10_000.0,
            "carbon_price_usd_per_tco2": 50.0,
            "fuel_price": 3.0,
        }
    )


def stage(source: Path, **frames: pd.DataFrame) -> Path:
    """Write deliverables frames into `source` under their expected filenames."""
    source.mkdir(parents=True, exist_ok=True)
    for name, frame in frames.items():
        frame.to_csv(source / f"{name}.csv", index=False)
    return source


@pytest.fixture()
def source(tmp_path: Path) -> Path:
    return stage(
        tmp_path / "01_raw",
        assets_forecasts=deliverables_assets(),
        companies_ownerships=deliverables_companies(),
        scenarios=deliverables_scenarios(),
    )


def test_transforms_emit_the_pipeline_contract_columns(source: Path):
    assets = build_assets(source)
    assert set(ASSETS_REQUIRED) <= set(assets.columns)
    # `year` is the pipeline's own column name here: filter_assets reads it
    # directly, and `production_year` appears nowhere in src/.
    assert list(assets["year"]) == YEARS

    companies = build_companies(source)
    assert set(COMPANIES_REQUIRED) <= set(companies.columns)
    assert list(companies["year"]) == YEARS
    # sector/technology/asset_name must SURVIVE: _consolidate_ownership_stakes
    # groups on them, so dropping them breaks the roll-up.
    assert {"sector", "technology", "asset_name"} <= set(companies.columns)

    scenarios = build_scenarios(source)
    assert set(SCENARIOS_REQUIRED) <= set(scenarios.columns)
    assert "scenario_name" not in scenarios.columns
    assert list(scenarios["year"]) == YEARS
    # Renamed verbatim: filter_scenarios only prefixes names that lack "AR6_".
    assert set(scenarios["scenario"]) == {"AR6_WITCH 5.0_EN_NoPolicy"}


def test_missing_required_column_raises_valueerror_naming_it(tmp_path: Path):
    source = stage(
        tmp_path / "01_raw",
        assets_forecasts=deliverables_assets().drop(columns=["capacity_factor"]),
    )
    with pytest.raises(ValueError, match="capacity_factor"):
        build_assets(source)


def test_companies_missing_a_group_column_raises_valueerror_naming_it(tmp_path: Path):
    # The pre-migration script DROPPED asset_name; on this tree that is a
    # breaking change, so it has to be a validation failure, not a transform.
    source = stage(
        tmp_path / "01_raw",
        companies_ownerships=deliverables_companies().drop(columns=["asset_name"]),
    )
    with pytest.raises(ValueError, match="asset_name"):
        build_companies(source)


def test_companies_without_a_tier_column_are_refused(tmp_path: Path):
    """The 2026-08-25 deliverables drop has 8 columns and none of them names
    the ownership rung. On such a frame `_select_ownership_tier` takes its
    keep-everything branch, the whole chain enters, and 92% of asset-years sum
    above 105%. Owner ruling: that is a data-export defect, so it stops here."""
    source = stage(
        tmp_path / "01_raw",
        companies_ownerships=deliverables_companies().drop(columns=["ownership_type"]),
    )
    with pytest.raises(ValueError, match="ownership_type") as excinfo:
        build_companies(source)

    message = str(excinfo.value)
    assert "over-allocated" in message, "the consequence must be stated"
    assert "marts" in message, "the remedy must be stated"


def test_companies_with_a_tier_column_pass_through(tmp_path: Path):
    """The other side of the guard: the marts export carries `ownership_type`,
    and a frame that has it is returned unchanged, tier column included."""
    source = stage(tmp_path / "01_raw", companies_ownerships=deliverables_companies())

    out = build_companies(source)

    assert list(out["ownership_type"]) == ["direct"] * 5
    assert len(out) == 5


def test_a_tier_less_companies_input_writes_nothing(tmp_path: Path):
    """The tier guard keeps the validate-before-write property: it runs during
    the build, so `data/05_model_input/` is never half-swapped."""
    source = stage(
        tmp_path / "01_raw",
        assets_forecasts=deliverables_assets(),
        companies_ownerships=deliverables_companies().drop(columns=["ownership_type"]),
        scenarios=deliverables_scenarios(),
    )
    dest = tmp_path / "05_model_input"
    with pytest.raises(ValueError, match="ownership_type"):
        main(["--source", str(source), "--dest", str(dest)])
    assert not list(dest.glob("*.csv"))


def test_scenarios_missing_a_cost_column_raises_valueerror_naming_it(tmp_path: Path):
    # The bare prices/pathways extract lacks the cost columns; without this
    # check it fails deep inside input preparation instead of here.
    source = stage(
        tmp_path / "01_raw",
        scenarios=deliverables_scenarios().drop(columns=["lifetime_years"]),
    )
    with pytest.raises(ValueError, match="lifetime_years"):
        build_scenarios(source)


def test_ownership_over_allocation_warns_but_does_not_raise():
    # Two rungs of the ownership chain each claiming the whole asset: 200%.
    chain = pd.concat([deliverables_companies(), deliverables_companies()])
    with pytest.warns(UserWarning, match="over-allocated"):
        check_ownership_allocation(chain)


def test_main_writes_the_three_model_inputs(source: Path, tmp_path: Path):
    dest = tmp_path / "05_model_input"
    main(["--source", str(source), "--dest", str(dest)])
    written = sorted(p.name for p in dest.glob("*.csv"))
    assert written == [
        "assets_forecasts.csv",
        "companies_ownerships.csv",
        "scenarios.csv",
    ]


def test_nothing_is_written_when_a_later_dataset_fails_validation(
    tmp_path: Path,
):
    # assets/companies are fine; scenarios is missing a required column. The
    # run must abort before writing ANY file (no half-swapped model inputs).
    source = stage(
        tmp_path / "01_raw",
        assets_forecasts=deliverables_assets(),
        companies_ownerships=deliverables_companies(),
        scenarios=deliverables_scenarios().drop(columns=["scenario_price"]),
    )
    dest = tmp_path / "05_model_input"
    with pytest.raises(ValueError, match="scenario_price"):
        main(["--source", str(source), "--dest", str(dest)])
    assert not list(dest.glob("*.csv"))
