# ALTR adjustments since the December 2025 model — status and measured impact

Audience: Jakub + Bertrand, for the still-open decision conversation.
Reference point: the model as validated in **December 2025** (pre NPV-direction
work, pre MCPR, pre consolidation). Measured impacts come from the one-switch
ablation suite against the pinned golden baseline (see
`decision-ablations.md`; golden headline risk signal **−3,980.39 bn USD**,
WITCH EN_NoPolicy → EN_NPi2020_500, full universe). Where an ablation turned an
adjustment OFF, its impact here is reported with the sign of turning it ON —
i.e. what the adjustment DID to the model relative to December.

Rows marked **DEC-CONFIRM** carry an assumption about the December behaviour
that Jakub or Bertrand should confirm from memory or the December tag — the
2026 lineages diverged enough that code archaeology was not decisive.

## Plain-language summary

Since December the model gained four cost/valuation mechanisms (replacement
CapEx, decommissioning charges, the price ramp, stranding-aware terminal
value), one input-handling parameter (ownership aggregation), one retired
experiment (MCPR), and — as of today — emission-factor inheritance for
synthetic build-out assets. Measured one at a time, only two of them
materially move the headline *risk signal*: the **price ramp** (makes the
measured shock 36% larger and removes a coal-gains-3-trillion windfall the
hard switch produces) and **decommissioning costs** (13% larger, concentrated
in the shock pathway). Replacement CapEx and the stranding tiers reshape
absolute NPV *levels* dramatically — hundreds of percent — but nearly cancel
out of the shock-minus-baseline difference. The ownership default is
unchanged from December (the tier filter); Bertrand's TRISK-style summing is
available behind a switch and inflates ownership-weighted exposure 2.68×.
Retirement is mechanically unchanged since December but is now quantified: it
dampens the measured risk signal by ~46%, and its alignment-year floor causes
the 2039 CapEx spike. Decisions on the price ramp, the two cost switches, the
perpetuity anchor and the 2039 floor are **still open**.

## Adjustment table

