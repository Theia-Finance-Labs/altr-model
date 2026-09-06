# ALTR model methodology - the full method map

**Brief v1 · 2026-09-04 · source of truth: `altr-model-migration` @ `79731a3` (2026-09-04), `conf/base` defaults · companion paper: Tang, Yilmaz, Gallice, Hejazi, Cervenka, Apeaning, Oweyssi, Kamboj, Buller, *Asset-level analysis of corporate value adjustment in the climate transition***

Purpose: the text behind the Day 1 morning session of the KAPSARC workshop ("Model methodology"). It describes the model as the code runs it today. Where the paper and the code differ, the code wins and the difference is named. Every default cited is from the six `conf/base/parameters_*.yml` files; every measured number names the run it comes from.

How to read it: plain language first, then one formula box per mechanism, then the switch that controls it. Paper equation numbers are given in brackets so you can map back to what you already know.

---

## 1. Origins, and the question the model answers

ALTR stands for asset-level transition risk. It grew out of the TRISK stress test that 1in1000 runs with banks and supervisors, and out of the joint KAPSARC paper, where we asked whether a stress test that sees individual power plants gives a different answer than one that only sees companies. It does - the paper's abstract puts the cost of transition roughly 7% lower when assets, their age and their ownership are modelled explicitly; the body gives 8.6% less loss on a common asset-level baseline (4.1% when both sides are recomputed at their own granularity), about 1.1 trillion USD, ranging from 2.6% in the Middle East and Africa to near 17% in the reforming economies.

The model answers one question:

> How much does the value of a company's power-generation assets move when a late and sudden climate-policy shock forces the company off its current-policy pathway and onto a climate-aligned one?

Three framing choices decide how to read any output, so they come first.

**The unit is the plant.** A power plant with a capacity, a technology, a country and an age. Companies are sums of plants weighted by ownership share. Scenario trajectories are first built per company, technology and geography, then allocated down to the plants; every money number is computed at plant level.

**Every plant is valued twice.** Once along a *baseline* pathway (the current-policy scenario) and once along a *late and sudden* shock pathway. The difference is the transition-risk signal. This means the baseline already carries current-policy transition costs - ALTR measures the *extra* loss from policy stricter than current policy, which puts it closer to economy-wide current-policy stress tests than to a "no carbon cost" counterfactual. A positive result is possible and is not a bug: where the current-policy pathway already damages a plant, the shock can mostly accelerate a decline that was coming anyway.

**The output is the value of the power-asset slice.** `company_npv` is the discounted free cash flow of a company's owned generation assets, weighted by its stake in each. It is not enterprise value and not market capitalization - no debt, no other business lines, no corporate overhead. An `npv_change` of −0.12 means the shock destroys 12% of the value of this power-asset slice.

**What the model does not do.** No physical climate risk, no litigation or reputational channel, no balance-sheet, leverage or liquidity effects, no credit-risk layer, and no demand response or market-share reallocation between companies - each company's fleet meets its own pathway independently. Coverage is power generation only, and a company is covered exactly as far as the asset data covers it.

---

## 2. The pipeline at a glance

Six Kedro stages. Five compute numbers, one draws figures. Each hands one table to the next; the arrows below are dataset names in the code, not a sketch.

```
inputs (3 CSVs)
   │
   ▼
1  prepare_scenario_asset_and_company_inputs   scenario pair, ownership, geography, market-share rates
   │  asset_forecast_panel ──────────────────────────────────┐
   │  company_projection_inputs                               │
   ▼                                                          │
2  calculate_company_trajectories               baseline, target, late & sudden per company-technology
   │  company_pathways_pre_allocation                         │
   ▼                                                          ▼
3  allocate_company_trajectories_to_assets      the company cut, plant by plant; retirement; build-out
   │  asset_trajectories
   ▼
4  calculate_asset_earnings                     production → revenue, costs, decommissioning → FCFF
   │  asset_earnings, asset_horizon_attributes
   ▼
5  calculate_asset_and_company_npv              discounting, terminal value, roll-ups
   │  asset_npv, company_technology_npv, company_npv
   ▼
6  plot_transition_risk_results                 figure packs (no new numbers)
```

The workshop plan names five modelling pipelines: data load, shock mechanism, staggered shock, earnings model, valuation model. They map one to one onto stages 1 to 5. Stage 6 is reporting.

Two conventions run through every stage:

- **Trajectory types.** Company tables carry `baseline`, `target`, `late_sudden_requested` (what the shock asks of the company) and `late_sudden_realized` (what its plants could deliver). Asset tables carry `baseline` and `latesudden`. Every money number is computed on both asset pathways.
- **The financial surface.** Twelve scenario columns ride on every row from stage 2 onward: scenario name, power price ex-carbon, fuel price, capacity factor, capex per MW, fixed O&M per MW-year, carbon price, efficiency, technology lifetime, scrap value per MW, the capture-price factor, and the level of the long-run-marginal-cost floor that stage 1 has already applied to the price (both adjustments ship switched off, §3). Which scenario's values a row carries is decided once, in stage 2, and never re-decided.

---

## 3. Stage 1 - inputs: scenarios, ownership, geography

### What goes in

Three tables, produced from the delivered files by `scripts/prepare_inputs.py`:

| Table | One row per | Carries |
| --- | --- | --- |
| `scenarios.csv` | scenario × sector × technology × geography × year | production pathway, price, capacity factor, fuel price, capex, O&M, carbon price, efficiency, lifetime, scrap |
| `assets_forecasts.csv` | asset × year (observed forecast years) | capacity, technology, country, age, emission factor, capacity factor |
| `companies_ownerships.csv` | company × asset × year × ownership tier | ownership percentage (0-100 scale), tier (`direct` / `equity`) |

The asset and ownership data descend from the database built for the paper (Global Energy Monitor at unit level, emission factors from GEM, company reporting or Climate TRACE country averages - paper §2.4). The data session in the afternoon covers their construction; this section covers only what the model does with them.

### The scenario pair

A run compares exactly two IAM scenarios: a **baseline** (current policy) and a **target** (the climate-policy pathway the shock forces the company onto). The model enforces that both start in the same year and intersects their geographies and technologies with a logged warning. It does not check that both come from the same IAM provider - that is your job, and mixing providers silently shrinks the universe.

The paper ran AIM/CGE 2.2, C5 baseline `EN-NPi2020-1200f` against C3 shock `EN-NPi2020-900f`. `conf/base` still ships those names, but the 2026-09-01 AR6 extract no longer carries them; every validated run since uses the WITCH pair, which the full-universe environment sets:

