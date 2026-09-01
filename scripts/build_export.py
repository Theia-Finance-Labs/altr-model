#!/usr/bin/env python
"""Assemble the external `altr-model` export from an explicit allowlist.

Usage::

    python scripts/build_export.py --dest ../altr-model-preview
    python scripts/build_export.py --dest ../altr-model-preview \
        --data-source "/path/to/deliverables"

Only paths listed in ``scripts/export_allowlist.txt`` are copied — assembly is
additive, never copy-then-delete, so a file that is not listed cannot leak by
being missed on a cleanup pass. On top of the allowlist a small set of
exclusions and copy-time rewrites strip the internal-only ``download_inputs``
ingestion path (BigQuery), which externals do not have access to.

The last step runs ``sanitize_check.py`` over the assembled tree; a hit fails the
build with a non-zero exit rather than shipping.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ALLOWLIST = HERE / "export_allowlist.txt"
SANITIZER = HERE / "sanitize_check.py"

#: Directory names pruned wherever they appear inside an allowlisted subtree.
SKIP_DIR_NAMES = frozenset({"__pycache__", ".ipynb_checkpoints", ".pytest_cache"})

#: Repo-relative paths excluded even though an allowlist entry covers them.
#: ``pipelines/download_inputs`` matches both the source pipeline and its tests.
SKIP_RELATIVE = (
    "src/crispy_kedro/pipelines/download_inputs",
    "tests/pipelines/download_inputs",
    "conf/base/parameters_download_inputs.yml",
    # Full-input smoke test: needs the internal data drop, so it can only fail
    # for a recipient. Kept in the internal repo, not shipped.
    "tests/test_run.py",
    # Tests the export tooling, which is itself internal-only (build_export.py
    # and sanitize_check.py are not allowlisted) — it would fail on import.
    "tests/unit/test_build_export.py",
    # Checks the fixture ids against the deliverables drop by path, which only
    # exists internally. Its job is done before the export is built.
    "tests/fixtures/test_fixture_ids_licensed.py",
)

#: The three deliverables files staged into ``data/01_raw/`` by --data-source.
#: ``scenarios.csv`` is often delivered zipped; a zip is extracted, not copied.
DELIVERABLES = ("assets_forecasts.csv", "companies_ownerships.csv", "scenarios.csv")

#: Warehouse-backed catalog entries used only by ``download_inputs``. They carry
#: internal dataset and GCP project identifiers, so they are dropped from the
#: exported catalog rather than shipped as dead configuration.
WAREHOUSE_DATASETS = (
    "db_assets_forecasts",
    "plant_ownerships",
    "db_scenarios_pathways",
    "financial_averages",
)


def read_allowlist(path: Path) -> list[str]:
    """Parse the allowlist: one repo-relative path per line, ``#`` comments."""
    entries: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            entries.append(line.rstrip("/"))
    return entries


def is_skipped(rel_path: str) -> bool:
    """True if this repo-relative path is pruned from the export."""
    parts = Path(rel_path).parts
    if SKIP_DIR_NAMES.intersection(parts):
        return True
    return any(
        rel_path == skip or rel_path.startswith(f"{skip}/") for skip in SKIP_RELATIVE
    )


def drop_yaml_blocks(text: str, keys: tuple[str, ...]) -> str:
    """Remove top-level ``key:`` blocks from a YAML document, comments intact.

    A block runs from its top-level key to the next line that starts in column
    zero (the next key, or a banner comment).
    """
    top_level_key = re.compile(r"^([A-Za-z_][\w.-]*):")
    kept: list[str] = []
    dropping = False
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        if dropping:
            if not stripped or stripped[0].isspace():
                continue
            dropping = False
        match = top_level_key.match(stripped)
        if match and match.group(1) in keys:
            dropping = True
            continue
        kept.append(line)
    return "".join(kept)


