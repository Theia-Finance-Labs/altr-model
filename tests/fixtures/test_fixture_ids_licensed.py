"""Internal-only guard: every id in the committed fixture slice is licensed.

`tests/fixtures/data/` ships inside the export, so its `asset_id` and
`company_id` values leave this machine with it. They may therefore only ever be
identifiers the recipient is already licensed for — i.e. ids that appear in the
deliverables files themselves. An id from outside that universe (a wider
internal extract, a hand-picked company, a re-cut slice taken from the full
inputs) would be a licence breach shipped inside a test fixture, and nothing
else in the suite would notice.

This file is not shipped: it needs the deliverables drop, which recipients get
as data but not as a path this test can find. `build_export.py` excludes it
(SKIP_RELATIVE) alongside the other internal-only tests.

Run it whenever the fixture slice is re-cut::

    ALTR_DELIVERABLES_DIR="/path/to/ALTR deliverables" \\
        python -m pytest tests/fixtures/test_fixture_ids_licensed.py -q
"""
import os
from pathlib import Path

import pandas as pd
import pytest

DATA = Path(__file__).parent / "data"
_DELIVERABLES_ENV = os.environ.get("ALTR_DELIVERABLES_DIR", "")
DELIVERABLES = Path(_DELIVERABLES_ENV) if _DELIVERABLES_ENV else None

# Fingerprint of the authoritative drop (2026-08-25 deliverables). A guard that
# accepts ANY directory holding files with the right names would pass against a
# wider internal extract — the in-repo data/05_model_input/ has the exact
# filenames and MORE ids, including unlicensed ones — so the licensed universe
# must prove its identity, not just exist. Update deliberately on a new drop.
EXPECTED_COMPANY_ID_COUNT = 7512
_REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    DELIVERABLES is None or not DELIVERABLES.is_dir(),
    reason="ALTR_DELIVERABLES_DIR not set (deliverables drop unavailable)",
)


def test_deliverables_drop_is_the_licensed_universe():
    """The mounted drop must be the real deliverables, not a look-alike."""
    resolved = DELIVERABLES.resolve()
    assert not resolved.is_relative_to(_REPO_ROOT), (
        f"ALTR_DELIVERABLES_DIR resolves inside the repository tree ({resolved}) "
        "- internal extracts are not the licensed universe"
    )
    n = len(_ids(DELIVERABLES / "companies_ownerships.csv", "company_id"))
    assert n == EXPECTED_COMPANY_ID_COUNT, (
        f"drop at {resolved} holds {n} company ids, expected "
        f"{EXPECTED_COMPANY_ID_COUNT} - wrong or stale drop mounted; if the "
        "deliverables were legitimately re-issued, update "
        "EXPECTED_COMPANY_ID_COUNT in the same commit as the re-cut fixture"
    )


def _ids(path: Path, column: str) -> set[str]:
    """The distinct values of one id column, read without the rest of the file."""
    return set(pd.read_csv(path, usecols=[column], low_memory=False)[column].dropna())


def test_fixture_asset_ids_are_in_the_deliverables():
    fixture = _ids(DATA / "downloaded_assets.csv", "asset_id")
    licensed = _ids(DELIVERABLES / "assets_forecasts.csv", "asset_id")
    unlicensed = fixture - licensed
    assert not unlicensed, (
        f"{len(unlicensed)} fixture asset_id(s) are not in the deliverables: "
        f"{sorted(unlicensed)[:10]}"
    )


def test_fixture_company_ids_are_in_the_deliverables():
    fixture = _ids(DATA / "downloaded_companies.csv", "company_id")
    licensed = _ids(DELIVERABLES / "companies_ownerships.csv", "company_id")
    unlicensed = fixture - licensed
    assert not unlicensed, (
        f"{len(unlicensed)} fixture company_id(s) are not in the deliverables: "
        f"{sorted(unlicensed)[:10]}"
    )
