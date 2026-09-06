# ALTR parameter audit — what drives the results, and how users see it

Date: 2026-09-06. Branch `feat/altr-npv-fixes`. Method: four Opus auditors (declared config, hidden constants, data/runtime, documentation UX) plus one Codex enumeration, results diffed; every HIGH item below re-verified by hand against the code. Read-only, nothing changed.

Full agent reports: scratchpad `agent_config_params.md`, `agent_hidden_params.md`, `agent_data_runtime_params.md`, `agent_docs_ux.md`, `agent_codex_params.md`.

## 1. Headline

**What actually runs is not `conf/base`.** `settings.py:36` sets `default_run_env: "local"`. `conf/local/` is gitignored yet populated with a leftover "vanilla" sweep variant written by `notebooks/run_all_scenarios_comparison.py` (its cleanup step did not run). A bare `kedro run` today flips 7 earnings switches and 3 valuation knobs versus the documented base, and points `downloaded_scenarios` at an absolute machine path. Verified.

| Key | base (documented) | local (runs) |
|---|---|---|
| `enable_mcpr` | True | false |
| `carbon_cost_method` | full_ef | differential_ef |
| `price_ramp` | True | false |
| `include_replacement_capex` / `include_decom_costs` | True / True | false / false |
| `apply_continued_om_shock` | True | false |
| `dynamic_marginal_ef` | True | false |
| `dcf.stranding_aware_tv` | True | false |
| `dcf.terminal_value.g_real_brown` | 0.0 | 0.02 |
| `dcf.terminal_value.normalization_window` | 3 | 1 |
| `baseline_scenario` / `target_scenario` | REMIND-MAgPIE pair | IMAGE 3.2 pair |
| `downloaded_scenarios.filepath` | `data/05_model_input/…` | `/Users/jakub/…/IMAGE_3.2_scenarios.csv` |

## 2. Result-affecting parameters: declared in conf (live)

| Key | File | Consumer | Status |
|---|---|---|---|
| `baseline_scenario`, `target_scenario` | inputs_processing | `filter_scenarios` | exact-match; no match raises (loud) |
| `max_forecast_horizon`, `ownership_type`, `ccs_on`, `company_ids` | inputs_processing | filters | `ownership_type` typo → empty universe, silent |
| `shock_year`, `alignment_year` | create_late_sudden | read by 4 pipelines | only validation in repo: `alignment_year >= shock_year` |
| `apply_retirement_baseline`, `apply_retirement_shock`, `apply_decreasing_staggered_shock` | distribute_impacts | retirement / shock branch | `g_k`, `n_quantiles` only live when staggered = True (currently False) |
| `reduce_granularity_from_asset_to_company_level` | inputs_postproc | pass-through switch | |
| `market_passthrough`, `enable_mcpr`, `mcpr_mode`, `mcpr_merit_order_alpha/floor`, `mcpr_markup_factor`, `enable_dynamic_capture_ratios`, `enable_regional_mcpr_vf`, `mcpr_regional_value_factors`, `price_ramp`, `include_growth/replacement_capex`, `include_decom_costs`, `apply_continued_om_baseline/shock`, `dynamic_marginal_ef`, `carbon_cost_method` | earnings_model | ops + capex blocks | all MCPR sub-keys dead when `enable_mcpr: false` (local). `mcpr_mode: auto` hard-resolves to `carbon_explicit` (nodes.py:526-546), never merit order. `dynamic_marginal_ef` inert in every shipped config (nodes.py:1598-1605). |
| `dcf.discount_rate_baseline/shock`, `brown/green_discount_spread`, `terminal_value.*`, `stranding_aware_tv`, `stranding_consecutive_years`, `brown_remaining_life_years` | valuation_model | NPV | `g_real_default` can never fire; stranding sub-keys dead under local |
| catalog: `db_*` BigQuery tables, `ar6_carbon_prices` (untracked repo-root CSV, 5-col `usecols` contract), `downloaded_*` CSVs | catalog.yml | inputs | input vintage unversioned; `.bak-20260831` pairs on disk |

## 3. Result-affecting parameters: hidden in code (no conf key)

Verified HIGH:

