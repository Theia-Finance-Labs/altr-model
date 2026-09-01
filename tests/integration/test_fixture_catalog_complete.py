"""Guard: every file-backed base dataset has a fixture override.

A base entry without one writes into the real `data/` tree during a fixture
run, so the regression fixture would quietly read or clobber production
artefacts. This fails the moment a new file-backed dataset lands in
`conf/base/catalog.yml` without its `conf/fixture/catalog.yml` twin.
"""

from pathlib import Path

import yaml

CONF = Path(__file__).resolve().parents[2] / "conf"
#: Fixture datasets may only live under a fixture-scoped directory.
ALLOWED_PREFIXES = ("data/fixture_run/", "tests/fixtures/data/")

#: Main's ten file-backed catalog datasets: three raw inputs and seven outputs.
#: Named rather than merely counted so a rename shows up as a rename.
BASE_DATASETS = {
    "assets_forecasts",
    "companies_ownerships",
    "scenarios",
    "company_trajectories",
    "asset_trajectories",
    "asset_earnings",
    "yearly_npv_trajectories",
    "asset_npv",
    "company_technology_npv",
    "company_npv",
}


def _filepaths(catalog_path: Path) -> dict[str, str]:
    """Dataset name -> filepath, for entries that have one."""
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) or {}
    return {
        name: entry["filepath"]
        for name, entry in catalog.items()
        if isinstance(entry, dict) and "filepath" in entry
    }


def test_base_catalog_is_the_expected_ten_datasets():
    assert set(_filepaths(CONF / "base" / "catalog.yml")) == BASE_DATASETS


def test_every_file_backed_base_dataset_has_a_fixture_override():
    base = _filepaths(CONF / "base" / "catalog.yml")
    fixture = _filepaths(CONF / "fixture" / "catalog.yml")
    assert base, "no file-backed datasets parsed from conf/base/catalog.yml"

    missing = sorted(set(base) - set(fixture))
    assert not missing, f"base datasets with no fixture override: {missing}"

    escaping = sorted(
        f"{name}={path}"
        for name, path in fixture.items()
        if not path.startswith(ALLOWED_PREFIXES)
    )
    assert not escaping, f"fixture filepaths outside the fixture tree: {escaping}"
