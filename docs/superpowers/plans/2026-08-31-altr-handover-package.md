# ALTR Handover Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn crispy-kedro's ALTR pipeline into a clean, deeply-refactored, fully-documented package that a scripted allowlist export assembles into the private `altr-model` repo for external collaborators.

**Architecture:** All work happens in an isolated git worktree on branch `feat/handover-package` (off `feat/altr-npv-fixes`) so the model runs in the main working tree are never touched. A fixture-slice regression harness is built first and re-run after every refactor task; the three oversized node files are split into focused modules behind re-export shims (strictly behavior-preserving); docs are a mkdocs-material site; `scripts/build_export.py` assembles the export from an allowlist and a sanitizer gate.

**Tech Stack:** Python 3.10, Kedro 0.19.12, pandas, pytest, mkdocs-material, ruff.

**Spec:** `docs/superpowers/specs/2026-08-31-altr-handover-package-design.md`

## Global Constraints

- **Behavior-preserving:** no logic changes anywhere. Anything that looks like a bug goes into `docs/superpowers/plans/implementation-notes-handover.md`, never fixed inline.
- **Never delete files** in the internal repo; the export is allowlist-assembled, so exclusion ≠ deletion.
- Module size target 200–400 lines, hard max 800.
- Python 3.10 only (3.11+ unsupported). Venv at `.venv/` (worktree gets its own).
- Pipeline names, dataset names, and tags are frozen — no renames.
- Kedro merges every `conf/<env>/parameters*.yml`; a key may exist in exactly one base file (duplicates break the run).
- Every task ends with the fixture regression command passing (once Task 2 exists): `.venv/bin/python -m pytest tests/integration/test_fixture_run.py -q` — except Phase 2 parallel tasks, which run only their own unit tests; the Phase 2 barrier task runs the fixture regression once for all three.
- Commit after every task, conventional commits, no attribution footer.
- The worktree has no `data/` (gitignored). Fixture data is built once from the main tree's `data/05_model_input/` and committed under `tests/fixtures/data/` (keep < 25 MB).
- Known blockers to note, not fix: carbon-price scenario data fix pending (colleague); ownership-tier check flagged in `notebooks/prepare_new_inputs.py`.

---

### Task 0: Worktree setup

**Files:** none created in-repo (worktree + venv).

**Interfaces:**
- Produces: worktree at `/Users/jakub/Documents/repos/crispy-kedro-handover` on branch `feat/handover-package`, with a working `.venv`.

- [ ] **Step 1: Create worktree and branch**

```bash
cd /Users/jakub/Documents/repos/crispy-kedro
git worktree add ../crispy-kedro-handover -b feat/handover-package feat/altr-npv-fixes
```