| # | Location | Value | Controls |
|---|---|---|---|
| H1 | `earnings_model/nodes.py:1257` | `* 0.02` | replacement capex rate (only the on/off switch is in conf) |
| H2 | `earnings_model/nodes.py:410` | `-capex / 2` | decommissioning cost = 50% of capex |
| H3 | `earnings_model/nodes.py:598-616`, `:588-593`, `:429` | value factors dict, marginal-tech list, `mcpr_floor_at_iam_price=True` | three MCPR args declared in the signature, never wired in pipeline.py:53-69 |
| H4 | `inputs_processing/nodes.py:286-311` | 22 ISO2 codes | assets in these countries dropped, `# TODO REMOVE HARDFIX FOR NGFS` |
| H5 | `distribute_impacts/nodes.py:496`, `:752`, `:1081` | `clip(lower=alignment_year+1)` | no retirement before 2039; lifetime retirements deferred through the shock window |
| H6 | `earnings_model/nodes.py:387` | `fillna(1.0)` | missing capacity factor → 100% utilisation |
| H7 | `inputs_processing/nodes.py:902,927` | `fillna(0.0)` | failed carbon-price join indistinguishable from zero carbon price |
| H8 | `earnings_model/nodes.py:1408` | `market_passthrough=0.5` default | disagrees with conf `0`; dormant while wired |
| H9 | `valuation_model/nodes.py:15` | `discount_rate_shock=0.08` default | disagrees with conf `0.07`; dormant while wired |

MED (verified by agents, spot-checked by me where marked ✓): non-fuel / VRE / CCS-eligible / carbontech tech lists duplicated across files; Hirth capture-ratio coefficients hardcoded though documented in yml as if configurable; `(1-vre_share)**2` exponent; lifetime = `ceil(mean)` over target rows; linear interpolation then flat carry-forward; zero-tolerance alignment test; `min_active_share=1e-12`, `n_iterations=32`; ungrouped `.ffill()` across assets in `inputs_postproc/nodes.py:284-299` ✓ (cross-asset bleed of capacity factor and emission factor); BAU boundary `< shock_year` for one cohort vs `<= shock_year` for three in `create_late_sudden/nodes.py:200 vs 330/454/588` ✓; ownership `/100` with a 1.5 scale guard; `(L\d+)` regex EF join.

## 4. Declared but dead

- `theta_capex_recovery` (`parameters_inputs_postproc.yml`) → `scale_electricity_price` body fully commented out, returns input ✓. Also filed under the wrong pipeline.
- `reporting.baseline_filter`, `top_n_companies`, `show_synthetic_assets`, `show_sensitivity_tornado`, `sensitivity_params` → zero references in `src/` ✓. `baseline_filter` names a WITCH scenario; base names REMIND; local names IMAGE.
- `g_real_default`, `mcpr_markup_factor` (identity at 1.0), all `mcpr_*` and `stranding_*` sub-keys under the current local config.
- `conf/prod/catalog.yml`: dataset names do not match pipeline inputs; worse, `assets_forecasts` is a node output in inputs_processing (pipeline.py:96) but a BigQuery `prod_marts` table in prod ✓. `--env prod` would try to write a filtered frame over the source table.
- `companies_npvs` catalog entry: labelled key output, nothing writes it; MLflow hooks commented out.

## 5. Runtime override surface

- `notebooks/run_all_scenarios_comparison.py`: 14 variants × scenario pairs, implemented by writing YAML into `conf/local/` and shelling out to `kedro run`. Default `--ar6-path` points at the 5-column carbon-price file, not the 23-column `ar6_scenarios_20260901.csv` the real runs used. Cache reuse is unconditional when the AR6 file is missing or empty (:806-811).
- `notebooks/generate_results.ipynb`: the only `KedroSession(extra_params=…)` usage.
- No `--params` example anywhere in tracked docs. Dockerfile entrypoint is `kedro viz`, never runs the model.

## 6. How parameters are presented to the user — verdict

**Not clearly, and not all accessible. Grade D+.** Methodology docs are strong; the configuration surface is not.

| File | Grade | Why |
|---|---|---|
| `conf/base/parameters.yml` | F | 0 bytes. The canonical Kedro entry point is empty. |
| `parameters_inputs_processing.yml` | D− | 12,109 lines, 6 live keys; lines 37-12109 are commented-out company IDs |
| `parameters_earnings_model.yml` | B− | best-commented, real citations; but an 86-line region table lives inside it and 3 MCPR args are unwired |
| `parameters_valuation_model.yml` | B | good citations; stale comment claims shock rate is higher (it equals baseline) |
| `parameters_create_late_sudden_trajectories.yml` | C+ | 2 keys, commented; no stated constraint |
| `parameters_distribute_impacts_to_asset_level.yml` | D+ | `g_k`, `n_quantiles`, staggered switch: no comment, unit, range, or note they are gated |
| `parameters_inputs_postproc.yml` | D | `theta_capex_recovery` uncommented and dead |
| `parameters_reporting.yml` | D− | 5 of 15 keys dead |
| `conf/README.md` | D | Kedro boilerplate, Instructions section empty, never mentions `default_run_env: local` |
| `README.md` | C− | 5-bullet config section, no key names, no `--params`, no local precedence warning |
| methodology brief Appendix A | D as a reference | documents a different repo's filenames and ~8 keys this codebase does not have |

