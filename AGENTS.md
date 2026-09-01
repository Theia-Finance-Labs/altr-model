# AGENTS.md — altr-model

Internal repository context. **This file is never shipped externally**: it is
deliberately absent from `scripts/export_allowlist.txt`, and
`tests/unit/test_build_export.py` asserts it stays absent. Recipients receive
product documentation, not agent or team-board context.

## Purpose
Kedro pipeline for ALTR: asset-level transition-risk valuation. Scenario
pathways in, company and asset NPV impacts out.

## Repositories
- `altr-model` — **this repo**, internal. Full history, internal tooling.
- `altr-model-refactored` — the external repo the export is delivered to.
  Anything aimed at recipients must name this one; a stale `altr-model`
  reference points them at private code.

## Team context
Board: Theia Team Board (org project #5). Issues carry
Status/Priority/Size/Product/Project/Review/Sprint fields; ALTR issues carry
Product=`ALTR`.
Conventions: theia-ops/docs/operating-manual.md. Technical review: Bertrand
first.

## Layout
- `src/altr_model/`  Kedro pipelines and nodes — six of them:
  `prepare_scenario_asset_and_company_inputs`, `calculate_company_trajectories`,
  `allocate_company_trajectories_to_assets`, `calculate_asset_earnings`,
  `calculate_asset_and_company_npv`, `plot_transition_risk_results`.
  Plus `bigquery_marts_downloader.py`, the maintainer-only input download.
- `conf/base/`       six per-pipeline `parameters_*.yml` files and `catalog.yml`.
                     There is no consolidated `parameters.yml`.
- `conf/fixture/`    the committed regression slice's environment.
- `docs/handover/`   the documentation site (mkdocs); shipped.
- `notebooks/`       exploratory analysis; only `walkthrough.ipynb` ships.
- `scripts/`         `prepare_inputs.py`, `gen_param_docs.py`, `pin_golden.py`
                     ship; `build_export.py` and `sanitize_check.py` are
                     internal-only export tooling.
- `tests/`           pytest suite, including the fixture regression gate.

## Commands
- `uv sync`
- `uv run kedro run`
- `uv run pytest tests/`
- `uv run python scripts/gen_param_docs.py` after changing a parameter
  annotation, and commit the regenerated `docs/handover/parameters.md`.

Two suites need internal data and fail rather than skip without it:
`tests/fixtures/test_fixture_ids_licensed.py` needs `ALTR_DELIVERABLES_DIR`.

## Rules
- Methodology docs live in `docs/`; **never delete files — archive instead.**
- ALTR changes need Bertrand's review before merge.
- No company identifier reaches the export. `sanitize_check.py` gates the
  pattern and `test_fixture_ids_licensed.py` gates the licence; adding a
  `company-id` suppression for `conf/` is forbidden.
