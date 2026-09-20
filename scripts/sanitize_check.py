#!/usr/bin/env python
"""Grep an assembled export tree for anything that must not leave the machine.

Usage::

    python scripts/sanitize_check.py <export-dir>

Prints ``file:line`` for every hit and exits 1 if there is at least one; exits 0
on a clean tree. ``build_export.py`` runs this as its final gate, so a hit fails
the export rather than shipping it.

Two things are deliberately NOT scanned: ``data/01_raw/`` (the delivered input
payloads, which the recipient already has) and binary files (PDF, images,
archives, parquet), which have no reviewable line numbers.

Every suppression is an explicit ``Suppression`` entry below with a written
justification. Nothing is suppressed silently.
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

#: A word naming a secret, bounded by non-alphanumerics so `API_TOKEN` and
#: `secret_key` count while `key` buried inside a base64 blob does not.
_SECRET_WORD = re.compile(
    r"(?<![A-Za-z0-9])(?:key|token|secret|password)(?![A-Za-z0-9])", re.IGNORECASE
)
#: A long opaque-looking run of identifier characters.
_LONG_RUN = re.compile(r"[A-Za-z0-9_\-]{28,}")
#: One `_`/`-` separated segment that is just a word.
_WORDLIKE = re.compile(r"[A-Za-z]{2,}\Z")


def looks_like_secret(line: str) -> bool:
    """True for a long opaque run on a line that also names a secret.

    Long ``snake_case`` identifiers are the false positive this codebase is full
    of, so a run whose ``_``/``-`` segments are all plain words counts as code,
    not as a credential.
    """
    if not _SECRET_WORD.search(line):
        return False
    for run in _LONG_RUN.finditer(line):
        segments = [seg for seg in re.split(r"[_\-]", run.group()) if seg]
        if not all(_WORDLIKE.match(seg) for seg in segments):
            return True
    return False


#: Patterns hunted for, as ``name -> predicate(line)``. Word boundaries keep the
#: short names from matching inside base64 blobs and hashes.
PATTERNS: dict[str, Callable[[str], object]] = {
    "jakub": re.compile(r"\bjakub\b", re.IGNORECASE).search,
    "hummusking": re.compile(r"\bhummusking\w*", re.IGNORECASE).search,
    "theia-dropbox": re.compile(r"Theia\s+Dropbox", re.IGNORECASE).search,
    "users-path": re.compile(r"/Users/").search,
    "bigquery": re.compile(r"\bbigquery\b", re.IGNORECASE).search,
    "gcp": re.compile(r"\bgcp\b", re.IGNORECASE).search,
    "credentials": re.compile(r"\bcredentials?\b", re.IGNORECASE).search,
    "bertrand": re.compile(r"\bbertrand\w*", re.IGNORECASE).search,
    "private-key": re.compile(r"BEGIN[A-Z ]*PRIVATE KEY").search,
    "secret-token": looks_like_secret,
    # Licensed company identifiers from the deliverables universe. Legitimate
    # inside the data payload the recipient is licensed for; a leak anywhere
    # else (docs, comments, notebooks), where it would ship ids for companies
    # outside that licence. Scoped by the EXCEPTIONS below, not by dropping it.
    # Lookarounds, not \b: "_" is a word character, so \b never matches between
    # it and a letter and the anchored form missed every composite id
    # ("NEW_CN_<id>_Power_HydroCap_EU"). Treat "_" as a separator instead.
    "company-id": re.compile(
        r"(?<![A-Za-z0-9])(?:CN|CP)_\d{8,}(?![0-9])"
    ).search,
}

#: Directories never scanned, relative to the export root.
SKIP_TREES = ("data/01_raw",)

#: Suffixes with no reviewable text content.
BINARY_SUFFIXES = frozenset(
    {
        ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
        ".xlsx", ".xls", ".zip", ".gz", ".parquet", ".pyc", ".so", ".woff",
        ".woff2", ".ttf",
    }
)


@dataclass(frozen=True)
class Suppression:
    """One allowlisted suppression: which file, which pattern, and why."""

    path_glob: str
    pattern: str
    why: str


#: Known-good hits. Each one has been read and judged safe to ship.
EXCEPTIONS: tuple[Suppression, ...] = (
    Suppression(
        ".gitignore",
        "credentials",
        "Ignore rules that keep credential files OUT of git — the words are the "
        "guard, not a leak.",
    ),
    Suppression(
        "pyproject.toml",
        "bigquery",
        "`ibis-framework[bigquery]` is a real pinned dependency; removing it "
        "would change the resolved environment. BigQuery is a public product "
        "name, not an internal reference.",
    ),
    Suppression(
        "pyproject.toml",
        "bertrand",
        "Package author attribution for the original author. Kept deliberately; "
        "the contact address is a judgement call for the repo owner, not the "
        "export script.",
    ),
    Suppression(
        "uv.lock",
        "bigquery",
        "Public PyPI package metadata for the optional `bigquery` dependency "
        "group (google-cloud-bigquery, google-cloud-bigquery-storage) — 13 "
        "dependency-name hits, no project, dataset or account identifier. The "
        "lock file must stay byte-identical or the resolved environment "
        "changes. RE-KEYED from the pre-migration `poetry.lock` entry: same "
        "pattern, same justification, the lock file this tree actually has.",
    ),
    # The pre-migration `poetry.lock` + `gcp` suppression is NOT re-keyed:
    # `gcp` has ZERO word-boundary hits in uv.lock (the grpcio-gcp / gcsfs
    # extras that justified it are not in this dependency tree). A suppression
    # matching nothing is a standing invitation to ship one, so it is dropped
    # rather than carried across.
    Suppression(
        "conf/base/catalog.yml",
        "bigquery",
        "Comment telling the reader where the three input CSVs come from — "
        "maintainers generate them from the warehouse, everyone else receives "
        "them. Load-bearing orientation for a recipient, and it names no "
        "project, dataset or account. The generator module itself is excluded "
        "from the export (SKIP_RELATIVE).",
    ),
    # The pre-migration `inputs_processing/nodes.py` + `bigquery` suppression is
    # dropped, not re-pathed: the input-preparation modules on this tree carry
    # no `bigquery` mention at all (verified across src/). Its only live
    # counterpart is bigquery_marts_downloader.py, which does not ship.
    Suppression(
        "tests/fixtures/data/*.csv",
        "company-id",
        "The committed input slice is licensed deliverables data: its "
        "`company_id` column is the payload, not a leak. The delivered payload "
        "under data/01_raw/ is skipped wholesale (SKIP_TREES) for the same "
        "reason; tests/fixtures/test_fixture_ids_licensed.py checks these ids "
        "stay inside the licensed universe.",
    ),
    Suppression(
        "tests/integration/test_fixture_run.py",
        "company-id",
        "Golden values pinned per company from the fixture slice — the ids are "
        "the assertion keys, and they come from that same licensed slice.",
    ),
    Suppression(
        "tests/fixtures/data/*.csv",
        "bertrand",
        "Real asset names in the committed input slice, e.g. 'L'Etang Bertrand "
        "solar farm' — a public French power plant, not a colleague.",
    ),
)


def is_excepted(rel_path: str, pattern: str) -> bool:
    """True if this (file, pattern) pair is explicitly allowlisted above."""
    return any(
        exc.pattern == pattern and fnmatch(rel_path, exc.path_glob)
        for exc in EXCEPTIONS
    )


def is_scannable(path: Path) -> bool:
    """True for text files worth grepping (binaries have no useful line hits)."""
    if path.suffix.lower() in BINARY_SUFFIXES:
        return False
    try:
        return b"\x00" not in path.open("rb").read(8192)
    except OSError:
        return False


def scan_file(path: Path, rel_path: str) -> list[str]:
    """Return ``file:line: [pattern] text`` for every non-excepted hit."""
    hits: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:  # unreadable file is itself a problem worth reporting
        return [f"{rel_path}:0: [unreadable] {exc}"]
    for lineno, line in enumerate(text.splitlines(), start=1):
        for name, matches in PATTERNS.items():
            if matches(line) and not is_excepted(rel_path, name):
                hits.append(f"{rel_path}:{lineno}: [{name}] {line.strip()[:160]}")
    return hits


def scan_tree(root: Path) -> list[str]:
    """Scan every scannable file under ``root``; returns all hits."""
    return scan_tree_with_skips(root)[0]


def scan_tree_with_skips(root: Path) -> tuple[list[str], list[str]]:
    """Scan ``root``; return (hits, binary files that could not be scanned).

    The second list is what keeps a "clean" verdict honest: binaries carry no
    reviewable line numbers, so they are never grepped, and a gate that reports
    clean without saying what it never looked at overclaims.
    """
    hits: list[str] = []
    unscanned: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(root).as_posix()
        if any(rel_path == t or rel_path.startswith(f"{t}/") for t in SKIP_TREES):
            continue
        if not is_scannable(path):
            unscanned.append(rel_path)
            continue
        hits.extend(scan_file(path, rel_path))
    return hits, unscanned


def selftest() -> int:
    """Prove the gate still fires: plant hits in a throwaway tree and scan it."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "leak.py").write_text(
            'HOME = "/Users/someone/secret-project"\n'
            'API_TOKEN = "sk_live_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5"\n'
            "# - CN_1234567890123456789\n",
            encoding="utf-8",
        )
        (root / ".gitignore").write_text("credentials/\n", encoding="utf-8")
        (root / "data" / "01_raw").mkdir(parents=True)
        (root / "data" / "01_raw" / "payload.csv").write_text(
            "name\n/Users/someone/x\n", encoding="utf-8"
        )
        hits = scan_tree(root)

    patterns = {hit.split("[", 1)[1].split("]", 1)[0] for hit in hits}
    assert "users-path" in patterns, f"internal path not detected: {hits}"
    assert "secret-token" in patterns, f"secret token not detected: {hits}"
    assert "company-id" in patterns, f"company id not detected: {hits}"
    assert not any(h.startswith(".gitignore") for h in hits), "exception not applied"
    assert not any("01_raw" in h for h in hits), "data/01_raw should not be scanned"
    print(f"sanitize: selftest OK ({len(hits)} planted hits found)")  # noqa: T201
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "export_dir", type=Path, nargs="?", help="Assembled export tree to scan"
    )
    parser.add_argument(
        "--selftest", action="store_true", help="Check the patterns still fire, then exit"
    )
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()
    if args.export_dir is None:
        parser.error("export_dir is required (or pass --selftest)")

    root: Path = args.export_dir
    if not root.is_dir():
        print(f"sanitize: not a directory: {root}", file=sys.stderr)  # noqa: T201
        return 2

    hits, unscanned = scan_tree_with_skips(root)
    if hits:
        print(f"sanitize: {len(hits)} hit(s) in {root}", file=sys.stderr)  # noqa: T201
        for hit in hits:
            print(hit, file=sys.stderr)  # noqa: T201
        return 1
    print(f"sanitize: clean ({root})")  # noqa: T201
    if unscanned:
        # Never silently: a binary shipping unreviewed is the gate's blind spot,
        # so name every one rather than let "clean" imply the tree was read.
        print(  # noqa: T201
            f"sanitize: {len(unscanned)} binary file(s) NOT scanned - review by hand:"
        )
        for rel_path in unscanned:
            print(f"  {rel_path}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