def strip_download_inputs_paragraph(text: str) -> str:
    """Drop the ``download_inputs`` note from the pipeline registry docstring.

    The note runs from its opening line to the next blank line or the closing
    ``\"\"\"``; the blank line above it goes with it.
    """
    lines = text.splitlines(keepends=True)
    start = next(
        (i for i, line in enumerate(lines) if line.startswith("``download_inputs``")),
        None,
    )
    if start is None:
        return text
    end = start
    while end < len(lines) and lines[end].strip() and not lines[end].startswith('"""'):
        end += 1
    if start and not lines[start - 1].strip():
        start -= 1
    return "".join(lines[:start] + lines[end:])


#: The fixture catalog's note about the warehouse datasets, which the export
#: does not carry — the note would point at datasets that are not there.
_FIXTURE_WAREHOUSE_NOTE = re.compile(
    r"^# \(BigQuery ibis datasets[^\n]*\n(?:^#[^\n]*\n)*", re.MULTILINE
)


#: Copy-time rewrites, keyed by repo-relative path. Applied to the copy only —
#: the source repo stays the single source of truth and is never edited here.
TRANSFORMS = {
    "conf/base/catalog.yml": lambda text: drop_yaml_blocks(text, WAREHOUSE_DATASETS),
    "conf/fixture/catalog.yml": lambda text: _FIXTURE_WAREHOUSE_NOTE.sub("", text),
    "src/crispy_kedro/pipeline_registry.py": strip_download_inputs_paragraph,
}


def copy_file(rel_path: str, dest_root: Path) -> None:
    """Copy one repo file into the export, applying its transform if it has one."""
    target = dest_root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    transform = TRANSFORMS.get(rel_path)
    if transform is None:
        shutil.copy2(ROOT / rel_path, target)
        return
    source_text = (ROOT / rel_path).read_text(encoding="utf-8")
    target.write_text(transform(source_text), encoding="utf-8")


def copy_entry(entry: str, dest_root: Path) -> int:
    """Copy one allowlist entry (file or subtree); returns the file count."""
    source = ROOT / entry
    if not source.exists():
        raise SystemExit(f"allowlist entry missing from repo: {entry}")
    if source.is_file():
        if is_skipped(entry):
            return 0
        copy_file(entry, dest_root)
        return 1

    count = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(ROOT).as_posix()
        if is_skipped(rel_path):
            continue
        copy_file(rel_path, dest_root)
        count += 1
    return count


def admonitions_to_markdown(text: str) -> str:
    """Rewrite mkdocs ``!!! note "Title"`` blocks as plain GitHub blockquotes."""
    lines = text.splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        header = re.match(r'^!!! *(\w+) *(?:"([^"]*)")? *$', lines[index])
        if header is None:
            out.append(lines[index])
            index += 1
            continue
        title = header.group(2) or header.group(1).capitalize()
        out.append(f"> **{title}**")
        index += 1
        while index < len(lines) and (
            not lines[index].strip() or lines[index].startswith("    ")
        ):
            body = lines[index].strip()
            out.append(f"> {body}" if body else ">")
            index += 1
        while out and out[-1] == ">":
            out.pop()
        out.append("")  # blank line closes the blockquote
    return "\n".join(out) + "\n"


def write_readme(dest_root: Path) -> None:
    """Write the export README from the quickstart plus a docs-site pointer."""
    quickstart = (ROOT / "docs/handover/quickstart.md").read_text(encoding="utf-8")
    body = admonitions_to_markdown(quickstart)
    # Quickstart links are relative to docs/handover/; from the repo root they
    # need the directory prefix.
    body = re.sub(r"\]\((?!https?://|/|#)([^)]+\.md)\)", r"](docs/handover/\1)", body)
    body = body.split("\n", 1)[1].lstrip("\n")  # drop its own "# Quickstart" title
    # Its sections nest one level deeper under the README's "## Quickstart".
    body = re.sub(r"^(#{2,5}) ", r"#\1 ", body, flags=re.MULTILINE)

    (dest_root / "README.md").write_text(
        "# ALTR Model\n"
        "\n"
        "Asset-level transition-risk valuation model: scenario pathways in,\n"
        "company and asset NPV impacts out.\n"
        "\n"
        "The full documentation lives in `docs/handover/` and reads either as\n"
        "plain markdown on GitHub or as a site:\n"
        "\n"
        "```bash\n"
        "pip install mkdocs-material\n"
        "python -m mkdocs serve\n"
        "```\n"
        "\n"
        "Start with the [user guide](docs/handover/user_guide.md) once the\n"
        "quickstart below has produced a run, and keep\n"
        "[troubleshooting](docs/handover/troubleshooting.md) to hand.\n"
        "\n"
        "## Quickstart\n"
        "\n" + body,
        encoding="utf-8",
    )


