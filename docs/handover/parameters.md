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
`conf/base/parameters.yml` holds the run configuration you normally touch;
the per-pipeline files hold the advanced, methodology-internal knobs.

Only keys at the top level of a file are listed. A nested block (`dcf:`,
`reporting:`, `mcpr_regional_value_factors:`, `staggered_shock:`) appears once,
with an empty default — its sub-keys are annotated in the YAML file itself and
are addressed in pipelines as `params:<block>.<sub_key>`.

## `conf/base/parameters.yml`

| Key | Default | Section | Description |
| --- | --- | --- | --- |
| `baseline_scenario` | `"AR6_REMIND-MAgPIE 2.1-4.2_EN_NPi2020_3000"` | Scenario selection | The scenario pair the run compares: `baseline_scenario` is the counterfactual<br>(current-policy) pathway; `target_scenario` is the climate-policy pathway whose<br>"late & sudden" alignment drives the shock.<br>Values: full scenario names as they appear in the `scenario` column of the<br>scenarios input (`data/05_model_input/downloaded_scenarios.csv`). Both must come<br>from the same IAM provider and start in the same year (asserted in filter_assets).<br>Note: filter_scenarios prepends "AR6_<provider>_" automatically<br>Known pairs per IAM: see docs/handover/scenario_catalog.md |
| `target_scenario` | `"AR6_REMIND-MAgPIE 2.1-4.2_EN_NPi2020_500"` | Scenario selection | — |
| `shock_year` | `2033` | Shock timing | Calendar years (integers). `shock_year` is when market participants learn about<br>the policy shock; `alignment_year` is when the target trajectory must be reached.<br>`alignment_year` must be >= `shock_year` (validated by check_input_parameters). |
| `alignment_year` | `2038` | Shock timing | Extended from 2035 to give 5-year transition window<br>Longer window = more realistic phase-out, but still abrupt enough<br>for meaningful fossil value destruction |
| `company_ids` | `[]` | Scope filters | Empty list = all companies (no filter)<br>Values: list of company_id strings present in the companies input.<br>Read the ids you can choose from off the `company_id` column of your own<br>companies input (`data/05_model_input/downloaded_companies.csv`). |
| `ownership_type` | `"direct"` | Scope filters | Ownership level used to attach assets to companies.<br>Values: "direct" (ownership_level == 1) \| "indirect" (ownership_level >= 2). |
| `ccs_on` | `False` | Scope filters | Technology scenario mapping control<br>If True, use w/ CCS scenarios for Coal, Gas, Biomass. If False, use w/o CCS<br>If Null, use technology without distinction. |
| `max_forecast_horizon` | `5` | Scope filters | Number of forecast years kept per asset, counted from the scenario start year:<br>assets are filtered to production years in [start_year, start_year + N] (years). |
| `enable_mcpr` | `True` | MCPR (market clearing price) | In wholesale electricity markets, all generators receive the same clearing price<br>set by the marginal (most expensive dispatched) plant. IAM scenarios report<br>technology-specific "prices" approximating LCOE, not market clearing prices.<br>This adjustment derives a reference market clearing price and applies value factors.<br><br>References:<br>- Hirth (2013), "The Market Value of Variable Renewables," Energy Economics 38:218-236<br>- Halttunen et al. (2022), "Global Assessment of the Merit-Order Effect," Nature Energy 7:1154-1164<br>- Ueckerdt et al. (2013), "System LCOE," Energy 63:61-75<br>- Borenstein, Bushnell & Wolak (2000), J. Industrial Economics 48(2):197-223<br>Advanced MCPR knobs (method, markup, merit-order alpha/floor, regional and dynamic<br>value factors) live in conf/base/parameters_earnings_model.yml.<br>Enable/disable the MCPR price adjustment |
| `mcpr_mode` | `"auto"` | MCPR (market clearing price) | "auto" \| "carbon_explicit" \| "merit_order_decline"<br>auto: selects mode based on carbon price coverage in scenario data<br>carbon_explicit: forces full_ef carbon cost (for IAMs with carbon prices)<br>merit_order_decline: clearing price declines with VRE share (for IAMs without) |
| `market_passthrough` | `0` | MCPR (market clearing price) | Share of the differential carbon cost passed through to customers, 0.0–1.0.<br>0 => firm absorbs all differential carbon cost (conservative/stress test) |
| `price_ramp` | `True` | MCPR (market clearing price) | Price ramp (RC4 fix): blend baseline->target prices over [shock_year, alignment_year]<br>instead of hard-switching at shock_year. Eliminates near-term price windfall where<br>target prices are 30-50% higher than baseline at shock year.<br>RC4 fix: blend baseline->target prices over [shock_year, alignment_year] |
| `include_growth_capex` | `False` | Cost switches | Which cost elements the earnings model charges to free cash flow (True/False).<br>OFF: IAM O&M already bundles annualized capital costs (REMIND/WITCH/POLES) |
| `include_replacement_capex` | `True` | Cost switches | Include CapEx for replacing retired eligible assets |
| `include_decom_costs` | `True` | Cost switches | Include decommissioning costs for retired assets |

## `conf/base/parameters_distribute_impacts_to_asset_level.yml`

| Key | Default | Section | Description |
| --- | --- | --- | --- |
| `apply_retirement_baseline` | `True` | — | Apply retirement to baseline trajectories |
| `apply_retirement_shock` | `True` | — | Apply retirement to shock (late sudden) trajectories |
| `apply_decreasing_staggered_shock` | `False` | — | — |
| `staggered_shock` | — | — | — |

## `conf/base/parameters_earnings_model.yml`

