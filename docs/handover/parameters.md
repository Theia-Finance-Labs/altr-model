# Parameters reference

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

ALTR splits that namespace across **six per-pipeline files**, one per pipeline —
there is no consolidated `conf/base/parameters.yml`. Scenario selection and run
scope live in `parameters_prepare_scenario_asset_and_company_inputs.yml`, which
is the file most runs are configured from; shock timing lives in
`parameters_calculate_company_trajectories.yml` and the cost switches in
`parameters_calculate_asset_earnings.yml`. The remaining three hold the
advanced, methodology-internal knobs for their own pipeline.

Only keys at the top level of a file are listed. A nested block (`dcf:`,
`reporting:`, `staggered_shock:`) appears once, with an empty default — its
sub-keys are annotated in the YAML file itself and are addressed in pipelines as
`params:<block>.<sub_key>`.

## `conf/base/parameters_allocate_company_trajectories_to_assets.yml`

| Key | Default | Section | Description |
| --- | --- | --- | --- |
| `apply_retirement_baseline` | `True` | — | Apply retirement to baseline trajectories |
| `apply_retirement_shock` | `True` | — | Apply retirement to shock (late sudden) trajectories |
| `apply_decreasing_staggered_shock` | `False` | — | — |
| `staggered_shock` | — | — | — |

## `conf/base/parameters_calculate_asset_and_company_npv.yml`

| Key | Default | Section | Description |
| --- | --- | --- | --- |
| `dcf` | — | — | Asset and company NPV parameters<br>Discount rate configuration<br>Baseline scenarios use standard discount rate |

## `conf/base/parameters_calculate_asset_earnings.yml`

| Key | Default | Section | Description |
| --- | --- | --- | --- |
| `market_passthrough` | `0` | — | Share of the differential carbon cost passed through to customers, 0.0–1.0.<br>0 => firm absorbs all differential carbon cost (conservative/stress test) |
| `include_growth_capex` | `False` | Cost switches | Which cost elements the earnings model charges to free cash flow (True/False).<br>OFF: IAM O&M already bundles annualized capital costs (REMIND/WITCH/POLES) |
| `include_replacement_capex` | `False` | Cost switches | Include CapEx for replacing retired eligible assets |
| `replacement_capex_rate` | `0.05` | Cost switches | Fraction (0.0–1.0) of each year's non-synthetic capacity growth capitalized as<br>roll-over / replacement CapEx. Read only when include_replacement_capex is True;<br>applied to `capacity_change` for assets that are not synthetic. |
| `include_decom_costs` | `False` | Cost switches | Include decommissioning costs for retired assets |
| `apply_continued_om_baseline` | `False` | Continued O&M | When enabled for a trajectory type, fixed O&M is charged on that trajectory's<br>FIRST-YEAR capacity for every year rather than on the year's actual capacity — so<br>a retiring asset keeps paying fixed costs it can no longer earn against. Enabling<br>it on the shock side only (the default) is what makes stranding bite in the shock<br>pathway without also penalising the baseline. |
| `apply_continued_om_shock` | `True` | Continued O&M | — |

## `conf/base/parameters_calculate_company_trajectories.yml`

| Key | Default | Section | Description |
| --- | --- | --- | --- |
| `shock_year` | `2033` | Shock timing | Calendar years (integers). `shock_year` is when market participants learn about<br>the policy shock; `alignment_year` is when the target trajectory must be reached.<br>`alignment_year` must be >= `shock_year` (validated by `check_input_parameters`).<br>The gap between them is the transition window: a longer window is a more realistic<br>phase-out, a shorter one a more abrupt repricing. |
| `alignment_year` | `2035` | Shock timing | — |

## `conf/base/parameters_plot_transition_risk_results.yml`

| Key | Default | Section | Description |
| --- | --- | --- | --- |
| `plot_staggered_shock_use_log_scale` | `False` | — | Transition-risk plotting parameters |
| `plot_staggered_shock_show_shock_absorption` | `False` | — | — |
| `reporting` | — | — | Reporting pipeline parameters<br>plotting toggles |

## `conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml`

| Key | Default | Section | Description |
| --- | --- | --- | --- |
| `baseline_scenario` | `"AR6_AIM/CGE 2.2_EN_NPi2020_1200f"` | Scenario selection | The scenario pair the run compares: `baseline_scenario` is the counterfactual<br>(current-policy) pathway; `target_scenario` is the climate-policy pathway whose<br>"late & sudden" alignment drives the shock.<br>Values: full scenario names as they appear in the `scenario` column of the<br>scenarios input (`data/05_model_input/scenarios.csv`). Both must come from the<br>same IAM provider and start in the same year (asserted in `filter_assets`).<br>Note: `filter_scenarios` prepends "AR6_<provider>_" automatically.<br>Known pairs per IAM: see docs/handover/scenario_catalog.md |
| `target_scenario` | `"AR6_AIM/CGE 2.2_EN_NPi2020_900f"` | Scenario selection | — |
| `reduce_granularity_from_asset_to_company_level` | `False` | Output granularity | True collapses asset-level results up to one row per company before the earnings<br>model runs; False keeps every asset distinct. Company-level runs are much cheaper<br>but lose the per-asset retirement and staggering detail the plots draw on. |
| `max_forecast_horizon` | `5` | Scope filters | Number of forecast years kept per asset, counted from the scenario start year:<br>assets are filtered to production years in [start_year, start_year + N] (years). |
| `ccs_on` | `False` | Scope filters | Technology scenario mapping control<br>If True, use w/ CCS scenarios for Coal, Gas, Biomass. If False, use w/o CCS<br>If Null, use technology without distinction. |
| `company_ids` | — | Scope filters | Empty list = all companies (no filter).<br>Values: list of company_id strings present in the companies input. Read the ids<br>you can choose from off the `company_id` column of your own companies input<br>(`data/05_model_input/companies_ownerships.csv`); the list below is an example<br>selection, not a required one. |
