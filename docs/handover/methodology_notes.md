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

!!! warning "22 countries never reach the matching at all"
    Before any geography is assigned, `filter_assets` silently drops every
    asset whose `country_iso2` is missing - and every asset in a hardcoded
    list of 22 jurisdictions: AS, BM, AW, SZ, FO, CW, DM, GF, PS, KN, MK, IM,
    PM, XK, SC, SS, AX, KY, BQ, GG, MS, JE. This is a legacy NGFS-scenario
    workaround (the code marks it `TODO REMOVE HARDFIX FOR NGFS`), kept for
    output comparability until it is removed deliberately. If an asset count
    does not reconcile against your source extract, check these countries
    before anything else - no warning is logged when they are dropped.

## Granularity changes the shape of every output

The `reduce_granularity_from_asset_to_company_level` parameter changes what an
"asset" *is* in the output, not just how many rows there are:

1. **Asset granularity** (the switch off, the default): every physical asset
   stays distinct, and `company_npv.csv`'s `asset_count` is the true number of
   physical assets behind the row.
2. **Company granularity** (the switch on): physical assets are aggregated into
   one synthetic row per company/sector/technology/geography *before* the model
   runs. `asset_npv.csv`'s `asset_id` becomes a generated identifier of the form
   `unique_company_asset_<sector>_<technology>_<company_id>_<geography>`, and
   `asset_count` drops to the number of technology/geography buckets rather
   than physical assets. (The similar-looking
   `NEW_<company_id>_<sector>_<technology>_<geography>` is a different id
   entirely - the synthetic build-out asset below - and it appears under either
   granularity setting.)

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

**The retirement floor.** The dated retirement year is not applied as-is: when
allocation zeroes retired capacity it clips retirement to `alignment_year + 1`,
so no asset retires before the transition window closes. An asset dated to
retire in 2035 under `alignment_year: 2038` therefore keeps running until 2039.
The floor exists so retirement never removes capacity the shock has not yet had
a chance to act on — the transition path would otherwise be reading a fleet
that had already shrunk for unrelated reasons. Every consumer of the retirement
year applies the same floor, `frozen_capacity_at_retirement` included; the raw
`retirement_year` carried on the panel is the *input* to it, not the year the
asset actually stops.

## Synthetic assets for increasing technologies

For technologies whose scenario pathway is *increasing* (a renewables
build-out, say), a company's real assets are left at business-as-usual
capacity, and any gap versus the company's requested trajectory is filled by a
single **synthetic** top-up asset. From `shock_year` onward (and only from
there - before the shock year the synthetic asset carries no capacity), its
capacity in year *t* is
`max(0, company_late_sudden_requested[t] − sum(real_assets[t]))`. The series
being closed on is the **late & sudden requested** company path, not the raw
`target` scenario path: the requested path is the one the company is actually
being held to.

The reconciliation is **one-sided**. The `max(0, ...)` closes a *shortfall*
only; there is no downward correction. Where a company's real assets already
carry more capacity at business-as-usual than the requested path asks for, the
top-up is zero and the company's total stays *above* the requested path - real
capacity is never reduced to meet it. So real + synthetic equals the requested
path exactly only in the years the real fleet falls short of it, and is greater
than or equal to it otherwise.

A synthetic asset can only appear where the company already has a real one.
The model only produces a company trajectory for a
(company, scenario_geography, sector, technology) combination where the company
has at least one real asset, so a company can never be handed synthetic
build-out in a country or technology it has no presence in at all.

A synthetic asset burns like the fleet it was built out from. It has no plant
record of its own, so it has no measured emission factor; it takes the
capacity-weighted mean emission factor of the company's real assets in the same
(sector, technology, scenario_geography) group, year by year. Where the company
holds no real asset in that group the model widens the group - first to every
real asset in that technology and geography, then to the technology as a whole -
and only falls back to zero when the technology carries no emission factor
anywhere, which it logs as a warning. The weighting capacity is the BAU
trajectory rather than the post-shock one, so a synthetic's emission factor is a
property of the fleet and not of the shock. Renewable technologies are the
exception: a missing emission factor there genuinely is zero, so they are
zero-filled before the inheritance rule sees them.

Synthetic rows are flagged `is_synthetic = True` in the asset-level outputs -
one of the [sanity checks](user_guide.md#5-sanity-checks-before-you-trust-a-run)
is watching for companies whose NPV a synthetic asset dominates. The allocation
mechanics are in
[Stage 3](pipelines/allocate_company_trajectories_to_assets.md).

## Ownership attribution and aggregation

A physical asset can appear in the ownership data under more than one
relationship type - a **direct** stake (the operating owner's share) and an
**equity** stake (a look-through share held via intermediaries) - and can be
claimed by several companies at once (a parent through equity, its subsidiary
through direct, JV partners each through theirs). Any attribution rule answers
two different questions, and no single rule answers both:

1. **Economic exposure** - what fraction of this asset's cash flows does
   *this company* have a claim on?
2. **Physical accounting** - do the attributed shares, summed over all
   companies in the universe, add up to the real fleet?

`ownership_aggregation` selects the rule. **`tier_filter`** (shipped default)
selects one relationship type (`ownership_type`, default `direct`) and
consolidates within it: each megawatt is counted once, under its operating
owner; the company universe is operating owners; this is the basis of the
validated baseline and previously published results. **`sum`** totals every
stake a company holds in an asset-year across relationship types
(50.00% direct + 0.45% equity = 50.45%): each company carries its full
economic claim; equity-only holders enter the universe. On the current data,
`sum` attributes 2.68x the fleet's ownership-weighted capacity across 7,752
claimants; `tier_filter` covers the same assets once through 4,899 operating
owners.

**Precedent.** PACTA-family attribution uses proportional equity look-through
including minority stakes, level by level up the ownership tree ("if Company A
owns x% of Asset 1, it gets attributed x% of its production" - PACTA for
Banks Methodology §1.7.2; PACTA for Investors Methodology v1.0 §1.2.3, the
"Equity Ownership" consolidation). Shares sum to 100% only at the
direct-asset level; the same megawatt then appears in the subsidiary and,
stake-weighted, in every parent - PACTA accepts this in the company universe
and avoids double counting only at the financial layer, where each security
maps to exactly one company node. PACTA also defines a second rule per asset
class (Credit Ownership, one node per debt instrument): attribution follows
analytical purpose even within one methodology, which is why ALTR exposes the
choice as a parameter rather than fixing one mode.

**Consequences to hold explicitly:**

- Under `sum`, every cross-company aggregate (company-technology tables,
  totals) is claim-weighted, not physical - the same plant is counted once
  per claimant. Label aggregates accordingly or de-duplicate first.
- Ownership enters the model as a linear scalar on capacity and every major
  cost line is linear in it, while stranding classification is sign-based -
  so a company's `npv_change` ratio is invariant to stake *size* and moves
  only through *composition* (which assets and companies enter). Absolute
  levels scale with the full attribution factor: risk signals may be compared
  across modes with care; absolute levels may never be.
- Allocation runs per company independently: under `sum` a company's claim
  list is larger and each claim smaller, giving the staggering finer
  granularity, but physical coherence across companies is not enforced - two
  claimants may retire their shares of one plant in different years.
- `sum` trusts the ownership tree's within-company non-overlap (a stake
  reported both directly and via look-through for the same company would
  double count inside that company - not observed in the current data, not
  guarded against). `tier_filter` conversely discards real economic exposure
  by construction. Both are conventions; every published number should name
  the one it used.