| Key | Default | Section | Description |
| --- | --- | --- | --- |
| `mcpr_method` | `"marginal_technology"` | MCPR (Marginal Cost Price Ratio) Adjustment | The on/off switch (enable_mcpr) and the mode selector (mcpr_mode) are in<br>conf/base/parameters.yml; the knobs below tune the mechanism itself.<br>Method: "marginal_technology" (max price among dispatchables) |
| `mcpr_markup_factor` | `1.0` | MCPR (Marginal Cost Price Ratio) Adjustment | Additional markup over marginal cost (1.0 = no extra markup) |
| `mcpr_merit_order_alpha` | `0.006` | MCPR (Marginal Cost Price Ratio) Adjustment | Merit order price elasticity: -0.6% per 1pp VRE share (IMF WP 2022/220) |
| `mcpr_merit_order_floor` | `0.5` | MCPR (Marginal Cost Price Ratio) Adjustment | Min clearing price as fraction of original (scarcity rents floor) |
| `enable_dynamic_capture_ratios` | `False` | MCPR (Marginal Cost Price Ratio) Adjustment | Region-specific VRE value factors (Hirth 2013; Halttunen et al. 2022; S&P Global 2025)<br>Three tiers based on VRE penetration and market structure:<br>Tier 1 (>20% VRE): EU, PAC_OECD — aggressive cannibalization, lower VF<br>Tier 2 (8-20% VRE): USA, China, India, Japan, LatAm — moderate, current defaults<br>Tier 3 (<8% VRE): Middle East, Africa, Indonesia, Ref Econ — near 1.0<br><br>When enable_regional_mcpr_vf is False, uniform global defaults are used (backward-compatible).<br>When True, geography-specific value factors from mcpr_regional_value_factors are applied.<br>Dynamic capture ratios (Hirth 2013; Halttunen et al. 2022)<br>When True, VRE value factors are computed as a function of VRE capacity share<br>per (geography, year, scenario_type), replacing the static defaults above.<br>This is a universal market mechanism applied consistently across all IAMs:<br>Solar PV:      VF = max(1.10 - 1.5 × vre_share, 0.40)<br>Wind Onshore:  VF = max(1.05 - 0.8 × vre_share, 0.50)<br>Wind Offshore: VF = max(1.07 - 0.7 × vre_share, 0.55)<br>Solar CSP:     VF = max(1.05 - 0.3 × vre_share, 0.80)<br>Dispatchable:  VF = 1.0<br>Overrides static VFs AND regional VFs when enabled. |
| `enable_regional_mcpr_vf` | `False` | MCPR (Marginal Cost Price Ratio) Adjustment | — |
| `mcpr_regional_value_factors` | — | MCPR (Marginal Cost Price Ratio) Adjustment | Tier 1: High VRE (>20%) — strong cannibalization observed empirically |
| `apply_continued_om_baseline` | `False` | MCPR (Marginal Cost Price Ratio) Adjustment | Frozen capacity feature - continued O&M costs on stranded capacity<br>Apply continued O&M costs to baseline trajectories |
| `apply_continued_om_shock` | `True` | MCPR (Marginal Cost Price Ratio) Adjustment | Apply continued O&M costs to shock trajectories |
| `dynamic_marginal_ef` | `True` | MCPR (Marginal Cost Price Ratio) Adjustment | Dynamic marginal emission factor (RC5 fix)<br>When True, marginal_EF declines over time proportional to VRE capacity share,<br>modeling the merit order evolution where renewables displace fossils from the<br>marginal position. This causes gas/coal to face increasing differential carbon<br>costs as the carbon rent from high-EF marginal generators disappears.<br>Formula: marginal_ef(t) = marginal_ef_static * (1 - vre_share(t))^2<br>Quadratic decay: gas starts paying at ~34% VRE (linear would be 56%).<br>RC5 fix: marginal EF declines with VRE share, gas faces rising carbon costs |
| `carbon_cost_method` | `"full_ef"` | MCPR (Marginal Cost Price Ratio) Adjustment | Carbon cost method: how emission factors are applied to compute carbon costs.<br><br>"differential_ef" — carbon_cost = Q × cp × max(EF - marginal_EF, 0) × (1 - passthrough)<br>Assumes IAM electricity prices embed the marginal generator's carbon cost.<br>Appropriate for IAMs where prices reflect carbon (e.g., AIM/CGE: $64/MWh C1→C7 spread).<br>Gas (as marginal generator) pays ~$0 differential carbon cost.<br><br>"full_ef" — carbon_cost = Q × cp × EF × (1 - passthrough)<br>Uses each technology's full emission factor. Appropriate for IAMs where<br>prices minimally embed carbon (e.g., WITCH: only $9/MWh C1→C7 spread<br>despite $722/tCO2 carbon price difference). Eliminates the gas free-ride.<br><br>For WITCH 5.0 scenarios: use "full_ef" (empirically justified — prices are near-flat<br>across stringencies, so there is no embedded carbon to double-count).<br>For AIM/CGE scenarios: use "differential_ef" (prices already capture carbon effects). |

## `conf/base/parameters_inputs_postproc.yml`

| Key | Default | Section | Description |
| --- | --- | --- | --- |
| `reduce_granularity_from_asset_to_company_level` | `False` | — | — |
| `theta_capex_recovery` | `1` | — | — |

## `conf/base/parameters_reporting.yml`

| Key | Default | Section | Description |
| --- | --- | --- | --- |
| `plot_staggered_shock_use_log_scale` | `False` | — | — |
| `reporting` | — | — | Reporting pipeline parameters |

## `conf/base/parameters_valuation_model.yml`

| Key | Default | Section | Description |
| --- | --- | --- | --- |
| `dcf` | — | — | DCF/Valuation model parameters<br>Discount rate configuration<br>Baseline scenarios use standard discount rate |
