"""Tests for the export tooling itself.

The export builder and its sanitizer are the only thing standing between the
internal repo and a public drop, and both lean on text patterns matched against
files they do not own. These tests fail when a source file is reworded and a
pattern goes stale, rather than silently shipping the un-rewritten text.
"""

from pathlib import Path

import pytest

from scripts.build_export import (
    ROOT,
    TRANSFORMS,
    WAREHOUSE_DATASETS,
    is_skipped,
    read_allowlist,
)
from scripts.sanitize_check import EXCEPTIONS, PATTERNS, selftest

ALLOWLIST = ROOT / "scripts" / "export_allowlist.txt"


def _transformed(rel_path: str) -> str:
    """The text of a repo file exactly as the export would ship it."""
    text = (ROOT / rel_path).read_text(encoding="utf-8", errors="replace")
    transform = TRANSFORMS.get(rel_path)
    return transform(text) if transform else text


# --------------------------------------------------------------------------
# allowlist


def test_every_allowlist_entry_exists_in_the_repo():
    entries = read_allowlist(ALLOWLIST)
    assert entries, "allowlist parsed empty"
    missing = [entry for entry in entries if not (ROOT / entry).exists()]
    assert not missing, f"allowlist entries not in the repo: {missing}"


def test_pin_golden_ships_and_the_full_input_smoke_test_does_not():
    entries = read_allowlist(ALLOWLIST)
    assert "scripts/pin_golden.py" in entries
    # tests/ ships wholesale, so test_run.py is excluded in code, not by omission.
    assert "tests" in entries or "tests/" in entries
    assert is_skipped("tests/test_run.py")


# --------------------------------------------------------------------------
# copy-time transforms: each must still remove what it is there to remove


def test_warehouse_dataset_blocks_are_dropped_from_the_base_catalog():
    rel = "conf/base/catalog.yml"
    source = (ROOT / rel).read_text(encoding="utf-8")
    shipped = _transformed(rel)
    for dataset in WAREHOUSE_DATASETS:
        assert f"\n{dataset}:" in source, f"{dataset} no longer in {rel}"
        assert f"\n{dataset}:" not in shipped, f"{dataset} survived the transform"


def test_warehouse_note_is_dropped_from_the_fixture_catalog():
    rel = "conf/fixture/catalog.yml"
    source = (ROOT / rel).read_text(encoding="utf-8")
    assert "bigquery" in source.lower(), f"{rel} note reworded; transform is stale"
    assert "bigquery" not in _transformed(rel).lower()


def test_download_inputs_paragraph_is_dropped_from_the_pipeline_registry():
    rel = "src/crispy_kedro/pipeline_registry.py"
    source = (ROOT / rel).read_text(encoding="utf-8")
    assert "``download_inputs``" in source, f"{rel} reworded; transform is stale"
    assert "``download_inputs``" not in _transformed(rel)


def test_every_transform_target_is_still_a_repo_file():
    missing = [rel for rel in TRANSFORMS if not (ROOT / rel).is_file()]
    assert not missing, f"TRANSFORMS keys with no source file: {missing}"


# --------------------------------------------------------------------------
# sanitizer


def test_sanitizer_selftest_passes():
    assert selftest() == 0


@pytest.mark.parametrize(
    "suppression", EXCEPTIONS, ids=lambda s: f"{s.path_glob}:{s.pattern}"
)
def test_every_suppression_still_matches_something_shipped(suppression):
    """A suppression that can never fire is dead weight hiding a stale rule."""
    matches = PATTERNS[suppression.pattern]
    paths = [
        path
        for path in sorted(ROOT.glob(suppression.path_glob))
        if path.is_file() and not is_skipped(path.relative_to(ROOT).as_posix())
    ]
    assert paths, f"suppression path matches nothing: {suppression.path_glob}"

    for path in paths:
        text = _transformed(path.relative_to(ROOT).as_posix())
        if any(matches(line) for line in text.splitlines()):
            return
    pytest.fail(
        f"suppression never fires on the shipped copy: "
        f"{suppression.path_glob} / {suppression.pattern}"
    )
