# Migration Disposition Ledger — `feat/handover-package` → `origin/main`

**Status:** draft for review. Not committed.
**Date:** 2026-09-01
**Merge base:** `91c0a7f`
**Source:** `feat/handover-package` (pre-migration, `src/crispy_kedro/`, 9 pipelines, poetry.lock)
**Target:** `origin/main` = `Theia-Finance-Labs/altr-model` (post-migration, `src/altr_model/`, 6 pipelines, uv.lock)
**Scope:** every one of the 172 entries in `git diff --name-status 91c0a7f..HEAD`, plus all 99 branch commits.

This ledger exists because two prior reviewers failed the previous plan for leaving
~40 files with no assigned fate. Every entry below carries a disposition. Where a
disposition could not be established from evidence, the entry is **ADJUDICATE** —
never a guess.

---

## 1. Binding decisions applied

From `docs/superpowers/plans/implementation-notes-handover.md`, "Decisions recorded 2026-09-01 (Jakub)":

1. **MCPR is retired.** No MCPR implementation, wiring, conf keys, MCPR-specific
   tests or `MCPR/` methodology docs are ported. Verified: `git grep -il mcpr origin/main`
   returns **zero** files. Nothing is undone; MCPR simply is not carried forward.
   AGENTS.md requires Bertrand's review for ALTR/MCPR changes — this retirement
   should be confirmed with him on the record.
2. **Repo naming.** Internal = `altr-model` (this `origin/main`). External =
   `altr-model-refactored`. Every export-tooling reference to the external repo
   name must be updated on port — flagged on entries 85, 86, 90 and 23.
3. **Ownership consolidation.** Implementation superseded by main's own
   (Bertrand's) `63f5b59`; the regression test `tests/unit/test_ownership_consolidation.py`
   is **not** on main and **is** ported, adapted to main's module paths (entry 171).

---

## 2. Verification basis

### 2.1 Main's 24 commits since merge base

```
63f5b59 _consolidate_ownership_stakes        9d7e195 delete trisk submodule
70300bd Merge PR #54 altr-followup-fixes     b9ca656 stagger-path adjusted series + co-owner plot slicing
5fd3c26 Merge PR #53 altr-npv-fixes-ported   13540c1 clamp transition anchor to last grid year
4dc3400 collapse capex flow-split rows       51d1177 per-owner reporting keys + vectorized PV loops
04bafcb pin geography-safe capacity flows     20490a2 vectorize NPV, close silent-drop paths
2c554cc single-application retirement        c45103f ownership allocation percentage points (x100)
7cf6544 stabilize carried-column dtypes      4233c4b grouping columns out of groupby.apply
3e285d1 .dockerignore + logging              970362e companies selection
62e6ba2 disable reporting in notebook        2791a45 Altr cleanups (#50)
6de4a7b rename to altr                       bdcd8c3 get rid of ownership_type
8772674 Data delivery prep (#49)             de07ad4 reporting fixes
be06986 bypass scenario_type column          672356d Cleanings (#21)
```

Main independently ported most of the branch's NPV-fix series (its own branch was
`feat/altr-npv-fixes-ported`). That is why so many branch fixes land as
DROP-SUPERSEDED rather than PORT.

### 2.2 Pipeline naming map (branch → main)

| Branch pipeline | Main pipeline |
|---|---|
| `inputs_processing` | `prepare_scenario_asset_and_company_inputs` |
| `inputs_postproc` (was `report_outputs`) | *absorbed into* `prepare_scenario_asset_and_company_inputs/_asset_preparation.py` |
| `create_baseline_and_target_trajectories` | `calculate_company_trajectories/_baseline_nodes.py` |
| `create_late_sudden_trajectories` | `calculate_company_trajectories/_late_sudden_nodes.py` |
| `distribute_impacts_to_asset_level` | `allocate_company_trajectories_to_assets` |
| `earnings_model` | `calculate_asset_earnings` |
| `valuation_model` | `calculate_asset_and_company_npv` |
| `reporting` | `plot_transition_risk_results` |
| `download_inputs` | *no pipeline*; main uses `src/altr_model/bigquery_marts_downloader.py` |
| `financial_model` (deleted) | *absent on main* |

**Every ported doc must have all path, pipeline, stage, dataset and parameter names
rewritten to this right-hand column.** This is restated per-row but applies globally.

### 2.3 Key evidence gathered

- `git grep -il mcpr origin/main` → zero hits. MCPR retirement is a no-op on main.
- `origin/main:.../calculate_asset_earnings/nodes.py:275-277` — replacement mask is
  `(~is_synthetic) & (capacity_change > 0)`; branch `capacity.py:226` is
  `is_real & ~retirement_mask`. Retirement masks also differ (main `capacity_change < 0`;
  branch `(capacity_change < 0) & is_real`). Rates differ (main `replacement_capex_rate`
  parameter default 0.05 on `capacity_change`; branch hardcoded `asset_trajectory * 0.02`).
- `git grep "price_ramp\|stranding\|dynamic_marginal_ef\|green_spread\|brown_spread" origin/main`
  → **zero hits repo-wide**. The entire `056d1f6` NPV-direction feature set is absent from main.
