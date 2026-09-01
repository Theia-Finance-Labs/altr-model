# Migration Disposition Ledger — `feat/handover-package` → `origin/main`

**Version:** v2 (revised against two independent reviews). See §9 CHANGELOG.
**Date:** 2026-09-01
**Scope frozen at:** `source_sha = 397f26f` — the ledger describes this exact tree and no other.
**Merge base:** `91c0a7f`
**Source:** `feat/handover-package` @ `397f26f` (pre-migration, `src/crispy_kedro/`, 9 pipelines, poetry.lock)
**Target:** `origin/main` @ `63f5b59` = `Theia-Finance-Labs/altr-model` (post-migration, `src/altr_model/`, 6 pipelines, uv.lock)
**Scope:** every one of the **173** entries in `git diff --name-status 91c0a7f..HEAD`, plus all **101** branch commits.

This ledger exists because two prior reviewers failed the previous plan for leaving
~40 files with no assigned fate. Every entry below carries a disposition. Where a
disposition could not be established from evidence, the entry is **ADJUDICATE** —
never a guess.

The ledger is itself inside its own scope: entry 54 is this file, and commits
`7a9f647` (this ledger) and `397f26f` (the notes update) carry dispositions like
any other. Both are REFERENCE — migration bookkeeping, not migrated content.

> **Renumbering notice (v1 → v2).** Entry numbers are line numbers in
> `git diff --name-status 91c0a7f..HEAD`, which sorts by path. Adding this file at
> `docs/superpowers/plans/migration-disposition-ledger.md` inserts it at **line 54**,
> not at the end. Every v1 entry numbered 54 or higher has therefore shifted **+1**
> in v2 (v1 `96–103` → v2 `97–104`; v1 `155` → v2 `156`; v1 `85, 86, 87, 90` →
> v2 `86, 87, 88, 91`). Entries 1–53 are unchanged. Verified line-by-line against
> the frozen diff.

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
   name must be updated on port — flagged on entries 86, 87, 91 and 23.