- [ ] **Step 2: Create venv and install** (poetry not on PATH; reuse the main tree's interpreter version)

```bash
cd /Users/jakub/Documents/repos/crispy-kedro-handover
/Users/jakub/Documents/repos/crispy-kedro/.venv/bin/python -m venv .venv
.venv/bin/pip install -q -e . pytest pytest-cov ruff mkdocs-material
```

If `pip install -e .` fails (poetry-only build), fall back to sharing the main venv read-only: run all commands with `/Users/jakub/Documents/repos/crispy-kedro/.venv/bin/python` and set `PYTHONPATH=/Users/jakub/Documents/repos/crispy-kedro-handover/src`. Record which path was taken in implementation notes.

- [ ] **Step 3: Smoke check**

Run: `.venv/bin/python -c "import crispy_kedro, kedro; print(kedro.__version__)"`
Expected: `0.19.12`

---

### Task 1: Fixture slice builder

**Files:**
- Create: `tests/fixtures/make_fixture_slice.py`
- Create: `tests/fixtures/data/` (generated CSVs, committed)
- Test: `tests/fixtures/test_fixture_slice.py`

**Interfaces:**
- Consumes: main tree `data/05_model_input/{downloaded_assets.csv,downloaded_companies.csv}` and the scenarios CSV named by `conf/base/catalog.yml` `downloaded_scenarios.filepath`.
- Produces: `tests/fixtures/data/downloaded_assets.csv`, `downloaded_companies.csv`, `downloaded_scenarios.csv` — schema-identical slices; ~5 companies, scenario pair `AR6_REMIND-MAgPIE 2.1-4.2_EN_NPi2020_3000` / `..._EN_NPi2020_500`.

- [ ] **Step 1: Write the failing test**

```python
# tests/fixtures/test_fixture_slice.py
# NOTE: this file ships in the export — no absolute internal paths anywhere.
# The full-inputs comparison only runs where ALTR_FULL_INPUTS is set (internal).
import os
from pathlib import Path

import pandas as pd
import pytest

DATA = Path(__file__).parent / "data"
FULL = Path(os.environ.get("ALTR_FULL_INPUTS", ""))

def test_fixture_files_exist_and_are_small():
    for name in ("downloaded_assets.csv", "downloaded_companies.csv", "downloaded_scenarios.csv"):
        f = DATA / name
        assert f.exists(), f"missing {name}"
        assert f.stat().st_size < 25_000_000

@pytest.mark.skipif(not FULL.is_dir(), reason="ALTR_FULL_INPUTS not set (external machine)")
def test_fixture_schemas_match_full_inputs():
    # Columns must be identical to the full inputs the pipeline consumes.
    for name in ("downloaded_assets.csv", "downloaded_companies.csv"):
        fix_cols = list(pd.read_csv(DATA / name, nrows=0).columns)
        full_cols = list(pd.read_csv(FULL / name, nrows=0).columns)
        assert fix_cols == full_cols, name

def test_fixture_scenarios_contain_both_pair_members():
    df = pd.read_csv(DATA / "downloaded_scenarios.csv")
    col = "scenario" if "scenario" in df.columns else "scenario_name"
    names = set(df[col].unique())
    assert any("EN_NPi2020_3000" in n for n in names)
    assert any("EN_NPi2020_500" in n for n in names)

def test_fixture_companies_have_assets():
    comp = pd.read_csv(DATA / "downloaded_companies.csv")
    assets = pd.read_csv(DATA / "downloaded_assets.csv")
    assert set(comp["asset_id"]) <= set(assets["asset_id"])
    assert comp["company_id"].nunique() <= 8
```

- [ ] **Step 2: Run to verify it fails** — `.venv/bin/python -m pytest tests/fixtures/test_fixture_slice.py -q` → FAIL (missing files).

- [ ] **Step 3: Write the builder**

```python
# tests/fixtures/make_fixture_slice.py
"""Build a small, schema-identical slice of the model inputs for fast regression runs.

Reads the FULL inputs from the main working tree (source of truth for current
data) and writes the slice into tests/fixtures/data/, which is committed.
Selection: the N companies with the fewest assets that still span >=3
technologies, one scenario pair. Re-run whenever upstream inputs change.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "data"
SCENARIO_SUBSTRINGS = ("EN_NPi2020_3000", "EN_NPi2020_500")
N_COMPANIES = 5


def pick_companies(companies: pd.DataFrame, assets: pd.DataFrame) -> list[str]:
    merged = companies.merge(assets[["asset_id", "technology"]].drop_duplicates(), on="asset_id")
    stats = merged.groupby("company_id").agg(n_assets=("asset_id", "nunique"), n_tech=("technology", "nunique"))
    ranked = stats.sort_values(["n_tech", "n_assets"], ascending=[False, True])
    return ranked.head(N_COMPANIES).index.tolist()


def build(source: Path) -> None:
    assets = pd.read_csv(source / "downloaded_assets.csv", low_memory=False)
    companies = pd.read_csv(source / "downloaded_companies.csv", low_memory=False)
    chosen = pick_companies(companies, assets)
    comp_slice = companies[companies["company_id"].isin(chosen)]
    asset_slice = assets[assets["asset_id"].isin(comp_slice["asset_id"])]

    scen_path = source / "downloaded_scenarios.csv"
    scen = pd.read_csv(scen_path, low_memory=False)
    col = "scenario" if "scenario" in scen.columns else "scenario_name"
    mask = scen[col].apply(lambda n: any(s in str(n) for s in SCENARIO_SUBSTRINGS))
    scen_slice = scen[mask]

    OUT.mkdir(parents=True, exist_ok=True)
    asset_slice.to_csv(OUT / "downloaded_assets.csv", index=False)
    comp_slice.to_csv(OUT / "downloaded_companies.csv", index=False)
    scen_slice.to_csv(OUT / "downloaded_scenarios.csv", index=False)
    print(f"fixture: {comp_slice['company_id'].nunique()} companies, "
          f"{asset_slice['asset_id'].nunique()} assets, {scen_slice[col].nunique()} scenarios")


if __name__ == "__main__":
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path,
                    default=os.environ.get("ALTR_FULL_INPUTS"),
                    help="Directory with full downloaded_* inputs (or set ALTR_FULL_INPUTS)")
    args = ap.parse_args()
    if not args.source:
        raise SystemExit("pass --source or set ALTR_FULL_INPUTS")
    build(Path(args.source))
```

Note: the full scenarios file in the main tree may live at the repo-root path named in `conf/base/catalog.yml` (`downloaded_scenarios_witch_full.csv`) rather than `data/05_model_input/downloaded_scenarios.csv`. Resolve the actual path from the catalog before running; pass it via `--source`-relative symlink or adjust the `scen_path` line to read the catalog value. Record the resolution in implementation notes.

- [ ] **Step 4: Run builder, then tests** — `.venv/bin/python tests/fixtures/make_fixture_slice.py` then `.venv/bin/python -m pytest tests/fixtures/test_fixture_slice.py -q` → 4 passed. If the scenarios slice exceeds 25 MB, keep only columns the pipeline reads plus the pair rows, and note it.

- [ ] **Step 5: Commit** — `git add tests/fixtures && git commit -m "test: add fixture slice builder and data for fast regression runs"`

---

### Task 2: Fixture regression harness (`conf/fixture` env + integration test)

**Files:**
- Create: `conf/fixture/catalog.yml`, `conf/fixture/parameters_inputs_processing.yml`
- Test: `tests/integration/test_fixture_run.py`, `tests/integration/__init__.py`

**Interfaces:**
- Consumes: fixture CSVs from Task 1.
- Produces: `kedro run --env fixture --tags altrisk` completes on the slice; `tests/integration/test_fixture_run.py::test_full_pipeline_on_fixture` is THE regression gate every later task runs.

- [ ] **Step 1: Write the fixture env catalog** — override only the three input datasets and route all outputs under `data/fixture_run/` so a fixture run never touches real run outputs:

```yaml
# conf/fixture/catalog.yml
# Fixture environment: tiny committed input slice, outputs quarantined
# under data/fixture_run/. Everything else inherits from base.
downloaded_scenarios:
  type: pandas.CSVDataset
  filepath: tests/fixtures/data/downloaded_scenarios.csv

downloaded_assets:
  type: pandas.CSVDataset
  filepath: tests/fixtures/data/downloaded_assets.csv

downloaded_companies:
  type: pandas.CSVDataset
  filepath: tests/fixtures/data/downloaded_companies.csv
```

Then enumerate every OUTPUT dataset in `conf/base/catalog.yml` that has a `filepath:` and re-declare it here with the same type and `filepath:` rewritten to `data/fixture_run/<original relative path>`. Do this exhaustively (read base catalog, list every persisted dataset) — any dataset left un-overridden writes into the real `data/` tree, which is the one thing this env must prevent.

- [ ] **Step 2: Write fixture parameters** — `conf/fixture/parameters_inputs_processing.yml`:

```yaml
baseline_scenario: "AR6_REMIND-MAgPIE 2.1-4.2_EN_NPi2020_3000"
target_scenario: "AR6_REMIND-MAgPIE 2.1-4.2_EN_NPi2020_500"
company_ids: []   # slice already filtered
```

- [ ] **Step 3: Write the failing integration test**

```python
# tests/integration/test_fixture_run.py
"""THE regression gate: full pipeline on the committed fixture slice.

Run after every refactor task. Asserts completion plus row-count and
column stability of the final valuation output.
"""
from pathlib import Path

import pandas as pd
import pytest
from kedro.framework.session import KedroSession
from kedro.framework.startup import bootstrap_project

PROJECT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def fixture_run():
    bootstrap_project(PROJECT)
    with KedroSession.create(project_path=PROJECT, env="fixture") as session:
        return session.run(tags=["altrisk"])


def test_full_pipeline_on_fixture(fixture_run):
    assert fixture_run is not None


def test_valuation_output_shape_stable(fixture_run):
    # Adjust the dataset/file below to the final valuation table the catalog
    # persists (read conf/base/catalog.yml; it is the NPV/company-level output
    # of valuation_model). Pin its columns and a >0 row count.
    out_files = list((PROJECT / "data" / "fixture_run").rglob("*.csv"))
    assert out_files, "fixture run produced no CSV outputs"
```

During implementation, replace the generic `test_valuation_output_shape_stable` body with a read of the actual final valuation CSV (exact path from the fixture catalog written in Step 1) asserting: non-empty, expected column list captured verbatim from the first successful run, and `npv`-type columns finite. The column list is pinned in the test source — that is the behavioral contract later tasks must not break.

- [ ] **Step 4: Run it** — `.venv/bin/python -m pytest tests/integration/test_fixture_run.py -q`. Expected: first run likely fails on a missed catalog override or an inputs_processing filter — fix the fixture env (not the pipeline code!) until green. Every failure whose fix would require touching `src/` goes to implementation notes and STOPS this task for review.

- [ ] **Step 5: Commit** — `git add conf/fixture tests/integration && git commit -m "test: fixture-env regression harness running full pipeline on slice"`

---

### Task 3: Golden-run comparator (pinning deferred)

**Files:**
- Create: `scripts/pin_golden.py`, `tests/golden/compare.py`, `tests/golden/test_golden.py`, `tests/golden/__init__.py`

**Interfaces:**
- Produces: `pin_golden.py --run-dir <dir>` snapshots key output tables to `tests/golden/snapshots/` (parquet + manifest JSON); `compare.compare_frames(old, new, rtol=1e-9) -> list[str]` returns human-readable diffs; `test_golden.py` auto-skips when no snapshot exists.

- [ ] **Step 1: Write the comparator + failing unit test**

```python
# tests/golden/compare.py
"""Tolerance-based DataFrame comparison for golden-run pinning."""
from __future__ import annotations

import numpy as np
import pandas as pd


def compare_frames(old: pd.DataFrame, new: pd.DataFrame, rtol: float = 1e-9) -> list[str]:
    """Return a list of difference descriptions; empty list == match."""
    diffs: list[str] = []
    if list(old.columns) != list(new.columns):
        diffs.append(f"columns differ: {set(old.columns) ^ set(new.columns)}")
        return diffs
    if len(old) != len(new):
        diffs.append(f"row count {len(old)} -> {len(new)}")
        return diffs
    for col in old.columns:
        o, n = old[col].reset_index(drop=True), new[col].reset_index(drop=True)
        if pd.api.types.is_numeric_dtype(o) and pd.api.types.is_numeric_dtype(n):
            if not np.allclose(o.fillna(0), n.fillna(0), rtol=rtol, equal_nan=False):
                worst = (o - n).abs().max()
                diffs.append(f"{col}: numeric drift, max abs diff {worst}")
        elif not o.astype(str).equals(n.astype(str)):
            diffs.append(f"{col}: value mismatch")
    return diffs
```

```python
# tests/golden/test_golden.py
import json
from pathlib import Path

import pandas as pd
import pytest

from tests.golden.compare import compare_frames

SNAP = Path(__file__).parent / "snapshots"


def test_compare_frames_detects_drift():
    a = pd.DataFrame({"x": [1.0, 2.0]})
    b = pd.DataFrame({"x": [1.0, 2.1]})
    assert compare_frames(a, a) == []
    assert compare_frames(a, b) != []


@pytest.mark.skipif(not (SNAP / "manifest.json").exists(), reason="golden not pinned yet")
def test_outputs_match_golden():
    manifest = json.loads((SNAP / "manifest.json").read_text())
    for entry in manifest["tables"]:
        old = pd.read_parquet(SNAP / entry["snapshot"])
        new = pd.read_csv(Path(entry["source"]))
        assert compare_frames(old, new) == [], entry["source"]
```

- [ ] **Step 2: Write `scripts/pin_golden.py`** — walks `--run-dir` for the key output CSVs (final valuation table, company aggregation, asset earnings series — exact filenames from `conf/base/catalog.yml`), writes each as parquet under `tests/golden/snapshots/` and a `manifest.json` listing `{source, snapshot, pinned_at, git_sha}`. ~50 lines, argparse, no framework.

- [ ] **Step 3: Run** — `.venv/bin/python -m pytest tests/golden -q` → 1 passed, 1 skipped.

- [ ] **Step 4: Commit** — `git commit -m "test: golden-run comparator and pinning script (pinning deferred until model run completes)"`

**Deferred (manual, after the in-progress model run finishes):** `python scripts/pin_golden.py --run-dir data/07_model_output` in the MAIN tree, copy snapshots into the worktree, re-run `pytest tests/golden`. Re-pin again when the carbon-price fix lands.

---

### Task 4: Core computation unit tests

**Files:**
- Create: `tests/unit/test_mcpr_modes.py`, `tests/unit/test_capacity_flows.py`, `tests/unit/test_dcf.py`, `tests/unit/__init__.py`
- Reference (do not modify): `src/crispy_kedro/pipelines/earnings_model/nodes.py`, `src/crispy_kedro/pipelines/valuation_model/nodes.py`, existing `tests/test_mcpr_auto_fallback.py`, `tests/test_tv_flow_row_dedup.py`

**Interfaces:**
- Consumes: current public functions `apply_mcpr_adjustment`, `compute_scenario_vre_share`, `compute_capacity_flows`, `validate_capacity_flow_identity`, `compute_fcff`, and the valuation model's DCF entry function (read `valuation_model/nodes.py` to get its exact name/signature first).
- Produces: characterization tests that pin CURRENT behavior on minimal hand-built DataFrames — these are the contracts the Phase 2 splits must keep. Read each function's signature and construct minimal valid inputs from it; follow the style of `tests/test_mcpr_auto_fallback.py`.

- [ ] **Step 1: Read the five target functions end-to-end**; list in each test file's docstring which behaviors are pinned (mode resolution, floor clamping, flow identity, sign conventions, discounting).
- [ ] **Step 2: Write tests file-by-file, running each as you go** — `.venv/bin/python -m pytest tests/unit -q`. Minimum: 3 tests per file; every test asserts on values computed by hand in the test body (no snapshots). These are characterization tests of current behavior — if a result looks wrong, pin it anyway and add the observation to implementation notes.
- [ ] **Step 3: Coverage check** — `.venv/bin/python -m pytest tests/unit tests/test_mcpr_auto_fallback.py tests/test_tv_flow_row_dedup.py -q --cov=crispy_kedro.pipelines.earnings_model --cov=crispy_kedro.pipelines.valuation_model --cov-report=term | tail -20`. Target: the pure computation functions named above ≥ 80% lines each (module-total may be lower; plotting/IO exempt). Record the numbers.
- [ ] **Step 4: Commit** — `git commit -m "test: characterization tests for MCPR, capacity flows, and DCF core"`

---

### Task 5: Parameters entry point + conf cleanup

**Files:**
- Modify: `conf/base/parameters.yml` (currently empty), `conf/base/parameters_inputs_processing.yml` (12,109 → ~40 lines), `conf/base/parameters_earnings_model.yml`, `conf/base/parameters_create_late_sudden_trajectories.yml`, `conf/base/parameters_distribute_impacts_to_asset_level.yml`, `conf/base/catalog.yml` (fix `downloaded_scenarios` filepath to `data/05_model_input/downloaded_scenarios.csv`), `src/crispy_kedro/pipeline_registry.py`
- Create: `docs/handover/scenario_catalog.md` (the commented-out scenario list, preserved as docs)
- Test: existing `tests/integration/test_fixture_run.py` is the gate.

**Interfaces:**
- Produces: `conf/base/parameters.yml` holds exactly these user-facing keys (moved, not duplicated — each deleted from its per-pipeline file): `baseline_scenario`, `target_scenario`, `shock_year`, `alignment_year`, `company_ids`, `ownership_type`, `ccs_on`, `max_forecast_horizon`, `enable_mcpr`, `mcpr_mode`, `market_passthrough`, `include_growth_capex`, `include_replacement_capex`, `include_decom_costs`, `price_ramp`. Every key annotated: one comment line with meaning, units/valid values, and (where it exists) the methodology reference already present in the per-pipeline file. Advanced knobs (mcpr_markup_factor, merit-order alpha/floor, staggered_shock block, dcf block, reporting block…) stay in per-pipeline files under a `# --- Advanced:` header.
- Produces: `pipeline_registry.py` registers pipelines in stage order with a module docstring naming the 8 stages, and adds a `full` alias = stages 1–8.

- [ ] **Step 1: Move the keys.** For each key: cut from per-pipeline file, paste into `parameters.yml` under a section banner (`# ── Scenario selection ──`, `# ── Shock timing ──`, `# ── MCPR ──`, `# ── Cost switches ──`, `# ── Scope filters ──`). Copy existing inline comments verbatim; extend where missing.
- [ ] **Step 2: Preserve the scenario catalog.** Move the ~12k commented lines from `parameters_inputs_processing.yml` into `docs/handover/scenario_catalog.md` (as a fenced block, one header line explaining what it is). The YAML keeps its ~6 real keys only.
- [ ] **Step 3: Fix the catalog path** — `downloaded_scenarios.filepath: data/05_model_input/downloaded_scenarios.csv`. In the MAIN tree nothing changes (its conf/local can override); note this in implementation notes.
- [ ] **Step 4: Registry ordering + docstring** in `pipeline_registry.py`: build the dict explicitly in stage order instead of raw `find_pipelines()` insertion order; keep `__default__` = sum of all.
- [ ] **Step 5: Duplicate-key guard** — `.venv/bin/python - <<'EOF'` script that loads every `conf/base/parameters*.yml` with `yaml.safe_load` and asserts key-set disjointness; run it, expect no duplicates.
- [ ] **Step 6: Regression** — `.venv/bin/python -m pytest tests/integration/test_fixture_run.py tests/unit -q` → all pass (fixture env only overrode `parameters_inputs_processing` keys that still exist there; update `conf/fixture/` if a moved key needs overriding under its new home).
- [ ] **Step 7: Commit** — `git commit -m "refactor: single annotated parameters.yml entry point; slim per-pipeline conf; fix scenarios catalog path"`

---

### Task 6: Split `earnings_model/nodes.py` (1,801 lines)

**Files:**
- Create: `src/crispy_kedro/pipelines/earnings_model/validation.py`, `mcpr.py`, `capacity.py`, `ops.py`
- Modify: `src/crispy_kedro/pipelines/earnings_model/nodes.py` (becomes re-export shim), `pipeline.py` (import from submodules)
- Test gate: `tests/unit/test_mcpr_modes.py`, `tests/unit/test_capacity_flows.py`, `tests/test_mcpr_auto_fallback.py`, `tests/test_tv_flow_row_dedup.py`

**Move map (functions verbatim, including their private helpers and module-level constants they reference — trace each function's references before cutting):**

| New module | Functions (current line) |
|---|---|
| `validation.py` | `validate_and_standardize_inputs` (18), `validate_capacity_flow_identity` (1051) |
| `mcpr.py` | `compute_scenario_vre_share` (279), `build_scenario_surfaces` (340), `apply_mcpr_adjustment` (417) |
| `capacity.py` | `assemble_asset_panel` (913), `compute_capacity_flows` (1182), `compute_flow_based_capex` (1297) |
| `ops.py` | `compute_ops_block` (1406), `compute_fcff` (1712), `write_asset_earnings_series` (1740) |

- [ ] **Step 1: Cut-and-paste each function block verbatim** into its module with the imports it needs; module docstring (2–4 lines: stage role + methodology pointer). Shared helpers used by functions in two different new modules go to a new `_shared.py` (only if that case actually arises).
- [ ] **Step 2: Shim** — `nodes.py` becomes exactly:

```python
"""Back-compat re-exports; implementation lives in the sibling modules."""
from .validation import validate_and_standardize_inputs, validate_capacity_flow_identity  # noqa: F401
from .mcpr import compute_scenario_vre_share, build_scenario_surfaces, apply_mcpr_adjustment  # noqa: F401
from .capacity import assemble_asset_panel, compute_capacity_flows, compute_flow_based_capex  # noqa: F401
from .ops import compute_ops_block, compute_fcff, write_asset_earnings_series  # noqa: F401
```

- [ ] **Step 3: Point `pipeline.py` imports at the submodules** (not the shim).
- [ ] **Step 4: Type hints** on every public function signature in the new modules (pandas objects as `pd.DataFrame`; params as their YAML-native types). No body changes.
- [ ] **Step 5: Verify** — `.venv/bin/python -m pytest tests/unit/test_mcpr_modes.py tests/unit/test_capacity_flows.py tests/test_mcpr_auto_fallback.py tests/test_tv_flow_row_dedup.py -q` → pass; `.venv/bin/python -m ruff check src/crispy_kedro/pipelines/earnings_model/` → clean; `git diff --stat` shows `nodes.py` shrunk to the shim; `grep -c "^def " src/crispy_kedro/pipelines/earnings_model/*.py` totals 11 (unchanged function count).
- [ ] **Step 6: Commit** — `git commit -m "refactor: split earnings_model nodes into validation/mcpr/capacity/ops modules"`

---

### Task 7: Split `distribute_impacts_to_asset_level/nodes.py` (1,841 lines)

**Files:**
- Create: `.../distribute_impacts_to_asset_level/retirement.py`, `baseline.py`, `staggering_decrease.py`, `staggering_increase.py`, `assembly.py`
- Modify: `nodes.py` (shim), `pipeline.py`
- Test gate: fixture regression (this pipeline has no dedicated unit tests; its contract is pinned by Task 2's column/row assertions).

**Move map:**

| New module | Functions (current line) |
|---|---|
| `retirement.py` | `flag_phased_out_assets_as_retired` (44), `_build_retirement_map` (272), `create_frozen_capacity_at_retirement` (1539) |
| `baseline.py` | `compute_asset_baseline_trajectories` (296), `_compute_g_weights_array` (211), `_index_company_by_year` (256) |
| `staggering_decrease.py` | `stagger_decreasing_technologies` (1170), `_stagger_decreasing_fast` (630), `_prop_scale_decreasing_fast` (896), `_allocate_reduction_with_caps_array` (548), `_index_assets_by_group` (603) |
| `staggering_increase.py` | `stagger_increasing_technologies` (1261) |
| `assembly.py` | `split_late_sudden_trajectories_by_alignment_type` (10), `concatenate_staggered_shock_results` (128), `melt_asset_staggered_trajectories` (1739) |

- [ ] **Step 1–4:** same recipe as Task 6 (verbatim moves, shim in `nodes.py`, `pipeline.py` imports submodules, type hints on public functions). If `_index_assets_by_group` or `_allocate_reduction_with_caps_array` is also called from `staggering_increase.py`, move those two to a `_shared.py` instead — check callers with grep before cutting.
- [ ] **Step 5: Verify** — `.venv/bin/python -m ruff check src/crispy_kedro/pipelines/distribute_impacts_to_asset_level/` clean; function count unchanged (15); `python -c "from crispy_kedro.pipelines.distribute_impacts_to_asset_level import nodes"` imports.
- [ ] **Step 6: Commit** — `git commit -m "refactor: split distribute_impacts nodes into retirement/baseline/staggering/assembly modules"`

---

### Task 8: Split `reporting/nodes.py` (2,423 lines)

**Files:**
- Create: `.../reporting/views.py`, `plots_trajectories.py`, `plots_financials.py`, `exports.py`
- Modify: `nodes.py` (shim), `pipeline.py`
- Test gate: `tests/pipelines/reporting/test_pipeline.py` + import check (plots are figure-generation; the fixture run at the Phase 2 barrier exercises them).

**Move map:**

| New module | Functions (current line) |
|---|---|
| `views.py` | `reporting_validate_inputs` (1127), `build_reporting_views` (1247), `reporting_qc_summary` (2315) |
| `plots_trajectories.py` | `plot_late_sudden_trajectories` (24), `plot_staggered_shock` (402) |
| `plots_financials.py` | `plot_earnings_inner_workings` (1453), `plot_valuation_authority_pack` (1694), `plot_asset_financial_trajectories` (1983) |
| `exports.py` | `export_reporting_tables` (1853) |

- [ ] **Steps 1–4:** same recipe as Task 6. `plots_financials.py` will be ~1,150 lines of matplotlib — over the 800 hard max; if the three functions share no helpers, put `plot_asset_financial_trajectories` in its own `plots_assets.py` to get both under the cap.
- [ ] **Step 5: Verify** — ruff clean; function count unchanged (9); `.venv/bin/python -m pytest tests/pipelines/reporting -q` passes.
- [ ] **Step 6: Commit** — `git commit -m "refactor: split reporting nodes into views/plots/exports modules"`

---

### Task 9: Phase 2 barrier — full regression + polish sweep

**Files:**
- Modify: remaining `nodes.py` files (`inputs_processing`, `inputs_postproc`, `create_baseline_and_target_trajectories`, `create_late_sudden_trajectories`, `valuation_model`, `download_inputs`): module docstrings + public-function type hints only. No splits (all ≤ 939 lines).

- [ ] **Step 1: Full regression** — `.venv/bin/python -m pytest tests/ -q` (includes the fixture run) → everything passes except the pre-existing `test_run.py::test_kedro_run_no_pipeline` failure; investigate that one: if it fails identically on the branch point (`git stash` not needed — check out `feat/altr-npv-fixes` copy of the file logic or just read it), record as pre-existing in implementation notes; if the refactor broke it, fix the harness.
- [ ] **Step 2: Docstrings + hints sweep** over the six remaining pipelines; ruff clean repo-wide: `.venv/bin/python -m ruff check src/`.
- [ ] **Step 3: Re-run fixture regression once more after the sweep.**
- [ ] **Step 4: Commit** — `git commit -m "refactor: docstrings and type hints across remaining pipelines; repo-wide ruff clean"`

---

### Task 10: mkdocs site — scaffold, quickstart, user guide

**Files:**
- Create: `mkdocs.yml`, `docs/handover/index.md`, `docs/handover/quickstart.md`, `docs/handover/user_guide.md`, `docs/handover/troubleshooting.md`
- Copy: `~/Theia Dropbox/ALTR deliverables/ALTR Documentation.pdf` → `docs/handover/altr_documentation.pdf`

**Interfaces:**
- Produces: `mkdocs.yml` with `docs_dir: docs/handover`, material theme, nav = Index / Quickstart / User guide / Parameters / Pipelines / Architecture / Scenario catalog / Troubleshooting. Later tasks add pages to this nav.

- [ ] **Step 1: Scaffold** `mkdocs.yml` (material theme, repo-agnostic — no internal URLs) and `index.md`: what ALTR is (3 paragraphs, drawing on the PDF's framing), what the package contains, where to start.
- [ ] **Step 2: Quickstart** — the exact external-user path, written against the EXPORT layout: clone → `python3.10 -m venv` → `pip install -e .` → drop the three deliverables files into `data/01_raw/` → `python scripts/prepare_inputs.py` → `kedro run --tags altrisk` → outputs land in `data/07_model_output/`. Every command copy-pasteable; expected console landmarks quoted.
- [ ] **Step 3: User guide** — one worked example: pick a scenario pair from the catalog page, set 3 keys in `parameters.yml`, run, read the two headline output tables (name the exact files and columns), interpret NPV-direction sign conventions (source: `ALTR_NPV_Direction_Fix_Research.md` conclusions — summarize, do not copy internal deliberations).
- [ ] **Step 4: Troubleshooting** — the failure modes already known: wrong Python version, missing input files, scenario name not found in scenarios.csv, memory on full scenario file, re-running with stale intermediate data (`kedro run --from-nodes`), where logs are.
- [ ] **Step 5: Build check** — `.venv/bin/python -m mkdocs build --strict` → success, no warnings.
- [ ] **Step 6: Commit** — `git commit -m "docs: mkdocs site with quickstart, user guide, troubleshooting"`

---

### Task 11: Parameters reference (generated) + per-pipeline reference

**Files:**
- Create: `scripts/gen_param_docs.py`, `docs/handover/parameters.md` (generated), `docs/handover/pipelines/<one page per stage>.md` (8 pages)
- Modify: `mkdocs.yml` nav

**Interfaces:**
- Consumes: annotated `conf/base/parameters.yml` from Task 5 (comment lines directly above each key are its documentation).
- Produces: `gen_param_docs.py` parses `parameters.yml` + per-pipeline files into a markdown table (key, default, section, description-from-comments, defining file) and writes `docs/handover/parameters.md` with a "GENERATED — edit conf/base/parameters.yml instead" banner.

- [ ] **Step 1: Write the generator** (~80 lines: iterate file lines, accumulate consecutive `#` comments, attach to next `key:` at indent 0; emit table grouped by source file). Unit test `tests/unit/test_gen_param_docs.py` with a small inline YAML string asserting comment-to-key attachment.
- [ ] **Step 2: Generate + wire into nav; per-pipeline pages** — each stage page: purpose (from module docstring), consumes/produces datasets (from `pipeline.py` inputs/outputs), key functions (one line each), parameters it reads, methodology cross-reference (section of `altr_documentation.pdf` where applicable — cite section names, don't guess page numbers).
- [ ] **Step 3: Build check + commit** — `mkdocs build --strict`; `git commit -m "docs: generated parameters reference and per-pipeline reference pages"`

---

### Task 12: Architecture diagram

**Files:**
- Create: `docs/handover/architecture.md`
- Modify: `mkdocs.yml` (nav + mermaid support via `pymdownx.superfences`)

- [ ] **Step 1: Mermaid flowchart** — 8 stages as nodes, labeled edges naming the key datasets passed between them (derive edges from each `pipeline.py`'s inputs/outputs — draw the real data flow, not an idealized one), plus a box for the ingestion script feeding stage 1. Second small diagram: the conf layout (parameters.yml → advanced files).
- [ ] **Step 2: kedro-viz instructions** — `kedro viz run` paragraph for interactive exploration.
- [ ] **Step 3: Build check + commit** — `git commit -m "docs: architecture diagram and data-flow map"`

---

### Task 13: Walkthrough notebook

**Files:**
- Create: `notebooks/walkthrough.ipynb`

- [ ] **Step 1: Author the notebook** — cells: (1) intro + how this maps to the docs; (2) run the pipeline on the fixture slice programmatically (`KedroSession`, env="fixture"); (3) load and eyeball each stage's key intermediate output (5–6 checkpoints: processed inputs → trajectories → asset distribution → earnings → NPV), one short markdown interpretation per checkpoint; (4) a parameter experiment — flip `mcpr_mode`, re-run, compare NPV deltas in a small table + one matplotlib chart.
- [ ] **Step 2: Execute end-to-end** — `.venv/bin/python -m jupyter nbconvert --to notebook --execute notebooks/walkthrough.ipynb --output walkthrough.ipynb` → no errors; committed WITH outputs so externals see expected results without running.
- [ ] **Step 3: Commit** — `git commit -m "docs: executable walkthrough notebook on fixture slice"`

---

### Task 14: Promote the input adapter

**Files:**
- Create: `scripts/prepare_inputs.py` (adapted from `notebooks/prepare_new_inputs.py` — which stays untouched)
- Test: `tests/unit/test_prepare_inputs.py`

**Interfaces:**
- Consumes: `data/01_raw/{assets_forecasts.csv,companies_ownerships.csv,scenarios.csv}` (deliverables schema).
- Produces: `data/05_model_input/{downloaded_assets.csv,downloaded_companies.csv,downloaded_scenarios.csv}` (pipeline contract). CLI: `python scripts/prepare_inputs.py [--source data/01_raw] [--dest data/05_model_input]`.

- [ ] **Step 1: Port the transform functions** from `notebooks/prepare_new_inputs.py` (column renames, required-column validation, scenario prefix handling), dropping internal-only pieces: the `.bak` renaming, the BigQuery-source default, hardcoded `/Users/...` paths, and the AR6 manifest slicing (externals get the already-sliced `scenarios.csv`). Keep the validate-everything-before-writing-anything property — that is a data-loss guard, not internal cruft. Carry over the ownership-tier check as a WARNING (not a hard block) with a docs pointer.
- [ ] **Step 2: Unit test** — build 5-row deliverables-schema frames inline, run the transforms, assert output columns == pipeline contract lists (copy the `ASSETS_REQUIRED`-style lists from the notebook script) and that a missing required column raises `ValueError` naming the column.
- [ ] **Step 3: Run + commit** — `pytest tests/unit/test_prepare_inputs.py -q`; `git commit -m "feat: official deliverables->model-input ingestion script"`

---

### Task 15: Export builder + sanitizer

**Files:**
- Create: `scripts/build_export.py`, `scripts/export_allowlist.txt`, `scripts/sanitize_check.py`
- Create (generated, not committed here): the export tree at `--dest`

**Interfaces:**
- Produces: `python scripts/build_export.py --dest <dir> [--data-source "<deliverables dir>"]` assembles the export; exits non-zero if `sanitize_check.py` finds a hit.

- [ ] **Step 1: Allowlist file** (one path per line, `#` comments):

```
# scripts/export_allowlist.txt — everything shipped to altr-model; nothing else leaves.
src/crispy_kedro/            # minus pipelines/download_inputs — handled in code
conf/base/
conf/fixture/
conf/local/.gitkeep
docs/handover/
mkdocs.yml
notebooks/walkthrough.ipynb
tests/
scripts/prepare_inputs.py
scripts/gen_param_docs.py
pyproject.toml
poetry.lock
LICENSE
Dockerfile
.gitignore
```

- [ ] **Step 2: `build_export.py`** (~120 lines): copy allowlist entries; skip `pipelines/download_inputs` and every `__pycache__`; strip `download_inputs` references from `pipeline_registry.py` docstring and `conf/base/parameters_download_inputs.yml` from the copy; write the export `README.md` from `docs/handover/quickstart.md` + a pointer to the docs site; stage the three deliverables files from `--data-source` into `<dest>/data/01_raw/`; create empty `data/05_model_input/.gitkeep`; run `sanitize_check.py <dest>` and fail loudly on hits.
- [ ] **Step 3: `sanitize_check.py`** — grep the assembled tree (excluding `data/01_raw` payloads) for: `jakub` (case-insensitive), `hummusking`, `Theia Dropbox`, `/Users/`, `bigquery`, `gcp`, `credentials`, `bertrand`, private-key headers (`BEGIN.*PRIVATE KEY`), and 20-plus-char high-entropy tokens (`[A-Za-z0-9_\-]{28,}` filtered to lines containing `key|token|secret|password`). Print file:line for every hit; exit 1 on any. Allowlisted exceptions live in the script as an explicit list with justification comments.
- [ ] **Step 4: Dry run** — `python scripts/build_export.py --dest /private/tmp/claude-501/-Users-jakub-Documents-repos-crispy-kedro/*/scratchpad/altr-model-preview` → sanitizer green. Fix hits by cleaning the SOURCE files (not the copy) where internal references leaked into shipped code/docs.
- [ ] **Step 5: Commit** — `git commit -m "feat: allowlist export builder with sanitizer gate"`

---

### Task 16: Fresh-machine verification

**Files:** none (verification only; findings → implementation notes).

- [ ] **Step 1: Build the export** into a scratch dir (Task 15 command).
- [ ] **Step 2: Clean venv** — `python3.10 -m venv /tmp-scratch/venv && venv/bin/pip install -e <export dir>` (use the scratchpad; the exact python3.10 binary is `/Users/jakub/Documents/repos/crispy-kedro/.venv/bin/python`'s base — resolve via `readlink`).
- [ ] **Step 3: Follow `README.md` verbatim** — stage fixture-slice files as the "deliverables" (they are schema-identical post-adapter; full-data run is Jakub's final sign-off), `prepare_inputs.py`, `kedro run --env fixture --tags altrisk` inside the export.
- [ ] **Step 4: Verify outputs** — the export's fixture run passes the same integration test: `venv/bin/python -m pytest tests/integration -q` inside the export.
- [ ] **Step 5: Record** wall-clock time and every friction point in implementation notes; each friction point becomes a quickstart/troubleshooting edit; re-run until the README path is friction-free.

---

### Final gate: dual review (fable + codex)

- [ ] **Review 1 (fable):** high-effort code review of the full branch diff (`git diff feat/altr-npv-fixes...feat/handover-package`) — correctness of the moves (no dropped/duplicated logic), conf key relocation, export leakage, docs accuracy against code.
- [ ] **Review 2 (codex):** independent pass via the codex rescue agent, same scope, fresh context.
- [ ] Address all CRITICAL/HIGH findings; re-run `pytest tests/ -q`; log the verdicts.
- [ ] Deliver: summary + open loops (golden pinning after model run; carbon-price re-pin; Bertrand review before merge; first full-data run of the export).
