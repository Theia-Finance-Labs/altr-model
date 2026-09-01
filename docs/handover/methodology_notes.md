# Methodology notes

Five modelling behaviours that shape every result but belong to no single
stage. They used to live only in the *Additional notes* section of the
methodology PDF; this page carries them as the current, maintained version -
where the two disagree, this page describes the code you have.

## Economic viability of a scenario pair

Not every scenario × technology × geography combination in
[`scenarios.csv`](input_data.md#scenarioscsv) is economically sane - some
combinations imply an asset can never turn a profit under that scenario, no
matter how the run parameters are set. Two checks worth running against the
file before committing to a `baseline_scenario` / `target_scenario` pair:

* **Fixed cost check.** If `om_cost_usd_per_mw_per_yr` exceeds
  `scenario_capacity_factor × 8760 × scenario_price` - the fixed O&M bill alone
  is larger than what the asset could earn running at its scenario capacity
  factor for a full year - EBITDA is guaranteed negative for that row,
  regardless of fuel or carbon costs.
* **Variable cost check.** If `fuel_price ÷ efficiency_decimal` exceeds
  `scenario_price` - the fuel cost of one more unit of output is already larger
  than the price received for it - every unit produced loses money before fixed
  costs are even counted.

Either condition flags a combination the model will dutifully run the numbers
on, but that has no realistic economic future. Checking the input data first is
cheaper than a debugging session on the output - see also
[Troubleshooting → the numbers look economically impossible](troubleshooting.md#the-run-finishes-but-the-numbers-look-economically-impossible).

## How assets are matched to a scenario geography

Every asset is assigned exactly one `scenario_geography`, used as a
merge/groupby key for the rest of the pipeline. The assignment matches the
asset's `country_iso2` against the geography → country mapping implied by
`country_iso2_list` in the scenarios file.

The most specific match wins: when a country is covered by more than one
scenario geography - say a single-country entry *and* a multi-country regional
bucket - the geography with the fewest countries is used. An exact-country
geography beats a 10-country region, which beats a 100-country region. If two
geographies cover the same country with the same specificity, the run fails
rather than picking one arbitrarily
(`ValueError: Ambiguous scenario geography assignment detected` - see
[Troubleshooting](troubleshooting.md#valueerror-ambiguous-scenario-geography-assignment-detected)).

## Granularity changes the shape of every output

The `reduce_granularity_from_asset_to_company_level` parameter changes what an
"asset" *is* in the output, not just how many rows there are:

1. **Asset granularity** (the switch off, the default): every physical asset
   stays distinct, and `company_npv.csv`'s `asset_count` is the true number of
   physical assets behind the row.
2. **Company granularity** (the switch on): physical assets are aggregated into
   one synthetic row per company/sector/technology/geography *before* the model
   runs. `asset_npv.csv`'s `asset_id` becomes a generated identifier of the form
   `NEW_<company_id>_<sector>_<technology>_<geography>`, and `asset_count`
   drops to the number of technology/geography buckets rather than physical
   assets.

!!! warning "Do not mix outputs from different granularity settings"
    Aggregating before the model runs is **not** equivalent to aggregating the
    model's asset-level output afterwards. Retirement, the staggered shock and
    continued O&M all operate differently on one synthetic technology-level
    "asset" than on the fleet of real ones it replaced, so the two settings are
    two different models of the same company - compare runs within one setting
    only.

Where the switch lives and what else it touches:
[Stage 1](pipelines/prepare_scenario_asset_and_company_inputs.md) and the
[parameters reference](parameters.md).

## Asset retirement: refurbishment wrap-around, not a hard cutoff

An asset's observed age is not used as-is. At its first valid observation, age
is wrapped modulo the technology's `lifetime_years`, and the asset ages
linearly from there. The model, in other words, assumes assets are refurbished
on a rolling lifetime cycle rather than permanently retired the first time they
exceed their nominal lifetime.

This changes which assets the model treats as "old" - near their *next*
retirement point - versus "recently refurbished", and therefore which assets
are subject to retirement-driven capacity drop-off when
`apply_retirement_baseline` / `apply_retirement_shock` are on. A 45-year-old
plant with a 40-year technology lifetime is 5 years into its second cycle, not
5 years past its death.

Retirement dating happens in
[Stage 3](pipelines/allocate_company_trajectories_to_assets.md)
(`extend_assets_and_attach_retirement`), using functions that live with
[Stage 1](pipelines/prepare_scenario_asset_and_company_inputs.md)'s asset
preparation.

## Synthetic assets for increasing technologies

For technologies whose scenario pathway is *increasing* (a renewables
build-out, say), a company's real assets are left at business-as-usual
capacity, and any gap versus the company's target trajectory is filled by a
single **synthetic** top-up asset. From `shock_year` onward, the synthetic
asset's capacity in year *t* is
`max(0, company_target[t] − sum(real_assets[t]))` - it fills exactly the gap
between the company-level target and what the real fleet already delivers, so
real + synthetic always reconciles to the company total.

A synthetic asset can only appear where the company already has a real one.
The model only produces a company trajectory for a
(company, scenario_geography, sector, technology) combination where the company
has at least one real asset, so a company can never be handed synthetic
build-out in a country or technology it has no presence in at all.

Synthetic rows are flagged `is_synthetic = True` in the asset-level outputs -
one of the [sanity checks](user_guide.md#5-sanity-checks-before-you-trust-a-run)
is watching for companies whose NPV a synthetic asset dominates. The allocation
mechanics are in
[Stage 3](pipelines/allocate_company_trajectories_to_assets.md).
