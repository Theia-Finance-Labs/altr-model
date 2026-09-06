"""Comment-block attachment in scripts/gen_param_docs.py, plus a live check that
every key in conf/base carries a schema block (so the reference is complete)."""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gen_param_docs as g  # noqa: E402

SAMPLE = """\
# header comment without schema
# meaning:  top level thing
# unit:     bool
# default:  True because
#           reasons continue here
# source:   Someone 2020
# status:   live
top_key: True

block:
  # meaning:  nested thing
  # unit:     fraction [0, 1]
  # default:  0.5
  # source:   —
  # status:   gated-by:top_key
  inner: 0.5
  undocumented: 1
  deeper:
    # meaning:  three levels
    # unit:     int
    # default:  3
    # source:   —
    # status:   advanced
    leaf: 3

# meaning:  a list key
# unit:     list
# default:  two codes
# source:   —
# status:   advanced
codes:
  - AA
  - BB
"""


def test_blocks_attach_to_keys(tmp_path):
    f = tmp_path / "parameters.yml"
    f.write_text(SAMPLE)
    params = {p.key: p for p in g.parse_file(f, "user")}
    assert set(params) == {"top_key", "block.inner", "block.deeper.leaf", "codes"}
    assert params["top_key"].default == "True because reasons continue here"
    assert params["block.inner"].status == "gated-by:top_key"
    assert params["block.deeper.leaf"].unit == "int"
    assert params["codes"].value == "(block)"
    assert params["top_key"].line == 8


def test_every_shipped_key_is_documented():
    def leaves(d, pre=""):
        for k, v in d.items():
            if isinstance(v, dict) and k not in ("mcpr_value_factors", "mcpr_regional_value_factors", "plots"):
                yield from leaves(v, pre + k + ".")
            else:
                yield pre + k
    declared = set()
    for f in sorted((ROOT / "conf" / "base").glob("parameters*.yml")):
        declared |= set(leaves(yaml.safe_load(f.read_text()) or {}))
    documented = {p.key for p in g.collect(ROOT / "conf" / "base")}
    # plots.* are documented as one block on `plots`
    declared = {k.split(".plots.")[0] + ".plots" if ".plots." in k else k for k in declared}
    assert declared <= documented, sorted(declared - documented)


def test_renderers_run():
    params = g.collect(ROOT / "conf" / "base")
    md, page = g.render_md(params), g.render_html(params)
    assert md.startswith("<!-- GENERATED") and "| `shock_year` |" in md
    assert "ALTR parameters" in page and '"key": "dcf.discount_rate_shock"' in page