Docstrings: 19 param-taking nodes, 49 param args, 28 undocumented (57%); 7 nodes have no docstring. Worst: `apply_mcpr_adjustment` 6/9, `compute_flow_based_capex` 3/3, all six reporting nodes take an opaque `reporting_params` dict.

Validation: one check in the whole project (`alignment_year >= shock_year`). Every enum falls through silently: a typo in `carbon_cost_method` selects a different methodology; a typo in `terminal_value.method` zeroes TV; a typo in `ownership_type` empties the universe. No pydantic, no schema, no range checks.

Single view: none. `kedro viz` shows names and effective values only. The one run-stamped artifact, `methodology_parameters.csv`, hardcodes `"7%"`/`"8%"` at `reporting/nodes.py:1956-1957` ✓ while the config says 0.07/0.07. The compliance export misstates the shock discount rate.

## 7. Shortest path to A (ordered by value per hour)

1. Fill `conf/base/parameters.yml` with the ~15 user-facing keys, one comment line each (meaning · unit · range · source); head the rest "advanced". Delete-or-fix the stale local: make the sweep script write to a dedicated `conf/study/` env instead of `conf/local`. (Handover plan Task 5, not executed.)
2. `validate_parameters` node: plain dict of `{key: (type, allowed)}`, raise `ValueError` naming key/value/allowed. ~60 lines covers every enum and range above.
3. Six lines in `README.md` and `conf/README.md`: `default_run_env` is local, destructive top-level merge, prefer `kedro run --params=…`.
4. Wire H1–H5 as conf keys: `replacement_capex_rate`, `decom_cost_share_of_capex`, `mcpr_value_factors`, `mcpr_marginal_technologies`, `mcpr_floor_at_iam_price`, `excluded_country_iso2`, `retirement_floor_offset_years`, `default_capacity_factor` (or fail on NaN).
5. Replace the `"7%"/"8%"` literals with the real `params:dcf` values and dump the resolved parameter dict next to outputs.
6. Move lines 37-12109 of the inputs_processing file to `docs/scenario_catalog.md`; move `mcpr_regional_value_factors` to a catalog CSV.
7. Delete or mark NOT IMPLEMENTED the 5 dead reporting keys and `theta_capex_recovery`; fix or remove `conf/prod/catalog.yml`.
8. `scripts/gen_param_docs.py` → `docs/parameters.md` (Handover plan Task 11).
9. Docstring sweep on the 19 nodes; uncomment the finished docstring at `inputs_processing/nodes.py:746-767`.
10. Retitle methodology brief Appendix A as documenting `altr-model-migration`, link to the generated reference.

## 8. Agent disagreements resolved

- Docs agent claimed `price_ramp` is absent from local. Wrong: `conf/local/parameters_earnings_model.yml` has `price_ramp: false`. Kedro 0.19.12 OmegaConfigLoader merges destructively at top-level key, not per file.
- Hidden-params agent flagged `mcpr_mode: auto` never resolving to merit order; config agent did not. Code confirms the hidden-params agent (OP9 comment, nodes.py:526-546).
- Codex cross-check (second run, bounded verify-or-refute prompt): 17 CONFIRMED, 2 PARTIAL, 1 REFUTED of the 20 claims above. Partials: `settings.py` was outside its read scope (A1), and `mcpr_mode: auto` only resolves when MCPR is on (B7). Refuted: `g_real_default` is wired (`valuation_model/pipeline.py:25`) and is the fallback when brown/green are null; since both are always set, "unreachable" is the correct label, not "dead". Corrected in `conf/base/parameters.yml`.

## 9. Codex additions (not in the Opus reports)

| Location | Finding | Impact |
|---|---|---|
| `earnings_model/nodes.py:299-307, 677-683, 1620-1626` | VRE share is computed from the target scenario only and merged without `scenario_type`, so baseline rows also receive target VRE shares | MED — affects dynamic capture ratios and dynamic marginal EF in the baseline leg when enabled; likely a defect |
| `earnings_model/nodes.py:1716-1733` | FCFF hardcodes tax and working-capital effects to zero | MED — pre-tax FCFF presented as FCFF; document or expose |
| `valuation_model/nodes.py:120-151` | rows with missing or unrecognised `alignment_type` are treated as green and receive the greenium | MED |
| `create_baseline_and_target_trajectories/nodes.py:218-227` | `company_name` forward-filled without grouping | LOW (label leak) |
| `create_baseline_and_target_trajectories/nodes.py:234-259` | silent fallback to the baseline-change column if the target-change column is absent | MED |
| `earnings_model/nodes.py:395-398` | scenario-surface construction independently zeroes missing carbon prices (second fill site) | MED |
| `reporting/nodes.py:405-411, 1495` | several plot controls unwired; earnings plots capped at 5 assets | LOW |
