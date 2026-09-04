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
| `retirement_timing` | `"natural"` | Natural retirement timing (decision D9) | When a NATURAL retirement — asset age past its technology's lifetime — takes<br>effect. This is not a policy exit: the date is the same with or without the<br>shock, and it is read from `retirement_year` alone.<br>"deferred_to_window" — eff_retirement = max(retirement_year, alignment_year + 1).<br>Every natural retirement dated on or before the<br>alignment year is held back to alignment_year + 1.<br>With `alignment_year: 2038` that bunches decades of<br>retirements into 2039, and holds each of those assets<br>at full capacity until then, in BOTH pathways.<br>"natural"           — each retirement lands on its own year, in both<br>pathways identically. It then cancels out of the<br>shock-minus-baseline difference by construction,<br>which is the isolation the clamp was reaching for,<br>without inventing a cliff in either level.<br>SHOCK-INDUCED capacity reduction is unaffected either way: the staggering and<br>phase-out machinery runs off `shock_year` and the company's adjusted path,<br>never through this switch.<br>"deferred_to_window" \| "natural" |
| `staggered_shock` | — | Natural retirement timing (decision D9) | Read only when apply_decreasing_staggered_shock is True (it ships False). |

## `conf/base/parameters_calculate_asset_and_company_npv.yml`

| Key | Default | Section | Description |
| --- | --- | --- | --- |
| `dcf` | — | — | Asset and company NPV parameters<br>Discount rate configuration<br>Baseline scenarios use standard discount rate |

## `conf/base/parameters_calculate_asset_earnings.yml`

| Key | Default | Section | Description |
| --- | --- | --- | --- |
| `market_passthrough` | `0` | — | Share of the differential carbon cost passed through to customers, 0.0–1.0.<br>0 => firm absorbs all differential carbon cost (conservative/stress test) |
| `carbon_cost_method` | `"full_ef"` | Carbon cost | How emission factors enter the carbon cost.<br>"full_ef"         — cost = Q × cp × EF. Every technology pays for everything it<br>emits. Right for IAMs whose electricity prices barely move<br>with carbon stringency (WITCH: a $9/MWh C1→C7 price spread<br>against a $722/tCO2 carbon-price difference), so there is no<br>embedded carbon to double-count.<br>"differential_ef" — cost = Q × cp × max(EF − marginal_EF, 0): only the excess<br>over the price-setting generator. Right for IAMs whose<br>prices already embed the marginal generator's carbon cost<br>(AIM/CGE: a $64/MWh spread).<br><br>The key reads marginal_EF, which the market-clearing-price adjustment<br>produced. That adjustment is retired here (2026-09-01 owner ruling), so<br>marginal_EF is 0 on today's inputs and the two methods coincide. Kept so the<br>differential path works if the adjustment ever returns, and tested against an<br>injected non-zero marginal EF so the switch is not carried untested.<br><br>A companion key, `dynamic_marginal_ef`, decayed marginal_EF with the VRE<br>capacity share. It was deleted by owner ruling 14: it scaled a value that is<br>always zero, so it could not change a number, and its (1 - vre_share)² curve<br>was an untested assumption sitting in the tree waiting to become live. |
| `include_growth_capex` | `False` | Cost switches | Which cost elements the earnings model charges to free cash flow (True/False).<br>OFF: IAM O&M already bundles annualized capital costs (REMIND/WITCH/POLES) |
| `include_replacement_capex` | `True` | Cost switches | Include CapEx for routine capital maintenance |
| `replacement_capex_rate` | `0.02` | Cost switches | Fraction (0.0–1.0) of a real asset's INSTALLED capacity (MW) treated as rolled<br>over each year; the resulting MW are priced at `capex_usd_per_mw`, which is<br>what makes the charge equivalent to spending that fraction of replacement cost<br>per year — the 1–3%/yr standard utility benchmark for routine capital<br>maintenance (EPRI; Lazard LCOE methodology). One rate, two readings, same<br>number. Read only when include_replacement_capex is<br>True; charged on `asset_trajectory`, so a flat asset still pays it, and skipped<br>for assets retiring that year (already charged decommissioning) and for<br>synthetic assets (accounting constructs, not plant). |
| `include_decom_costs` | `True` | Cost switches | Decommissioning costs on retired capacity. `scrap_usd_per_mw` arrives negative<br>(= -capex/2); it is charged as a POSITIVE outflow, so retiring an asset costs<br>money rather than paying the owner.<br>Include decommissioning costs for retired assets |
| `apply_continued_om_baseline` | `False` | Continued O&M | When enabled for a trajectory type, fixed O&M is charged on that trajectory's<br>FIRST-YEAR capacity for every year rather than on the year's actual capacity — so<br>a retiring asset keeps paying fixed costs it can no longer earn against. Enabling<br>it on the shock side only (the default) is what makes stranding bite in the shock<br>pathway without also penalising the baseline. Applies ONLY to<br>decreasing-technology (high-carbon alignment) assets on the covered<br>trajectory; every other row is charged on actual capacity regardless. |
| `apply_continued_om_shock` | `True` | Continued O&M | The single biggest stranding lever: on the fixture slice, turning this off<br>moves the median npv_change from -0.42 to -0.16. Same first-year-capacity<br>mechanics as the baseline switch above, applied to the shock pathway. |

