"""Generate the parameters reference page from the annotated YAML in `conf/base/`.

The YAML files are the single source of truth: the comment lines directly above
a key (plus its trailing inline comment) *are* that key's documentation, so the
page cannot drift from the configuration it describes.

Usage (from the repository root):

    python scripts/gen_param_docs.py

Re-run it whenever a parameter is added, removed, re-annotated or moved between
files, and commit the regenerated page.
"""

from __future__ import annotations

import argparse
import dataclasses
import re
from dataclasses import dataclass
from pathlib import Path

#: `# ── Title ──` — a titled section banner.
SECTION = re.compile(r"^#\s*[─=]{2,}\s*(.+?)\s*[─=]{2,}\s*$")
#: `# =========` — a bare rule; a single buffered line above it is its title.
RULE = re.compile(r"^#\s*[─=-]{3,}\s*$")
#: A key at indent 0, e.g. `shock_year: 2033`.
KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(.*)$")

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONF = REPO_ROOT / "conf" / "base"
DEFAULT_OUT = REPO_ROOT / "docs" / "handover" / "parameters.md"

PREAMBLE = """# Parameters reference

!!! warning "GENERATED — do not edit this page"
    Written by `scripts/gen_param_docs.py` from the YAML files in `conf/base/`.
    Edit the file named in each section heading — the comment lines above a key
    are its documentation here — then regenerate:

    ```bash
    python scripts/gen_param_docs.py
    ```

Kedro merges every `conf/base/parameters*.yml` into one flat namespace, so each
key below is defined in exactly one file (a duplicate breaks the run) and any of
them can be overridden per environment in `conf/<env>/parameters*.yml`.
`conf/base/parameters.yml` holds the run configuration you normally touch;
the per-pipeline files hold the advanced, methodology-internal knobs.

Only keys at the top level of a file are listed. A nested block (`dcf:`,
`reporting:`, `mcpr_regional_value_factors:`, `staggered_shock:`) appears once,
with an empty default — its sub-keys are annotated in the YAML file itself and
are addressed in pipelines as `params:<block>.<sub_key>`.
"""


@dataclass(frozen=True)
class Param:
    """One documented top-level parameter."""

    key: str
    default: str
    section: str
    description: tuple[str, ...]


def _split_inline_comment(rest: str) -> tuple[str, str]:
    """Split a YAML value from its trailing `#` comment, ignoring quoted `#`."""
    quote = ""
    for i, char in enumerate(rest):
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "#" and (i == 0 or rest[i - 1].isspace()):
            return rest[:i].strip(), rest[i + 1 :].strip()
    return rest.strip(), ""


def _comment_text(line: str) -> str:
    """The text of a comment line, without its leading `#`."""
    return line.lstrip("#").strip()


def parse_params(text: str) -> list[Param]:
    """Parse annotated YAML text into the top-level parameters it documents.

    Comment lines accumulate until a key claims them; a blank line, a section
    banner or an indented value discards the buffer, which keeps file headers
    and nested-block bodies out of the next key's description.
    """
    params: list[Param] = []
    buffer: list[str] = []
    section = ""
    last: int | None = None  # index of the key an indented comment continues

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            buffer, last = [], None
            continue
        if line.startswith("#"):
            if RULE.match(line):  # checked first: a bare rule has no title
                if len(buffer) == 1:
                    section = buffer[0]
                buffer, last = [], None
                continue
            titled = SECTION.match(line)
            if titled:
                section, buffer, last = titled.group(1), [], None
                continue
            buffer.append(_comment_text(line))
            last = None
            continue
        if stripped.startswith("#"):
            # Indented comment: continues the key above it, if any.
            if last is not None:
                param = params[last]
                params[last] = dataclasses.replace(
                    param, description=param.description + (_comment_text(stripped),)
                )
            continue
        key = KEY.match(line)
        if key is None:  # indented value, list item, document marker
            buffer, last = [], None
            continue
        value, inline = _split_inline_comment(key.group(2))
        description = tuple(buffer) + ((inline,) if inline else ())
        params.append(
            Param(
                key=key.group(1),
                default=value,
                section=section,
                description=description,
            )
        )
        buffer, last = [], len(params) - 1
    return params


def collect(conf_dir: Path) -> dict[str, list[Param]]:
    """Parse every `parameters*.yml` in `conf_dir`, entry point file first."""
    files = sorted(conf_dir.glob("parameters*.yml"))
    entry = conf_dir / "parameters.yml"
    ordered = ([entry] if entry in files else []) + [f for f in files if f != entry]
    collected: dict[str, list[Param]] = {}
    for path in ordered:
        params = parse_params(path.read_text())
        if params:
            collected[path.relative_to(REPO_ROOT).as_posix()] = params
    return collected


def _cell(lines: tuple[str, ...]) -> str:
    """Render comment lines as one table cell, preserving the author's lines."""
    return "<br>".join(line.replace("|", "\\|") for line in lines) or "—"


def render_page(files: dict[str, list[Param]]) -> str:
    """Render the full markdown page: one table per source file."""
    parts = [PREAMBLE]
    for source, params in files.items():
        parts.append(f"## `{source}`\n")
        parts.append("| Key | Default | Section | Description |")
        parts.append("| --- | --- | --- | --- |")
        for param in params:
            default = f"`{param.default}`" if param.default else "—"
            parts.append(
                f"| `{param.key}` | {default} | {param.section or '—'} | {_cell(param.description)} |"
            )
        parts.append("")
    return "\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--conf",
        type=Path,
        default=DEFAULT_CONF,
        help="Directory holding parameters*.yml",
    )
    ap.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help="Markdown page to write"
    )
    args = ap.parse_args()
    files = collect(args.conf)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_page(files))
    total = sum(len(params) for params in files.values())
    print(f"wrote {args.out} — {total} parameters from {len(files)} files")  # noqa: T201


if __name__ == "__main__":
    main()