| Role | Scenario |
| --- | --- |
| Baseline | `AR6_WITCH 5.0_EN_NoPolicy` |
| Target | `AR6_WITCH 5.0_EN_NPi2020_500` |

Before any pair is committed, two viability checks against `scenarios.csv` are worth running: if fixed O&M exceeds `capacity_factor × 8760 × price`, EBITDA is negative before fuel is counted; if `fuel_price ÷ efficiency` exceeds price, every MWh loses money. The model runs such combinations without complaint.

### Technology market-share rate

The scenario pathway is turned into a growth factor relative to its first year. This is the paper's proportional downscaling (eq. 1-2): every company keeps its market share, so assets of the same technology in the same geography see the same relative change.

```
tmsr[s, tech, geo, t] = (pathway[t] − pathway[first year]) / pathway[first year]
scenario_activity[company, t] = initial_company_activity × (1 + tmsr[t])
```

A technology is labelled **increasing** in a geography if the *target* pathway ends above where it starts, else **decreasing**. This label drives the four-way classification in stage 2 and the two allocation branches in stage 3.

### Ownership: which stakes count

A plant can appear under a **direct** stake (the operating owner) and an **equity** stake (look-through via intermediaries), and can be claimed by several companies. Two rules are available and they are not comparable in absolute terms:

| `ownership_aggregation` | What it does | Universe |
| --- | --- | --- |
| `tier_filter` (default) with `ownership_type: direct` | keep one tier, then sum stakes within it; each MW counted once under its operating owner | the validated baseline and the paper's results |
| `sum` | total every stake a company holds (50.00% direct + 0.45% equity = 50.45%); equity-only holders enter | TRISK's reading; 6.43× the owner-asset rows and 2.68× the ownership-weighted capacity on the full ownership input (measurement A1) |

Capacity then enters the model as the owner's share, and every cost line is linear in it:

```
asset_activity = capacity × ownership_percentage / 100      (the column is on the 0-100 scale; a 0-1 file raises)
```

So a 40%-owned plant contributes 40% of its cash flows to that company, never the whole asset - and `(asset_id, company_id)` is the unique key in every asset-level output.

### Two price adjustments, both switched off by default

The IAM price is an annual regional average, paid to every technology alike. Two optional corrections to it were added on 2026-09-04 and both ship at `method: none`, so the validated behaviour is unchanged; they exist so the owner can rule on them with measurements in hand.

**Capture-price factor** (`capture_price.method: hirth2013`). Onshore wind, offshore wind and solar PV earn less than the average price as their market share grows (Hirth 2013 measures the value factor falling from about 1.1 at zero share to 0.5-0.8 at 30%). The factor is linear in the share of region-year generation held by wind (onshore and offshore together) or by solar PV, floored at 0.4. Every other technology, CSP included, takes the dispatchable residual that keeps the generation-weighted average equal to the system price, capped at 2.0; where a region-year is entirely wind and PV the residual is set to 1. Shares come from each scenario's own leaf-technology pathways, so the factor follows the transition and differs between the two pathways.

```
f_wind  = max(1.1 − 1.5 × share_wind, 0.4)          f_pv = max(1.1 − 3.5 × share_pv, 0.4)
f_other = min((1 − s_wind × f_wind − s_pv × f_pv) / (1 − s_wind − s_pv), 2.0)      = 1 if 1 − s_wind − s_pv ≈ 0
```

**Long-run-marginal-cost floor** (`price_floor.method: lrmc`). Under WITCH, MESSAGE and REMIND the IAM price sits below the full cost of the plants the pathway keeps building (the anchor case in batch L: WITCH China 2030 coal, an IAM price of 25.27 USD/MWh against a levelised cost of 40.18). The floor is derived from the *baseline* scenario only: per region-year, the price-setter is the coal, gas, oil or biomass leaf technology with the largest generation whose six cost inputs (fuel price, efficiency, O&M, capex, capacity factor, lifetime) are all finite and positive; a broken row is skipped and the next largest usable one sets the price, ties resolve by technology name, and a region-year with no usable candidate keeps its delivered price exactly as delivered, zero or negative included (where a floor exists, a missing price takes the floor). That one floor is then applied to every technology in both scenarios. The consequence to keep in mind: the floor never falls in the transition, so late-transition target prices below the fossil-era cost level are lifted, and target-pathway revenues with them.

```
LRMC  = fuel_price / efficiency + fom / hours + capex × CRF(r, lifetime) / hours      hours = capacity_factor × 8760
CRF   = r / (1 − (1 + r)^−lifetime)                                                  r = price_floor.discount_rate (0.08)
price = max(IAM price, LRMC of the baseline price-setter)          per region-year, both scenarios
```

What each does to the numbers is in §10 (R15 for the factor, R16 for the floor).

### Geography, horizon, lifetime, decommissioning price

- **Geography.** Each asset's country is matched to the most specific scenario geography that contains it (fewest countries wins; an exact tie fails the run rather than guessing). Assets without a country, and a hardcoded list of 22 small jurisdictions kept from an NGFS-era workaround, are dropped silently before matching. A country that matches no geography falls back to a "global" geography if the extract defines one with an empty country list (the first such geography, if there are several); otherwise the run fails.
- **Forecast horizon.** `max_forecast_horizon: 5` keeps observed forecast years in `[start, start + 5]` - six calendar years from 2025. It is not the valuation window: after the cut every asset is flat-extended to the scenario's last year (2050), so the shock always sits inside the valued period.
- **Technology lifetime.** One per sector-technology, the rounded-up mean of the target scenario's `lifetime_years`. Used to date retirement in stage 3.
- **Decommissioning price.** The extract delivers `scrap_usd_per_mw` at half the build cost. `decom_cost_fraction_of_capex: 0.15` (owner ruling 2026-09-04) rewrites it as `−0.15 × capex_usd_per_mw` for every scenario row, so both places that read it (the retirement charge in stage 4 and the exit floor in stage 5) move together.
- **CCS.** `ccs_on: False` points coal, gas, oil and biomass at the "w/o CCS" scenario variant.
- **Granularity.** `reduce_granularity_from_asset_to_company_level: False` keeps every physical asset distinct. Switching it on collapses assets to one synthetic row per company-technology-geography before the model runs - a different model of the same company, not a cheaper view of the same one.

---

