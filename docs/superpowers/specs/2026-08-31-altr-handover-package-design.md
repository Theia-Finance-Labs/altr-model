# ALTR Handover Package — Design

**Date:** 2026-08-31
**Status:** Approved by Jakub (brainstorming session)
**Branch context:** builds on `feat/altr-npv-fixes` (unmerged; Bertrand review gate applies)

## Goal

Prepare the crispy-kedro ALTR pipeline for handover to external collaborators: a
fresh, clean repo that runs end-to-end from the prepared deliverables input files,
with all run parameters visible in one place, deeply refactored for readability,
and documented so a new user goes from `git clone` to a completed run in under
30 minutes using the README alone.

## Decisions (locked)

| Decision | Choice |
|---|---|
| Delivery vehicle | Fresh export repo, assembled by script from this repo (Approach A) |
| Export repo | `altr-model` under Theia-Finance-Labs, **private** |
| Data entry point | Deliverables files only (`assets_forecasts.csv`, `companies_ownerships.csv`, `scenarios.csv`); no GCP/BigQuery for externals |
| Refactor depth | Deep: split large node files, type hints, ruff clean — strictly behavior-preserving |
| Pipeline names | Keep current names; document stage order (no renames) |
| Docs format | mkdocs-material site (also readable as plain markdown on GitHub) |
| ALTR Documentation PDF | Ships inside the export repo |
| Handover materials | Quickstart + user guide, per-pipeline reference, architecture diagram, walkthrough notebook |

## Audience & success contract

External collaborators are Python-literate analysts, new to Kedro and to this
codebase. Success test: a new user on a clean machine follows the README verbatim
— clean venv, install, place data, run — and gets a completed run with outputs
matching the golden baseline, in under 30 minutes of wall-clock effort.

## Architecture

### Pipeline organization

The live pipelines remain the unit of structure. The 8 external-facing ones are
presented as numbered stages in the registry ordering, docs, and diagram:

1. `inputs_processing`
2. `inputs_postproc`
3. `create_baseline_and_target_trajectories`
4. `create_late_sudden_trajectories`
5. `distribute_impacts_to_asset_level`
6. `earnings_model`
7. `valuation_model`
8. `reporting`

`download_inputs` (BigQuery) is stripped from the export (internal-only).
Empty legacy dirs (`layer1`, `layer2`, `outputs_processing`, `report_outputs`)
do not ship.

### Parameters entry point

- `conf/base/parameters.yml` (currently empty) becomes the single user-facing
  run configuration: scenario pair, shock/alignment years, MCPR mode + toggles,
  capex/decom switches, company filter — every headline knob, annotated with
  units, valid ranges, and methodology references.
- Per-pipeline `parameters_*.yml` files keep only advanced/internal knobs.
- `parameters_inputs_processing.yml` shrinks from 12,109 lines to its ~6 real
  keys; the commented-out scenario catalog moves to a docs page.
- Pure key relocation (Kedro merges all parameter files); no duplicate keys; no
  node-code changes beyond referencing relocated keys.

### Deep refactor (behavior-preserving)

Split the three oversized node files along natural seams; target 200–400 lines
per module, hard max 800:

| Pipeline | Current | Split into |
|---|---|---|
| `earnings_model/nodes.py` | 1,801 lines | mcpr / carbon costs / capex / earnings core |
| `distribute_impacts_to_asset_level/nodes.py` | 1,841 lines | retirement / shock distribution / staggered shock |
| `reporting/nodes.py` | 2,423 lines | tables / plots / exports |

- `pipeline.py` imports from the new modules.
- Node function signatures get type hints; ruff clean across `src/`.
- Naming normalized only where actively misleading.
- **No logic changes.** Anything that looks like a bug is flagged in
  implementation notes, never fixed inline.

### Safety net (built before any refactor)

1. **Fixture slice** — a cut of the deliverables data (handful of companies, one
   scenario pair) running the full pipeline in minutes; the fast regression loop
   after every split.
2. **Golden run** — full-data run pinned with tolerance-based comparisons
   (numeric rtol) on key output tables; seeded from the model run currently in
   progress; re-run at phase boundaries.
3. **Unit tests** for the computation core: MCPR modes, merit-order decline,
   NPV/DCF, retirement exclusion, capex flow-split (extends the two regression
   tests already on `feat/altr-npv-fixes`).
4. **Coverage bar:** computation modules ~80%; plotting/reporting exempt.

Known dependency: the carbon-price input fix is with a colleague. Baseline pins
on current working data; re-pin when the fix lands.

### Export mechanism

`scripts/build_export.py` in this repo assembles the export from an explicit
**allowlist**:

- `src/` minus `download_inputs`
- cleaned `conf/`
- `docs/` (the new mkdocs site) including the ALTR Documentation PDF
- walkthrough notebook
- `tests/`
- `pyproject.toml`, `poetry.lock`, `LICENSE`, `Dockerfile`
- input data staged from `~/Theia Dropbox/ALTR deliverables/` into `data/01_raw/`

A sanitizer pass greps the assembled tree for secrets, internal paths, and
personal names before anything leaves the machine. The script is re-runnable
whenever the model evolves; crispy-kedro stays the single source of truth.

## Documentation set (in the export, mkdocs-material)

- **Quickstart** — install → data → run → outputs
- **User guide** — one fully worked example run
- **Parameters reference** — table generated from the annotated `parameters.yml`
  so it cannot drift
- **Per-pipeline reference** — purpose, inputs/outputs, key functions,
  cross-references into the ALTR Documentation PDF
- **Architecture diagram** — mermaid data-flow map + kedro-viz instructions
- **Walkthrough notebook** — fixture-slice run end-to-end with
  intermediate-output inspection
- **Troubleshooting / FAQ**

## Sequencing

- **Phase 0** — safety net (fixture slice, golden baseline, core unit tests)
- **Phase 1** — conf/params cleanup, registry stage ordering
- **Phase 2** — deep refactor pipeline-by-pipeline, regression after each
- **Phase 3** — docs site, walkthrough notebook, diagram
- **Phase 4** — export script, sanitize, fresh-machine verification (clean venv,
  README followed verbatim, outputs match golden)

All work on a new branch off `feat/altr-npv-fixes`. Bertrand's review gate
(AGENTS.md) applies before merge.

## Error handling & risks

- **Refactor regression** — mitigated by fixture-slice loop + golden run; any
  numeric drift beyond rtol fails the phase.
- **Carbon-price fix landing mid-work** — re-pin the golden baseline; fixture
  slice regenerated from the corrected data.
- **Export leakage** — allowlist assembly (never copy-then-remove) + sanitizer
  grep pass.
- **Doc drift** — parameters reference generated from the YAML, not hand-written.

## Out of scope

- Renaming pipelines or datasets
- Any model/logic changes (belong on `feat/altr-npv-fixes` or follow-ups)
- Public open-source release (private repo; revisit later if needed)
- BigQuery path documentation for externals
