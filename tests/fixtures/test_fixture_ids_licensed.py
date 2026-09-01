"""Internal-only guard: every shipped id is one the recipient is licensed for.

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

**It does not skip.** The pre-migration version carried
`pytestmark = pytest.mark.skipif(...)` on `ALTR_DELIVERABLES_DIR`, so the one
check standing between an unlicensed identifier and a shipped artefact passed
silently when unconfigured. In an export gate that is the worst possible
default, so a missing or unidentifiable drop is now a hard failure. The file
never ships, so failing closed costs a recipient nothing.

Run it whenever the fixture slice is re-cut, or against a built export::

    ALTR_DELIVERABLES_DIR="/path/to/ALTR deliverables" \\
        python -m pytest tests/fixtures/test_fixture_ids_licensed.py -q

    ALTR_EXPORT_ROOT=/path/to/built/export ALTR_DELIVERABLES_DIR=... \\
        python -m pytest tests/fixtures/test_fixture_ids_licensed.py -q
"""
import os
from pathlib import Path

import pandas as pd
import pytest
from scripts.sanitize_check import COMPANY_ID_RE

DATA = Path(__file__).parent / "data"
_DELIVERABLES_ENV = os.environ.get("ALTR_DELIVERABLES_DIR", "")
DELIVERABLES = Path(_DELIVERABLES_ENV) if _DELIVERABLES_ENV else None

_EXPORT_ENV = os.environ.get("ALTR_EXPORT_ROOT", "")
EXPORT_ROOT = Path(_EXPORT_ENV) if _EXPORT_ENV else None

# Fingerprint of the authoritative drop (2026-08-25 deliverables). A guard that
# accepts ANY directory holding files with the right names would pass against a
# wider internal extract — the in-repo data/05_model_input/ has the exact
# filenames and MORE ids, including unlicensed ones — so the licensed universe
# must prove its identity, not just exist. Update deliberately on a new drop.
EXPECTED_COMPANY_ID_COUNT = 7512
_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Company identifiers as they appear in text — the SANITIZER's pattern, not a
#: second copy of it. This gate and the sanitizer gate must recognise exactly
#: the same id shapes: an id form only one of them sees is an id form that can
#: cross one boundary unnoticed. The `\b`-anchored form kept here previously
#: missed every composite id ("NEW_CN_<id>_Power_HydroCap_EU"), which is the
#: divergence the sanitizer had already fixed on its side.
COMPANY_ID = COMPANY_ID_RE

#: Text formats an export can carry an identifier in. Binary payloads are the
#: sanitizer's business (it names its unscanned binaries); these are the ones
#: an id can hide in as plain text.
SCANNED_SUFFIXES = (".csv", ".yml", ".yaml", ".ipynb", ".md", ".txt", ".py")


def _require_drop() -> Path:
    """The deliverables drop, or a hard failure naming what is missing."""
    if DELIVERABLES is None:
        pytest.fail(
            "ALTR_DELIVERABLES_DIR is unset. This guard does not skip: it is the "
            "check between an unlicensed identifier and a shipped artefact. "
            "Mount the deliverables drop and re-run."
        )
    if not DELIVERABLES.is_dir():
        pytest.fail(f"ALTR_DELIVERABLES_DIR={DELIVERABLES} is not a directory")
    return DELIVERABLES


def _ids(path: Path, column: str) -> set[str]:
    """The distinct values of one id column, read without the rest of the file."""
    return set(pd.read_csv(path, usecols=[column], low_memory=False)[column].dropna())


@pytest.fixture(scope="module")
def licensed_company_ids() -> set[str]:
    return _ids(_require_drop() / "companies_ownerships.csv", "company_id")


def test_deliverables_drop_is_the_licensed_universe(licensed_company_ids):
    """The mounted drop must be the real deliverables, not a look-alike."""
    resolved = _require_drop().resolve()
    assert not resolved.is_relative_to(_REPO_ROOT), (
        f"ALTR_DELIVERABLES_DIR resolves inside the repository tree ({resolved}) "
        "- internal extracts are not the licensed universe"
    )
    n = len(licensed_company_ids)
    assert n == EXPECTED_COMPANY_ID_COUNT, (
        f"drop at {resolved} holds {n} company ids, expected "
        f"{EXPECTED_COMPANY_ID_COUNT} - wrong or stale drop mounted; if the "
        "deliverables were legitimately re-issued, update "
        "EXPECTED_COMPANY_ID_COUNT in the same commit as the re-cut fixture"
    )


def test_fixture_asset_ids_are_in_the_deliverables():
    fixture = _ids(DATA / "assets_forecasts.csv", "asset_id")
    licensed = _ids(_require_drop() / "assets_forecasts.csv", "asset_id")
    unlicensed = fixture - licensed
    assert not unlicensed, (
        f"{len(unlicensed)} fixture asset_id(s) are not in the deliverables: "
        f"{sorted(unlicensed)[:10]}"
    )


def test_fixture_company_ids_are_in_the_deliverables(licensed_company_ids):
    fixture = _ids(DATA / "companies_ownerships.csv", "company_id")
    unlicensed = fixture - licensed_company_ids
    assert not unlicensed, (
        f"{len(unlicensed)} fixture company_id(s) are not in the deliverables: "
        f"{sorted(unlicensed)[:10]}"
    )


def test_every_identifier_in_the_built_export_is_licensed(licensed_company_ids):
    """Coverage past the two fixture CSVs: scan the export as it will ship.

    The pre-migration guard read exactly two CSVs, so an identifier living in a
    YAML or a notebook shipped unnoticed. This scans every text file of the
    built export instead — which is also the only place the question is
    well-posed, because `build_export.py` transforms the source tree on the way
    out (the conf example-company list is emptied there, so scanning the source
    tree would flag identifiers that never leave it).
    """
    if EXPORT_ROOT is None:
        pytest.skip("ALTR_EXPORT_ROOT not set (run from build_export.py)")
    assert EXPORT_ROOT.is_dir(), f"ALTR_EXPORT_ROOT={EXPORT_ROOT} is not a directory"

    offenders: dict[str, set[str]] = {}
    for path in sorted(EXPORT_ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SCANNED_SUFFIXES:
            continue
        found = set(COMPANY_ID.findall(path.read_text(encoding="utf-8", errors="ignore")))
        unlicensed = found - licensed_company_ids
        if unlicensed:
            offenders[str(path.relative_to(EXPORT_ROOT))] = unlicensed

    assert not offenders, "unlicensed company ids in the built export: " + "; ".join(
        f"{name}: {sorted(ids)[:5]}" for name, ids in sorted(offenders.items())
    )