## 4. Stage 2 - company trajectories and the shock

### The two reference paths

For every company × geography × sector × technology the model builds two paths from the company's observed capacity:

- **Baseline.** Observed capacity for as long as the asset data reports it, then the last observed value carried forward by the baseline scenario's year-on-year change. Floored at zero and held there once reached.
- **Target.** The company's capacity moved by the *target* scenario's cumulative change from the start year. Same zero floor.

```
target[t]   = observed_ffill[t] + Σ_{u≤t} Δscenario_activity_target[u]      floored at 0
              (observed capacity forward-filled, plus the target's cumulative change from the start year)
baseline[t] = observed[t]                                   for t ≤ last observed year
            = observed[last] + Σ_{u>last, u≤t} Δscenario_activity_baseline[u]   floored at 0
```

This is Figure 1 of the paper: the forecast leg, then baseline and target diverging.

### Four alignment cases

Each company-technology is classified on two axes. **Direction** comes from the scenario (increasing or decreasing technology). The labels `high_carbon` and `low_carbon` in the case names mean decreasing and increasing; they are trajectory-direction labels, not a fuel test, and a scenario can put offshore wind or nuclear into a `high_carbon` case (§7 says what that does and does not affect). **Alignment** compares the company's own path with the target: for a decreasing technology the company is *aligned* if both the sum and the final-year value of its *observed* capacity (the forecast years only, not the projected baseline) sit at or below the target over those same years; for an increasing technology, at or above. The four cases each get their own shock shape:

| `alignment_type` | Who | Shock shape |
| --- | --- | --- |
| `misaligned_high_carbon` | decreasing technology, company above the target | transition to target, then **compensation** below it |
| `aligned_high_carbon` | decreasing technology, company already at or below target | transition to target, no compensation |
| `misaligned_low_carbon` | increasing technology, company building slower than target | transition up to target |
| `aligned_low_carbon` | increasing technology, company already ahead | from the year after the shock year, grow at the target's growth rate from its own shock-year level (where the previous year's target is zero, take the target level directly) |

### The late and sudden path, phase by phase

Two dates control the shock: `shock_year: 2033` (the year the policy becomes known) and `alignment_year: 2038` (the year the target must be met). The paper used 2033 and 2035; the shipped five-year window is a deliberate compromise between a realistic phase-out and an abrupt repricing. Every year of the path is labelled with a `late_sudden_phase` that survives into the earnings table and the plots:

| Phase | Years | Value |
| --- | --- | --- |
| `forecast` | up to the last observed year | observed capacity (baseline where a year is missing) |
| `bau` | after that, up to the year before the shock year (through the shock year where no transition follows) | baseline |
| `transition` | `shock_year` … `alignment_year` | straight line from baseline at `shock_year − 1` to target at `alignment_year` |
| `aligned` | after `alignment_year` | target |
| `aligned_compensation` | after `alignment_year`, misaligned high-carbon only | target minus the compensation |

The aligned low-carbon case is the exception to this table: it has no transition phase. It stays on `bau` through the shock year and is `aligned` from the year after, growing at the target's rate from its own shock-year level.

```
transition:  ls[t] = v_start + (t − (shock_year − 1)) / (alignment_year − shock_year + 1) × (v_end − v_start)
             v_start = baseline at the last grid year ≤ shock_year − 1 (first grid year if none),  v_end = target[alignment_year]
```

With `alignment_year` equal to `shock_year` the window is empty: the misaligned high-carbon case still computes the single-year step, the other two transition cases skip the transition and go straight from `bau` to `aligned`.

**Compensation** (paper §2.3, eq. 2 second form). Everything the company produced above the target before alignment is excess against the scenario's carbon budget. The model sums that excess, nets off any shortfall below target already booked after alignment, and spreads what remains evenly over the post-alignment years as a further cut, floored at zero:

```
pre_excess  = Σ_{t ≤ alignment_year} (ls[t] − target[t])
post_gap    = Σ_{t > alignment_year} (ls[t] − target[t])
volume      = max(pre_excess − post_gap, 0)
ls[t]       = max(ls[t] − volume / n_post_years, 0)      for t > alignment_year
```

This is the "retirement +" tail in the paper's Figure 2: the transition reaches the target at the alignment year, and the compensation tail after it sits below the target, not on it.

### Which prices the shock path sees - the price ramp

The target path always carries the target scenario's financial surface. The late and sudden path has two options, controlled by `price_ramp`:

- `False` - hard switch: baseline surface until `shock_year`, target surface from then on. This is what the paper describes and what TRISK does.
- `True` (shipped) - linear blend from the baseline surface at `shock_year` to the target surface at `alignment_year`.

```
surface_ls[t] = surface_baseline[t] × (1 − b[t]) + surface_target[t] × b[t]
b[t] = clip((t − shock_year) / (alignment_year − shock_year), 0, 1)
```

The ramp exists because target electricity prices sit 30-50% above baseline at the shock year. Under the hard switch a coal plant gets that price jump on day one of the shock and can *gain* value from a climate policy. Measured on the full universe (ablation A4), the hard switch makes the headline risk signal 36% smaller and moves coal by +3.0 trillion USD against gas at −2.0 trillion - the windfall made visible. The ramp removes it.

One side effect to hold onto: a blended row is a mixture of the two scenarios, so it keeps the *baseline* scenario label. Stage 5 picks its discount rate off that label, which means `dcf.discount_rate_shock` is inert under the shipped configuration (see §7).

---

## 5. Stage 3 - from the company to its plants

The company-level shock is a number per year. This stage decides which plant absorbs how much of it. It also dates retirement, builds new capacity where the scenario asks for growth, and records what the fleet could not deliver.

### Retirement: age wraps around a refurbishment cycle

Observed age is not used as-is. At the first valid observation, age is taken modulo the technology's lifetime and the plant ages linearly from there - the model assumes assets are refurbished on a rolling cycle rather than dying the first time they pass their nominal lifetime. A 45-year-old plant with a 40-year lifetime is 5 years into its second cycle. Retirement is the first year age exceeds lifetime; capacity is zero from that year on.

```
start_age        = first_observed_age mod lifetime_years
age[t]           = start_age + (t − first_observed_year)
retirement_year  = first t with age[t] > lifetime_years
```

