"""Unit tests for the parameters-reference generator.

Pinned behaviours:

* consecutive ``#`` comment lines directly above a top-level ``key:`` become
  that key's description, and a blank line breaks the association (so file
  headers are not attributed to the first key);
* a banner line (``# ── Title ──`` or a title fenced by ``# ====`` rules) sets
  the section every following key belongs to;
* the trailing inline comment on a key line, and any indented comment lines
  continuing it, are appended to that key's description;
* only keys at indent 0 are documented — a nested block is listed once, with
  its sub-keys left to the YAML file itself;
* rendering escapes table-breaking pipes and keeps one table per source file.
"""

from scripts.gen_param_docs import Param, parse_params, render_page

SAMPLE = """\
# ==================================================================================
# Sample run configuration
# ==================================================================================
# Header prose that documents the file as a whole, not any single key.

# ── Scenario selection ────────────────────────────────────────────────────────────
# The scenario the run compares against.
# Values: any name in the scenarios input.
baseline_scenario: "AR6_X"  # inline note

shock_year: 2033
alignment_year: 2038  # first inline line
                      # continuation of the inline comment

# ── Advanced ──
dcf:
  discount_rate: 0.07  # not a top-level key
"""


FENCED = """\
# ==================================================================================
# Fenced title
# ==================================================================================
# key doc
some_key: 1
"""


def parsed() -> dict[str, Param]:
    return {p.key: p for p in parse_params(SAMPLE)}


def test_only_top_level_keys_are_documented():
    assert [p.key for p in parse_params(SAMPLE)] == [
        "baseline_scenario",
        "shock_year",
        "alignment_year",
        "dcf",
    ]


def test_comment_block_attaches_to_the_next_key():
    param = parsed()["baseline_scenario"]
    assert param.description == (
        "The scenario the run compares against.",
        "Values: any name in the scenarios input.",
        "inline note",
    )
    assert param.default == '"AR6_X"'


def test_blank_line_breaks_the_association():
    # The file header sits above a blank line, so it belongs to no key, and
    # `shock_year` (also preceded by a blank line) documents nothing.
    assert parsed()["shock_year"].description == ()
    assert "Header prose" not in " ".join(parsed()["baseline_scenario"].description)


def test_indented_comment_continues_the_inline_comment():
    assert parsed()["alignment_year"].description == (
        "first inline line",
        "continuation of the inline comment",
    )


def test_banner_lines_set_the_section():
    params = parsed()
    assert params["baseline_scenario"].section == "Scenario selection"
    assert params["shock_year"].section == "Scenario selection"
    assert params["dcf"].section == "Advanced"


def test_bare_rule_is_not_a_section_title():
    # A `# ====` rule carries no title; the line it fences does.
    (param,) = parse_params(FENCED)
    assert param.section == "Fenced title"
    assert param.description == ("key doc",)


def test_nested_block_has_no_scalar_default():
    assert parsed()["dcf"].default == ""


def test_render_page_groups_by_file_and_escapes_pipes():
    params = [Param(key="a", default="1", section="S", description=("x | y",))]
    page = render_page({"conf/base/parameters.yml": params})
    assert "## `conf/base/parameters.yml`" in page
    assert "| `a` |" in page
    assert "x \\| y" in page
    assert "GENERATED" in page