| # | Adjustment | December 2025 behaviour | Current behaviour | Measured impact of the adjustment (vs golden) | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | **Replacement CapEx** (`include_replacement_capex`) | Off — no capital-maintenance charge (DEC-CONFIRM; matches Bertrand's 2026 main default) | On: 2%/yr on installed capacity, retiring/synthetic assets excluded | Headline **−88.3 bn (signal +2.2%)**. Levels: baseline −2,713.9 bn (from +2.3 tn to −0.4 tn), shock −2,802.2 bn. 91.8% of companies move >10%. Lands on renewables (Solar, Wind), fossil nearly untouched | **OPEN** — defaults contested (Jakub: on, utility convention; Bertrand: growth-fraction only) |
| 2 | **Decommissioning costs** (`include_decom_costs`) | Off; scrap value signed, retiring could *pay* the owner (DEC-CONFIRM) | On: `abs(scrap)` charged as an outflow at retirement | Headline **−524.0 bn (signal +13.2%)**. Strongly shock-side: turning it off flips 98 companies risk-negative→positive vs only 8 the other way | **OPEN** — same contested pair. Calibration arm R11 (2026-09-04, `decom_cost_fraction_of_capex: 0.15`, i.e. decom at 15% of build cost instead of the delivered 50%): Σ baseline NPV −305 → +901 bn, signal +287 bn (+8.4%) milder, technologies below cost coverage 7 → 6, but 65.8% of companies still baseline-negative — see `measurement-batch-results.md` R11 |
| 3 | **Price ramp** (`price_ramp`) | Hard switch to target prices at `shock_year` (TRISK-style) | Linear blend of price surfaces across [shock_year, alignment_year] | Headline **−1,434.3 bn (signal +36.0%)** — the largest adjustment. Baseline untouched (Δ exactly 0). The hard switch produces a fossil windfall: coal +3.0 tn, gas −2.0 tn; the ramp removes it. Side effect: makes `dcf.discount_rate_shock` inert (all rows labelled baseline) | **OPEN** — the single most consequential decision on the table |
| 4 | **Stranding-aware terminal value** (`dcf.stranding_aware_tv`) | Single Gordon perpetuity for every asset (DEC-CONFIRM) | Three tiers: stranded→0, declining carbontech→finite annuity, else perpetuity | Headline **−22.1 bn (signal +0.6%)** — smallest. Levels: baseline +1,048.5 bn, shock +1,026.4 bn (they cancel). Function: bounds the negative-perpetuity exposure (#5) | **OPEN**, must be decided jointly with #5 |
| 5 | **Perpetuity anchor** (`final_fcff != 0` vs `> 0`) | `> 0` — terminal value floored at zero for loss-makers (Bertrand's explicit December-era choice; DEC-CONFIRM) | `!= 0` — loss-making non-stranded assets take a negative perpetuity | 2,699 groups (5.2%) carry a negative perpetuity today, −293.0 bn normalised terminal FCFF, split near-evenly across both pathways — so flooring at zero would lift both levels and barely move the signal. Unbounded only if #4's tiers are also removed | **OPEN**, joint with #4 |
| 6 | **Ownership aggregation** (`ownership_aggregation`) | Tier filter (select direct, consolidate within tier) — this *was* the December behaviour | Same default, now an explicit parameter; `sum` (Bertrand's 2026 TRISK-style change) available | Default = no change vs December. `sum` measured at mechanism level (full universe): 6.43× owner-asset rows, 2.68× ownership-weighted exposure, +2,853 equity-only companies. NPV run disk-blocked | **DECIDED** (Jakub, 2026-09-01): parameter, default tier_filter |
| 7 | **MCPR** (merit-order clearing-price adjustment) | Did not exist | Does not exist — built during 2026, retired before consolidation | Net zero vs December | **DECIDED** (Jakub, 2026-09-01): retired |
| 8 | **Synthetic-asset EF inheritance** | Synthetic build-out assets carried zero EF → zero carbon cost (as inherited from the original synthetic-asset design) | Inherit capacity-weighted EF of the real assets they extend (company group → tech×geo → tech fallbacks) | **Implementation in flight — impact measured against the golden before re-pinning; number lands in this row when the run completes.** Affects 181 synthetic biomass/oil assets, 9,412 asset-years, both pathways | **DECIDED** (Jakub, 2026-09-02): inherit |
| 9 | **Retirement mechanism + alignment-year floor** | Same mechanism (floor present in both lineages) | Unchanged — but now quantified | Not an adjustment; a bound: retirement dampens the risk signal by **46%** (turning it off → −5,814.6 bn headline), bites gas/wind/hydro not coal. The floor causes the 2039 spike: CapEx +341% in one year, −13% capacity cliff; ~73% of the spike is the floor, the residual is the alignment year itself | **OPEN** — keep-and-document vs smooth retirements across the window |
| 10 | **EF forward-fill** (Q3) | Zero-fill only (DEC-CONFIRM) | Forward-fill added, on the stricter series grain | **Inert — zero fillable gaps in the full universe.** The debate resolved to #8, which is where the real hole was | Decided by measurement: moot |
| 11 | **Ownership tier validation, NaN-name handling, licence guards, sanitizer, docs site, golden regression gate** | None of this existed | Hard-fail on tier-less data; names carried not keyed; identity-asserting licence guard; export sanitizer; mkdocs site; pinned golden gate | No model-number impact by construction (pins byte-identical through all of it) | Done — engineering hardening, not methodology |

## How to read the numbers

Impacts are **one-at-a-time** against the current golden configuration, not a
cumulative walk from December — interactions exist (notably #3 with #5's
labels, and #4 with #5's bound), so the sum of rows does not equal the total
December-to-now shift. When the open decisions (#1–#5, #9) are made, a single
cumulative reconciliation run December-config → final-config can be produced
on request.

*Maintained alongside `decision-ablations.md` (full evidence) and
`consolidation-clash-report.md` (who argued what, per clash).*
