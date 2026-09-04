# Stage 5 - `calculate_asset_and_company_npv`

| | |
| --- | --- |
| Source | `src/altr_model/pipelines/calculate_asset_and_company_npv/` |
| Tags | `altrisk` |
| Runs after | [Stage 4 - `calculate_asset_earnings`](calculate_asset_earnings.md) |
| Runs before | [Stage 6 - `plot_transition_risk_results`](plot_transition_risk_results.md) |
| Nodes | 4 |

## Purpose

Converts the per-asset FCFF series into present values. Each year's cash flow is
discounted at one real rate, `dcf.discount_rate` (owner ruling 2026-09-05: a
single rate for both pathways; until then two keys shipped equal at 7%, and the
shock key was inert under the price ramp), plus the technology carbon-risk
spread; a terminal value is added beyond the forecast horizon; and the result is
rolled up from asset to company-technology to company level. The whole
baseline-vs-shock difference therefore comes from the cash flows, never from a
pathway-specific rate. The two pathways stay distinguishable by
`trajectory_type` regardless.

The terminal value is where most of the valuation judgement sits. It can be
switched off (`terminal_value.method: "none"`) or computed from a **normalized**
terminal FCFF — the mean of the last `terminal_value.normalization_window` years
rather than the final year alone, so that one transition-period CapEx spike
cannot decide an asset's entire terminal value. Switching the method to
`"none"` disables the **whole** three-tier structure below - the stranding
zero and the carbontech annuity included, not just the perpetuity - because
the tier split lives inside the perpetuity method.

With `dcf.stranding_aware_tv` on (the default), that terminal FCFF is routed
through a tiered split rather than a single perpetuity. The tiers are checked in
order and the first match wins:

| Tier | Condition | Terminal value |
| --- | --- | --- |
| Stranded | FCFF <= 0 for the last `stranding_consecutive_years` years | **Zero.** A rational owner exercises the abandonment option rather than funding perpetual losses |
| Declining carbontech | Still profitable, `alignment_type` is high-carbon | A **finite annuity** over `brown_remaining_life_years`, reflecting a fossil asset's finite remaining economic life in a transition |
| Bounded negative | Terminal FCFF negative, not stranded | Under `negative_tv_method: "bounded_annuity"` (shipped), the **least bad of two exits**; see below |
| Everything else | — | The standard Gordon-growth **perpetuity** |

The perpetuity tier is the remainder: it applies wherever the terminal FCFF is
non-zero, the discount rate exceeds the growth rate, **and none of the earlier
tiers claimed the row** - a still-profitable declining carbontech asset takes
the annuity, never the perpetuity.

### The negative terminal value is bounded

An asset whose terminal FCFF is negative but which is *not* stranded used to
take a negative Gordon-growth perpetuity, which on a negative cash flow is
**unbounded below**: worth less than nothing, forever. `negative_tv_method`
replaces that with the two choices an owner actually has, both negative, taking
the larger (the smaller loss):

    run it out = final_fcff * annuity_factor(r, N_remaining)
    exit now   = -decom_cost = -abs(scrap_usd_per_mw) * capacity
    TV         = max(run_out, exit_now)

`r` is the group's own rate with its spread included, and `N_remaining` is
`lifetime_years - asset_age` at the horizon, falling back to
`brown_remaining_life_years` where the asset carries no lifetime. Where no
scrap price is available there is no exit quote, so there is no floor and the
run-out annuity stands alone.

**Past its lifetime and still standing** (`N_remaining <= 0`, capacity above
zero) the run-out arm does not exist — there is no life left to run out — so
the exit arm binds and the terminal value is `-decom_cost` (owner ruling C2).
Clamping `N_remaining` to zero and keeping the arm would make `run_out` exactly
zero, which beats every negative exit bill and hands the asset a free walk-away
from its decommissioning cost. Where *neither* arm is available — past its
lifetime and no scrap price — the group takes no terminal value at all.

`negative_tv_method: "perpetuity"` reaches the old unbounded behaviour for the
ablation batch.

### The terminal anchor

`dcf.tv_anchor_policy` decides what the anchor is allowed to see. Under
`"operating"` (shipped) two corrections apply, both about the anchor describing
a *perpetuity*: a group standing at **zero capacity at the horizon** has no
terminal value at all regardless of what its final cash flows say, and
**decommissioning charges are excluded** from the anchor years' FCFF, because
capitalising a one-off exit bill into a perpetuity charges it every year
forever. `"raw"` reaches the pre-proposal behaviour for the ablation.

The zero-capacity rule outranks every tier above. The tiers cannot reach it on
their own because the anchor is a *window*: at `normalization_window: 3` a
plant that retired two years before the horizon still has live years inside the
window, and was handed a terminal value off cash flows it can no longer earn.

### Which carrier decides "brown"

`dcf.spread_carrier` decides it once, for **both** the discount spread and the
terminal growth rate — owner ruling 13 tied them together deliberately, so an
asset cannot be brown for its rate and green for its growth.