- `origin/main:.../calculate_asset_earnings/nodes.py:16-23` — `ASSET_SERIES_KEYS`
  includes `scenario_geography`, so the geography-safe capacity-flow half of `aa1e10d`
  is already on main (pinned by main's `04bafcb`).
- `git grep ffill origin/main -- src/` → hits only in allocation, trajectory and
  asset-preparation modules; **no EF forward-fill in `calculate_asset_earnings`**.
  Main uses `fillna(0.0)` at `nodes.py:464`.
- `origin/main:.../allocate_company_trajectories_to_assets/_allocation_nodes.py:513-517`
  — retirement application merges with `validate="many_to_one"`: main **has** the
  retirement-mask alignment fix, but **not** its regression test.
- `git grep create_frozen_capacity_at_retirement origin/main -- src/` → zero hits.
  The function does not exist on main.
- All three `inputs_postproc` node functions exist on main in
  `prepare_scenario_asset_and_company_inputs/_asset_preparation.py`.
- `origin/main:.../plot_transition_risk_results/nodes.py` already contains
  `build_reporting_views`, `export_reporting_tables`, `plot_earnings_inner_workings`,
  `plot_valuation_authority_pack`, `plot_asset_financial_trajectories`,
  `plot_staggered_shock`, `plot_late_sudden_trajectories`, `reporting_qc_summary`.
- `origin/main:.gitmodules` still carries the `[submodule "pkg/trisk.model"]` stanza
  even though `9d7e195` removed the directory — a dangling entry the branch fixed.
- **Correction to the brief:** `d963ec8` (AR6 cache-freshness) touches only
  `notebooks/run_all_scenarios_comparison.py`, and `6ca15d1` (scenario cost-column
  validation) touches only `scripts/prepare_inputs.py` + its test. Neither is a
  `src/` change. Dispositions follow the files, not the assumption.

---

## 3. Diff ledger — 172 entries

Entry numbers are line numbers in `git diff --name-status 91c0a7f..HEAD`.
Status codes: A add, M modify, D delete, R rename.

### 3.1 Root and configuration

| # | Path(s) | Disposition | Target / reason |
|---|---|---|---|
| 1 | `A .cursorignore` | DROP-SUPERSEDED | `origin/main:.cursorignore` is byte-identical (verified by diff). |
| 2 | `M .gitmodules` | **PORT** → `.gitmodules` | Main deleted `pkg/trisk.model` in `9d7e195` but `origin/main:.gitmodules` still declares the submodule. Branch `a8c0fa5` empties it. Real cleanup main lacks. |
| 3 | `M .vscode/launch.json` | DROP-SUPERSEDED | `origin/main:.vscode/launch.json` already has the equivalent debug entry, pointing at `src/altr_model/bigquery_marts_downloader.py`. The branch entry targets `--tags=download_inputs`, a pipeline main does not have. |
| 4 | `A AGENTS.md` | REFERENCE | Internal agent/board context. Every fact is stale for main: repo name `crispy-kedro`, poetry commands, `MCPR/` + `pkg/` layout. Main would need a rewrite, not a port; externals never receive agent context. |
| 5 | `A ALTR_NPV_Direction_Fix_Research.md` | REFERENCE | Internal research note backing `056d1f6`, whose implementation is ADJUDICATE. Not a deliverable; keep with the branch that holds the code it argues for. |
| 6 | `A MCPR/ALTR_MCPR_methodology_v1.md` | DROP-RETIRED | Owner decision 1. |
| 7 | `M README.md` | **PORT (partial)** → `README.md` | Port only the handover-docs pointer (docs site + `docs/handover/`), rewritten to uv and `src/altr_model/`. The poetry / `crispy_kedro` prose is superseded by `origin/main:README.md`, already ALTR-branded and uv-based. |
| 8 | `A SKIP_FIX.txt` | REFERENCE | Cloud Run `kedro-viz` deploy incident record, explicitly "not a repo defect". Already deleted in the working tree. |
| 9 | `M conf/base/catalog.yml` | **ADJUDICATE** | Mixed. (a) `ar6_carbon_prices` dataset + per-IAM carbon-price strategy comment belong to the `056d1f6` carbon-price-injection feature set, absent from main. (b) `bertrand_marts`→`bertrand2_marts` is `download_inputs` scope, superseded by main's `bigquery_marts_downloader.py`. (c) Path/layer renumbering superseded by main's own 10-dataset catalog. **Ruling needed on (a) only.** |
| 10, 12 | `M conf/base/parameters.yml`, `M conf/base/parameters_distribute_impacts_to_asset_level.yml` | **PORT (annotations only)** → main's six `conf/base/parameters_*.yml` | `272ef46`'s value is the annotated parameter documentation that `scripts/gen_param_docs.py` consumes. Port the annotations into main's six per-pipeline files; do **not** port the single-file collapse — main's per-pipeline split is its own structure. Rewrite keys to main's pipeline names. |
| 11 | `M conf/base/parameters_create_late_sudden_trajectories.yml` | **ADJUDICATE** | `272ef46` annotations follow row 10; the `056d1f6` shock-window / price-ramp values are the open question. Target if ruled in: `conf/base/parameters_calculate_company_trajectories.yml`. |
| 13 | `A conf/base/parameters_earnings_model.yml` | **ADJUDICATE** | MCPR keys are DROP-RETIRED. The `price_ramp` / `dynamic_marginal_ef` / replacement-CapEx switches conflict with main's deliberate `include_replacement_capex: False`, `include_decom_costs: False`, `replacement_capex_rate: 0.05` in `origin/main:conf/base/parameters_calculate_asset_earnings.yml`. |
| 14 | `D conf/base/parameters_financial_model.yml` | DROP-SUPERSEDED | Main has no `financial_model` pipeline and no such parameter file; `origin/main:conf/` holds six per-pipeline files, none financial. Deletion already effective on main. |
| 15 | `R069 conf/base/parameters_report_outputs.yml → conf/base/parameters_inputs_postproc.yml` | DROP-SUPERSEDED | Main has no postproc stage; the parameters live in `origin/main:conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml` (verified: `reduce_granularity_from_asset_to_company_level` is present there). |
| 16 | `M conf/base/parameters_inputs_processing.yml` | **ADJUDICATE** | Carries `056d1f6` carbon-price/VRE parameters and `5ecdca6` MCPR VRE keys (retired). Target if ruled in: `conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml`. |
| 17 | `A conf/base/parameters_reporting.yml` | DROP-SUPERSEDED | `origin/main:conf/base/parameters_plot_transition_risk_results.yml`. |
| 18 | `M conf/base/parameters_valuation_model.yml` | **ADJUDICATE** | Stranding-aware TV, brown/green discount spreads, finite-annuity window — verified absent from main repo-wide. Target if ruled in: `conf/base/parameters_calculate_asset_and_company_npv.yml`. |
| 19, 20 | `A conf/fixture/catalog.yml`, `A conf/fixture/parameters_inputs_processing.yml` | **PORT** → `conf/fixture/` | Fixture-slice regression environment (`f838f0f`, `2e35c9f`); in the export allowlist. Rename the parameters file to `parameters_prepare_scenario_asset_and_company_inputs.yml` and rewrite dataset keys to main's catalog. |
| 21 | `M conf/prod/catalog.yml` | DROP-SUPERSEDED | `conf/prod/catalog.yml` existed at merge base and main removed it: `origin/main:conf/` contains only `README.md`, `base/`, `local/.gitkeep`. |
| 22 | `A create_asset_shock_file.py` | REFERENCE | Root-level one-off input-prep script (`be55926`). No counterpart on main, not in the export allowlist; superseded within the handover package by `scripts/prepare_inputs.py`. |

### 3.2 Handover documentation — all PORT

**Global rule for this block:** every path, pipeline name, stage name, dataset key,
parameter key and command inside these documents must be rewritten to main's naming
per §2.2 (`src/altr_model/`, six `calculate_*`-style pipelines, uv not poetry).
The external repo is `altr-model-refactored`.

| # | Path(s) | Disposition | Target / reason |
|---|---|---|---|
| 23 | `A docs/handover/altr_documentation.pdf` | **PORT** → `docs/handover/altr_documentation.pdf` | Delivered binary; cannot be edited. It hardcodes the `altr-model` clone URL, which after the rename resolves to the **internal** repo. `index.md` and `quickstart.md` must continue to supersede it explicitly and name `altr-model-refactored`. Carry that superseding text across on port. |
| 24, 25, 26, 35, 36, 37, 38 | `A docs/handover/architecture.md`, `index.md`, `parameters.md`, `quickstart.md`, `scenario_catalog.md`, `troubleshooting.md`, `user_guide.md` | **PORT** → same paths | Core handover package. `parameters.md` is generated by `scripts/gen_param_docs.py`, so regenerate it against main's six parameter files rather than copying. Apply the global naming rewrite. |
| 27–34 | `A docs/handover/pipelines/{create_baseline_and_target_trajectories, create_late_sudden_trajectories, distribute_impacts_to_asset_level, earnings_model, inputs_postproc, inputs_processing, reporting, valuation_model}.md` | **PORT (renamed + merged)** → `docs/handover/pipelines/` | Eight branch pages collapse onto main's six pipelines: `create_baseline_and_target_trajectories.md` + `create_late_sudden_trajectories.md` → `calculate_company_trajectories.md`; `distribute_impacts_to_asset_level.md` → `allocate_company_trajectories_to_assets.md`; `earnings_model.md` → `calculate_asset_earnings.md`; `valuation_model.md` → `calculate_asset_and_company_npv.md`; `reporting.md` → `plot_transition_risk_results.md`; `inputs_processing.md` → `prepare_scenario_asset_and_company_inputs.md`, into which `inputs_postproc.md` is folded (main absorbed that stage). Strip any MCPR prose from `earnings_model.md` before porting. |

### 3.3 Presentations and research

| # | Path(s) | Disposition | Target / reason |
|---|---|---|---|
| 39–45 | `A docs/presentations/altr_improvements_Deck_v2.{html,pdf,pptx}`, `altr_update_assessments_v1.{html,pdf}`, `altr_updates_Brief_v1.{html,md}` | REFERENCE | Internal stakeholder decks and briefs. Not code, not deliverables to the recipient; main gains nothing and the export allowlist excludes `docs/presentations/`. |
| 46 | `A docs/research/ALTR_IMPROVEMENT_BRIEF.md` | REFERENCE | Internal improvement brief; argues for work whose fate is decided elsewhere in this ledger. |
| 47 | `A docs/research/ALTR_RESEARCH_VERIFICATION_REPORT.md` | REFERENCE | Internal verification write-up of the research brief. |
| 48 | `A docs/research/company_id_archive_2026.md` | **NEVER-SHIP** | Owner-designated guard item: the company-id archive must never reach the external repo. Excluded from the export allowlist and gated by `scripts/sanitize_check.py` (`7dfc533`, `9c1f40f`). Does not port to main's export scope either. |

### 3.4 Superpowers plans and specs

| # | Path(s) | Disposition | Target / reason |
|---|---|---|---|
| 49, 55 | `A docs/superpowers/plans/2026-04-14-mcpr-v2-redesign.md`, `A docs/superpowers/specs/2026-04-14-mcpr-v2-redesign.md` | DROP-RETIRED | MCPR design documents. Owner decision 1. |
| 50, 51, 52, 53, 54, 56, 57 | `A docs/superpowers/plans/{2026-07-06-altr-reconciliation-and-effectiveness-plan, 2026-07-07-theia-ops-phase-1-foundations, 2026-08-31-altr-handover-package, implementation-notes-handover}.md`, `A docs/superpowers/specs/{2026-04-13-fullef-batch-rerun-design, 2026-07-07-team-ops-system-design, 2026-08-31-altr-handover-package-design}.md` | REFERENCE | Internal planning artefacts and session notes. `implementation-notes-handover.md` is the running deviation log for this very migration and must stay with the branch that produced it. Externals receive product docs, not plans; main carries no `docs/` tree at all. |
| 58 | `A mkdocs.yml` | **PORT** → `mkdocs.yml` | Rewrite `nav:` to the renamed pipeline pages from rows 27–34; set `site_name`/`repo_url` for the external repo `altr-model-refactored`. |

### 3.5 Notebooks

| # | Path(s) | Disposition | Target / reason |
|---|---|---|---|
| 59, 60, 61 | `A notebooks/analyze_fullef_comparison.py`, `clean_input_data.R`, `cleaning_summary.xlsx` | REFERENCE | Internal one-off analysis and cleaning artefacts; not in the export allowlist, no counterpart needed on main. |
| 62 | `D notebooks/countries_discount_rate.csv` | DROP-SUPERSEDED | Already absent from `origin/main:notebooks/` (which holds only `.gitkeep`, `example_company_selection.csv`, `example_run_configurations.yml`, `generate_results.ipynb`, `run_kedro_batch.py`, `scenario_utils.py`, `streamlit_app.py`). Deletion already effective. |
| 63 | `A notebooks/generate_results.ipynb` | DROP-SUPERSEDED | `origin/main:notebooks/generate_results.ipynb` exists (15 KB, outputs stripped) and main tuned it further in `62e6ba2`/`970362e`. The branch file is 818 KB of embedded outputs. |
| 64 | `A notebooks/run_all_scenarios_comparison.py` | REFERENCE | Internal scenario-comparison batch harness. **This is where `d963ec8` (AR6 cache-freshness) lives** — it is not a `src/` fix. Main's batch runner is `notebooks/run_kedro_batch.py`, a different tool with no such cache; the file is not in the export allowlist. Also carries uncommitted working-tree edits. |
| 65, 66, 67, 76, 77, 78, 79, 80 | `A notebooks/scripts/{beforeafter_compatible_scenario, comparison_times2price_vs_ratio, find_same_start_scenarios}.ipynb`, `scenario_distance_analyzer.py`, `{scenarios_pathways_clean_price_ratio, scenarios_with_carbontax, statdesc_scenarios_data, unique_valid_scenarios_and_providers}.ipynb` | REFERENCE | Exploratory scenario-analysis notebooks. Internal only; excluded from the export allowlist, which ships `notebooks/walkthrough.ipynb` alone. |
| 68 | `R100 tests/pipelines/layer1/__init__.py → notebooks/scripts/gather_combined_results.R` | REFERENCE | Rename artefact: git paired a deleted empty `__init__.py` with a new R script. Both halves resolve here — main has no `tests/pipelines/layer1` package (already gone), and the R results-gathering script is internal tooling. |
| 69, 70, 71, 72 | `A notebooks/scripts/{gather_npv_results, gather_prod_and_financial_trajs, results_cleaning, results_confirming}.R` | REFERENCE | Internal R post-processing harness; no R tooling on main, none shipped externally. |
| 73, 74, 75 | `R100 notebooks/run_trisk_with_R.R → notebooks/scripts/run_trisk_with_R.R`, `run_trisk_with_R_local.R → scripts/run_trisk_with_R_local.R`, `run_trisk_with_python.ipynb → scripts/run_trisk_with_python.ipynb` | REFERENCE | Pure relocation of the internal trisk harness. Main **deleted the pre-rename originals** during its cleanups — `origin/main:notebooks/` has none of them — so porting the rename would re-add files main deliberately removed. |
| 81 | `A notebooks/walkthrough.ipynb` | **PORT** → `notebooks/walkthrough.ipynb` | Executable walkthrough on the fixture slice (`134ba4e`); explicitly in the export allowlist. Re-point every pipeline, dataset and parameter name to main's naming and re-execute against main's fixture environment. |

### 3.6 Packaging

| # | Path(s) | Disposition | Target / reason |
|---|---|---|---|
| 82 | `D pkg/trisk.model` | DROP-SUPERSEDED | Main removed the submodule in `9d7e195`; `pkg/` is absent from the `origin/main` tree. (The leftover `.gitmodules` stanza is handled by row 2.) |
| 83 | `M poetry.lock` | DROP-SUPERSEDED | Main migrated to uv: `origin/main:uv.lock` exists, no `poetry.lock`. |
| 84 | `M pyproject.toml` | **PORT (partial)** → `pyproject.toml` | Port only the docs/test tooling: the mkdocs dependency group, `ruff`, and the pytest/ruff tool configuration, translated into main's uv `[dependency-groups]`. The poetry build-system, project name and `crispy_kedro` packaging are superseded by `origin/main:pyproject.toml` (name `altr-model`, uv-managed). Also drop `poetry.lock` from the ported export allowlist in favour of `uv.lock`. |

### 3.7 Export and helper scripts — all PORT

Main has no `scripts/` directory; the whole block is new there.

| # | Path(s) | Disposition | Target / reason |
|---|---|---|---|
| 85 | `A scripts/build_export.py` | **PORT** → `scripts/build_export.py` | **Update the external repo name to `altr-model-refactored`.** Rewrite `SKIP_RELATIVE` / `SKIP_DIR_NAMES` and the package-rename logic for `src/altr_model/`; the `download_inputs` carve-outs no longer apply (main has no such pipeline) and must be replaced by whatever exclusion `bigquery_marts_downloader.py` needs. |
| 86 | `A scripts/export_allowlist.txt` | **PORT** → `scripts/export_allowlist.txt` | **Update the external repo name to `altr-model-refactored`** in the header comment. Rewrite every path: `src/crispy_kedro/`→`src/altr_model/`, drop the `download_inputs` and `parameters_download_inputs.yml` carve-outs, replace `poetry.lock` with `uv.lock`, and re-point `conf/base/` at main's six parameter files. |
| 87 | `A scripts/gen_param_docs.py` | **PORT** → `scripts/gen_param_docs.py` | Must read main's six per-pipeline `conf/base/parameters_*.yml` rather than a single consolidated `parameters.yml` (see row 10). |
| 88 | `A scripts/pin_golden.py` | **PORT** → `scripts/pin_golden.py` | Golden-baseline pinning; shipped so recipients can pin their own (`3c0d8b0`). |
| 89 | `A scripts/prepare_inputs.py` | **PORT** → `scripts/prepare_inputs.py` | Official-deliverables ingestion (`63691a9`). **Carries `6ca15d1`** — scenario cost-column validation and removal of the identity `AR6_` prefix strip. Verified absent from main, which has no `scripts/` at all. This is one of the flagged fixes; it ports as tooling, not as a `src/` change. |
| 90 | `A scripts/sanitize_check.py` | **PORT** → `scripts/sanitize_check.py` | Sanitizer gate (`f69f7b8`, `7dfc533`, `9c1f40f`, including the composite-company-id fix). This is the guard that keeps entry 48 out of the export; **update the external repo name to `altr-model-refactored`** wherever it appears. |

### 3.8 `src/` — modified files main has since relocated

| # | Path(s) | Disposition | Target / reason |
|---|---|---|---|
| 91 | `M src/crispy_kedro/pipeline_registry.py` | DROP-SUPERSEDED | `origin/main:src/altr_model/pipeline_registry.py` registers its own six pipelines. The branch's nine-pipeline registry (MCPR-era earnings, `inputs_postproc`, `download_inputs`) has no place on main. Branch change is `272ef46` only. |
| 92, 93 | `M src/crispy_kedro/pipelines/create_baseline_and_target_trajectories/{nodes,pipeline}.py` | DROP-SUPERSEDED | `origin/main:src/altr_model/pipelines/calculate_company_trajectories/_baseline_nodes.py` + `pipeline.py` carry the equivalent, including CCS handling (`" - w/ CCS"` present in main's `prepare_scenario_asset_and_company_inputs/_input_nodes.py`). Branch-unique content is `1259a10` docstring/ruff formatting — cosmetic. |
| 94, 95 | `M src/crispy_kedro/pipelines/create_late_sudden_trajectories/{nodes,pipeline}.py` | DROP-SUPERSEDED | `origin/main:.../calculate_company_trajectories/_late_sudden_nodes.py`. The one substantive branch touch here (`a9f4cb5`) is on main as `4dc3400`; main additionally has `13540c1` (shock-anchor clamp), which the branch lacks — porting backwards would regress it. |
| 96–103 | `A .../distribute_impacts_to_asset_level/{_shared,assembly,baseline,retirement,staggering_decrease,staggering_increase}.py`, `M .../{nodes,pipeline}.py` | DROP-SUPERSEDED | `origin/main:src/altr_model/pipelines/allocate_company_trajectories_to_assets/{nodes.py,_allocation_nodes.py}` carries the behaviour: single-application retirement (`2c554cc`), retirement-mask alignment via `validate="many_to_one"` at `_allocation_nodes.py:513-517`, grouping-columns fix (`4233c4b`), plus main-only `b9ca656` and `7cf6544`. The `b802a79` module split is cosmetic. **Note:** `create_frozen_capacity_at_retirement` (the third part of `484ba88`) has **no counterpart on main** — main handles frozen capacity inside `calculate_asset_earnings` instead — so there is no implementation to port; the open question is carried on entry 155. |
| 104 | `M src/crispy_kedro/pipelines/download_inputs/nodes.py` | DROP-SUPERSEDED | Main has no `download_inputs` pipeline (`origin/main:src/altr_model/pipeline_registry.py` registers six, none of them download); ingestion lives in `origin/main:src/altr_model/bigquery_marts_downloader.py`. Branch change is `1259a10` docstrings only. The export tooling excludes this pipeline anyway. |
| 105 | `A src/crispy_kedro/pipelines/earnings_model/capacity.py` | **ADJUDICATE** | **The named divergence.** Replacement mask: main `(~is_synthetic) & (capacity_change > 0)` vs branch `is_real & ~retirement_mask`. Retirement mask: main `capacity_change < 0` vs branch `(capacity_change < 0) & is_real`. Rate: main parameterised `replacement_capex_rate` (0.05) applied to `capacity_change` vs branch hardcoded `asset_trajectory * 0.02`. Three coupled behaviour changes from `31596a0` + `056d1f6`; model owner must rule. |
| 106 | `A src/crispy_kedro/pipelines/earnings_model/mcpr.py` | DROP-RETIRED | Owner decision 1. |
| 107 | `M src/crispy_kedro/pipelines/earnings_model/nodes.py` | **ADJUDICATE** | Mixed. MCPR re-exports are DROP-RETIRED; the geography-safe capacity-flow half of `aa1e10d` is superseded by main's `ASSET_SERIES_KEYS` + `04bafcb`; the remainder is `31596a0` + `056d1f6`, both open. Target if ruled in: `src/altr_model/pipelines/calculate_asset_earnings/nodes.py`. |
| 108 | `A src/crispy_kedro/pipelines/earnings_model/ops.py` | **ADJUDICATE** | `056d1f6` operating logic: continued O&M on stranded fossil capacity, differential carbon-cost injection, price ramp, dynamic marginal EF. Verified zero trace on main. |
| 109 | `M src/crispy_kedro/pipelines/earnings_model/pipeline.py` | **ADJUDICATE** | Wires both the retired MCPR nodes and the `056d1f6` parameters; cannot be split until 105/107/108 are ruled. |
| 110 | `A src/crispy_kedro/pipelines/earnings_model/validation.py` | **ADJUDICATE** | Duplicate-year and continuity checks are already on main (`calculate_asset_earnings/nodes.py:37-95`). The open part is the emission-factor **forward fill** (`aa1e10d`, `validation.py:134`): main has no `ffill` anywhere in `calculate_asset_earnings` and instead sets missing EFs to `0.0` (`nodes.py:464`). Forward-filling vs zero-filling emission factors is a model-behaviour choice. |
| 111–113 | `D src/crispy_kedro/pipelines/financial_model/{__init__,nodes,pipeline}.py` | DROP-SUPERSEDED | Main has no `financial_model` pipeline anywhere in `origin/main:src/`; replaced by `calculate_asset_earnings`. Deletion already effective. |
| 114, 115, 116 | `R072 .../report_outputs/__init__.py → .../inputs_postproc/__init__.py`, `A .../inputs_postproc/{nodes,pipeline}.py` | DROP-SUPERSEDED | All three node functions verified on main in `origin/main:src/altr_model/pipelines/prepare_scenario_asset_and_company_inputs/_asset_preparation.py`: `apply_reduce_granularity_from_asset_to_company_level`, `determine_assets_retirement_dates`, `extend_allocated_assets_to_companies` (the latter two also referenced from `allocate_company_trajectories_to_assets/nodes.py`). Main absorbed the stage rather than keeping a separate pipeline. |
| 117 | `M src/crispy_kedro/pipelines/inputs_processing/nodes.py` | **ADJUDICATE** | Most of this file's history is already on main: `b71f1a8` is a port *of* main's `63f5b59`; `593059c` is main's `c45103f`; `13707f2` geography filtering is main's `common_geographies` in `_input_nodes.py`; `1259a10` is cosmetic. The unique remainder is `056d1f6` carbon-price/VRE-share computation (open) and `5ecdca6` MCPR VRE (retired). Target if ruled in: `prepare_scenario_asset_and_company_inputs/`. |
| 118 | `M src/crispy_kedro/pipelines/inputs_processing/pipeline.py` | **ADJUDICATE** | Wires the `056d1f6` nodes from row 117. |
| 119, 120 | `D src/crispy_kedro/pipelines/report_outputs/{nodes,pipeline}.py` | DROP-SUPERSEDED | Same absorption as rows 114–116; main has no `report_outputs` module. Deletion already effective. |
| 121–129 | `A src/crispy_kedro/pipelines/reporting/{__init__,_style,exports,nodes,pipeline,plots_financials,plots_staggered,plots_trajectories,views}.py` | DROP-SUPERSEDED | `origin/main:src/altr_model/pipelines/plot_transition_risk_results/nodes.py` already contains the equivalent function set (`build_reporting_views`, `export_reporting_tables`, `plot_earnings_inner_workings`, `plot_valuation_authority_pack`, `plot_asset_financial_trajectories`, `plot_staggered_shock`, `plot_late_sudden_trajectories`, `reporting_qc_summary`), plus main-only fixes `51d1177` (per-owner keys) and `b9ca656` (co-owner plot slicing). The `5a48631` module split is cosmetic and would discard main's later fixes. |
| 130 | `M src/crispy_kedro/pipelines/valuation_model/__init__.py` | DROP-SUPERSEDED | `1259a10` docstring only; `origin/main:src/altr_model/pipelines/calculate_asset_and_company_npv/__init__.py`. |
| 131 | `M src/crispy_kedro/pipelines/valuation_model/nodes.py` | **ADJUDICATE** | `5ef65b2` and `a9f4cb5` are on main as `20490a2` and `4dc3400`. The unique remainder is `056d1f6`: stranding-aware terminal value (Gourdel 2024, 3-tier), finite-annuity double-discount fix, green/brown discount spreads, `g_effective` initialisation, terminal-FCFF normalisation. Verified **zero** trace on main. Target if ruled in: `calculate_asset_and_company_npv/nodes.py`. |
| 132 | `M src/crispy_kedro/pipelines/valuation_model/pipeline.py` | **ADJUDICATE** | Wires the `056d1f6` valuation parameters from row 131. |
| 133 | `M src/crispy_kedro/settings.py` | DROP-SUPERSEDED | `1259a10` docstrings/ruff only; `origin/main:src/altr_model/settings.py`. |

### 3.9 Tests

| # | Path(s) | Disposition | Target / reason |
|---|---|---|---|
| 134–137 | `A tests/fixtures/data/{ar6_carbon_prices,downloaded_assets,downloaded_companies,downloaded_scenarios}.csv` | **PORT** → `tests/fixtures/data/` | Fixture-slice data (`2e35c9f`, `689d312`); ships under the export allowlist. Re-verify the WITCH scenario pair resolves against main's catalog. `ar6_carbon_prices.csv` ports as fixture data regardless of row 9's ruling — it is inert unless the carbon-price dataset is wired. |
| 138 | `A tests/fixtures/make_fixture_slice.py` | **PORT** → `tests/fixtures/make_fixture_slice.py` | Slice builder; re-point at main's dataset names. |
| 139 | `A tests/fixtures/test_fixture_ids_licensed.py` | **PORT** → `tests/fixtures/test_fixture_ids_licensed.py` | Licensing guard on shipped ids (`55a90a8`); pairs with entry 90 and protects entry 48's boundary. |
| 140 | `A tests/fixtures/test_fixture_slice.py` | **PORT** → `tests/fixtures/test_fixture_slice.py` | Slice integrity test. |
| 141, 142, 143 | `R100 tests/pipelines/layer2/__init__.py → tests/golden/__init__.py`, `A tests/golden/{compare,test_golden}.py` | **PORT** → `tests/golden/` | Golden-run comparator and NaN-drift surfacing (`8c81839`, `ff96e3a`, `59fe033`). Create `tests/golden/__init__.py` fresh — the rename source `tests/pipelines/layer2/` is already absent from `origin/main:tests/`. Baseline must be re-pinned against main. |
| 144, 145, 146 | `R100 tests/pipelines/outputs_processing/__init__.py → tests/integration/__init__.py`, `A tests/integration/{test_fixture_catalog_complete,test_fixture_run}.py` | **PORT** → `tests/integration/` | Fixture-environment regression harness (`f838f0f`, `063cf17`). Same rename note: create `__init__.py` fresh. `test_fixture_catalog_complete.py` must assert against main's 10 catalog keys. |
| 147, 148 | `R100 tests/pipelines/report_outputs/__init__.py → tests/pipelines/inputs_postproc/__init__.py`, `R079 tests/pipelines/layer1/test_pipeline.py → tests/pipelines/inputs_postproc/test_pipeline.py` | DROP-SUPERSEDED | Main has no postproc stage and no such test package; the file content is the Kedro 0.19.12 boilerplate placeholder with no tests in it (verified). Main's equivalent coverage is `origin/main:tests/pipelines/prepare_scenario_asset_and_company_inputs/test_nodes.py`. |
| 149, 150 | `D tests/pipelines/layer2/test_pipeline.py`, `D tests/pipelines/outputs_processing/test_pipeline.py` | DROP-SUPERSEDED | Both already absent from `origin/main:tests/`. Deletions already effective. |
| 151 | `A tests/pipelines/reporting/__init__.py` | DROP-SUPERSEDED | `origin/main:tests/pipelines/reporting/__init__.py` exists. |
| 152 | `R100 tests/pipelines/report_outputs/test_pipeline.py → tests/pipelines/reporting/test_pipeline.py` | DROP-SUPERSEDED | Verified: Kedro boilerplate placeholder, docstring only, zero tests. Main dropped the placeholders and `origin/main:tests/pipelines/reporting/` holds the real `test_reporting_ownership_keys.py` instead. |
| 153 | `A tests/test_capacity_flows_geography.py` | DROP-SUPERSEDED | `origin/main:tests/pipelines/calculate_asset_earnings/test_capacity_flows_geography.py` (main's `04bafcb`). |
| 154 | `A tests/test_ef_ffill_vectorized.py` | **ADJUDICATE** | Pins the EF forward-fill that main does not implement (row 110). Porting it would fail on main's `fillna(0.0)`; it can only follow row 110's ruling. |
| 155 | `A tests/test_frozen_capacity_vectorized.py` | **ADJUDICATE** | Characterises `create_frozen_capacity_at_retirement`, verified absent from main repo-wide. Main handles frozen capacity inside `calculate_asset_earnings` instead. Whether main's earnings-side logic needs the same guarantee is a model-owner question, not a mechanical port. |
| 156 | `A tests/test_mcpr_auto_fallback.py` | DROP-RETIRED | MCPR-specific test. Owner decision 1. |
| 157 | `A tests/test_npv_dropna_keys.py` | DROP-SUPERSEDED | `origin/main:tests/pipelines/calculate_asset_and_company_npv/test_npv_dropna_keys.py`. |
| 158 | `A tests/test_npv_vectorized_equivalence.py` | DROP-SUPERSEDED | `origin/main:tests/pipelines/calculate_asset_and_company_npv/test_npv_vectorized_equivalence.py`. |
| 159 | `A tests/test_ownership_allocation_scale.py` | DROP-SUPERSEDED | `origin/main:tests/pipelines/prepare_scenario_asset_and_company_inputs/test_ownership_allocation_scale.py`. |
| 160 | `A tests/test_prop_scale_retirement.py` | DROP-SUPERSEDED | `origin/main:tests/pipelines/allocate_company_trajectories_to_assets/test_prop_scale_retirement.py`. |
| 161 | `A tests/test_reporting_ownership_keys.py` | DROP-SUPERSEDED | `origin/main:tests/pipelines/reporting/test_reporting_ownership_keys.py`. |
| 162 | `A tests/test_retirement_mask_alignment.py` | **PORT** → `tests/pipelines/allocate_company_trajectories_to_assets/test_retirement_mask_alignment.py` | Main **has** the implementation fix (`validate="many_to_one"`, `_allocation_nodes.py:513-517`) but **not** the regression test — verified absent from `origin/main:tests/`. Exactly the shape the owner ruled on for ownership consolidation. Adapt imports to main's module paths. |
| 163 | `A tests/test_stagger_adjusted_splice.py` | DROP-SUPERSEDED | `origin/main:tests/pipelines/allocate_company_trajectories_to_assets/test_stagger_adjusted_splice.py`. |
| 164 | `A tests/test_tv_flow_row_dedup.py` | DROP-SUPERSEDED | `origin/main:tests/pipelines/calculate_asset_and_company_npv/test_tv_flow_row_dedup.py`. |
| 165 | `A tests/unit/__init__.py` | **PORT** → `tests/unit/__init__.py` | Package marker for the ported unit tests below; main has no `tests/unit/`. |
| 166 | `A tests/unit/test_build_export.py` | **PORT** → `tests/unit/test_build_export.py` | Pairs with entry 85. Note `7bd6d00`: this test must itself stay out of the export — preserve that exclusion in the ported allowlist. |
| 167 | `A tests/unit/test_capacity_flows.py` | **ADJUDICATE** | Characterisation test of the earnings capacity flows. It pins the branch's mask and 2% rate, which **contradict** main's mask and `replacement_capex_rate`. Cannot port until row 105 is ruled; porting as-is would fail on main. |
| 168 | `A tests/unit/test_dcf.py` | **ADJUDICATE** | Characterisation test of the DCF core including the `056d1f6` terminal-value and discount-spread behaviour that main does not have (row 131). |
| 169 | `A tests/unit/test_gen_param_docs.py` | **PORT** → `tests/unit/test_gen_param_docs.py` | Pairs with entry 87; update fixtures to main's six-file parameter layout. |
| 170 | `A tests/unit/test_mcpr_modes.py` | DROP-RETIRED | MCPR-specific test. Owner decision 1. |
| 171 | `A tests/unit/test_ownership_consolidation.py` | **PORT** → `tests/pipelines/prepare_scenario_asset_and_company_inputs/test_ownership_consolidation.py` | Owner decision 3, explicit: the implementation is superseded by main's `63f5b59`, but this regression test is not on main (verified absent from `origin/main:tests/`) and must be ported, adapted to main's module paths. |
| 172 | `A tests/unit/test_prepare_inputs.py` | **PORT** → `tests/unit/test_prepare_inputs.py` | Pairs with entry 89; carries `6ca15d1`'s cost-column and prefix-strip assertions. |

---

## 4. Commit ledger — 99 commits

Tags: **PORTED-VIA-FILES** (its content reaches main through PORT rows) ·
**RETIRED** (MCPR) · **SUPERSEDED** (main has an equivalent, or main removed the
target) · **REFERENCE-ONLY** (stays on the branch) · **ADJUDICATE** (blocked on a ruling).

```
765ed5f  PORTED-VIA-FILES   docs: point external users away from internal repo; naming + MCPR decisions
9c1f40f  PORTED-VIA-FILES   fix: company-id gate missed composite ids; name unscanned binaries
15f07a2  PORTED-VIA-FILES   docs: rewrite handover docs in house voice
b71f1a8  SUPERSEDED         fix: total each company's multiple stakes (port of main's own 63f5b59)
a8c0fa5  PORTED-VIA-FILES   chore: drop trisk.model submodule — .gitmodules stanza still dangling on main
4e6a423  REFERENCE-ONLY     docs: dual-review outcomes, incident log, open loops
59fe033  PORTED-VIA-FILES   test: pin asset-level values; assert the loud scenario_type drop
68e97ad  ADJUDICATE         docs: carbon-price strategy in catalog comment (ties to conf/base/catalog.yml)
012602e  PORTED-VIA-FILES   docs: say what replaces the internal tooling the PDF names
55a90a8  PORTED-VIA-FILES   test: guard shipped fixture slice against unlicensed ids
7dfc533  PORTED-VIA-FILES   fix: move company-id list out of shipped docs and gate on it
7bd6d00  PORTED-VIA-FILES   fix: keep the export-tooling test out of the export
3c0d8b0  PORTED-VIA-FILES   fix: extract zipped deliverables, ship pin_golden, test export tooling
063cf17  PORTED-VIA-FILES   test: guard fixture catalog against base-dataset drift
ff96e3a  PORTED-VIA-FILES   fix: surface NaN drift in golden compare; record snapshot sources
6ca15d1  PORTED-VIA-FILES   fix: require scenario cost columns; drop identity AR6_ prefix strip
04776c7  REFERENCE-ONLY     docs: consolidated implementation notes from swarm run
8b4d292  PORTED-VIA-FILES   docs: quickstart and troubleshooting fixes from fresh-machine verification
f69f7b8  PORTED-VIA-FILES   feat: allowlist export builder with sanitizer gate
05bd0ca  PORTED-VIA-FILES   docs: architecture diagram and data-flow map
10214bd  PORTED-VIA-FILES   docs: generated parameters reference and per-pipeline pages
134ba4e  PORTED-VIA-FILES   docs: executable walkthrough notebook on fixture slice
b5d0b94  PORTED-VIA-FILES   docs: mkdocs site with quickstart, user guide, troubleshooting
63691a9  PORTED-VIA-FILES   feat: official deliverables->model-input ingestion script
1259a10  SUPERSEDED         refactor: docstrings and type hints; repo-wide ruff clean (cosmetic)
b802a79  SUPERSEDED         refactor: split distribute_impacts nodes into modules
5a48631  SUPERSEDED         refactor: split reporting nodes into views/plots/exports
98c4308  ADJUDICATE         refactor: split earnings_model nodes (carries MCPR + divergent capacity mask)
272ef46  PORTED-VIA-FILES   refactor: annotated parameters (annotations only, not the single-file collapse)
f838f0f  PORTED-VIA-FILES   test: fixture-env regression harness running full pipeline on slice
689d312  PORTED-VIA-FILES   test: fixture slice uses extended scenario table + direct-ownership companies
64c2eb7  ADJUDICATE         test: characterization tests for MCPR (retired), capacity flows, DCF core
8c81839  PORTED-VIA-FILES   test: golden-run comparator and pinning script
2e35c9f  PORTED-VIA-FILES   test: add fixture slice builder and data
58c8a4d  REFERENCE-ONLY     docs: plan fixture pair uses WITCH scenarios present in working data
f8079ee  REFERENCE-ONLY     docs: ALTR handover package implementation plan
6de3ecd  SUPERSEDED         fix: grouping columns out of groupby.apply (main 4233c4b)
d963ec8  REFERENCE-ONLY     fix: AR6 cache-freshness — notebooks/run_all_scenarios_comparison.py only
3b71d83  SUPERSEDED         fix+perf: per-owner reporting keys and vectorized PV loops (main 51d1177)
aa1e10d  ADJUDICATE         fix+perf: geography half on main (04bafcb); EF ffill half absent from main
5ef65b2  SUPERSEDED         fix+perf: vectorize NPV trajectories; close silent-drop paths (main 20490a2)
484ba88  SUPERSEDED         fix: retirement zeroing + single-application retirement (main 2c554cc + validate=)
593059c  SUPERSEDED         fix: ownership capacity allocation percentage points (main c45103f)
2e4e694  REFERENCE-ONLY     docs: ALTR handover package design spec
a9f4cb5  SUPERSEDED         fix: collapse capex flow-split rows before terminal value (main 4dc3400)
5b307b8  RETIRED            docs: U0 measurement-apparatus section; inert dynamic-EF box (MCPR methodology)
896332a  RETIRED            fix: mcpr auto mode never resolves to merit_order_decline (OP9)
96e1e1a  RETIRED            feat: suite-combined MCPR v2 configs (its decks are REFERENCE-ONLY)
eccb4a7  REFERENCE-ONLY     docs: correct board field schema in AGENTS.md
816441c  REFERENCE-ONLY     docs: add AGENTS.md agent context
2c37bd2  REFERENCE-ONLY     docs: theia-ops phase 1 foundations implementation plan
6a2d862  REFERENCE-ONLY     docs: team roles, handover requirement, implementation strategy
190bee7  REFERENCE-ONLY     docs: theia-ops team-ops system design spec
7b7546a  RETIRED            fix: apply merit order decline to clearing price, not adjusted price
5ecdca6  RETIRED            fix: MCPR v2 — VRE baseline calc and carbon_explicit warning
49efb56  RETIRED            feat: MCPR v2 — two-mode price adjustment with auto-detection
31596a0  ADJUDICATE         fix: exclude retiring assets from replacement CapEx (THE named divergence)
056d1f6  ADJUDICATE         feat: comprehensive ALTR NPV direction fixes (MCPR sub-parts RETIRED)
7781306  SUPERSEDED         update readme
dce299a  SUPERSEDED         move files
b5f02f8  SUPERSEDED         ok
f24c834  SUPERSEDED         ok
90e10fa  SUPERSEDED         ok
5b11c20  SUPERSEDED         split retirment application
fc7cdc3  SUPERSEDED         wip
59f4964  SUPERSEDED         wip
873ff6c  SUPERSEDED         misc fixes
1fb459b  SUPERSEDED         fixes
805c8d2  SUPERSEDED         wip
e15110f  SUPERSEDED         fixx cconf
85d83a0  SUPERSEDED         update readme
13707f2  SUPERSEDED         add filtering on common geographies (main: common_geographies in _input_nodes)
f36cd6b  SUPERSEDED         minor fix
204e212  SUPERSEDED         some fixes, and auto select of companies in results_v1 notebook
4d33810  SUPERSEDED         Squashed commit of the following
3b9ffd4  SUPERSEDED         Squashed commit of the following
e33d748  SUPERSEDED         Squashed commit of the following
ba5e08e  SUPERSEDED         tiny fix
aa1dddf  SUPERSEDED         fix
f68c2d1  SUPERSEDED         refacto/cleaning
c7e255a  SUPERSEDED         Squashed commit of the following
d2ca5f6  SUPERSEDED         Results v1 kevin (#12)
3420626  SUPERSEDED         add ccs compatibility (main carries CCS handling)
be55926  SUPERSEDED         pipeline config + asset shock file (root script is REFERENCE-ONLY)
ac3d273  SUPERSEDED         fix staggered shock plot
1c0c86e  SUPERSEDED         re-enable scenarios interpolation
2072924  SUPERSEDED         staggered shock ok (#11)
836ce94  SUPERSEDED         fix performance in retirement_replacement_split_per_asset
dd8b52b  SUPERSEDED         Fix duplicate dcf.basis parameter between earnings and valuation
6315f25  SUPERSEDED         Removed depreciation due to slowness and redundance
c8d4100  SUPERSEDED         Implement linear interpolation for scenario data
23af34f  SUPERSEDED         Fix target_scenario to use actual target scenario_type
e8f3902  SUPERSEDED         Fix scenario names to match downloaded_scenarios.csv
b8210b2  SUPERSEDED         Remove duplicate shock_year and alignment_year parameters
4a7049e  SUPERSEDED         Fix missing shock_year and alignment_year parameters
4532bf8  SUPERSEDED         Fix restrictive asset filtering that prevented pipeline execution
8cdbd8e  SUPERSEDED         Replace financial_model with earnings_model (main: calculate_asset_earnings)
0131208  SUPERSEDED         Implement reporting pipeline (main: plot_transition_risk_results)
eb48531  REFERENCE-ONLY     load r pckg
```

Commit tag counts: SUPERSEDED 50 · PORTED-VIA-FILES 25 · REFERENCE-ONLY 12 ·
RETIRED 6 · ADJUDICATE 6. Total 99.

---

## 5. Counts

| Disposition | Entries |
|---|---:|
| PORT | 50 |
| DROP-SUPERSEDED | 57 |
| DROP-RETIRED | 6 |
| REFERENCE | 40 |
| NEVER-SHIP | 1 |
| ADJUDICATE | 18 |
| **Total** | **172** |

**every diff entry assigned: 172/172**

---

## 6. ADJUDICATE queue — 18 entries, 4 questions

The 18 entries collapse into four rulings. Nothing in the PORT set is blocked by them;
the migration can proceed and land these afterwards.

**Q1 — Replacement-CapEx and retirement masks in earnings capacity logic.**
Entries 105, 107, 109, 167. Main `(~is_synthetic) & (capacity_change > 0)` with a
parameterised `replacement_capex_rate`; branch `is_real & ~retirement_mask` with a
hardcoded 2% of `asset_trajectory`. Retirement masks also differ. `31596a0`.

**Q2 — The `056d1f6` NPV-direction feature set.**
Entries 9, 11, 13, 16, 18, 108, 117, 118, 131, 132, 168. Stranding-aware terminal
value, finite-annuity double-discount fix, brown/green discount spreads, price ramp,
dynamic marginal EF, differential carbon-price injection. Verified **zero** trace on
main. Main's parameters deliberately disable replacement CapEx and decom costs.
This is a large deliberate model-behaviour change main's maintainers have not taken.

**Q3 — Emission-factor forward fill vs zero fill.**
Entries 110, 154. Branch forward-fills EFs within a series (`aa1e10d`); main sets
missing EFs to `0.0`. Different numbers, not just different code.

**Q4 — Frozen capacity at retirement.**
Entry 155. `create_frozen_capacity_at_retirement` does not exist on main; main
handles frozen capacity inside `calculate_asset_earnings`. Whether main's
implementation needs the branch's vectorisation guarantee is a model question.

---

## 7. Notes for the executing session

- The ledger is read-only with respect to git state. Nothing here has been committed.
- PORT rows touching `docs/` all require the §2.2 naming rewrite. Do not copy any
  handover document verbatim.
- Export tooling (85, 86, 90) and the shipped PDF (23) must name the external repo
  `altr-model-refactored`. The name `altr-model` now resolves to the internal repo,
  so a stale reference silently points recipients at private code.
- Entry 48 is the hard boundary: `docs/research/company_id_archive_2026.md` never
  ships, and the guard that enforces it (entry 90) must land before any export runs.
- Main carries three fixes the branch lacks — `13540c1` (shock-anchor clamp),
  `b9ca656` (co-owner plot slicing), `7cf6544` (dtype stabilisation). No port may
  overwrite them; this is the main reason the `src/` refactor-splits are dropped
  rather than applied.
