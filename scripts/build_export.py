#!/usr/bin/env python
"""Assemble a shareable export of this repo from an explicit allowlist.

Usage::

    python scripts/build_export.py --dest ../altr-model-export-preview
    python scripts/build_export.py --dest ../altr-model-export-preview \
        --data-source "/path/to/deliverables"

Only paths listed in ``scripts/export_allowlist.txt`` are copied — assembly is
additive, never copy-then-delete, so a file that is not listed cannot leak by
being missed on a cleanup pass. On top of the allowlist a small set of
exclusions and copy-time rewrites strip the internal-only BigQuery ingestion
path, which externals do not have access to, and empty the example-company
list out of the exported configuration.

The destination is whatever ``--dest`` names — a directory, not a repository.
Under the 2026-09-01 owner ruling the end state is a SINGLE repo,
`Theia-Finance-Labs/altr-model` (this one), and this script is kept as an
internal utility for producing a sanitized copy on demand. It deliberately does
not name a destination repository: wiring one in is how a stale name ends up
pointing recipients at private code.

The last steps run ``sanitize_check.py`` and the licensing guard over the
assembled tree; a hit in either fails the build with a non-zero exit rather
than shipping.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

try:  # imported as `scripts.build_export` (the tests, and -m)
    from scripts.sanitize_check import COMPANY_ID_RE
except ImportError:  # run as `python scripts/build_export.py` — sys.path[0] is scripts/
    from sanitize_check import COMPANY_ID_RE

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ALLOWLIST = HERE / "export_allowlist.txt"
SANITIZER = HERE / "sanitize_check.py"
LICENCE_GUARD = ROOT / "tests" / "fixtures" / "test_fixture_ids_licensed.py"

#: Directory names pruned wherever they appear inside an allowlisted subtree.
SKIP_DIR_NAMES = frozenset({"__pycache__", ".ipynb_checkpoints", ".pytest_cache"})

#: Repo-relative paths excluded even though an allowlist entry covers them.
SKIP_RELATIVE = (
    # The maintainer-only BigQuery ingestion path. There is no `download_inputs`
    # pipeline here (the pre-migration exclusions named one); ingestion is this
    # single module, and externals have no warehouse access.
    "src/altr_model/bigquery_marts_downloader.py",
    # Tests the export tooling, which is itself internal-only (build_export.py
    # and sanitize_check.py are not allowlisted) — it would fail on import.
    "tests/unit/test_build_export.py",
    # Checks the fixture ids against the deliverables drop by path, which only
    # exists internally. Its job is done before the export is built.
    "tests/fixtures/test_fixture_ids_licensed.py",
)

# NOTE on `tests/test_run.py`: the pre-migration exclusion list carried it with
# the justification "full-input smoke test: needs the internal data drop". That
# is false here — it is a data-free pipeline-registration test that calls
# bootstrap_project + register_pipelines and asserts on pipeline names,
# namespaces, dataset contracts and REMOVED_DATASETS, opening no data file. It
# passes for a recipient, and it is exactly the kind of structural test they
# benefit from: it fails loudly if a pipeline is renamed, a namespace moves or
# a dataset contract drifts, none of which needs data to detect. (It used to be
# justified here as the guard against a re-introduced
# `frozen_capacity_at_retirement`; the Q4 port restored that dataset
# deliberately, so the test now asserts it EXISTS.) It SHIPS.

#: The three deliverables files staged into ``data/01_raw/`` by --data-source.
#: ``scenarios.csv`` is often delivered zipped; a zip is extracted, not copied.
DELIVERABLES = ("assets_forecasts.csv", "companies_ownerships.csv", "scenarios.csv")

#: Where the example-company list lives in the exported configuration.
COMPANY_IDS_CONF = "conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml"

_COMPANY_IDS_REPLACEMENT = """company_ids: []
# The example selection that ships internally is removed on export: an
# identifier list is licensed data, and an empty list means "all companies in
# your own input files". Put your own `company_id` values here to narrow a run;
# read the ones you can choose from off the `company_id` column of
# `data/05_model_input/companies_ownerships.csv`, or see the scenario catalog
# in docs/handover/scenario_catalog.md for how a run is scoped.
"""


class TransformError(SystemExit):
    """A copy-time rewrite did not find what it exists to remove."""


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


def empty_company_ids(text: str) -> str:
    """Replace the `company_ids:` list with an empty one plus an explanation.

    The internal default names 30 example companies. Identifiers are licensed
    data, so none of them leaves — not the 26 inside the deliverables universe
    and certainly not the 4 outside it. Emptying the list at export time is what
    keeps the sanitizer suppression-free on `conf/`: after this runs, the
    exported configuration carries no `CN_`/`CP_` literal at all.

    The block runs from `company_ids:` to the next line starting in column zero.
    Raises if it is not found or if an identifier survives — a transform that
    silently does nothing is how an unlicensed id ships.

    The survivor check uses the SANITIZER's `COMPANY_ID_RE` rather than a second
    copy of the pattern: a private copy is how this check and the gate that runs
    after it drift into recognising different id shapes.
    """
    lines = text.splitlines(keepends=True)
    start = next(
        (i for i, line in enumerate(lines) if line.startswith("company_ids:")), None
    )
    if start is None:
        raise TransformError(
            f"{COMPANY_IDS_CONF}: no `company_ids:` block found — the export "
            "transform that empties it cannot verify what it removed"
        )
    end = start + 1
    while end < len(lines) and (
        not lines[end].strip() or lines[end][0].isspace()
    ):
        end += 1

    result = "".join(lines[:start]) + _COMPANY_IDS_REPLACEMENT + "".join(lines[end:])
    leftover = COMPANY_ID_RE.search(result)
    if leftover is not None:
        raise TransformError(
            f"{COMPANY_IDS_CONF}: company id {leftover.group()} survives the "
            "export transform"
        )
    return result


#: The tail appended below the dependency stanzas of the exported Dockerfile.
#: An ENTRYPOINT (not CMD) so `docker run <image> --tags altrisk` appends
#: ordinary `kedro run` arguments.
_DOCKERFILE_TAIL = """\
# data/ is not baked into the image: mount your local data/ folder at runtime
# so the pipeline reads the staged inputs and writes its outputs back to disk:
#
#     docker build -t altr-model .
#     docker run --rm -v "$PWD/data:/app/data" altr-model
ENTRYPOINT ["kedro", "run"]
"""


def dockerfile_for_recipients(text: str) -> str:
    """Rewrite the Dockerfile so the delivered image runs the pipeline.

    The internal image launches the Streamlit batch runner, which is internal
    tooling and does not ship (docs/handover/batch_runs.md). Delivered as-is
    the image builds — build_export.py generates the README.md the early COPY
    needs — and then crashes at startup looking for notebooks/streamlit_app.py.

    Everything from the first Streamlit-only instruction onward is replaced
    with a `kedro run` tail, and the two `uv sync` stanzas above it lose their
    `--group streamlit` flag. Raises if a marker is missing or if `streamlit`
    survives anywhere in the result — a rewrite that silently no-ops is how a
    broken image ships.
    """
    marker = "# Don't run streamlit's first-launch prompt"
    cut = text.find(marker)
    if cut == -1:
        raise TransformError(
            "Dockerfile: streamlit tail marker not found — the export "
            "transform cannot see what it exists to replace"
        )
    head = text[:cut]
    if " --group streamlit" not in head:
        raise TransformError(
            "Dockerfile: no `--group streamlit` flag above the tail marker"
        )
    head = head.replace(" --group streamlit", "")
    head = head.replace(
        "needed to run the Streamlit batch-runner app", "needed to run the pipeline"
    )
    head = head.replace("(data/ and workspace/ are", "(data/ is")
    result = head + _DOCKERFILE_TAIL
    if "streamlit" in result.lower():
        raise TransformError("Dockerfile: `streamlit` survives the export transform")
    return result


def drop_streamlit_group(text: str) -> str:
    """Remove the `streamlit` dependency group from the exported pyproject.

    The group exists to install the batch-run Streamlit app, and the app does
    not ship — `notebooks/streamlit_app.py` is not allowlisted, and the
    Dockerfile transform above strips the same dependency out of the image.
    Left declared, `uv sync --group streamlit` succeeds for a recipient and
    installs a dependency with nothing to run.

    The group's own comment block goes with it. Raises if the group is not
    found or if `streamlit` survives — the same no-op guard the other
    transforms carry.
    """
    lines = text.splitlines(keepends=True)
    group = next(
        (i for i, line in enumerate(lines) if line.startswith("streamlit = [")), None
    )
    if group is None:
        raise TransformError(
            "pyproject.toml: no `streamlit = [` group found — the export "
            "transform that removes it cannot verify what it removed"
        )
    end = group + 1
    while end < len(lines) and lines[end].rstrip() != "]":
        end += 1
    if end == len(lines):
        raise TransformError("pyproject.toml: `streamlit` group is unterminated")

    start = group
    while start > 0 and lines[start - 1].lstrip().startswith("#"):
        start -= 1

    result = "".join(lines[:start]) + "".join(lines[end + 1 :])
    if "streamlit" in result.lower():
        raise TransformError(
            "pyproject.toml: `streamlit` survives the export transform"
        )
    return result


def _block_end(lines: list[str], start: int) -> int:
    """Index one past a `[[package]]` block: the next one, or end of file."""
    end = start + 1
    while end < len(lines) and not lines[end].startswith("[[package]]"):
        end += 1
    return end


def prune_streamlit_lock(text: str) -> str:
    """Remove the `streamlit` dependency group from the exported uv.lock.

    `drop_streamlit_group` takes the group out of the exported pyproject.toml,
    but the lock file is copied verbatim, so the export still shipped the
    group's declaration in both `[package.optional-dependencies]` and
    `[package.metadata.requires-dev]` plus the resolved `[[package]]` block —
    which contradicts the docs' "a delivered copy carries neither the app nor
    this group" and would leave the lock disagreeing with the pyproject it
    locks.

    Three shapes are cut: a `streamlit = [` list (multi-line or the single-line
    `[{ ... }]` form) and the `[[package]]` block named `streamlit`.

    Deliberately NOT pruned: streamlit's transitive-only dependencies (altair,
    pydeck, blinker, ...). Walking the resolution graph to decide which of them
    nothing else needs is the brittle surgery this avoids; an unreferenced
    package in a lock is inert, whereas a wrongly removed one breaks a sync.
    A regenerated lock (`uv lock` without the group) is the clean fix if this
    ever needs to be exact — it needs a network resolve, which an export build
    cannot assume.

    Raises if it finds nothing to cut or if `streamlit` survives — the same
    no-op guard the other transforms carry.
    """
    lines = text.splitlines(keepends=True)
    kept: list[str] = []
    index = 0
    cuts = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("streamlit = ["):
            end = index
            while end < len(lines) and not lines[end].rstrip().endswith("]"):
                end += 1
            if end == len(lines):
                raise TransformError("uv.lock: `streamlit = [` list is unterminated")
            index = end + 1
            cuts += 1
            continue
        if line.startswith("[[package]]") and any(
            probe.startswith('name = "streamlit"')
            for probe in lines[index + 1 : _block_end(lines, index)]
        ):
            index = _block_end(lines, index)
            cuts += 1
            continue
        kept.append(line)
        index += 1

    if not cuts:
        raise TransformError(
            "uv.lock: nothing named `streamlit` found — the export transform "
            "that removes it cannot verify what it removed"
        )
    result = "".join(kept)
    if "streamlit" in result.lower():
        raise TransformError("uv.lock: `streamlit` survives the export transform")
    return result


#: Copy-time rewrites, keyed by repo-relative path. Applied to the copy only —
#: the source repo stays the single source of truth and is never edited here.
#: Each transform raises if it does not find its target, so a rewrite cannot
#: quietly become a no-op when the file it targets is restructured.
#:
#: Three pre-migration transforms are gone, verified dead rather than renamed:
#: `conf/base/catalog.yml` carried four warehouse dataset blocks
#: (db_assets_forecasts, plant_ownerships, db_scenarios_pathways,
#: financial_averages) — this catalog has NONE of them, only its ten real
#: datasets; `conf/fixture/catalog.yml` carried a BigQuery ibis note this
#: fixture catalog does not have; and `pipeline_registry.py` carried a
#: `download_inputs` docstring paragraph that does not exist here.
TRANSFORMS = {
    COMPANY_IDS_CONF: empty_company_ids,
    "Dockerfile": dockerfile_for_recipients,
    "pyproject.toml": drop_streamlit_group,
    "uv.lock": prune_streamlit_lock,
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
        "uv sync --group docs\n"
        "uv run mkdocs serve\n"
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


def run_licence_guard(dest: Path) -> int:
    """Run the licensing guard against the assembled tree.

    The guard fails rather than skips when `ALTR_DELIVERABLES_DIR` is unset, so
    a build without the drop mounted cannot pass by not looking. This is the
    other half of the boundary `sanitize_check.py` guards: the sanitizer knows
    what an identifier LOOKS like, this knows which ones are licensed.
    """
    env = dict(os.environ, ALTR_EXPORT_ROOT=str(dest))
    return subprocess.run(
        [
            sys.executable, "-m", "pytest", str(LICENCE_GUARD),
            "-q", "-p", "no:cacheprovider", "-o", "addopts=",
        ],
        check=False,
        env=env,
        cwd=str(ROOT),
    ).returncode


def build(dest: Path, data_source: Path | None) -> int:
    """Assemble the export at ``dest`` and return the gate's exit code."""
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

    sanitizer_code = subprocess.run(
        [sys.executable, str(SANITIZER), str(dest)], check=False
    ).returncode
    if sanitizer_code != 0:
        return sanitizer_code
    return run_licence_guard(dest)


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