3. **Ownership consolidation.** Implementation superseded by main's own
   (Bertrand's) `63f5b59`; the regression test `tests/unit/test_ownership_consolidation.py`
   is **not** on main and **is** ported, adapted to main's module paths (entry 172).

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
- **Frozen capacity was removed from main deliberately, not by omission.**
  `origin/main:tests/test_run.py:17-25` defines `REMOVED_DATASETS`, which lists
  `frozen_capacity_at_retirement`, and
  `test_default_pipeline_has_no_dead_private_or_removed_datasets` asserts the default
  pipeline's datasets do **not** intersect that set. Main still has frozen-capacity
  *logic* inside `calculate_asset_earnings/nodes.py:460,521,525` — it is the
  allocation-stage **dataset and its producing node** that main retired. On the
  branch, `distribute_impacts_to_asset_level/retirement.py:123` creates
  `create_frozen_capacity_at_retirement`, `nodes.py:18` re-exports it, and
  `pipeline.py:106-114` **wires** it as the node `create_frozen_capacity` producing
  `outputs="frozen_capacity_at_retirement"`. Porting that back would fail main's own
  guard test. This is why rows 100–102 are split rather than dropped wholesale.
- **Every other function in the branch's `distribute_impacts` split exists on main**
  (checked by name against `origin/main -- src/`):
  `flag_phased_out_assets_as_retired`, `compute_asset_baseline_trajectories`,
  `split_late_sudden_trajectories_by_alignment_type`,
  `concatenate_staggered_shock_results`, `melt_asset_staggered_trajectories`,
  `stagger_decreasing_technologies`, `stagger_increasing_technologies` — all present in
  `allocate_company_trajectories_to_assets/{nodes,_allocation_nodes}.py`.
  `create_frozen_capacity_at_retirement` is the **only** absentee.
- `origin/main:src/.../calculate_asset_and_company_npv/nodes.py:348,393,432` computes
  `npv_change` as `(latesudden − baseline) / abs(baseline)` — **identical** to the
  branch's definition. The `npv_change` sign-convention prose in the handover docs is
  therefore portable as-is and is **not** gated on Q2.
- `origin/main:tests/test_run.py` is a **data-free** test: it calls `bootstrap_project`
  + `register_pipelines` and asserts on pipeline names, namespaces, dataset contracts
  and node names. It reads no data file. See row 86.
- `scripts/gen_param_docs.py:145-147` globs `parameters*.yml` and treats
  `parameters.yml` as an optional entry-point file
  (`[entry] if entry in files else []`) — it already tolerates that file's absence, so
  it runs against main's six-file layout without code change. Only its module-docstring
  prose (lines 44-53, which names `conf/base/parameters.yml` and
  `mcpr_regional_value_factors:`) needs rewriting. See row 88.
- `tests/fixtures/test_fixture_ids_licensed.py` checks **only** the two fixture CSVs
  (`data/downloaded_assets.csv`, `data/downloaded_companies.csv`) and carries
  `pytestmark = pytest.mark.skipif(...)` on `ALTR_DELIVERABLES_DIR` — it **skips**,
  silently, when the variable is unset. Both facts drive §4.
- `AGENTS.md` does not appear in `scripts/export_allowlist.txt` (verified) — it is
  already outside the export boundary and must stay there. See row 4.
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

## 3. Diff ledger — 173 entries

Entry numbers are line numbers in `git diff --name-status 91c0a7f..HEAD` at
`source_sha = 397f26f`. Status codes: A add, M modify, D delete, R rename.

**PORT-PARTIAL** means the file ports now, but named sections inside it are tagged to
an open gate: they are deleted on port (MCPR, retired outright) or left out and
rewritten once the gate is ruled (Q1/Q2/Q4). A PORT-PARTIAL file is never copied whole.

### 3.1 Root and configuration

| # | Path(s) | Disposition | Target / reason |
|---|---|---|---|
| 1 | `A .cursorignore` | DROP-SUPERSEDED | `origin/main:.cursorignore` is byte-identical (verified by diff). |
| 2 | `M .gitmodules` | **PORT** → `.gitmodules` | Main deleted `pkg/trisk.model` in `9d7e195` but `origin/main:.gitmodules` still declares the submodule. Branch `a8c0fa5` empties it. Real cleanup main lacks. |
| 3 | `M .vscode/launch.json` | DROP-SUPERSEDED | `origin/main:.vscode/launch.json` already has the equivalent debug entry, pointing at `src/altr_model/bigquery_marts_downloader.py`. The branch entry targets `--tags=download_inputs`, a pipeline main does not have. |
| 4 | `A AGENTS.md` | **PORT-ADAPTED** → `AGENTS.md` (internal main only) | Main should carry agent context; the branch file is the only version that exists. It ports as a **rewrite, not a copy** — every fact in it is stale: repo name `crispy-kedro` → `altr-model`; `poetry install` / `poetry run kedro run` / `poetry run pytest` → the uv equivalents; the `MCPR/`, `pkg/` and `workspace/` layout entries are gone (MCPR retired, submodule deleted in `9d7e195`); `src/` must name main's six pipelines per §2.2. The team rules (Theia Team Board fields, Bertrand-first technical review, never-delete-files) carry over and should be restated as current. **NEVER shipped externally:** verified absent from `scripts/export_allowlist.txt` and it must stay absent — recipients never receive agent or board context. Do not add it to the allowlist when porting row 87. |
| 5 | `A ALTR_NPV_Direction_Fix_Research.md` | REFERENCE | Internal research note backing `056d1f6`, whose implementation is ADJUDICATE. Not a deliverable; keep with the branch that holds the code it argues for. |
| 6 | `A MCPR/ALTR_MCPR_methodology_v1.md` | DROP-RETIRED | Owner decision 1. |
| 7 | `M README.md` | **PORT (partial)** → `README.md` | Port only the handover-docs pointer (docs site + `docs/handover/`), rewritten to uv and `src/altr_model/`. The poetry / `crispy_kedro` prose is superseded by `origin/main:README.md`, already ALTR-branded and uv-based. |
| 8 | `A SKIP_FIX.txt` | REFERENCE | Cloud Run `kedro-viz` deploy incident record, explicitly "not a repo defect". Already deleted in the working tree. |
| 9 | `M conf/base/catalog.yml` | **ADJUDICATE** | Mixed. (a) `ar6_carbon_prices` dataset + per-IAM carbon-price strategy comment belong to the `056d1f6` carbon-price-injection feature set, absent from main. (b) `bertrand_marts`→`bertrand2_marts` is `download_inputs` scope, superseded by main's `bigquery_marts_downloader.py`. (c) Path/layer renumbering superseded by main's own 10-dataset catalog. **Ruling needed on (a) only.** |
| 10, 12 | `M conf/base/parameters.yml`, `M conf/base/parameters_distribute_impacts_to_asset_level.yml` | **PORT (annotations only)** → main's six `conf/base/parameters_*.yml` | Unambiguously: **main keeps its six per-pipeline parameter files. No consolidated `conf/base/parameters.yml` is created on main — not now, not as a follow-up.** What ports is `272ef46`'s **annotations only**: the explanatory comments, units, value domains and literature references written against each key. They are copied onto the *same key where it already lives* in main's six files (verified list in §2.2 and below); the branch's single-file collapse is **not** ported. Row 88 (`gen_param_docs.py`) reads those **six** files and needs no consolidated file to exist. **Keys that get NO annotation port** (branch key absent from all six of main's files, verified): `enable_mcpr` and `mcpr_mode` — the whole MCPR block at `conf/base/parameters.yml:60-77`, DROP-RETIRED under owner decision 1, along with the advanced MCPR knobs in `parameters_earnings_model.yml` (row 13); `price_ramp` (`parameters.yml:82-85`) — Q2, absent from main repo-wide; `ownership_type` (`parameters.yml:46-48`) — main removed it in `bdcd8c3` and it survives on main only as a docstring word in `_input_nodes.py:127`, so there is no key to annotate. Everything else in `parameters.yml` has a home on main: `baseline_scenario`, `target_scenario`, `company_ids`, `ccs_on`, `max_forecast_horizon` → `parameters_prepare_scenario_asset_and_company_inputs.yml`; `shock_year`, `alignment_year` → `parameters_calculate_company_trajectories.yml`; `market_passthrough`, `include_growth_capex`, `include_replacement_capex`, `include_decom_costs` → `parameters_calculate_asset_earnings.yml`. Note the reverse gap too: main's `replacement_capex_rate`, `apply_continued_om_baseline`, `apply_continued_om_shock` and `reduce_granularity_from_asset_to_company_level` have **no branch annotation to inherit** and need new ones written. |
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
| 25, 36, 37 | `A docs/handover/index.md`, `scenario_catalog.md`, `troubleshooting.md` | **PORT** → same paths | Core handover package, no gated behaviour: greps for `mcpr`, `price_ramp`, `strand`, `frozen`, `dynamic_marginal_ef`, `green_spread`, `brown_spread` return **zero** hits in all three. Apply the global naming rewrite only. |
| 26 | `A docs/handover/parameters.md` | **PORT (regenerate)** → `docs/handover/parameters.md` | Generated by `scripts/gen_param_docs.py` (row 88). Its 16 gated-term hits are **self-resolving**: regenerating against main's six parameter files emits only main's keys, so no MCPR or Q2 key can survive. **Regenerate — never copy.** Verify afterwards that the output contains no `mcpr*` or `price_ramp` row. |
| 35 | `A docs/handover/quickstart.md` | **PORT-PARTIAL** → `docs/handover/quickstart.md` | Structure and commands port now (rewritten to uv and `src/altr_model/`). Gated sections: **`### The fourth file: carbon prices` (lines 83-111, whole section) → Q2** — it documents the `ar6_carbon_prices` catalog entry, the root-level `6_final_AR6_viable_scenarios.csv` and the carbon-price injection, the feature set on row 9(a) that is absent from main; the section is omitted on port and rewritten only if Q2 rules it in. **`## 5. Choose the run configuration` (line 138) → MCPR, delete on port**: the bullet lists "MCPR settings and cost switches" — strike the MCPR clause, keep the cost switches. |
| 38 | `A docs/handover/user_guide.md` | **PORT-PARTIAL** → `docs/handover/user_guide.md` | Structure ports now. **`## Changing one thing at a time` (line 173) → MCPR, delete on port**: it names `enable_mcpr` / `mcpr_mode` as the knobs with the most interpretable effect on the headline number; that recommendation must be replaced with a knob main actually has. **Not gated:** `## Reading the sign of npv_change` (lines 105-146) and the `npv_change` definitions at lines 80, 91, 165 — verified identical on main (`nodes.py:348,393,432`), so they port unchanged. |
| 24 | `A docs/handover/architecture.md` | **PORT-PARTIAL** → `docs/handover/architecture.md` | Structure and the stage map port now. Gated sections, both **Q4**: **`## Data flow` (line 45)** — the mermaid edge `S5 -->|"asset_level_staggered_shock_melted<br>frozen_capacity_at_retirement"| S6` draws a dataset main retired; and **`## What crosses stage boundaries` (line 98)** — the table row for `frozen_capacity_at_retirement` (stage 5 → 6). Both must be removed on port and restored only if Q4 rules the dataset back in; leaving them would document a dataset main's `test_run.py` asserts does not exist. |
| 27–34 | `A docs/handover/pipelines/{create_baseline_and_target_trajectories, create_late_sudden_trajectories, distribute_impacts_to_asset_level, earnings_model, inputs_postproc, inputs_processing, reporting, valuation_model}.md` | **PORT (renamed + merged)** → `docs/handover/pipelines/` | Eight branch pages collapse onto main's six pipelines: `create_baseline_and_target_trajectories.md` + `create_late_sudden_trajectories.md` → `calculate_company_trajectories.md`; `distribute_impacts_to_asset_level.md` → `allocate_company_trajectories_to_assets.md`; `earnings_model.md` → `calculate_asset_earnings.md`; `valuation_model.md` → `calculate_asset_and_company_npv.md`; `reporting.md` → `plot_transition_risk_results.md`; `inputs_processing.md` → `prepare_scenario_asset_and_company_inputs.md`, into which `inputs_postproc.md` is folded (main absorbed that stage). **Three of the eight are PORT-PARTIAL** (the other five — `create_baseline_and_target_trajectories.md`, `create_late_sudden_trajectories.md`, `inputs_postproc.md`, `inputs_processing.md`, `reporting.md` — grep clean for every gated term and port whole):<br>**`earnings_model.md` → `calculate_asset_earnings.md`** — the heaviest. MCPR sections, **delete on port**: `## Purpose` lines 15 and 22 (the MCPR adjustment and `mcpr_mode` clauses), the three `## Nodes` rows for `build_scenario_surfaces`, `compute_scenario_vre_share`, `apply_mcpr_adjustment` (all `mcpr.py`, line 51-53), the `## Parameters read` rows at lines 73, 76, 77 and the MCPR half of line 81, and the MCPR clause of `## Methodology reference` line 89-91. Q1/Q2 sections, **rewrite after ruling**: `price_ramp` (line 73), `dynamic_marginal_ef` / `carbon_cost_method` (line 79), and the `## Consumes` row for `frozen_capacity_at_retirement` (line 31) which is **Q4**. Once the MCPR and Q2 rows are struck, the `## Nodes` table must match main's five earnings nodes, which `origin/main:tests/test_run.py` pins exactly.<br>**`valuation_model.md` → `calculate_asset_and_company_npv.md`** — Q2 sections, rewrite after ruling: `## Purpose` line 20 (the `stranding_aware_tv` three-way terminal-value split), `## Parameters read` lines 71-72 (`dcf.stranding_aware_tv`, `dcf.stranding_consecutive_years` — neither exists in `origin/main:conf/base/parameters_calculate_asset_and_company_npv.yml`, which has only `discount_rate_baseline`, `discount_rate_shock` and `terminal_value.{method,g_real_default}`), and `## Methodology reference` line 85 (discount spreads + stranding-aware TV). The `npv_change` references at lines 38, 42-43 are **not** gated and port as-is.<br>**`distribute_impacts_to_asset_level.md` → `allocate_company_trajectories_to_assets.md`** — Q4 sections: the `## Produces` row for `frozen_capacity_at_retirement` (line 35) and the `## Nodes` row for `create_frozen_capacity_at_retirement` (line 54). Both describe exactly the node and dataset main retired (rows 100-102); remove on port, restore only if Q4 rules them in. |

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
| 49, 56 | `A docs/superpowers/plans/2026-04-14-mcpr-v2-redesign.md`, `A docs/superpowers/specs/2026-04-14-mcpr-v2-redesign.md` | DROP-RETIRED | MCPR design documents. Owner decision 1. |
| 50, 51, 52, 53, 55, 57, 58 | `A docs/superpowers/plans/{2026-07-06-altr-reconciliation-and-effectiveness-plan, 2026-07-07-theia-ops-phase-1-foundations, 2026-08-31-altr-handover-package, implementation-notes-handover}.md`, `A docs/superpowers/specs/{2026-04-13-fullef-batch-rerun-design, 2026-07-07-team-ops-system-design, 2026-08-31-altr-handover-package-design}.md` | REFERENCE | Internal planning artefacts and session notes. `implementation-notes-handover.md` is the running deviation log for this very migration and must stay with the branch that produced it. Externals receive product docs, not plans; main carries no `docs/` tree at all. |
| 54 | `A docs/superpowers/plans/migration-disposition-ledger.md` | REFERENCE | **This file.** Migration bookkeeping: it describes the port, it is not part of it. Added by `7a9f647` and revised here; sorts into the diff at line 54, which is why entries 54+ are renumbered (see the header notice). It stays on `feat/handover-package` with the other planning artefacts — main receives the migrated content, not the record of how the migration was decided, and externals receive neither. |
| 59 | `A mkdocs.yml` | **PORT** → `mkdocs.yml` | Rewrite `nav:` to the renamed pipeline pages from rows 27–34; set `site_name`/`repo_url` for the external repo `altr-model-refactored`. |

### 3.5 Notebooks

| # | Path(s) | Disposition | Target / reason |
|---|---|---|---|
| 60, 61, 62 | `A notebooks/analyze_fullef_comparison.py`, `clean_input_data.R`, `cleaning_summary.xlsx` | REFERENCE | Internal one-off analysis and cleaning artefacts; not in the export allowlist, no counterpart needed on main. |
| 63 | `D notebooks/countries_discount_rate.csv` | DROP-SUPERSEDED | Already absent from `origin/main:notebooks/` (which holds only `.gitkeep`, `example_company_selection.csv`, `example_run_configurations.yml`, `generate_results.ipynb`, `run_kedro_batch.py`, `scenario_utils.py`, `streamlit_app.py`). Deletion already effective. |
| 64 | `A notebooks/generate_results.ipynb` | DROP-SUPERSEDED | `origin/main:notebooks/generate_results.ipynb` exists (15 KB, outputs stripped) and main tuned it further in `62e6ba2`/`970362e`. The branch file is 818 KB of embedded outputs. |
| 65 | `A notebooks/run_all_scenarios_comparison.py` | REFERENCE | Internal scenario-comparison batch harness. **This is where `d963ec8` (AR6 cache-freshness) lives** — it is not a `src/` fix. Main's batch runner is `notebooks/run_kedro_batch.py`, a different tool with no such cache; the file is not in the export allowlist. Its state is frozen at `397f26f` like every other entry; working-tree edits made after that sha are out of scope for this ledger. |
| 66, 67, 68, 77, 78, 79, 80, 81 | `A notebooks/scripts/{beforeafter_compatible_scenario, comparison_times2price_vs_ratio, find_same_start_scenarios}.ipynb`, `scenario_distance_analyzer.py`, `{scenarios_pathways_clean_price_ratio, scenarios_with_carbontax, statdesc_scenarios_data, unique_valid_scenarios_and_providers}.ipynb` | REFERENCE | Exploratory scenario-analysis notebooks. Internal only; excluded from the export allowlist, which ships `notebooks/walkthrough.ipynb` alone. |
| 69 | `R100 tests/pipelines/layer1/__init__.py → notebooks/scripts/gather_combined_results.R` | REFERENCE | Rename artefact: git paired a deleted empty `__init__.py` with a new R script. Both halves resolve here — main has no `tests/pipelines/layer1` package (already gone), and the R results-gathering script is internal tooling. |
| 70, 71, 72, 73 | `A notebooks/scripts/{gather_npv_results, gather_prod_and_financial_trajs, results_cleaning, results_confirming}.R` | REFERENCE | Internal R post-processing harness; no R tooling on main, none shipped externally. |
| 74, 75, 76 | `R100 notebooks/run_trisk_with_R.R → notebooks/scripts/run_trisk_with_R.R`, `run_trisk_with_R_local.R → scripts/run_trisk_with_R_local.R`, `run_trisk_with_python.ipynb → scripts/run_trisk_with_python.ipynb` | REFERENCE | Pure relocation of the internal trisk harness. Main **deleted the pre-rename originals** during its cleanups — `origin/main:notebooks/` has none of them — so porting the rename would re-add files main deliberately removed. |
| 82 | `A notebooks/walkthrough.ipynb` | **PORT-PARTIAL** → `notebooks/walkthrough.ipynb` | Executable walkthrough on the fixture slice (`134ba4e`); explicitly in the export allowlist. Structure ports now — re-point every pipeline, dataset and parameter name to main's naming and **re-execute** against main's fixture environment (a stale execution is worse than none, since the notebook ships with outputs). MCPR sections, **delete on port**: **cells 22, 23, 24** are the entire `### Experiment A — mcpr_mode` block — cell 22 explains MCPR and `mcpr_mode`, cell 23 runs `run_altr(mcpr_mode="merit_order_decline")`, cell 24 interprets the null result via `mcpr_floor_at_iam_price`. None of that resolves on main; the parameter experiment needs a replacement knob (a cost switch or a discount rate) chosen when the notebook is re-executed. Also strike the MCPR clause in **cell 14** (`### Checkpoint 5 — earnings`, "the MCPR step"). **Not gated:** cells 18, 19, 21 — the `npv_change` sign convention and the company/asset NPV reads — verified identical on main. |

### 3.6 Packaging

| # | Path(s) | Disposition | Target / reason |
|---|---|---|---|
| 83 | `D pkg/trisk.model` | DROP-SUPERSEDED | Main removed the submodule in `9d7e195`; `pkg/` is absent from the `origin/main` tree. (The leftover `.gitmodules` stanza is handled by row 2.) |
| 84 | `M poetry.lock` | DROP-SUPERSEDED | Main migrated to uv: `origin/main:uv.lock` exists, no `poetry.lock`. |
| 85 | `M pyproject.toml` | **PORT (partial)** → `pyproject.toml` | Port only the docs/test tooling: the mkdocs dependency group, `ruff`, and the pytest/ruff tool configuration, translated into main's uv `[dependency-groups]`. The poetry build-system, project name and `crispy_kedro` packaging are superseded by `origin/main:pyproject.toml` (name `altr-model`, uv-managed). Also drop `poetry.lock` from the ported export allowlist in favour of `uv.lock`. |

### 3.7 Export and helper scripts — all PORT

Main has no `scripts/` directory; the whole block is new there.

| # | Path(s) | Disposition | Target / reason |
|---|---|---|---|
| 86 | `A scripts/build_export.py` | **PORT** → `scripts/build_export.py` | **Update the external repo name to `altr-model-refactored`.** Rewrite `SKIP_RELATIVE` / `SKIP_DIR_NAMES` and the package-rename logic for `src/altr_model/`; the `download_inputs` carve-outs no longer apply (main has no such pipeline) and must be replaced by whatever exclusion `bigquery_marts_downloader.py` needs. **`SKIP_RELATIVE` re-evaluation — `tests/test_run.py` (line 45).** Its exclusion comment reads "Full-input smoke test: needs the internal data drop, so it can only fail for a recipient." **That justification is false on main.** `origin/main:tests/test_run.py` is a **data-free pipeline-registration test**: it calls `bootstrap_project` + `register_pipelines` and asserts on pipeline names, per-pipeline namespaces, the narrow public dataset contracts, the visible methodology node names, and `REMOVED_DATASETS` — it opens no data file and would pass for a recipient. (The branch file it was written about is a different thing entirely: a Kedro template placeholder expecting `"Pipeline contains no nodes"`.) On port, **re-evaluate this exclusion and default to shipping it** — it is exactly the kind of structural test a recipient benefits from, and it is the guard that would catch a re-introduced `frozen_capacity_at_retirement` (rows 100-102, Q4). The other three `SKIP_RELATIVE` entries keep their justification: `tests/unit/test_build_export.py` and `tests/fixtures/test_fixture_ids_licensed.py` genuinely cannot run outside this repo, and the `download_inputs` paths do not exist on main. |
| 87 | `A scripts/export_allowlist.txt` | **PORT** → `scripts/export_allowlist.txt` | **Update the external repo name to `altr-model-refactored`** in the header comment. Rewrite every path: `src/crispy_kedro/`→`src/altr_model/`, drop the `download_inputs` and `parameters_download_inputs.yml` carve-outs, replace `poetry.lock` with `uv.lock`, and re-point `conf/base/` at main's six parameter files. |
| 88 | `A scripts/gen_param_docs.py` | **PORT** → `scripts/gen_param_docs.py` | Reads main's **six** per-pipeline `conf/base/parameters_*.yml`; no consolidated `parameters.yml` is created on main (row 10). The code already supports this: `collect()` at lines 145-147 globs `parameters*.yml` and treats `parameters.yml` as optional (`[entry] if entry in files else []`), so it runs unchanged against six files. What must change is the **module-docstring prose** at lines 44-53, which tells the reader `conf/base/parameters.yml` "holds the run configuration you normally touch" and names `mcpr_regional_value_factors:` as an example nested block — both false on main. Rewrite that prose to describe the six-file layout and name a nested block main has (`dcf:`, `reporting:`, `staggered_shock:`). |
| 89 | `A scripts/pin_golden.py` | **PORT** → `scripts/pin_golden.py` | Golden-baseline pinning; shipped so recipients can pin their own (`3c0d8b0`). |
| 90 | `A scripts/prepare_inputs.py` | **PORT** → `scripts/prepare_inputs.py` | Official-deliverables ingestion (`63691a9`). **Carries `6ca15d1`** — scenario cost-column validation and removal of the identity `AR6_` prefix strip. Verified absent from main, which has no `scripts/` at all. This is one of the flagged fixes; it ports as tooling, not as a `src/` change. |
| 91 | `A scripts/sanitize_check.py` | **PORT** → `scripts/sanitize_check.py` | Sanitizer gate (`f69f7b8`, `7dfc533`, `9c1f40f`, including the composite-company-id fix). This is the guard that keeps entry 48 out of the export; **update the external repo name to `altr-model-refactored`** wherever it appears. |

### 3.8 `src/` — modified files main has since relocated

| # | Path(s) | Disposition | Target / reason |
|---|---|---|---|
| 92 | `M src/crispy_kedro/pipeline_registry.py` | DROP-SUPERSEDED | `origin/main:src/altr_model/pipeline_registry.py` registers its own six pipelines. The branch's nine-pipeline registry (MCPR-era earnings, `inputs_postproc`, `download_inputs`) has no place on main. Branch change is `272ef46` only. |
| 93, 94 | `M src/crispy_kedro/pipelines/create_baseline_and_target_trajectories/{nodes,pipeline}.py` | DROP-SUPERSEDED | `origin/main:src/altr_model/pipelines/calculate_company_trajectories/_baseline_nodes.py` + `pipeline.py` carry the equivalent, including CCS handling (`" - w/ CCS"` present in main's `prepare_scenario_asset_and_company_inputs/_input_nodes.py`). Branch-unique content is `1259a10` docstring/ruff formatting — cosmetic. |
| 95, 96 | `M src/crispy_kedro/pipelines/create_late_sudden_trajectories/{nodes,pipeline}.py` | DROP-SUPERSEDED | `origin/main:.../calculate_company_trajectories/_late_sudden_nodes.py`. The one substantive branch touch here (`a9f4cb5`) is on main as `4dc3400`; main additionally has `13540c1` (shock-anchor clamp), which the branch lacks — porting backwards would regress it. |

> **Rows 97–104 were a single DROP-SUPERSEDED row in v1. A reviewer verified the
> equivalence claim does not hold for all of it**, so the block is split. Main's
> `allocate_company_trajectories_to_assets/{nodes.py,_allocation_nodes.py}` carries the
> behaviour of every branch function here **except** `create_frozen_capacity_at_retirement`,
> which main removed **deliberately** — `origin/main:tests/test_run.py` lists
> `frozen_capacity_at_retirement` in `REMOVED_DATASETS` and asserts the default pipeline
> does not produce it. The branch does not merely define that function, it **wires** it.
> The equivalent parts stay DROP-SUPERSEDED; the creation and the wiring move to Q4.

| # | Path(s) | Disposition | Target / reason |
|---|---|---|---|
| 97, 98, 99, 103, 104 | `A .../distribute_impacts_to_asset_level/{_shared,assembly,baseline,staggering_decrease,staggering_increase}.py` | DROP-SUPERSEDED | Every function in these five modules is verified present on main by name in `allocate_company_trajectories_to_assets/{nodes,_allocation_nodes}.py`: `_allocate_reduction_with_caps_array`/`_index_assets_by_group` (97), `split_late_sudden_trajectories_by_alignment_type`, `concatenate_staggered_shock_results`, `melt_asset_staggered_trajectories` (98), `compute_asset_baseline_trajectories` (99), `stagger_decreasing_technologies` (103), `stagger_increasing_technologies` (104). Main additionally carries single-application retirement (`2c554cc`), retirement-mask alignment via `validate="many_to_one"` at `_allocation_nodes.py:513-517`, the grouping-columns fix (`4233c4b`), and main-only `b9ca656` + `7cf6544`. The `b802a79` module split is cosmetic; applying it would discard main's later fixes. |
| 100 | `M .../distribute_impacts_to_asset_level/nodes.py` | **SPLIT — DROP-SUPERSEDED + ADJUDICATE Q4** | Facade re-exporting the split modules; superseded by main's `nodes.py` except **line 18**, which re-exports `create_frozen_capacity_at_retirement` into the pipeline's public surface. That single import follows Q4 with rows 101-102. |
| 101 | `M .../distribute_impacts_to_asset_level/pipeline.py` | **SPLIT — DROP-SUPERSEDED + ADJUDICATE Q4** | The node graph is otherwise superseded by main's own `pipeline.py` for `allocate_company_trajectories_to_assets`. **The one part that is not: lines 106-114**, the node `name="create_frozen_capacity"` running `create_frozen_capacity_at_retirement` with `outputs="frozen_capacity_at_retirement"`. **This is the wiring, and it is what makes Q4 a live question rather than a dormant one** — the dataset is produced and handed to stage 6. Adding this node to main would fail `test_default_pipeline_has_no_dead_private_or_removed_datasets`. → **ADJUDICATE Q4**. |
| 102 | `A .../distribute_impacts_to_asset_level/retirement.py` | **SPLIT — DROP-SUPERSEDED + ADJUDICATE Q4** | Two of three functions are **DROP-SUPERSEDED**: `flag_phased_out_assets_as_retired` (line 15) is on main in `_allocation_nodes.py`/`nodes.py`, and `_build_retirement_map` (line 99) is its private helper. **`create_frozen_capacity_at_retirement` (lines 123-320) → ADJUDICATE Q4**: verified zero hits on main, and main's removal is deliberate, not accidental. Do not port it as part of the mechanical migration. |
| 105 | `M src/crispy_kedro/pipelines/download_inputs/nodes.py` | DROP-SUPERSEDED | Main has no `download_inputs` pipeline (`origin/main:src/altr_model/pipeline_registry.py` registers six, none of them download); ingestion lives in `origin/main:src/altr_model/bigquery_marts_downloader.py`. Branch change is `1259a10` docstrings only. The export tooling excludes this pipeline anyway. |
| 106 | `A src/crispy_kedro/pipelines/earnings_model/capacity.py` | **ADJUDICATE** | **The named divergence.** Replacement mask: main `(~is_synthetic) & (capacity_change > 0)` vs branch `is_real & ~retirement_mask`. Retirement mask: main `capacity_change < 0` vs branch `(capacity_change < 0) & is_real`. Rate: main parameterised `replacement_capex_rate` (0.05) applied to `capacity_change` vs branch hardcoded `asset_trajectory * 0.02`. Three coupled behaviour changes from `31596a0` + `056d1f6`; model owner must rule. |
| 107 | `A src/crispy_kedro/pipelines/earnings_model/mcpr.py` | DROP-RETIRED | Owner decision 1. |
| 108 | `M src/crispy_kedro/pipelines/earnings_model/nodes.py` | **ADJUDICATE** | Mixed. MCPR re-exports are DROP-RETIRED; the geography-safe capacity-flow half of `aa1e10d` is superseded by main's `ASSET_SERIES_KEYS` + `04bafcb`; the remainder is `31596a0` + `056d1f6`, both open. Target if ruled in: `src/altr_model/pipelines/calculate_asset_earnings/nodes.py`. |
| 109 | `A src/crispy_kedro/pipelines/earnings_model/ops.py` | **ADJUDICATE** | `056d1f6` operating logic: continued O&M on stranded fossil capacity, differential carbon-cost injection, price ramp, dynamic marginal EF. Verified zero trace on main. |
| 110 | `M src/crispy_kedro/pipelines/earnings_model/pipeline.py` | **ADJUDICATE** | Wires both the retired MCPR nodes and the `056d1f6` parameters; cannot be split until 105/107/108 are ruled. |
| 111 | `A src/crispy_kedro/pipelines/earnings_model/validation.py` | **ADJUDICATE** | Duplicate-year and continuity checks are already on main (`calculate_asset_earnings/nodes.py:37-95`). The open part is the emission-factor **forward fill** (`aa1e10d`, `validation.py:134`): main has no `ffill` anywhere in `calculate_asset_earnings` and instead sets missing EFs to `0.0` (`nodes.py:464`). Forward-filling vs zero-filling emission factors is a model-behaviour choice. |
| 112–114 | `D src/crispy_kedro/pipelines/financial_model/{__init__,nodes,pipeline}.py` | DROP-SUPERSEDED | Main has no `financial_model` pipeline anywhere in `origin/main:src/`; replaced by `calculate_asset_earnings`. Deletion already effective. |
| 115, 116, 117 | `R072 .../report_outputs/__init__.py → .../inputs_postproc/__init__.py`, `A .../inputs_postproc/{nodes,pipeline}.py` | DROP-SUPERSEDED | All three node functions verified on main in `origin/main:src/altr_model/pipelines/prepare_scenario_asset_and_company_inputs/_asset_preparation.py`: `apply_reduce_granularity_from_asset_to_company_level`, `determine_assets_retirement_dates`, `extend_allocated_assets_to_companies` (the latter two also referenced from `allocate_company_trajectories_to_assets/nodes.py`). Main absorbed the stage rather than keeping a separate pipeline. |
| 118 | `M src/crispy_kedro/pipelines/inputs_processing/nodes.py` | **ADJUDICATE** | Most of this file's history is already on main: `b71f1a8` is a port *of* main's `63f5b59`; `593059c` is main's `c45103f`; `13707f2` geography filtering is main's `common_geographies` in `_input_nodes.py`; `1259a10` is cosmetic. The unique remainder is `056d1f6` carbon-price/VRE-share computation (open) and `5ecdca6` MCPR VRE (retired). Target if ruled in: `prepare_scenario_asset_and_company_inputs/`. |
| 119 | `M src/crispy_kedro/pipelines/inputs_processing/pipeline.py` | **ADJUDICATE** | Wires the `056d1f6` nodes from row 118. |
| 120, 121 | `D src/crispy_kedro/pipelines/report_outputs/{nodes,pipeline}.py` | DROP-SUPERSEDED | Same absorption as rows 115–117; main has no `report_outputs` module. Deletion already effective. |
| 122–130 | `A src/crispy_kedro/pipelines/reporting/{__init__,_style,exports,nodes,pipeline,plots_financials,plots_staggered,plots_trajectories,views}.py` | DROP-SUPERSEDED | `origin/main:src/altr_model/pipelines/plot_transition_risk_results/nodes.py` already contains the equivalent function set (`build_reporting_views`, `export_reporting_tables`, `plot_earnings_inner_workings`, `plot_valuation_authority_pack`, `plot_asset_financial_trajectories`, `plot_staggered_shock`, `plot_late_sudden_trajectories`, `reporting_qc_summary`), plus main-only fixes `51d1177` (per-owner keys) and `b9ca656` (co-owner plot slicing). The `5a48631` module split is cosmetic and would discard main's later fixes. |
| 131 | `M src/crispy_kedro/pipelines/valuation_model/__init__.py` | DROP-SUPERSEDED | `1259a10` docstring only; `origin/main:src/altr_model/pipelines/calculate_asset_and_company_npv/__init__.py`. |
| 132 | `M src/crispy_kedro/pipelines/valuation_model/nodes.py` | **ADJUDICATE** | `5ef65b2` and `a9f4cb5` are on main as `20490a2` and `4dc3400`. The unique remainder is `056d1f6`: stranding-aware terminal value (Gourdel 2024, 3-tier), finite-annuity double-discount fix, green/brown discount spreads, `g_effective` initialisation, terminal-FCFF normalisation. Verified **zero** trace on main. Target if ruled in: `calculate_asset_and_company_npv/nodes.py`. |
| 133 | `M src/crispy_kedro/pipelines/valuation_model/pipeline.py` | **ADJUDICATE** | Wires the `056d1f6` valuation parameters from row 132. |
| 134 | `M src/crispy_kedro/settings.py` | DROP-SUPERSEDED | `1259a10` docstrings/ruff only; `origin/main:src/altr_model/settings.py`. |

### 3.9 Tests

| # | Path(s) | Disposition | Target / reason |
|---|---|---|---|
| 135–138 | `A tests/fixtures/data/{ar6_carbon_prices,downloaded_assets,downloaded_companies,downloaded_scenarios}.csv` | **PORT** → `tests/fixtures/data/` | Fixture-slice data (`2e35c9f`, `689d312`); ships under the export allowlist. Re-verify the WITCH scenario pair resolves against main's catalog. `ar6_carbon_prices.csv` ports as fixture data regardless of row 9's ruling — it is inert unless the carbon-price dataset is wired. |
| 139 | `A tests/fixtures/make_fixture_slice.py` | **PORT** → `tests/fixtures/make_fixture_slice.py` | Slice builder; re-point at main's dataset names. |
| 140 | `A tests/fixtures/test_fixture_ids_licensed.py` | **PORT** → `tests/fixtures/test_fixture_ids_licensed.py` | Licensing guard on shipped ids (`55a90a8`); pairs with entry 91 and protects entry 48's boundary. |
| 141 | `A tests/fixtures/test_fixture_slice.py` | **PORT** → `tests/fixtures/test_fixture_slice.py` | Slice integrity test. |
| 142, 143, 144 | `R100 tests/pipelines/layer2/__init__.py → tests/golden/__init__.py`, `A tests/golden/{compare,test_golden}.py` | **PORT** → `tests/golden/` | Golden-run comparator and NaN-drift surfacing (`8c81839`, `ff96e3a`, `59fe033`). Create `tests/golden/__init__.py` fresh — the rename source `tests/pipelines/layer2/` is already absent from `origin/main:tests/`. Baseline must be re-pinned against main. |
| 145, 146, 147 | `R100 tests/pipelines/outputs_processing/__init__.py → tests/integration/__init__.py`, `A tests/integration/{test_fixture_catalog_complete,test_fixture_run}.py` | **PORT** → `tests/integration/` | Fixture-environment regression harness (`f838f0f`, `063cf17`). Same rename note: create `__init__.py` fresh. `test_fixture_catalog_complete.py` must assert against main's 10 catalog keys. |
| 148, 149 | `R100 tests/pipelines/report_outputs/__init__.py → tests/pipelines/inputs_postproc/__init__.py`, `R079 tests/pipelines/layer1/test_pipeline.py → tests/pipelines/inputs_postproc/test_pipeline.py` | DROP-SUPERSEDED | Main has no postproc stage and no such test package; the file content is the Kedro 0.19.12 boilerplate placeholder with no tests in it (verified). Main's equivalent coverage is `origin/main:tests/pipelines/prepare_scenario_asset_and_company_inputs/test_nodes.py`. |
| 150, 151 | `D tests/pipelines/layer2/test_pipeline.py`, `D tests/pipelines/outputs_processing/test_pipeline.py` | DROP-SUPERSEDED | Both already absent from `origin/main:tests/`. Deletions already effective. |
| 152 | `A tests/pipelines/reporting/__init__.py` | DROP-SUPERSEDED | `origin/main:tests/pipelines/reporting/__init__.py` exists. |
| 153 | `R100 tests/pipelines/report_outputs/test_pipeline.py → tests/pipelines/reporting/test_pipeline.py` | DROP-SUPERSEDED | Verified: Kedro boilerplate placeholder, docstring only, zero tests. Main dropped the placeholders and `origin/main:tests/pipelines/reporting/` holds the real `test_reporting_ownership_keys.py` instead. |
| 154 | `A tests/test_capacity_flows_geography.py` | DROP-SUPERSEDED | `origin/main:tests/pipelines/calculate_asset_earnings/test_capacity_flows_geography.py` (main's `04bafcb`). |
| 155 | `A tests/test_ef_ffill_vectorized.py` | **ADJUDICATE** | Pins the EF forward-fill that main does not implement (row 111). Porting it would fail on main's `fillna(0.0)`; it can only follow row 111's ruling. |
| 156 | `A tests/test_frozen_capacity_vectorized.py` | **ADJUDICATE Q4** | Characterises `create_frozen_capacity_at_retirement`, verified absent from main repo-wide. Main handles frozen capacity inside `calculate_asset_earnings` (`nodes.py:460,521,525`) and retired the allocation-stage dataset on purpose. Porting this test as-is would fail on main — the function it imports does not exist. It follows Q4 with rows 100-102. |
| 157 | `A tests/test_mcpr_auto_fallback.py` | DROP-RETIRED | MCPR-specific test. Owner decision 1. |
| 158 | `A tests/test_npv_dropna_keys.py` | DROP-SUPERSEDED | `origin/main:tests/pipelines/calculate_asset_and_company_npv/test_npv_dropna_keys.py`. |
| 159 | `A tests/test_npv_vectorized_equivalence.py` | DROP-SUPERSEDED | `origin/main:tests/pipelines/calculate_asset_and_company_npv/test_npv_vectorized_equivalence.py`. |
| 160 | `A tests/test_ownership_allocation_scale.py` | DROP-SUPERSEDED | `origin/main:tests/pipelines/prepare_scenario_asset_and_company_inputs/test_ownership_allocation_scale.py`. |
| 161 | `A tests/test_prop_scale_retirement.py` | DROP-SUPERSEDED | `origin/main:tests/pipelines/allocate_company_trajectories_to_assets/test_prop_scale_retirement.py`. |
| 162 | `A tests/test_reporting_ownership_keys.py` | DROP-SUPERSEDED | `origin/main:tests/pipelines/reporting/test_reporting_ownership_keys.py`. |
| 163 | `A tests/test_retirement_mask_alignment.py` | **PORT** → `tests/pipelines/allocate_company_trajectories_to_assets/test_retirement_mask_alignment.py` | Main **has** the implementation fix (`validate="many_to_one"`, `_allocation_nodes.py:513-517`) but **not** the regression test — verified absent from `origin/main:tests/`. Exactly the shape the owner ruled on for ownership consolidation. Adapt imports to main's module paths. |
| 164 | `A tests/test_stagger_adjusted_splice.py` | DROP-SUPERSEDED | `origin/main:tests/pipelines/allocate_company_trajectories_to_assets/test_stagger_adjusted_splice.py`. |
| 165 | `A tests/test_tv_flow_row_dedup.py` | DROP-SUPERSEDED | `origin/main:tests/pipelines/calculate_asset_and_company_npv/test_tv_flow_row_dedup.py`. |
| 166 | `A tests/unit/__init__.py` | **PORT** → `tests/unit/__init__.py` | Package marker for the ported unit tests below; main has no `tests/unit/`. |
| 167 | `A tests/unit/test_build_export.py` | **PORT** → `tests/unit/test_build_export.py` | Pairs with entry 86. Note `7bd6d00`: this test must itself stay out of the export — preserve that exclusion in the ported allowlist. |
| 168 | `A tests/unit/test_capacity_flows.py` | **ADJUDICATE** | Characterisation test of the earnings capacity flows. It pins the branch's mask and 2% rate, which **contradict** main's mask and `replacement_capex_rate`. Cannot port until row 106 is ruled; porting as-is would fail on main. |
| 169 | `A tests/unit/test_dcf.py` | **ADJUDICATE** | Characterisation test of the DCF core including the `056d1f6` terminal-value and discount-spread behaviour that main does not have (row 132). |
| 170 | `A tests/unit/test_gen_param_docs.py` | **PORT** → `tests/unit/test_gen_param_docs.py` | Pairs with entry 88; update fixtures to main's six-file parameter layout. |
| 171 | `A tests/unit/test_mcpr_modes.py` | DROP-RETIRED | MCPR-specific test. Owner decision 1. |
| 172 | `A tests/unit/test_ownership_consolidation.py` | **PORT** → `tests/pipelines/prepare_scenario_asset_and_company_inputs/test_ownership_consolidation.py` | Owner decision 3, explicit: the implementation is superseded by main's `63f5b59`, but this regression test is not on main (verified absent from `origin/main:tests/`) and must be ported, adapted to main's module paths. |
| 173 | `A tests/unit/test_prepare_inputs.py` | **PORT** → `tests/unit/test_prepare_inputs.py` | Pairs with entry 90; carries `6ca15d1`'s cost-column and prefix-strip assertions. |

---

## 4. Main-side obligations — licensing exposure in `origin/main`

Everything in §3 is a *branch* entry. This section is different: it records defects
that already exist **on `origin/main`** and that the migration inherits the moment an
export is built from main's structure. They are not diff entries and are deliberately
**excluded from the 173 count**.

### 4.1 The finding

`origin/main` carries a hard-coded example-company list of **30 `CN_`/`CP_` identifiers**.
Verified: the same 30 ids, an identical set, appear in all three of

- `origin/main:conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml` (the `company_ids:` block)
- `origin/main:notebooks/example_company_selection.csv` (with company names, e.g. `Saudi Electricity Co`, `JERA`, `NTPC Ltd`, `Eskom Holdings SOC Ltd`)
- `origin/main:notebooks/generate_results.ipynb`

The reviews report that **26 are licensed and 4 fall outside the deliverables universe**:

| Identifier | Reported status |
|---|---|
| `CN_3609115420225854555` | outside the deliverables universe |
| `CN_4440463050459774439` | outside the deliverables universe |
| `CP_3185202543523296674` | outside the deliverables universe |
| `CP_8560203160377002286` | outside the deliverables universe |

**Verification status — read this before acting.** All four identifiers are confirmed
present in main's list, and the 30-id count and three-file spread are confirmed against
the tree. The **licensed/unlicensed split itself was VERIFIED twice on 2026-09-01 (independently by the coordinator and by round-3 Reviewer B, both against the live Dropbox drop) here**: it
requires the deliverables drop, and `ALTR_DELIVERABLES_DIR` is unset with no drop on
this machine (`data/05_model_input/` holds only `.gitkeep`). The split is therefore
carried as **reported by the reviews, ADJUDICATE pending a re-run** of the guard with
the drop mounted. The three obligations below stand regardless of how the count lands —
they are gaps in the machinery, not in the arithmetic.

### 4.2 The three obligations

**O1 — Reduce the example-company list before any export from main's structure.**
`example_company_selection.csv` carries ids *and company names*, so an unlicensed id
ships as an attributed record, not an opaque string. Before the first export: either
reduce the list in all three files to licensed ids only, or transform the file at
export time in `build_export.py`. Prefer **reducing at source** — a transform leaves
the unlicensed ids in the internal repo's history and in every developer's checkout,
and the three files must not drift apart.

**O2 — Extend the licensing guard beyond fixture CSVs.**
`tests/fixtures/test_fixture_ids_licensed.py` (row 140) checks exactly two files —
`tests/fixtures/data/downloaded_assets.csv` and `downloaded_companies.csv`. Main's 30
ids live in a **YAML** and a **notebook**, which the guard does not read, so it would
pass while shipping them. On port, the guard must scan **every allowlisted YAML and CSV**
(and the notebook, or the notebook must stop hard-coding ids) for `C[NP]_[0-9]+` and
check each hit against the deliverables. Its own docstring already frames the rule
correctly — "ids that appear in the deliverables files themselves"; only its coverage is
too narrow.

**O3 — The guard must FAIL, not skip, when `ALTR_DELIVERABLES_DIR` is unset.**
Today the file carries
`pytestmark = pytest.mark.skipif(DELIVERABLES is None or not DELIVERABLES.is_dir(), ...)`.
In an export gate that is the worst possible default: the one check standing between an
unlicensed identifier and a shipped artefact **silently passes when unconfigured**.
Keep `skipif` for ordinary local runs if you like, but the export path must treat a
missing drop as a **hard failure** — `build_export.py` refuses to build unless the guard
actually ran and passed. Pair this with row 91 (`sanitize_check.py`), which is the other
half of the boundary.

---

## 5. Commit ledger — 101 commits

Tags: **PORTED-VIA-FILES** (its content reaches main through PORT rows) ·
**RETIRED** (MCPR) · **SUPERSEDED** (main has an equivalent, or main removed the
target) · **REFERENCE-ONLY** (stays on the branch) · **ADJUDICATE** (blocked on a ruling).

```
397f26f  REFERENCE-ONLY     docs: MCPR retirement final on owner authority, no review gate (notes only)
7a9f647  REFERENCE-ONLY     docs: the migration disposition ledger itself (entry 54)
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

Commit tag counts: SUPERSEDED 50 · PORTED-VIA-FILES 25 · REFERENCE-ONLY **14** ·
RETIRED 6 · ADJUDICATE 6. **Total 101.**

Sanity check: `50 + 25 + 14 + 6 + 6 = 101`, matching
`git log --oneline 91c0a7f..HEAD | wc -l` = 101. The v1 subtotals were re-counted line
by line off the block above and were correct at 99; the only movement in v2 is
REFERENCE-ONLY 12 → 14 for the two new commits. `397f26f` touches only
`docs/superpowers/plans/implementation-notes-handover.md` (entry 53) and `7a9f647` only
adds entry 54 — neither carries migrated content, so neither changes any other tag.

---

## 6. Counts

| Disposition | Entries | Movement from v1 |
|---|---:|---|
| PORT (incl. PORT-PARTIAL, PORT-ADAPTED, PORT-partial/regenerate) | 51 | +1 — AGENTS.md (row 4) REFERENCE → PORT-ADAPTED |
| DROP-SUPERSEDED | 54 | −3 — rows 100, 101, 102 split out to ADJUDICATE Q4 |
| DROP-RETIRED | 6 | — |
| REFERENCE | 40 | +1 the ledger (row 54), −1 AGENTS.md |
| NEVER-SHIP | 1 | — |
| ADJUDICATE | 21 | +3 — rows 100, 101, 102 |
| **Total** | **173** | +1 entry (row 54) |

`51 + 54 + 6 + 40 + 1 + 21 = 173`.

Counting conventions, unchanged from v1: a **split or mixed row counts once, under its
blocking disposition** — rows 100-102 are part-superseded and part-Q4, and count as
ADJUDICATE because that is what gates them. **PORT-PARTIAL and PORT-ADAPTED count as
PORT**; the file moves, with named sections withheld. §4's main-side obligations are
**not** counted — they are not diff entries.

**every diff entry assigned: 173/173**

---

## 7. ADJUDICATE queue — 21 entries, 4 questions

The 21 entries collapse into four rulings. Nothing in the PORT set is blocked by them;
the migration can proceed and land these afterwards. Q2 and Q4 now also gate **named
sections inside PORT-PARTIAL documents** — those sections are withheld on port, so an
open gate never blocks a file, only a passage.

**Q1 — Replacement-CapEx and retirement masks in earnings capacity logic.**
Entries 106, 108, 110, 168. Main `(~is_synthetic) & (capacity_change > 0)` with a
parameterised `replacement_capex_rate`; branch `is_real & ~retirement_mask` with a
hardcoded 2% of `asset_trajectory`. Retirement masks also differ. `31596a0`.

**Q2 — The `056d1f6` NPV-direction feature set.**
Code and config entries: 9, 11, 13, 16, 18, 109, 118, 119, 132, 133, 169. Stranding-aware
terminal value, finite-annuity double-discount fix, brown/green discount spreads, price
ramp, dynamic marginal EF, differential carbon-price injection. Verified **zero** trace
on main. Main's parameters deliberately disable replacement CapEx and decom costs.
This is a large deliberate model-behaviour change main's maintainers have not taken.

*Q2 also gates documentation* (rows 35, 27–34, 10 — withheld on port, rewritten after
the ruling): `quickstart.md` `### The fourth file: carbon prices` (whole section, the
`ar6_carbon_prices` input); `pipelines/valuation_model.md` `## Purpose` line 20,
`## Parameters read` lines 71-72, `## Methodology reference` line 85;
`pipelines/earnings_model.md` `## Parameters read` lines 73 (`price_ramp`) and 79
(`dynamic_marginal_ef`, `carbon_cost_method`); and the `price_ramp` annotation in
row 10, which has no key on main to attach to. **Explicitly not gated:** the
`npv_change` sign-convention prose in `user_guide.md` and `walkthrough.ipynb` — main's
formula is verified identical, so it ports whatever Q2 decides.

**Q3 — Emission-factor forward fill vs zero fill.**
Entries 111, 155. Branch forward-fills EFs within a series (`aa1e10d`); main sets
missing EFs to `0.0`. Different numbers, not just different code.

**Q4 — Frozen capacity at retirement.**
Entries **100, 101, 102, 156** — grown from v1's single entry 155 (now 156), because a
reviewer showed the branch does not merely *define* `create_frozen_capacity_at_retirement`,
it **creates and wires** it: `retirement.py:123-320` builds the dataframe,
`pipeline.py:106-114` registers the node `create_frozen_capacity` with
`outputs="frozen_capacity_at_retirement"`, `nodes.py:18` re-exports it, and entry 156 is
its characterisation test. Those parts were wrongly folded into a DROP-SUPERSEDED
equivalence claim in v1.

Main's position is **deliberate, and defended by a test**: `frozen_capacity_at_retirement`
is in `origin/main:tests/test_run.py`'s `REMOVED_DATASETS`, and
`test_default_pipeline_has_no_dead_private_or_removed_datasets` asserts the default
pipeline does not produce it. Main keeps frozen-capacity *logic* inside
`calculate_asset_earnings` (`nodes.py:460,521,525`) — it retired the allocation-stage
dataset and node, not the concept.

The question is therefore not "port or not" but **"was main right to move frozen capacity
into earnings?"** If yes: rows 100-102 and 156 close as DROP-RETIRED, and the Q4 doc
sections (architecture.md lines 45 + 98; `pipelines/distribute_impacts_to_asset_level.md`
lines 35 + 54; `pipelines/earnings_model.md` line 31) are deleted rather than rewritten.
If no: restoring the node also means amending main's `REMOVED_DATASETS` and `test_run.py`,
which is a change to main's own contract and needs its maintainers, not just a port.

---

## 8. Notes for the executing session

- **Scope is frozen at `source_sha = 397f26f` against `origin/main` @ `63f5b59`.** This
  ledger is committed; it describes those two trees and no others. If either moves, the
  entry numbers and the equivalence claims must be re-verified before use — re-run
  `git diff --name-status 91c0a7f..<new sha> | cat -n` and check the count is still 173.
- PORT rows touching `docs/` all require the §2.2 naming rewrite. Do not copy any
  handover document verbatim.
- **PORT-PARTIAL files are the trap.** A file marked PORT-PARTIAL looks portable and is
  not: rows 24, 35, 38, 82 and three of the eight pages in row 27–34 each carry named
  sections that must be deleted (MCPR) or withheld pending a ruling (Q1/Q2/Q4). Port the
  structure, then walk the section list in the row before declaring the file done.
- **§4 is main-side work with no branch entry to hang it on.** The licensing obligations
  O1-O3 will not surface from any diff row, and O3 in particular fails open — the guard
  skips silently when `ALTR_DELIVERABLES_DIR` is unset. Run the guard with the drop
  mounted and confirm the 26/4 split before the first export; it could not be verified
  when this ledger was written.
- Export tooling (86, 87, 91) and the shipped PDF (23) must name the external repo
  `altr-model-refactored`. The name `altr-model` now resolves to the internal repo,
  so a stale reference silently points recipients at private code.
- Entry 48 is the hard boundary: `docs/research/company_id_archive_2026.md` never
  ships, and the guard that enforces it (entry 91) must land before any export runs.
- Main carries three fixes the branch lacks — `13540c1` (shock-anchor clamp),
  `b9ca656` (co-owner plot slicing), `7cf6544` (dtype stabilisation). No port may
  overwrite them; this is the main reason the `src/` refactor-splits are dropped
  rather than applied.

---

## 9. CHANGELOG — v1 (`7a9f647`) → v2

Nine revisions, each verified against `feat/handover-package` @ `397f26f` and
`origin/main` @ `63f5b59` before it was written.

1. **Scope frozen.** Header now states `source_sha = 397f26f`, target `origin/main` @
   `63f5b59`, and counts of 173 entries / 101 commits. The ledger itself (entry 54) and
   the two post-`765ed5f` commits (`7a9f647`, `397f26f`) carry REFERENCE dispositions.
   Every "Not committed" / "uncommitted" line is gone — the ledger is committed and
   describes a frozen pair of trees.
2. **Rows 97–104 split on verified non-equivalence.** The v1 block claimed main
   supersedes the whole `distribute_impacts` module split. Confirmed true for every
   function except `create_frozen_capacity_at_retirement`, which the branch **creates
   and wires** (`retirement.py:123`, `pipeline.py:106-114`, `nodes.py:18`) and which main
   removed deliberately (`REMOVED_DATASETS` in `origin/main:tests/test_run.py`). Rows 97,
   98, 99, 103, 104 stay DROP-SUPERSEDED; rows 100, 101, 102 become split rows under Q4.
3. **Q2/Q4 scope expanded to documentation.** `quickstart.md`, `user_guide.md`,
   `architecture.md`, `pipelines/valuation_model.md`,
   `pipelines/distribute_impacts_to_asset_level.md`, `pipelines/earnings_model.md` and
   `notebooks/walkthrough.ipynb` become **PORT-PARTIAL**: structure and commands port
   now, each behaviour section tagged to its gate — MCPR sections deleted on port, Q2/Q4
   sections rewritten after the ruling. Sections listed per file from actual greps.
   `parameters.md` is PORT (regenerate); its gated terms self-resolve.
4. **New §4, main-side obligations.** Main's 30 hard-coded `CN_`/`CP_` ids (identical set
   in `parameters_prepare_scenario_asset_and_company_inputs.yml`,
   `notebooks/example_company_selection.csv`, `notebooks/generate_results.ipynb`), of
   which 4 are reported outside the deliverables universe. Three obligations: reduce the
   list before any export (O1), extend the licensing guard past fixture CSVs to every
   allowlisted YAML/CSV (O2), and make it **fail rather than skip** when
   `ALTR_DELIVERABLES_DIR` is unset (O3). Not diff entries; excluded from the 173.
5. **Row 10 made unambiguous.** Main keeps its six per-pipeline parameter files; only the
   branch's *annotations* port onto the keys that already exist there; no consolidated
   `parameters.yml` is created; row 88's `gen_param_docs.py` reads the six. Lists the
   branch keys with **no** annotation target: `enable_mcpr`, `mcpr_mode` (MCPR block,
   retired), `price_ramp` (Q2), `ownership_type` (removed by main's `bdcd8c3`) — plus the
   reverse gap, main's four keys with no branch annotation to inherit.
6. **AGENTS.md (row 4): REFERENCE → PORT-ADAPTED.** Rewritten for internal main (uv
   commands, `altr-model`, six pipelines, no `MCPR/`+`pkg/`, current team rules) and
   **never shipped externally** — verified absent from `scripts/export_allowlist.txt` and
   it stays absent.
7. **`SKIP_RELATIVE` note added to row 86.** On main, `tests/test_run.py` is a data-free
   pipeline-registration test, so its branch-era exclusion rationale ("needs the internal
   data drop") is false there. Re-evaluate on port and default to shipping it — it is the
   guard that would catch a re-introduced `frozen_capacity_at_retirement`.
8. **Commit ledger → 101.** Added `7a9f647` and `397f26f` as REFERENCE-ONLY. Tag
   subtotals re-counted off the block: SUPERSEDED 50 · PORTED-VIA-FILES 25 ·
   REFERENCE-ONLY 14 · RETIRED 6 · ADJUDICATE 6 = 101, matching `git log`.
9. **Renumbering (not in the original brief, forced by verification).** The brief assumed
   this file would be the 173rd diff entry. `git diff --name-status` sorts by path, so it
   lands at **line 54**; every v1 entry ≥ 54 shifts **+1**. All rows and every in-prose
   cross-reference were remapped and re-checked against the frozen diff.

**Carried as unverified.** The 26-licensed / 4-unlicensed split in §4 is reported by the
reviews and was VERIFIED twice on 2026-09-01 (independently by the coordinator and by round-3 Reviewer B, both against the live Dropbox drop) here: `ALTR_DELIVERABLES_DIR` is unset and no
deliverables drop is present (`data/05_model_input/` holds only `.gitkeep`). The
identifiers' presence in main and the three obligations are verified; the split is marked
ADJUDICATE pending a guard run with the drop mounted.


## Addendum (2026-09-01, post round-3 review)

- Licence split of main's 30 conf ids: **VERIFIED** twice, independently
  (coordinator + round-3 Reviewer B), against
  `~/Theia Dropbox/ALTR deliverables/companies_ownerships.csv` — exactly 7,512
  unique company_ids; 26 of the 30 present; 4 absent:
  CN_3609115420225854555, CN_4440463050459774439, CP_3185202543523296674,
  CP_8560203160377002286. Drop fingerprint (7,512) is now asserted by
  tests/fixtures/test_fixture_ids_licensed.py, which also refuses any
  ALTR_DELIVERABLES_DIR resolving inside the repo tree. §4.1/§9's ADJUDICATE
  status for this item is superseded by this addendum: O1 is executable.

## Addendum 2 (2026-09-01, owner rulings — governs the behaviour-port pass)

- Q1-Q4 RESOLVED by owner (recorded in implementation-notes-handover.md @
  cd46ed5/c310339): all four behaviours PORT into Bertrand's structure —
  minimal diffs inside his modules, his conventions, no imported layouts.
  Every ADJUDICATE entry becomes PORT-BEHAVIOUR under this ruling.
- The 056d1f6 NPV-direction feature set ports (price_ramp, stranding,
  dynamic marginal EF, replacement capex incl. Q1 masks, decom costs).
  MCPR remains DROP-RETIRED.
- External delivery superseded: single-repo end state (altr-model);
  altr-model-refactored deleted after validation. Export tooling is KEPT as
  an internal utility; its prose references to altr-model-refactored are
  neutralised (destination is the --dest argument, not a repo name).
- The 10 pending-adjudication TODO doc blocks are rewritten as each ported
  behaviour lands (they were staged exactly for this).
- Frozen source advances 0fc3127 -> c310339 (docs/decision commits only; no
  code moved on the source branch since 397f26f except the guard hardening
  already ported).
- Verification bar: behaviour equivalence — the migration branch's fixture
  outputs must match the handover branch's fixture outputs within numeric
  tolerance on an ALIGNED slice (same companies, same scenario pair).