Retirement is applied to both pathways (`apply_retirement_baseline: True`, `apply_retirement_shock: True`), so a natural retirement cancels out of the shock-minus-baseline difference by construction. When it takes effect is a switch: `retirement_timing: "natural"` (shipped) lets each retirement land on its own year; `"deferred_to_window"` holds every retirement dated on or before `alignment_year` back to `alignment_year + 1`, which bunches decades of retirements into 2039 and produced a +341% one-year capex spike on the golden run `015a861` (finding D1). Measured on the full universe (R3), deferral makes the signal 15.6% larger.

Turning retirement off entirely (ablation A6) makes the measured risk signal 46% *larger*: retirement currently dampens it, and the effect lands on gas, wind and hydro rather than coal.

### The asset baseline

Each asset's baseline path is its observed capacity scaled by the ratio of the company baseline in that year to the company baseline in the nearest observed year, forward- and back-filled, and zeroed from retirement. Where a company path is flat after the forecast years, so is every plant.

### Decreasing technologies: how the cut is shared

Two allocation modes, one switch.

**Proportional scaling (`apply_decreasing_staggered_shock: False`, shipped).** Each plant's share of the company's capacity in the last year at or before the shock is frozen; from the shock year on, each plant carries that share of the company's late and sudden path. Retirement is then applied on top: a retired plant's capacity is lost, not redistributed.

```
w_a      = capacity_a[shock_ref] / Σ_a capacity_a[shock_ref]        shock_ref = last year ≤ shock_year
after_a[t] = w_a × C_ls[t]                                          for t ≥ shock_year
after_a[t] = 0                                                      for t ≥ retirement_year_a
```