## `conf/base/parameters_calculate_company_trajectories.yml`

| Key | Default | Section | Description |
| --- | --- | --- | --- |
| `shock_year` | `2033` | Shock timing | Calendar years (integers). `shock_year` is when market participants learn about<br>the policy shock; `alignment_year` is when the target trajectory must be reached.<br>`alignment_year` must be >= `shock_year` (validated by `check_input_parameters`).<br>The gap between them is the transition window: a longer window is a more realistic<br>phase-out, a shorter one a more abrupt repricing. |
| `alignment_year` | `2038` | Shock timing | 5-year transition window: long enough to be a realistic<br>phase-out, short enough to still reprice abruptly. |
| `price_ramp` | `True` | Price ramp | How the late & sudden pathway picks up the target scenario's financial surfaces<br>(prices, fuel, capacity factor, CapEx, O&M, carbon price).<br>False — hard switch at `shock_year`.<br>True  — blend baseline -> target linearly across [shock_year, alignment_year].<br>The hard switch hands the shock pathway a near-term price windfall: target<br>prices sit 30-50% above baseline at the shock year, so fossil assets can gain<br>value under a climate shock. Blending removes that artefact. A ramped pathway<br>keeps carrying the BASELINE scenario name and scenario_type, because its<br>surfaces are a mixture rather than either scenario's. |

## `conf/base/parameters_plot_transition_risk_results.yml`

| Key | Default | Section | Description |
| --- | --- | --- | --- |
| `plot_staggered_shock_use_log_scale` | `False` | — | Transition-risk plotting parameters |
| `plot_staggered_shock_show_shock_absorption` | `False` | — | — |
| `reporting` | — | — | Reporting pipeline parameters<br>plotting toggles |

## `conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml`