| `spread_carrier` | Brown means | Greenium |
| --- | --- | --- |
| `"technology"` (shipped) | Membership of `brown_technologies` | None. `green_discount_spread` is retired and ignored with a warning |
| `"alignment_type"` | `misaligned_high_carbon` or `aligned_high_carbon` | `green_discount_spread` is live; `0.005` reproduces the pre-ruling-12 behaviour |

Under the shipped carrier `brown_discount_spread` is added to the scenario base
rate for the named technologies and nothing is subtracted from anything, and
`g_real_brown` / `g_real_green` follow the same list. The `"alignment_type"`
arm exists so the ablation batch can *measure* what rulings 12 and 13 changed
rather than quote it: alignment describes an asset's trajectory against its
scenario, not what its plant burns, and on the fixture slice it misfires in
both directions — 30 offshore-wind, 21 nuclear and 7 biomass assets paid the
fossil penalty and grew at the fossil rate, while 3 oil assets collected the
greenium.

The **tier-2 carbontech annuity is not governed by this switch**. It still
selects on `alignment_type` under either carrier, and is the last consumer in
this stage that does; see the clash report (Q2-4).

!!! note "Tier census — check it on your own run"

    The tiers are mutually exclusive and their counts sum to the group total,
    and the first node logs the census at `INFO` on every run, so the split is
    checkable rather than assumed. On the committed fixture slice, of 1,442
    asset-trajectory groups: **80 stranded, 33 carbontech annuity, 2 bounded
    negative, 625 perpetuity, and 702 with no terminal anchor at all** (a
    terminal FCFF of exactly zero). Separately, 804 of the 1,442 stand at zero
    capacity at the horizon and are zeroed by `tv_anchor_policy: "operating"`
    ahead of whatever tier claimed them.

    The perpetuity is therefore neither universal nor rare here — it covers
    roughly 43% of groups — and half the groups have no terminal value to
    argue about. Expect a different split on the full universe.

One structural detail worth knowing: before any row-indexed logic runs, the
first node collapses CapEx flow-split rows to **one row per asset-year**.
Upstream, the capacity-flow decomposition can emit separate component rows for
the same (asset, year); their FCFFs sum correctly for present value, but the
terminal-value anchor is the group's last *row*, so duplicate years in the
anchor zone would corrupt it.

## Consumes

| Dataset | Produced by |
| --- | --- |
| `asset_earnings` | Stage 4 (`data/07_model_output/asset_earnings.csv`) |
| `asset_horizon_attributes` | Stage 4 (`data/07_model_output/asset_horizon_attributes.csv`) |

`asset_horizon_attributes` is one row per asset series carrying its
`lifetime_years`, `asset_age`, `scrap_usd_per_mw` and `asset_trajectory`
capacity **in the last forecast year** — the four scalars the bounded negative
terminal value prices its remaining life and its exit off, and the capacity the
operating anchor reads. They travel in their own table rather than repeated
down every row of `asset_earnings` because they are per-series constants, not
flows, and widening a per-asset-year-flow table with them invites a
`"first"`-aggregation hack in the flow-row collapse below.

The input is optional: a direct caller that passes only an earnings frame, or a
catalog with no such dataset, still values — every group falls back to the
tier-2 annuity horizon and takes no exit floor. A table carrying *more* than one
row per asset series raises rather than being silently deduplicated.

## Produces

Every output is persisted; these four tables are the model's headline result.

| Dataset | Persisted to | What it is |
| --- | --- | --- |
| `yearly_npv_trajectories` | `data/07_model_output/yearly_npv_trajectories.csv` | Year-by-year discounted detail per asset and trajectory type: `discount_rate`, `discount_factor`, `years_from_base`, `pv_fcff`, `terminal_value`, `yearly_npv` and the financial components |
| `asset_npv` | `data/07_model_output/asset_npv.csv` | One row per asset and owning company: `baseline_npv`, `latesudden_npv`, the two discount rates, the undiscounted component sums and the `npv_change` between them |
| `company_technology_npv` | `data/07_model_output/company_technology_npv.csv` | The same comparison per company, technology and geography, with an asset count |
| `company_npv` | `data/07_model_output/company_npv.csv` | The same comparison per company |