**Age-staggered allocation (`apply_decreasing_staggered_shock: True`, the paper's eq. 12-14).** The year-on-year cut in the company path is distributed with weights from a logistic curve over the fleet's age quantiles, so older plants absorb more. No plant is cut below zero; what a saturated plant cannot absorb is redistributed to the others in a few clamp-and-redistribute rounds. Parameters `staggered_shock.g_k: 6.0` (curve steepness) and `n_quantiles: 3` (age buckets) are read only when the switch is on.

```
raw_a   = 1 − Σ_q 1 / (1 + exp(−k (age_a − cut_q)))       cut_q = age quantiles of the fleet
g_a     = normalized(−raw_a)                               older ⇒ larger weight, Σ g_a = 1
cut_a   = min(g_a × ΔC[t], capacity_a[t−1])                redistribute any remainder
```

The paper presents staggering as the model; the code ships proportional scaling as the default and staggering as the option. Two details differ from the paper's eq. 13: the code places its cuts at the fleet's own age quantiles rather than at fractions of the technical lifetime, and it drops the paper's 1/2^j weighting of the logistic terms. The age-as-priority reading is a proxy for emissions intensity and retirement proximity (paper Appendix 8.2), not an economic optimization, and should be described as such.

A plant whose capacity the shock permanently zeroes is tagged `retirement` in its phase column, so a policy-driven exit is visible next to a natural one.

### Increasing technologies: real plants stay, a synthetic plant grows

Real assets are left on their baseline path. Any gap between the company's requested late and sudden path and the sum of its real assets is filled by one **synthetic** top-up asset per company-technology-geography, from the shock year onward (paper Appendix 8.3, eq. A1):

```
synthetic[t] = max(0, C_ls_requested[t] − Σ_real after_a[t])     for t ≥ shock_year, else 0
synthetic baseline capacity = 0
```

The reconciliation is one-sided: it closes a shortfall and never corrects a surplus. A synthetic asset can only appear where the company already has a real plant in that technology and geography, and it inherits the capacity-weighted emission factor of the real fleet it extends (company group first, then technology × geography, then technology; where no real asset in the technology carries a factor at all it falls back to zero with a logged warning; renewables are zero-filled before that rule runs). Synthetic rows are flagged `is_synthetic = True` in every output.

### Requested versus realized

After allocation, the allocated asset capacities are summed back to company level as `late_sudden_realized`. The gap between it and `late_sudden_requested` is the shock the fleet could not absorb - through retirement, floors or the one-sided top-up. When a company-level number surprises you, this gap is the first thing to check.

---

## 6. Stage 4 - from capacity to cash

Each asset-year, on each pathway, becomes money. The arithmetic is short and the modelling choices sit in three switches.

```
Q_t          = K_t × capacity_factor × 8760                                     MWh
revenue_t    = Q_t × power_price_excarbon_usd_per_mwh × capture_price_factor_t   (factor = 1 under the shipped method: none)
var_cost_t   = Q_t × fuel_price_usd_per_mwh_fuel / efficiency_decimal
fixed_cost_t = fom_usd_per_mw_yr × K_fixed_t
carbon_t     = Q_t × carbon_price_usd_per_tco2 × emission_factor × (1 − market_passthrough)
EBITDA_t     = revenue_t − var_cost_t − fixed_cost_t − carbon_t                 [paper eq. 3-7]

decom_t      = |scrap_usd_per_mw| × capacity_reduction_t        any year-on-year fall in a real asset's capacity,
                                                                natural retirement and shock cuts alike, if include_decom_costs
growth_t     = capex_usd_per_mw × new_build_t                    synthetic assets only, if include_growth_capex
capex_t      = growth_t + decom_t                                                [paper eq. 8]
FCFF_t       = EBITDA_t − capex_t                                                [paper eq. 9]
```

No corporate tax, no depreciation - everything is tax-neutral and real, which is why EBITDA rather than EBIT is the operating measure and why figures across years compare without deflating.

### The three choices that bite

**Continued O&M - the stranding mechanism.** `K_fixed` is the year's actual capacity, except for decreasing-technology assets on the shock pathway (`apply_continued_om_shock: True`), where it is the pathway's *first-year* capacity for as long as the plant still stands (a table arriving without an `alignment_type` column would apply it to every technology, with a warning). A coal plant whose output the shock cuts to a fraction keeps paying the fixed bill it can no longer earn against. The baseline side is off (`apply_continued_om_baseline: False`): on the current-policy path the plant winds down on schedule and sheds costs on schedule. Once capacity reaches zero the charge stops with it (owner ruling 15 - before that fix one closed nuclear plant paid 1.26 billion USD a year for twelve years after closing).

The asymmetry is the stranded-cost story itself, and it carries a large share of the result: on the committed fixture slice (`tests/fixtures`, quoted in the handover user guide) turning the shock switch off moves the median `npv_change` from −0.42 to −0.16; on the full universe (R9) it moves the headline by 4.8%.

**Carbon cost - who pays.** `market_passthrough: 0` means the plant absorbs its whole carbon bill, the conservative stress-test reading. `carbon_cost_method: "full_ef"` charges every technology its full emission factor. The alternative, `"differential_ef"`, would charge only the excess over the price-setting generator and only matters for IAMs whose electricity prices already embed the marginal generator's carbon cost; on today's inputs the marginal emission factor is zero and the two coincide.

**Which capital costs are charged.** `include_growth_capex: False` - IAM O&M series already bundle annualized capital cost, so charging new-build capex on top would double count. The former replacement capex (a 2%-a-year charge on standing capacity) was removed on 2026-09-04 for the same reason. `include_decom_costs: True` - shedding capacity costs money: every year-on-year reduction in a real asset's capacity, whether natural retirement or a shock-driven cut during the transition window, is charged at 15% of build cost after the calibration above (the scrap value arrives negative in the data and is charged as a positive outflow). This is why the charge lands mostly on the shock pathway. Under the paper's eq. 8 the retirement term was a 10% *recovery*, so retiring paid the owner; the sign is now the other way.

Two data repairs happen in this stage and change numbers: emission factors are forward-filled within each asset series, and the seven zero-carbon technologies get a zero where the factor is missing.

---

## 7. Stage 5 - valuation

### Discounting

Cash flows are discounted from each series' first year at a real rate that is a scenario base rate plus a technology spread:

```
r = base_rate + brown_discount_spread × [technology ∈ brown_technologies]
base_rate = 0.07 on both surfaces       brown_discount_spread = 0.01
brown_technologies = coal, gas, oil (with and without CCS)

DF_t = (1 + r)^−(t − base_year)
NPV  = Σ_t FCFF_t × DF_t + TV                                                     [paper eq. 10]
```

The spread is a carbon-risk penalty on high emitters (Bolton and Kacperczyk 2021, 2023: roughly 1.5-2.5% higher equity returns for high-emission firms, which the parameter file translates to a 60-150 bps cost-of-capital spread) and there is no greenium leg on the other side, because the same literature finds no discount for clean firms (owner ruling 12). It is charged by *technology*, not by alignment type: alignment describes a plant's trajectory against its scenario, and under the previous carrier offshore wind and nuclear classed `misaligned_high_carbon` were paying the fossil penalty. Removing the spread (R6) makes the signal 22% larger; the pre-ruling carrier with a −50 bps greenium (R5) makes it 13% smaller.

`dcf.discount_rate_shock` also ships at 0.07. Under the price ramp every late and sudden row carries the baseline label, so raising this key changes nothing - it becomes live only with `price_ramp: False` or `alignment_year == shock_year`.

### Terminal value: what a plant is worth beyond 2050

The paper used one Gordon-growth perpetuity per company. The code values each asset series through an anchor and a set of tiers.

**The anchor.** Terminal cash flow is the mean of the last `normalization_window: 3` years (fewer if the series is shorter) - so one transition-period capex spike cannot decide a plant's terminal value. Under `tv_anchor_policy: "operating"` two corrections apply: decommissioning charges are added back (a one-off exit bill must not be capitalized forever), and a series standing at zero capacity at the horizon has no terminal value at all, whatever its last cash flows say.

**The tiers**, checked in order, first match wins (`stranding_aware_tv: True`):

| Tier | Condition | Terminal value |
| --- | --- | --- |
| Stranded | FCFF ≤ 0 in each of the last 3 years, as booked (decommissioning included), with at least 3 measured years and no gap in the window | 0 - a rational owner abandons rather than funds perpetual losses (Gourdel 2024) |
| Declining carbontech | still profitable, `alignment_type` high-carbon | a 10-year annuity (`brown_remaining_life_years`) - a fossil plant in transition has a finite economic life |
| Bounded negative | anchor negative, not stranded | the least bad of two exits (below) |
| Everything else | r > g | Gordon growth perpetuity, `g = 0` for brown technologies, `0.02` for everything else (a group with r ≤ g takes no terminal value and is logged as a perpetuity-clause reject) |

```
perpetuity:   TV = anchor × (1 + g) / (r − g) × (1 + r)^−(T + 1 − base_year)
annuity:      TV = anchor × (1 + g) × Σ_{k=1..10} (1 + r)^−k × (1 + r)^−(T − base_year)
bounded neg:  TV = max( anchor × annuity_factor(r, lifetime − age),  −|scrap| × capacity_T ) discounted from T
              remaining life missing ⇒ 10 years (brown_remaining_life_years); no scrap price ⇒ no exit floor
              past its lifetime and still standing ⇒ the exit arm binds; both arms unavailable ⇒ TV = 0
```

The bounded-negative tier (`negative_tv_method: "bounded_annuity"`) replaces an unbounded negative perpetuity - a plant worth less than nothing forever - with the two choices an owner has: run the remaining life out at a loss, or pay to decommission now. Both are negative; the larger is the smaller loss.

The tier census is logged on every run, as assignments made *before* the zero-capacity override; the override then zeroes whatever a retired group was assigned. On the committed fixture slice (decision note D3 addendum), of 1,442 asset-trajectory groups: 80 stranded, 33 carbontech annuity, 2 bounded negative, 625 perpetuity, 702 with no terminal anchor. On the candidate full-universe run (R1 census, measurement batch), of 52,066 groups: 8,242 stranded, 1,100 annuity, 115 bounded negative, 16,128 perpetuity, 26,481 no anchor; the override then zeroes 30,709 groups standing at zero capacity at the horizon, leaving 14,745 with a terminal-value row.

### Roll-ups and the headline ratio

Asset NPVs sum to company-technology-geography and then to company. Discount rates are averaged for reporting; asset counts are carried. The ratio is recomputed at each level from that level's own totals:

```
npv_change = (latesudden_npv − baseline_npv) / |baseline_npv|
```

The paper's value adjustment (eq. 15) is the raw difference `latesudden_npv − baseline_npv`, with no denominator. The code reports that difference normalized by the baseline level; the headline signal in §10 is the paper's unnormalized form, summed over companies.

Negative means the shock destroys value. The absolute value in the denominator keeps the sign meaningful when a company's baseline NPV is itself negative; a baseline near zero gives a large, meaningless ratio, and a baseline of exactly zero gives `NaN`. Always read the two levels next to the ratio.

---

## 8. What changed since the paper - and since December 2025

KAPSARC knows the paper; the December 2025 model is the one the reconciliation notes measure against. The pricing and revenue side is where most of the movement is. December cells marked *(assumed)* are recorded in the reconciliation note as assumptions still to be confirmed from the December tag; cells marked *(July brief)* come from the 2026-07-08 model-updates brief, which describes the pre-change starting point.

| Mechanism | Paper | December 2025 | Now (HEAD) | Measured effect |
| --- | --- | --- | --- | --- |
| Scenario pair | AIM/CGE 2.2, C5 `NPi2020-1200f` vs C3 `NPi2020-900f` | not in the notes | WITCH `EN_NoPolicy` vs `EN_NPi2020_500` in the validated environment; base conf still names the AIM pair | scenario names change between extract vintages - list what your extract carries first |
| Shock timing | 2033 → 2035 | not in the notes | 2033 → 2038 | wider window, gentler phase-out |
| Price surface on the shock path | hard switch at the shock year | hard switch | linear ramp 2033-2038 (`price_ramp: True`) | the hard switch makes the signal 36% smaller than the ramp (A4, measured against the ramp); removes a +3.0 tn coal windfall |
| Revenue | Q × scenario price | not in the notes | Q × power price ex-carbon; carbon charged separately | - |
| Carbon cost | `EF × T × (1 − φ)` inside profit | not in the notes | `Q × cp × EF × (1 − passthrough)`, passthrough 0, full EF | - |
| Market-clearing price adjustment (MCPR) | did not exist | built during 2026 (two modes) | retired 2026-09-01 | net zero vs paper; `carbon_cost_method` kept for the differential path |
| Capture-price factor | did not exist | did not exist | switchable (`capture_price.method`), ships `none` | on: signal −32%, baseline-negative companies 58% → 29%, PV owners take the loss (R15) |
| Long-run-marginal-cost price floor | did not exist | did not exist | switchable (`price_floor.method`), ships `none` | on: signal +25.8% (smaller), baseline-negative companies 58% → 23%, coal companies negative 74% → 0%, loss does not move onto renewables (R16) |
| Fixed O&M | `FOM/2 × ΔPC` | not covered by the reconciliation notes | on first-year capacity for decreasing-tech plants on the shock path, stops at zero capacity | ~60% of the fixture median signal; 4.8% of the full-universe headline (R9) |
| Growth capex | `A × C` | no capex at all *(July brief)* | off (IAM O&M bundles capital) | - |
| Replacement capex | `R × C` roll-over | off *(assumed)* | on during 2026, **removed 2026-09-04** | on the candidate, switching it off grew the signal 6% (R12); deletion proven equivalent (R14 ≡ R13) |
| Decommissioning | `−γX × C`, γ = 10% recovery (retiring pays) | off *(assumed)* | positive outflow at 15% of build cost (`decom_cost_fraction_of_capex: 0.15`) | switch worth 13% of the golden headline (A3); 15% vs 50% calibration +8.4% (R11) |
| Terminal value | single perpetuity, one r, one g | single perpetuity, 2% growth for all *(assumed; July brief)* | anchor + four tiers, brown g = 0 | tiers move levels by ~1 tn each side and the signal by 0.5% (A5, R8) |
| Discount rate | one rate | 7% baseline / 8% shock *(July brief)* | 7% both + 100 bps brown technology spread, no greenium | spread off: signal +22% (R6) |
| Allocation to assets | age-staggered (eq. 12-14) | not covered by the reconciliation notes | proportional default, staggering optional | - |
| Retirement timing | not modelled as a floor | floored to `alignment_year + 1` | natural (`retirement_timing: "natural"`) | deferral grows the signal 15.6% and makes the 2039 cliff (R3, D1) |
| Ownership | direct ownership only | tier filter | parameter: `tier_filter` default, `sum` available | `sum` inflates ownership-weighted exposure 2.68× |
| Synthetic-asset emission factor | not specified | zero (no carbon cost) | inherited from the real fleet | −1.4 bn on a −3,980 bn signal (R0) |

**What is still open.** The price ramp, the decommissioning charge and its 15% calibration, the terminal-value tiers together with the negative-anchor treatment, retirement timing, and whether to switch on the capture-price factor or the price floor are documented as owner decisions still under review. The document describes the shipped behaviour; treat those rows as "current default", not "settled".

---

## 9. Reading a result

Two headline tables, one diagnostic pair.

`company_npv.csv` - one row per company: `baseline_npv`, `latesudden_npv`, the two averaged discount rates, `asset_count`, `npv_change`.

`asset_npv.csv` - one row per asset and owning company, with the same valuation columns plus undiscounted sums of `FCFF`, `EBITDA`, `revenue`, `var_cost`, `fixed_cost`, `carbon_cost_net`, `capex_total` per pathway. A large NPV gap with near-identical revenue and cost sums points at the terminal value or the rates, not at the physical trajectory.

Four checks before you trust a run:

1. **Did the fleet absorb the shock?** Compare `late_sudden_requested` and `late_sudden_realized` in `company_trajectories.csv`. A persistent gap means the allocation, not the valuation, is where the number comes from.
2. **Do the levels reconcile?** `asset_npv` summed by company equals `company_npv`. Per asset and pathway, `pv_fcff` summed over years plus `terminal_value` in `yearly_npv_trajectories.csv` reproduces the NPV columns; hand-discounting `asset_earnings` reproduces `pv_fcff` only.
3. **The usual suspects.** Companies with `asset_count = 1`, synthetic assets dominating a company, ratios whose baseline is near zero.
4. **Record the configuration.** Nothing stamps parameters onto outputs. Copy the six parameter files next to any result you share.

---

## 10. Where the model stands on the full universe

All full-universe numbers: WITCH `EN_NoPolicy` → `EN_NPi2020_500`, 4,878 companies, 26,033 owner-asset rows, 52,066 valuation groups, `tier_filter` ownership. Provisional until the golden snapshot is re-pinned on the ruled configuration.

**Reference levels (billion USD):**

| Run | Σ baseline NPV | Σ late & sudden NPV | Headline Σ(ls − base) |
| --- | --- | --- | --- |
| Golden `015a861` (replacement capex on, decom 50%) | −421 | −4,402 | −3,980 |
| R1 candidate (all current proposals, replacement on, decom 50%) | −305 | −3,715 | −3,409 |
| **R13 = ruled configuration** (replacement removed, decom 15%) | **+3,667** | **+340** | **−3,327** |

The ruled configuration leaves the risk signal within 2.4% of R1 while turning both levels positive in aggregate. The per-company picture is more mixed: 57.8% of companies still carry a negative baseline NPV (median company baseline −12 million USD), and it is concentrated in fossil-dominant companies - gas 70%, coal 74%, biomass 88%, oil 98% negative - against PV 9%, hydro 1%, nuclear 24%. The shortfall there is operating margin under WITCH's prices (China coal at 25 USD/MWh, a zero spark spread for gas), which is a revenue-side question the cost switches cannot answer.

**Revenue-to-cost coverage at baseline, by technology (ruled configuration R13):**

| Technology | Ratio |
| --- | --- |
| WindCap - Onshore | 3.36 |
| HydroCap | 1.82 |
| WindCap - Offshore | 1.60 |
| SolarCap - PV | 1.56 |
| NuclearCap | 1.16 |
| CoalCap - w/o CCS | 1.11 |
| SolarCap - CSP | 0.94 |
| GasCap - w/o CCS | 0.89 |
| BiomassCap - w/o CCS | 0.77 |
| OilCap - w/o CCS | 0.32 |

**One-switch sensitivities on the headline signal** (each vs its reference, so rows do not add):

| Switch | Reference | Δ headline | Δ % |
| --- | --- | --- | --- |
| retirement off on both pathways (A6) | golden | −1,834 bn | −46.1% (signal grows) |
| `price_ramp: False` (A4) | golden | +1,434 bn | +36.0% |
| `brown_discount_spread: 0` (R6) | R1 | −765 bn | −22.4% (grows) |
| `retirement_timing: deferred_to_window` (R3) | R1 | −532 bn | −15.6% (grows) |
| `include_decom_costs: False` (A3) | golden | +524 bn | +13.2% |
| alignment-type carrier + greenium (R5) | R1 | +459 bn | +13.5% |
| decom at 15% of build cost (R11) | R1 | +287 bn | +8.4% |
| replacement capex off (R12) | R1 | −207 bn | −6.1% (grows) |
| `apply_continued_om_shock: False` (R9) | R1 | −165 bn | −4.8% (grows) |
| replacement off + decom 15% (R13, the ruled configuration) | R1 | +82 bn | +2.4% |
| `capture_price.method: hirth2013` (R15) | R14 (= R13) | −1,070 bn | −32.2% (grows) |
| `price_floor.method: lrmc` (R16) | R14 (= R13) | +858 bn | +25.8% |
| `stranding_aware_tv: False` (A5 / R8) | golden / R1 | +22 / −16 bn | +0.6% / −0.5% |
| `tv_anchor_policy: raw` (R4) | R1 | +4 bn | +0.1% |
| `negative_tv_method: perpetuity` (R2) | R1 | −2 bn | −0.1% |
| uniform terminal growth (R7) | R1 | −1 bn | 0.0% |
| synthetic-asset EF inheritance (R0) | golden | −1 bn | 0.0% |
| `ownership_aggregation: sum` (A1 / R10) | - | not obtainable (disk) | universe 6.43× rows, 2.68× exposure |

The pattern to take home: mechanisms charged symmetrically on *both* pathways (replacement capex, decommissioning, the terminal-value tiers, retirement) move the absolute levels by hundreds of percent and mostly cancel out of the difference. The mechanisms that move the risk signal are the ones that act on *only* the shock pathway (the price ramp, the shipped continued-O&M asymmetry) or that act on both pathways but scale with how much fossil value is at stake (the brown spread, the capture-price factor).

**Provider sensitivity (batch P, ruled configuration `d75bd8b`, each provider's own valid pair from the 2026-09-01 extract).** The baseline-profitability picture is set by the data, not the model: the same code and the same asset source (each provider's scenario coverage trims the company and asset universe differently) give 57.8% baseline-negative companies under WITCH and 0.1% under AIM/CGE, because the 2030 median regional power price runs from 31 USD/MWh (MESSAGE) to 134 (AIM/CGE).

| Provider | Pair | Companies | Σ baseline (bn) | Signal (bn) | Baseline-negative | Note |
| --- | --- | --- | --- | --- | --- | --- |
| WITCH | EN_NoPolicy → EN_NPi2020_500 | 4,878 | 3,667 | −3,327 | 57.8% | reference (R14) |
| MESSAGE | EN_NoPolicy → EN_NPi2020_500 | 4,830 | −2,432 | −17,632 | 50.2% | carbon to 1,070 USD/t, Chinese coal flat to 2050 |
| AIM/CGE | EN_INDCi2100 → EN_NPi2020_500f | 4,660 | 46,192 | −2,713 | 0.1% | target carbon price is 0 in the extract |
| REMIND | EN_NoPolicy → SusDev_SSP2-PkBudg900 | 4,696 | 3,329 | −3,033 | 56.6% | 900 Gt budget |
| IMAGE | EN_NoPolicy → CO_2Deg2020 | 4,690 | 20,917 | −16,095 | 19.6% | carbon to 882 USD/t, coal to zero |
| POLES | EN_INDCi2100 → EN_NPi2020_500 | 4,705 | 18,045 | −78,196 | 13.8% | carbon column 5,503-10,698 USD/t: extract defect, not a result |
| GEM-E3 | EN_INDCi2100 → EN_NPi2020_500 | 4,340 | 7,047 | +1,187 | 49.8% | baseline carries a 13-19 USD/t carbon price; no wind or PV pathways |

Oil and biomass companies are negative under every provider; gas is out of merit under every low-price provider because the model pays every technology the regional average price. That is the gap the capture-price factor was built to test.

**Capture-price factor, measured (batch S and run R15).** On 869 sampled negative-baseline firms across six providers, 22% turn positive with the factor on; it works where the shortfall is small (97% of WITCH coal firms clear break-even) and not where it is structural (oil 6%). On the whole WITCH universe (R15 vs R14): baseline-negative companies fall from 57.8% to 29.2%, coal companies negative from 74% to 2%, but PV companies negative rise from 9% to 83% because WITCH's no-policy pathway reaches 29% solar and 38% wind share by 2050, where the factor sits at its 0.4 floor. The headline signal grows by a third (−3,327 to −4,397 bn, −32.2%). The owner rulings still open: adopt it at all, the floor and cap, and whether shares should be frozen at start-year values rather than follow the pathway to 2050.

**Long-run-marginal-cost floor, measured (batch L and run R16).** On 607 sampled negative-baseline firms across four providers, 68% turn positive with the floor on (WITCH 64%, MESSAGE 88%, REMIND 70%, IMAGE 32%) and every positive control stays positive. On the whole WITCH universe (R16 vs R14): baseline NPV rises from 3,667 to 11,501 bn, baseline-negative companies fall from 57.8% to 23.1%, coal companies negative from 74% to 0%, and renewables are untouched (PV negative 9% → 1%). The signal shrinks by a quarter (−3,327 to −2,470 bn, +25.8%) because the target pathway's prices are floored too. Remaining negatives are oil, out of merit everywhere, and half of gas, because the floor is set by coal and WITCH's zero spark spread persists. Against the capture-price factor, the floor reaches a smaller negative share without moving the loss onto renewable owners. Open for the owner: adopt `lrmc` as the default, the 8% discount rate, and whether it should be tied to the `dcf` rate.

**A data defect that shapes the coal result (batch L).** In the 2026-09-01 extract the *target* scenarios carry capacity factors near 1e-12 for phased-out thermal technologies while their generation columns stay at baseline magnitude. On the golden run, Chinese coal on the late and sudden pathway in 2045 has 645 GW standing and produces 4e-8 TWh: zero revenue, zero carbon cost, fixed O&M only. The post-2040 coal stranding signal is that contradiction, not a modelled shutdown. The floor is derived from the baseline scenario for this reason, and the marts extract is flagged for reconciliation.

---

## Appendix A - parameter defaults cited in this document

> Scope note (2026-09-06): this appendix documents the `altr-model-migration` repository (`conf/full`, `parameters_prepare_scenario_asset_and_company_inputs.yml`, etc.). The `crispy-kedro` working repo uses different file names and does not implement several keys listed here (`ownership_aggregation`, `decom_cost_fraction_of_capex`, `capture_price.*`, `price_floor.*`, `retirement_timing`, `dcf.spread_carrier`, `dcf.negative_tv_method`, `dcf.tv_anchor_policy`). For crispy-kedro, the generated reference `docs/parameters.md` (and the explorer `docs/parameters.html`) is authoritative.

| File | Key | Default |
| --- | --- | --- |
| `parameters_prepare_scenario_asset_and_company_inputs.yml` | `baseline_scenario` / `target_scenario` | `AR6_AIM/CGE 2.2_EN_NPi2020_1200f` / `AR6_AIM/CGE 2.2_EN_NPi2020_900f` (absent from the 2026-09-01 extract; `conf/full` uses the WITCH pair) |
| | `ownership_type` / `ownership_aggregation` | `direct` / `tier_filter` |
| | `reduce_granularity_from_asset_to_company_level` | `False` |
| | `max_forecast_horizon` | `5` |
| | `ccs_on` | `False` |
| | `company_ids` | 30 example ids in the internal repo; empty (= all) in a delivered copy |
| | `decom_cost_fraction_of_capex` | `0.15` |
| | `capture_price.method` | `none` (`hirth2013` available: wind 1.1 − 1.5 × share, solar 1.1 − 3.5 × share, `vre_floor` 0.4, `dispatchable_cap` 2.0) |
| | `price_floor.method` / `price_floor.discount_rate` | `none` / `0.08` |
| `parameters_calculate_company_trajectories.yml` | `shock_year` / `alignment_year` | `2033` / `2038` |
| | `price_ramp` | `True` |
| `parameters_allocate_company_trajectories_to_assets.yml` | `apply_retirement_baseline` / `apply_retirement_shock` | `True` / `True` |
| | `apply_decreasing_staggered_shock` | `False` |
| | `retirement_timing` | `natural` |
| | `staggered_shock.g_k` / `n_quantiles` | `6.0` / `3` |
| `parameters_calculate_asset_earnings.yml` | `market_passthrough` | `0` |
| | `carbon_cost_method` | `full_ef` |
| | `include_growth_capex` / `include_decom_costs` | `False` / `True` |
| | `apply_continued_om_baseline` / `apply_continued_om_shock` | `False` / `True` |
| `parameters_calculate_asset_and_company_npv.yml` | `dcf.discount_rate_baseline` / `discount_rate_shock` | `0.07` / `0.07` |
| | `dcf.brown_discount_spread` / `green_discount_spread` | `0.01` / `0.0` |
| | `dcf.spread_carrier` | `technology` |
| | `dcf.brown_technologies` | Coal, Gas, Oil × (w/o CCS, w/ CCS) |
| | `dcf.terminal_value.method` | `perpetuity` |
| | `dcf.terminal_value.g_real_default` / `g_real_brown` / `g_real_green` | `0.02` / `0.0` / `0.02` |
| | `dcf.terminal_value.normalization_window` | `3` |
| | `dcf.stranding_aware_tv` / `stranding_consecutive_years` / `brown_remaining_life_years` | `True` / `3` / `10` |
| | `dcf.negative_tv_method` | `bounded_annuity` |
| | `dcf.tv_anchor_policy` | `operating` |

## Appendix B - sources

- Code: `altr-model-migration` @ `79731a3`, `src/altr_model/pipelines/*/nodes.py` and private helpers; `conf/base/parameters_*.yml`. Where each formula box lives: market-share rate and price adjustments in `prepare_scenario_asset_and_company_inputs/_input_nodes.py` and `calculate_company_trajectories/_baseline_nodes.py`; shock shapes in `calculate_company_trajectories/_late_sudden_nodes.py`; price ramp in `calculate_company_trajectories/nodes.py`; retirement dating in `prepare_scenario_asset_and_company_inputs/_asset_preparation.py`; both allocation modes and the synthetic top-up in `allocate_company_trajectories_to_assets/_allocation_nodes.py`; earnings in `calculate_asset_earnings/nodes.py`; valuation in `calculate_asset_and_company_npv/nodes.py`.
- Handover site: `docs/handover/` (index, user guide, methodology notes, per-stage pages). The stage-3 page, the methodology notes and the architecture page still describe the alignment-year retirement floor as unconditional; the shipped `retirement_timing: "natural"` supersedes them.
- Pre-change state: `crispy-kedro/docs/presentations/altr_updates_Brief_v1.md` (2026-07-08), for the "July brief" cells in §8.
- Measured numbers: `docs/superpowers/plans/decision-ablations.md` (A1-A6, D1-D5, golden `015a861`), `measurement-batch-results.md` (R0-R16, provider batch P, capture-price sample S, price-floor batch L), `adjustments-vs-december-2025.md`.
- Paper: Tang et al., *Asset-level analysis of corporate value adjustment in the climate transition*, §2.1-2.6, §3, Appendices 8.2-8.4.