| Key | Default | Section | Description |
| --- | --- | --- | --- |
| `baseline_scenario` | `"AR6_AIM/CGE 2.2_EN_NPi2020_1200f"` | Scenario selection | The scenario pair the run compares: `baseline_scenario` is the counterfactual<br>(current-policy) pathway; `target_scenario` is the climate-policy pathway whose<br>"late & sudden" alignment drives the shock.<br>Values: full scenario names as they appear in the `scenario` column of the<br>scenarios input (`data/05_model_input/scenarios.csv`). Both must start in the<br>same year (asserted in `filter_assets`) and SHOULD come from the same IAM<br>provider - the provider is NOT checked: a cross-provider pair that shares a<br>start year runs to completion, silently intersecting the two providers'<br>geographies/technologies with only a logged warning. Enforce same-provider<br>yourself.<br>NOTE (corrected 2026-09-02): `filter_scenarios` does NOT prepend<br>"AR6_<provider>_" -- it asserts the name below appears VERBATIM in the<br>`scenario` column and prefixes nothing (`_input_nodes.py::filter_scenarios`;<br>`grep -rn 'AR6_' src/` is empty). The committed fixture stores full names<br>("AR6_WITCH 5.0_EN_NoPolicy") for exactly this reason. If your scenarios<br>extract carries bare names, the prefix must be restored upstream -- the<br>internal staging script (`workspace/stage_marts_inputs.py`) does it, and is<br>not part of a delivered copy.<br>The pair below is NOT present in the 2026-09-01 extract; the full-universe<br>run overrides it in `conf/full/` with the WITCH pair that is.<br>Known pairs per IAM: see docs/handover/scenario_catalog.md |
| `target_scenario` | `"AR6_AIM/CGE 2.2_EN_NPi2020_900f"` | Scenario selection | — |
| `ownership_type` | `"direct"` | Ownership tier | Which rung of the ownership tree attaches assets to companies.<br>Values: whatever the companies input's tier column actually holds. The column<br>comes from the marts export; under the NAMED schema (`ownership_type`) its<br>values there are "direct" and "equity" — not "indirect". Under the NUMBERED<br>schema (`ownership_level`) "direct" selects level 1, "indirect"/"equity"<br>select level 2+, and a bare number selects that level; anything else raises<br>rather than being taken as "some indirect rung".<br>Matching ignores case and surrounding whitespace on both sides.<br>The 2026-08-25 deliverables drop carries NEITHER column, and<br>`scripts/prepare_inputs.py` refuses such a file rather than letting every rung<br>of the ownership chain into the run: a re-export including `ownership_type`<br>is required before that drop can be converted.<br>A tier the data does not carry is rejected with a ValueError listing the<br>values that are available, rather than silently emptying the run.<br>A company's stake in an asset is recorded at several tiers — a direct holding<br>and the equity stakes rolling up through subsidiaries. They are alternative<br>views of the same capacity, not additive ones, so a run reports on one tier.<br>The tier is selected BEFORE stakes are consolidated, so consolidation only ever<br>sums within the tier it was given.<br>Read only when `ownership_aggregation` is "tier_filter" (the default); "sum"<br>keeps every tier and ignores this key. |
| `ownership_aggregation` | `"tier_filter"` | Ownership aggregation | How the several stakes one company holds in one asset-year are combined.<br>Values: "tier_filter" (DEFAULT) \| "sum".<br>"tier_filter" — select the `ownership_type` rung above, then consolidate the<br>duplicate stakes WITHIN that rung into one row per company-asset-year. The<br>tiers are alternative views of the same capacity, so only one is reported.<br>This is the validated baseline: it is the behaviour the pinned fixture NPVs<br>and last year's published results were produced under.<br>"sum" — total every holding: direct + equity per company-asset-year, all<br>tiers entering. This is TRISK's reading, and the mode to pick when results<br>have to line up with a TRISK run.<br>Absolute outputs are NOT comparable across the two modes. On the fixture slice<br>one company holds a plant at 50.00% direct and 0.45% equity: "tier_filter"<br>gives it 50.00%, "sum" gives it 50.45%, and the owner-asset universe grows<br>roughly 2.2× under "sum" — every absolute number (NPV, earnings, capacity)<br>scales with it. Only within-mode comparisons mean anything. |
| `reduce_granularity_from_asset_to_company_level` | `False` | Output granularity | True collapses asset-level results up to one row per company before the earnings<br>model runs; False keeps every asset distinct. Company-level runs are much cheaper<br>but lose the per-asset retirement and staggering detail the plots draw on. |
| `max_forecast_horizon` | `5` | Scope filters | Observed forecast years kept per asset, counted from the scenario start year:<br>assets are filtered to production years in [start_year, start_year + N], a<br>closed interval - N=5 keeps six calendar years. Not the valuation window: the<br>kept panel is then flat-extended to the scenario's last year, so the shock is<br>always inside the valued period. |
| `ccs_on` | `False` | Scope filters | Technology scenario mapping control<br>If True, use w/ CCS scenarios for Coal, Gas, Biomass. If False, use w/o CCS<br>If Null, use technology without distinction. |
| `company_ids` | — | Scope filters | Empty list = all companies (no filter). NOTE: in the internal repository the<br>list below is POPULATED with 30 example companies, so an out-of-the-box run<br>covers those 30, not the universe (a sanitized delivered copy ships it<br>empty - the export strips the ids). Empty it (company_ids: []) for a full<br>run, or use `--env full` (internal repository only), which does.<br>Values: list of company_id strings present in the companies input. Read the ids<br>you can choose from off the `company_id` column of your own companies input<br>(`data/05_model_input/companies_ownerships.csv`); the list below is an example<br>selection, not a required one. |
| `decom_cost_fraction_of_capex` | `null` | Decommissioning cost calibration | The scenarios input delivers `scrap_usd_per_mw` as -capital_cost/2: retiring a<br>plant is charged HALF of what building it costs (`include_decom_costs` in<br>parameters_calculate_asset_earnings.yml books it as a positive outflow, and the<br>terminal value's decommissioning floor prices standing capacity with the same<br>number). Real-world decommissioning for thermal and renewable plant runs closer<br>to 5–15% of build cost; nuclear is the exception.<br>Values: null (DEFAULT) keeps the delivered column, i.e. the 50% convention the<br>pinned fixture and golden runs were produced under. A number in [0, 1] rewrites<br>scrap as -(fraction × capex_usd_per_mw) for every scenario row, so BOTH<br>consumers move together. Measured on the full universe as calibration arm R11<br>(docs/superpowers/plans/measurement-batch-results.md). |