How to read `npv_change`, including its sign convention, is covered in the
[user guide](../user_guide.md#reading-the-sign-of-npv_change).

!!! note "Loud rather than silent"
    Three inputs abort the run rather than producing quiet nonsense: a row whose
    `scenario_type` is unresolved, a row whose `year` is `NaN` (the integer
    casts would wrap it and produce astronomical terminal values), and a missing
    required column. Group keys containing `NaN` are deliberately **kept**
    (`dropna=False` throughout), because dropping them would make assets vanish
    between two nodes with no warning.

## Nodes

| Node | Function | What it does |
| --- | --- | --- |
| `calculate_yearly_npv_trajectories` | `compute_yearly_npv_trajectories` | Discounts each year's FCFF and adds the terminal-value row |
| `aggregate_npv_by_asset` | `calculate_npv_per_asset` | Collapses the yearly detail to one row per asset, pivoting by trajectory type |
| `aggregate_npv_by_company_and_technology` | `aggregate_to_company_technology_npv` | Sums asset NPVs to company-technology-geography level |
| `aggregate_npv_by_company` | `aggregate_to_company_npv` | Sums company-technology NPVs to company level |

This set of four node names is pinned by
`tests/test_run.py::test_methodology_steps_are_visible_as_individual_nodes`.

The two roll-ups are plain sums of `baseline_npv` and `latesudden_npv` with the
discount rates averaged and the asset counts carried; `npv_change` is recomputed
at each level from that level's own totals rather than averaged up from below.

## Parameters read

Every key sits in the `dcf` block of
`conf/base/parameters_calculate_asset_and_company_npv.yml`, and is addressed in
`pipeline.py` by its dotted path:

| Key | Default | What it controls |
| --- | --- | --- |
| `dcf.discount_rate` | `0.07` | Real discount rate for every row, both pathways |
| `dcf.terminal_value.method` | `"perpetuity"` | `"none"` or `"perpetuity"` |
| `dcf.terminal_value.g_real_default` | `0.02` | Real terminal growth rate, used where a technology-specific rate is not set |
| `dcf.terminal_value.g_real_brown` | `0.0` | Terminal growth for whatever `spread_carrier` calls brown - declining assets, no perpetual growth |
| `dcf.terminal_value.g_real_green` | `0.02` | Terminal growth for everything else |
| `dcf.terminal_value.normalization_window` | `3` | How many final years are averaged into the terminal FCFF |
| `dcf.brown_discount_spread` | `0.01` | Carbon risk premium added to whatever `spread_carrier` calls brown |
| `dcf.green_discount_spread` | `0.0` | The greenium. Ignored with a warning under `spread_carrier: "technology"`; live under `"alignment_type"` |
| `dcf.brown_technologies` | Coal / Gas / Oil, both CCS variants | Which technologies pay the premium under the technology carrier; everything else takes the base rate |
| `dcf.spread_carrier` | `"technology"` | `"technology"` or `"alignment_type"` - what decides "brown" for **both** the spread and the growth rate |
| `dcf.stranding_aware_tv` | `True` | Use the multi-tier terminal value instead of a single perpetuity |
| `dcf.stranding_consecutive_years` | `3` | Consecutive loss-making years at the horizon end that mark an asset stranded |
| `dcf.brown_remaining_life_years` | `10` | Annuity horizon for declining but profitable carbontech, and the fallback remaining life for the bounded negative branch |
| `dcf.negative_tv_method` | `"bounded_annuity"` | `"perpetuity"` (unbounded below) or `"bounded_annuity"` (the least-bad exit) |
| `dcf.tv_anchor_policy` | `"operating"` | `"raw"` or `"operating"` - whether zero-capacity groups are zeroed and decommissioning excluded from the anchor |

Every one of `negative_tv_method`, `tv_anchor_policy` and `spread_carrier` is
validated against its legal values: an unrecognised or misspelled setting raises
naming the key and the options, rather than falling through to the other branch
and silently changing the model.

That is the whole set - `PIPELINE_PARAMETERS` in `pipeline.py` lists them
explicitly, so nothing else in the `dcf` block is visible to this stage. The two
scenario discount rates ship equal, so out of the box the rate differential in
`npv_change` comes from the technology spreads rather than from the scenario.

The [parameters reference](../parameters.md) lists the `dcf` block as a single
entry - nested sub-keys are annotated in the YAML file itself, which is the
source of truth for their defaults.

## Methodology reference

*ALTR Model User Guide* ([`altr_documentation.pdf`](../altr_documentation.pdf)),
**Pipeline reference → Valuation model**, which the PDF already calls
`calculate_asset_and_company_npv` and which describes the discounting, the
terminal value and the two roll-ups.

The PDF predates the stranding-aware terminal value, the bounded negative
terminal value, the operating anchor and the technology-differentiated discount
spreads, so it describes a single perpetuity on a single rate. Where the two
disagree, this page is current. The underlying arguments are Gourdel (2024) for
the abandonment logic behind the stranded tier, Bolton & Kacperczyk (2021, 2023)
for the carbon risk premium — and for the absence of a greenium on the other
side — and the Damodaran / McKinsey normalized-terminal-cash-flow convention for
the averaging window.

!!! warning "Proposal branch"

    The bounded negative terminal value, its past-lifetime exit reading, the
    operating anchor and the `spread_carrier` switch are PROPOSALS pending owner
    sign-off, and the fixture value pins are deliberately not re-derived while
    they are. The full-universe magnitudes quoted in the parameter file's
    comments are provisional until the measurement batch runs.