def extract_deliverable(archive: Path, raw: Path, name: str) -> None:
    """Extract ``name`` out of a zipped deliverable into ``raw``.

    ``prepare_inputs.py`` reads CSVs, so a copied-through archive would only
    surface as a confusing "deliverable not found" later. The member is written
    to ``raw / name`` by hand rather than with ``extractall``, so a member path
    inside the archive cannot decide where anything lands.
    """
    with zipfile.ZipFile(archive) as bundle:
        member = next(
            (m for m in bundle.namelist() if Path(m).name == name), None
        )
        if member is None:
            raise SystemExit(
                f"{archive}: no {name} inside (members: {bundle.namelist()[:10]})"
            )
        with bundle.open(member) as source, (raw / name).open("wb") as target:
            shutil.copyfileobj(source, target)


def stage_data(dest_root: Path, data_source: Path | None) -> list[str]:
    """Stage the deliverables into ``data/01_raw/``; returns what was staged."""
    raw = dest_root / "data" / "01_raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / ".gitkeep").touch()
    (dest_root / "data" / "05_model_input").mkdir(parents=True, exist_ok=True)
    (dest_root / "data" / "05_model_input" / ".gitkeep").touch()

    if data_source is None:
        return []
    if not data_source.is_dir():
        raise SystemExit(f"--data-source is not a directory: {data_source}")

    staged: list[str] = []
    for name in DELIVERABLES:
        candidates = [data_source / name, data_source / f"{name}.zip"]
        found = next((c for c in candidates if c.is_file()), None)
        if found is None:
            raise SystemExit(f"deliverable not found in {data_source}: {name}[.zip]")
        if found.suffix == ".zip":
            extract_deliverable(found, raw, name)
            staged.append(f"{name} (extracted from {found.name})")
            continue
        shutil.copy2(found, raw / found.name)
        staged.append(found.name)
    return staged


def build(dest: Path, data_source: Path | None) -> int:
    """Assemble the export at ``dest`` and return the sanitizer's exit code."""
    # Never clear the destination: the script only ever adds files, so pointing
    # --dest at a populated directory by mistake cannot destroy anything.
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(
            f"--dest is not empty: {dest}\n"
            f"Remove it yourself and re-run, e.g.  rm -rf {dest}"
        )
    dest.mkdir(parents=True, exist_ok=True)

    total = sum(copy_entry(entry, dest) for entry in read_allowlist(ALLOWLIST))
    write_readme(dest)
    staged = stage_data(dest, data_source)

    print(f"export: {total} files copied to {dest}", flush=True)  # noqa: T201
    print(  # noqa: T201
        f"export: staged into data/01_raw/: {', '.join(staged) or '(none)'}",
        flush=True,
    )

    return subprocess.run(
        [sys.executable, str(SANITIZER), str(dest)], check=False
    ).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", type=Path, required=True, help="Export directory")
    parser.add_argument(
        "--data-source",
        type=Path,
        default=None,
        help="Directory holding the three deliverables CSVs to stage into data/01_raw/",
    )
    args = parser.parse_args(argv)
    return build(args.dest.resolve(), args.data_source)


if __name__ == "__main__":
    raise SystemExit(main())
