"""The batch runner must produce a complete study parameter set: every base
key present, overrides applied, scenario pair injected, nothing left behind
after cleanup. Guards the 2026-09-01 incident where partial per-file
overrides in conf/local silently replaced conf/base for five days."""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "notebooks"))
import run_all_scenarios_comparison as sweep  # noqa: E402

BASE = Path(__file__).resolve().parents[1] / "conf" / "base"


def test_study_overrides_are_complete_and_cleaned(tmp_path):
    study = tmp_path / "conf" / "study"
    (tmp_path / "conf" / "base").mkdir(parents=True)
    for f in BASE.glob("parameters*.yml"):
        (tmp_path / "conf" / "base" / f.name).write_text(f.read_text())

    variant = sweep.CONFIG_VARIANTS["vanilla"]
    sweep.write_param_overrides(variant, study)
    sweep.write_catalog_override(Path("/x/IMAGE.csv"), "AR6_b", "AR6_t", study)

    params = yaml.safe_load((study / sweep.STUDY_PARAMS_FILE).read_text())
    base = sweep._load_base_params(BASE)

    assert set(base) <= set(params), "override dropped a base key"
    assert params["enable_mcpr"] is False
    assert params["dcf"]["discount_rate_baseline"] == 0.07  # sibling kept
    assert params["baseline_scenario"] == "AR6_b" and params["target_scenario"] == "AR6_t"
    assert yaml.safe_load((study / "catalog.yml").read_text())["downloaded_scenarios"]["filepath"] == "/x/IMAGE.csv"

    sweep.cleanup_overrides(study)
    assert list(study.iterdir()) == []
