"""Unit tests for the deliverables -> model-input ingestion script.

Pinned behaviours:

* the three transforms rename the deliverables columns onto the pipeline
  contract (`year` -> `production_year` / `scenario_year`, `scenario_name` ->
  `scenario` with the ``AR6_<provider>_`` prefix stripped) and emit every
  column in ``ASSETS_REQUIRED`` / ``COMPANIES_REQUIRED`` / ``SCENARIOS_REQUIRED``;
* a missing required column raises ``ValueError`` naming the column;
* the ownership-tier check warns (it does not raise) when the tier the pipeline
  will select over-allocates an asset;
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
    check_ownership_tier,
    main,
)

YEARS = [2025, 2026, 2027, 2028, 2029]


def deliverables_assets() -> pd.DataFrame:
    """Five rows in the deliverables schema: `year`, no `workforce_size`."""
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
    """Five rows in the deliverables schema, incl. the columns that get dropped."""
    return pd.DataFrame(
        {
            "asset_id": [f"A{i}" for i in range(5)],
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
    assert "year" not in assets.columns
    assert list(assets["production_year"]) == YEARS
    assert assets["workforce_size"].isna().all()

    companies = build_companies(source)
    assert set(COMPANIES_REQUIRED) <= set(companies.columns)
    assert list(companies["production_year"]) == YEARS
    # sector/technology/asset_name are dropped: filter_companies projects them
    # away before the merge, so they only bloat the file.
    assert not {"sector", "technology", "asset_name"} & set(companies.columns)

    scenarios = build_scenarios(source)
    assert set(SCENARIOS_REQUIRED) <= set(scenarios.columns)
    assert "scenario_name" not in scenarios.columns
    assert list(scenarios["scenario_year"]) == YEARS
    # "AR6_<provider>_" is stripped; filter_scenarios re-adds it.
    assert set(scenarios["scenario"]) == {"EN_NoPolicy"}


def test_missing_required_column_raises_valueerror_naming_it(tmp_path: Path):
    source = stage(
        tmp_path / "01_raw",
        assets_forecasts=deliverables_assets().drop(columns=["capacity_factor"]),
    )
    with pytest.raises(ValueError, match="capacity_factor"):
        build_assets(source)


def test_ownership_tier_over_allocation_warns_but_does_not_raise():
    # Two rungs of the ownership chain each claiming the whole asset: 200%.
    chain = pd.concat([deliverables_companies(), deliverables_companies()])
    chain = chain.rename(columns={"year": "production_year"})
    with pytest.warns(UserWarning, match="over-allocated"):
        check_ownership_tier(chain)


def test_main_writes_the_three_model_inputs(source: Path, tmp_path: Path):
    dest = tmp_path / "05_model_input"
    main(["--source", str(source), "--dest", str(dest)])
    written = sorted(p.name for p in dest.glob("*.csv"))
    assert written == [
        "downloaded_assets.csv",
        "downloaded_companies.csv",
        "downloaded_scenarios.csv",
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
