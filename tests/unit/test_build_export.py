"""Tests for the export tooling itself.

The export builder and its sanitizer are the only thing standing between the
internal repo and an external drop, and both lean on text patterns matched
against files they do not own. These tests fail when a source file is reworded
and a pattern goes stale, rather than silently shipping the un-rewritten text.
"""

from pathlib import Path

import pytest

from scripts.build_export import (
    COMPANY_IDS_CONF,
    ROOT,
    TRANSFORMS,
    TransformError,
    dockerfile_for_recipients,
    drop_streamlit_group,
    empty_company_ids,
    is_skipped,
    prune_streamlit_lock,
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


def test_agents_md_is_never_allowlisted():
    # Recipients never receive agent or team-board context. This is the
    # assertion that keeps row 4's "never shipped externally" true.
    assert "AGENTS.md" not in read_allowlist(ALLOWLIST)


def test_uv_lock_ships_and_poetry_lock_does_not():
    entries = read_allowlist(ALLOWLIST)
    assert "uv.lock" in entries
    assert "poetry.lock" not in entries


def test_pin_golden_ships_and_the_internal_only_tests_do_not():
    entries = read_allowlist(ALLOWLIST)
    assert "tests/golden/pin_golden.py" in entries
    # tests/ ships wholesale, so exclusions are made in code, not by omission.
    assert "tests" in entries or "tests/" in entries
    # The licence guard reads the deliverables drop by path; the export-tooling
    # test imports scripts/ modules that are not allowlisted.
    assert is_skipped("tests/fixtures/test_fixture_ids_licensed.py")
    assert is_skipped("tests/unit/test_build_export.py")


def test_the_pipeline_registration_test_ships():
    # The pre-migration exclusion justified dropping it as a "full-input smoke
    # test needing the internal data drop". On this tree it is a data-free
    # registration test that passes for a recipient and catches renamed
    # pipelines, moved namespaces and drifted dataset contracts.
    assert not is_skipped("tests/test_run.py")


def test_the_bigquery_downloader_does_not_ship():
    # Maintainer-only ingestion: externals have no warehouse access.
    assert is_skipped("src/altr_model/bigquery_marts_downloader.py")


# --------------------------------------------------------------------------
# copy-time transforms: each must still remove what it is there to remove


def test_example_company_ids_are_emptied_out_of_the_exported_conf():
    source = (ROOT / COMPANY_IDS_CONF).read_text(encoding="utf-8")
    assert "company_ids:" in source, f"{COMPANY_IDS_CONF} reworded; transform is stale"
    assert PATTERNS["company-id"](source.replace("\n", " ")), (
        "no company id in the source conf — the transform has nothing to remove, "
        "which means this test can no longer prove it works"
    )

    shipped = _transformed(COMPANY_IDS_CONF)
    assert "company_ids: []" in shipped
    assert not any(PATTERNS["company-id"](line) for line in shipped.splitlines()), (
        "a company id survived the export transform"
    )


def test_company_ids_transform_raises_when_its_target_is_gone():
    # A transform that silently no-ops is how an unlicensed id ships.
    with pytest.raises(TransformError, match="no `company_ids:` block"):
        empty_company_ids("baseline_scenario: x\ntarget_scenario: y\n")


def test_dockerfile_is_rewritten_to_run_the_pipeline():
    # The internal image launches the Streamlit batch runner, which does not
    # ship — delivered unrewritten, the image builds and then crashes at
    # startup looking for notebooks/streamlit_app.py.
    source = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "streamlit" in source.lower(), "Dockerfile reworded; transform is stale"

    shipped = _transformed("Dockerfile")
    assert 'ENTRYPOINT ["kedro", "run"]' in shipped
    assert "streamlit" not in shipped.lower(), "streamlit survives the export"
    assert "8501" not in shipped
    # docker-compose.yml does not ship; the delivered file must not point at it.
    assert "compose" not in shipped.lower()


def test_dockerfile_transform_raises_when_its_target_is_gone():
    with pytest.raises(TransformError, match="tail marker"):
        dockerfile_for_recipients('FROM python:3.10-slim\nENTRYPOINT ["true"]\n')


def test_streamlit_group_is_dropped_from_the_exported_pyproject():
    # The group installs the batch-run app, which does not ship. Left declared,
    # the documented `uv sync --group streamlit` installs a dependency with
    # nothing to run.
    source = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "streamlit = [" in source, "pyproject.toml reworded; transform is stale"

    shipped = _transformed("pyproject.toml")
    assert "streamlit" not in shipped.lower(), "streamlit survives the export"
    # The neighbouring groups are untouched — the cut is the streamlit block,
    # not everything around it.
    for group in ("dev = [", "bigquery = [", "docs = ["):
        assert group in shipped, f"{group} lost to the streamlit transform"


def test_streamlit_transform_raises_when_its_target_is_gone():
    with pytest.raises(TransformError, match="no `streamlit = \\[` group"):
        drop_streamlit_group("[dependency-groups]\ndocs = [\n    \"mkdocs\",\n]\n")


def test_streamlit_is_pruned_from_the_exported_uv_lock():
    # The pyproject transform above drops the group, but the lock was copied
    # verbatim — so the export shipped the group's two declarations and the
    # resolved [[package]] block, contradicting the docs and leaving the lock
    # disagreeing with the pyproject it locks.
    source = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert "streamlit" in source.lower(), "uv.lock re-locked; transform is stale"

    shipped = _transformed("uv.lock")
    assert "streamlit" not in shipped.lower(), "streamlit survives the export"
    # The cut is the streamlit entries, not the file around them: the other
    # groups, the lock header and the neighbouring packages all stay.
    assert "docs = [" in shipped and "bigquery = [" in shipped
    assert shipped.startswith("version = "), "lock header lost to the transform"
    for package in ('name = "kedro"', 'name = "pandas"', 'name = "strawberry-graphql"'):
        assert package in shipped, f"{package} lost to the streamlit transform"
    # Exactly the streamlit lines go: three blocks out of a file this size.
    assert len(shipped.splitlines()) < len(source.splitlines())
    assert len(source.splitlines()) - len(shipped.splitlines()) < 50


def test_uv_lock_transform_raises_when_its_target_is_gone():
    # The other half of the no-op guard: a lock with no streamlit in it means
    # the transform can no longer verify what it removed.
    with pytest.raises(TransformError, match="nothing named `streamlit`"):
        prune_streamlit_lock('version = 1\n\n[[package]]\nname = "kedro"\n')


def test_dockerignore_ships_alongside_the_dockerfile():
    # Without it, every recipient `docker build` hashes their staged data/
    # (hundreds of MB) into the build context.
    entries = read_allowlist(ALLOWLIST)
    assert "Dockerfile" in entries
    assert ".dockerignore" in entries
    # It ships untransformed, so its comments must not point recipients at
    # internal-only files.
    assert "compose" not in _transformed(".dockerignore").lower()


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


def test_no_suppression_touches_conf():
    # The export empties the example-company list instead of suppressing it.
    # A conf/ suppression would silently re-open that hole.
    offenders = [
        f"{s.path_glob}:{s.pattern}"
        for s in EXCEPTIONS
        if Path(s.path_glob).parts and Path(s.path_glob).parts[0] == "conf"
        and s.pattern == "company-id"
    ]
    assert not offenders, f"company-id suppressions on conf/ are forbidden: {offenders}"


# --- company-id pattern: composite forms must not slip the gate -------------
# Regression for the Santa round-1 refuter finding: the original pattern was
# anchored with \b, which cannot match between "_" and a word character, so any
# id embedded in a generated composite identifier passed the gate unnoticed.

COMPOSITE_IDS = [
    "NEW_CN_2023551807935057693_Power_HydroCap_EU",
    "NEW_CN_2023551807935057693",
    "CN_2023551807935057693_Power",
    "asset=CP_3685197042895689972_Gas",
]

BARE_IDS = [
    "company_id,CN_2023551807935057693,2025",
    "- CP_3685197042895689972",
]

NOT_IDS = [
    "SCN_12345678 is not a company id",
    "CN_12345 too short",
]


@pytest.mark.parametrize("line", COMPOSITE_IDS)
def test_company_id_pattern_catches_composite_forms(line):
    assert PATTERNS["company-id"](line), f"composite id slipped the gate: {line}"


@pytest.mark.parametrize("line", BARE_IDS)
def test_company_id_pattern_still_catches_bare_forms(line):
    assert PATTERNS["company-id"](line), f"bare id no longer caught: {line}"


@pytest.mark.parametrize("line", NOT_IDS)
def test_company_id_pattern_does_not_over_match(line):
    assert not PATTERNS["company-id"](line), f"false positive on: {line}"
