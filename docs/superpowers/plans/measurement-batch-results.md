# ALTR full-universe measurement batch — decision suite

Companion to `decision-ablations.md` (the A/D table and its runbook addendum).
Everything here is a **full-universe** run: `kedro run --env full --tags altrisk`,
inputs staged in `data/05_model_input`, WITCH `AR6_WITCH 5.0_EN_NoPolicy` →
`AR6_WITCH 5.0_EN_NPi2020_500`, no company filter.

**OLD GOLDEN** = `tests/golden/snapshots/*.parquet`, pinned from model run
`015a861`. Reference levels reproduced exactly by this batch's comparator before
any run: Σ`baseline_npv` **−421.16 bn**, Σ`latesudden_npv` **−4,401.56 bn**,
headline **−3,980.39 bn**, `npv_change` mean −1.3967 / median −1.5394 / 13 NaN,
4,878 companies. The golden was **not re-pinned** — that waits on the owners'
sign-off on the final configuration.

## How each number is defined

| Metric | Definition |
| --- | --- |
| Σ baseline / Σ latesudden | Sum over `company_npv.csv` of `baseline_npv` / `latesudden_npv` |
| **headline** | Σ(`latesudden_npv` − `baseline_npv`) — the risk signal |
| `npv_change` | The shipped per-company **ratio** `(ls−base)/\|base\|`, reported as mean/median/NaN count |
| sign flips | Companies whose per-company headline `(ls−base)` changes sign vs the reference |
| moved >10% | Companies whose per-company headline moves more than 10% in relative terms vs the reference |
| median rel | Median of that same per-company relative move |
| top-3 technology | Largest \|Δ\| in Σ(ls−base) per technology, from `company_technology_npv.csv` |
| **Q2 ratio** | Per technology, Σ`revenue` / (Σ`var_cost` + Σ`fixed_cost` + Σ`carbon_cost_net` + Σ`capex_total`) over `asset_earnings.csv`, **baseline trajectory** |

**Measurement kind** follows the runbook's arm table: *toggle ablation* = both
behaviours reachable from config, one switch against the run's own reference;
*branch comparison* = no config arm exists, so the effect is the same inputs run
at two commits.

## Method notes

- Runs are driven through the `KedroSession` API rather than `kedro run --params`,
  because the CLI splits `--params` values on commas and cannot express a nested
  dict at all. This also makes the **dcf-block replacement trap** easy to respect:
  every nested `dcf` override in this batch respecifies **all 12 top-level `dcf`
  keys** (16 dotted paths with `terminal_value`'s five), loaded from
  `conf/base/parameters_calculate_asset_and_company_npv.yml` and splatted.
  Flat top-level keys (`retirement_timing`, `apply_continued_om_shock`,
  `ownership_aggregation`) are passed on their own.
- `data/07_model_output` is deleted before every run (owner-approved: these
  outputs are regenerable). Free space is checked before each run and the batch
  aborts rather than filling the volume below 2.5 GB.
- Each run's comparison is written to this file **immediately after it is
  computed**, before the next run starts.

## Run ledger

| Run | Branch / arm | Kind | Runtime | Nodes | Headline (bn) | Δ vs its reference |
| --- | --- | --- | --- | --- | --- | --- |
| **OLD GOLDEN** | `015a861`, pinned snapshots | reference | — | 29/29 | **−3,980.39** | — |
| **R0** | `feat/consolidation-followups` @ 874b9ce — synthetic EF | branch comparison | 262 s | **29/29** | **−3,981.79** | **−1.40 (−0.035%)** vs GOLDEN |
| **R1** | `feat/decision-proposals` @ fa2addb — CANDIDATE, all defaults | branch comparison | 263 s | **30/30** | **−3,409.34** | **+572.45 (+14.38%)** vs R0; +571.06 (+14.35%) vs GOLDEN |
| R2 | `dcf.negative_tv_method = perpetuity` | toggle ablation | 259 s | 30/30 | −3,411.74 | −2.40 (−0.070%) vs R1 |
| **R3** | `retirement_timing = deferred_to_window` | toggle ablation | 262 s | 30/30 | −3,941.81 | **−532.47 (−15.62%)** vs R1 |
| R4 | `dcf.tv_anchor_policy = raw` | toggle ablation | 260 s | 30/30 | −3,405.05 | +4.29 (+0.126%) vs R1 |
| **R5** | `dcf.spread_carrier = alignment_type` + `green_discount_spread = 0.005` | toggle ablation | 258 s | 30/30 | −2,950.32 | **+459.02 (+13.46%)** vs R1 |
| **R6** | `dcf.brown_discount_spread = 0.0` | toggle ablation | 259 s | 30/30 | −4,174.34 | **−765.00 (−22.44%)** vs R1 |
| R7 | `terminal_value.g_real_brown = 0.02` (uniform g) | toggle ablation | 263 s | 30/30 | −3,410.02 | −0.68 (−0.020%) vs R1 |
| R8 | `dcf.stranding_aware_tv = false` | toggle ablation | 259 s | 30/30 | −3,425.75 | −16.42 (−0.482%) vs R1 |
| **R9** | `apply_continued_om_shock = false` | toggle ablation | 260 s | 30/30 | −3,574.42 | **−165.09 (−4.84%)** vs R1 |
| R10 | `ownership_aggregation = sum` | toggle ablation | ~2,340 s | **21/30, killed** | **not obtainable** | disk-blocked (259 MB free) |
| **R11** | `decom_cost_fraction_of_capex = 0.15` (calibration arm, added 2026-09-04 @ d7219b8) | toggle ablation | 272 s | 30/30 | −3,122.06 | **+287.28 (+8.43%)** vs R1 |
| **R12** | `include_replacement_capex = false` (decom at the delivered 50%) | toggle ablation | 266 s | 30/30 | -3,616.60 | **-207.27 (-6.08%)** vs R1 |
| **R13** | `include_replacement_capex = false` + `decom_cost_fraction_of_capex = 0.15` | toggle ablation (two switches) | 288 s | 30/30 | -3,327.32 | **+82.02 (+2.41%)** vs R1; -205.26 (-6.57%) vs R11; +289.29 (+8.00%) vs R12 |
| R14 | replacement CapEx **deleted from the code** (`afa1bd6`) + `decom_cost_fraction_of_capex = 0.15` | equivalence proof | 260 s | 30/30 | -3,327.32 | max abs diff vs R13: company NPV 0, company×technology 0 |

**Ranked by absolute impact on the risk signal** (all vs R1 except where noted):

| Rank | Arm | Δ headline | Δ % | Direction |
| --- | --- | --- | --- | --- |
| 1 | **R6** brown spread off | −765.00 bn | **−22.44%** | signal *grows* |
| 2 | **R1** the proposals, jointly | +572.45 bn | **+14.38%** | signal shrinks (vs R0) |
| 3 | **R3** retirement deferred | −532.47 bn | **−15.62%** | signal *grows* |
| 4 | **R5** pre-ruling-12/13 carrier | +459.02 bn | **+13.46%** | signal shrinks |
| 5 | **R11** decom at 15% of build cost | +287.28 bn | **+8.43%** | signal shrinks |
| 6 | **R12** replacement CapEx off | -207.27 bn | **-6.08%** | signal *grows* |
| 7 | **R9** continued O&M off | −165.09 bn | −4.84% | signal *grows* |
| 8 | **R13** replacement off + decom 15% (the ruled configuration) | +82.02 bn | +2.41% | signal shrinks |
| 9 | R8 stranding tiers off | −16.42 bn | −0.482% | signal grows |
| 10 | R4 raw TV anchor | +4.29 bn | +0.126% | signal shrinks |
| 11 | R2 unbounded negative TV | −2.40 bn | −0.070% | signal grows |
| 12 | **R0** synthetic EF | −1.40 bn | −0.035% | signal grows (vs GOLDEN) |
| 13 | R7 uniform terminal growth | −0.68 bn | −0.020% | signal grows |
| — | R14 replacement deleted from code | ≡ R13 | | equivalence, not an arm |
| — | R10 ownership `sum` | **not obtainable** | | disk |

**Confirmations carried on every run:** node completion **29/29** for R0 and the
golden lineage, **30/30** for R1–R9 and R11–R14 (the proposals add `asset_horizon_attributes`
and its node); 4,878 companies, 26,033 asset rows, 1,353,716 earnings rows and
52,066 valuation groups on all fourteen completed runs; **0 NaN-empty-window
perpetuity groups on every run**, R1 included, as expected.

---
## R0 — synthetic-EF marginal impact (`feat/consolidation-followups` @ 874b9ce vs OLD GOLDEN)

**Kind: branch comparison.** No config arm exists — the D2 ruling of 2026-09-02
(synthetic top-ups inherit their fleet's capacity-weighted emission factor) is a
code path, not a switch. `git diff 015a861..874b9ce -- conf/` touches **comments
only** (`g_k`, `n_quantiles` doc strings), and the only other source change is one
`ValueError` message string in `_input_nodes.py`. So this run isolates the
synthetic-EF rule and nothing else — it is the December table's last missing cell.

Runtime **262 s**, **29/29** nodes, 4,878 companies / 26,033 asset rows /
1,353,716 earnings rows — identical shape to the golden.

| Quantity | OLD GOLDEN | R0 | Δ | Δ % |
| --- | --- | --- | --- | --- |
| Σ `baseline_npv` | −421.16 bn | **−421.16 bn** | **exactly 0** | 0.00% |
| Σ `latesudden_npv` | −4,401.56 bn | −4,402.95 bn | −1.397 bn | −0.032% |
| **headline** Σ(ls−base) | −3,980.39 bn | **−3,981.79 bn** | **−1.397 bn** | **−0.035%** |
| `npv_change` mean | −1.3967 | −1.3976 | −0.0009 | |
| `npv_change` median | −1.5394 | −1.5501 | −0.0107 | |
| `npv_change` NaN | 13 | **13** | 0 | |

Sign flips **0**. Companies moving >10%: **4 of 4,878 (0.08%)**. Median relative
move **exactly 0.000%** — the rule touches a named minority and leaves the rest
untouched.

**Technology concentration — one technology moves, and only one.** Summed over
all ten technologies the deltas are exactly zero except:

| Technology | Δ headline | vs its own golden level |
| --- | --- | --- |
| **OilCap - w/o CCS** | **−1.397 bn** | −0.74% (of −189.33 bn) |
| every other technology | **0.000 bn** | 0.00% |

**Direction is as the D2 note predicted, and the magnitude is small.** Σ baseline
moves by *exactly* zero because a synthetic top-up's baseline capacity is zero by
construction, so a new emission factor has no baseline production to act on. The
whole effect therefore widens the shock-minus-baseline gap rather than shifting
both sides — the direction D2 argued was missing. At full-universe scale that
widening is **1.4 bn on a −3,980 bn signal: 3.5 basis points.**

**Anomaly worth recording: the biomass synthetics do not move at all.** The D2
finding named 181 synthetic assets carrying null EF — `BiomassCap - w/o CCS`
(7,748 rows) *and* `OilCap - w/o CCS` (1,664 rows) — and the fixture measurement
only ever exercised the oil population (52 rows). On the full universe the oil
synthetics move as expected and `BiomassCap - w/o CCS` moves by **exactly
0.000 bn**. That is a larger row population producing no effect at all, which is
worth a look before sign-off: the likely explanations are that the biomass
synthetics carry no shock-side production, or that their companies hold no real
biomass asset in the same group and the fallback chain resolved to something
that changes no cash flow. It is not a failure — but "the bigger half of the
affected population contributes zero" should be confirmed, not assumed.

### Q2 diagnostic — revenue-to-total-cost ratio per technology (R0, baseline)

Σ`revenue` / (Σ`var_cost` + Σ`fixed_cost` + Σ`carbon_cost_net` + Σ`capex_total`).

| Technology | Revenue (bn) | Total cost (bn) | Ratio |
| --- | --- | --- | --- |
| OilCap - w/o CCS | 359.41 | 1,224.82 | **0.293** |
| SolarCap - CSP | 174.03 | 390.79 | **0.445** |
| BiomassCap - w/o CCS | 155.28 | 244.36 | **0.635** |
| GasCap - w/o CCS | 9,553.95 | 11,857.27 | **0.806** |
| WindCap - Offshore | 809.54 | 983.31 | **0.823** |
| NuclearCap | 2,437.56 | 2,910.55 | **0.837** |
| CoalCap - w/o CCS | 9,210.76 | 9,325.84 | **0.988** |
| SolarCap - PV | 3,723.69 | 3,706.87 | 1.005 |
| HydroCap | 4,425.96 | 4,300.93 | 1.029 |
| WindCap - Onshore | 3,983.79 | 2,271.80 | 1.754 |

> **FLAG — 7 of 10 technologies run a ratio below 1 at BASELINE.** Only
> `SolarCap - PV`, `HydroCap` and `WindCap - Onshore` cover their costs, and two
> of those three only barely. This is the *baseline* pathway — no transition
> shock — so it says the shipped cost stack prices most of the fleet as
> loss-making before any climate scenario is applied. `OilCap` at 0.293 and
> `SolarCap - CSP` at 0.445 are the extremes. Note that `capex_total` carries
> replacement CapEx and decommissioning, both of which ablation A2/A3 showed to
> be worth thousands of billions on the levels — so this ratio is a direct
> readout of the A2/A3 decisions and should be read alongside them. Carried on
> every run below; watch which arms move it.

---
## R1 — the CANDIDATE configuration (`feat/decision-proposals` @ fa2addb, all defaults)

**Kind: branch comparison** (against both R0 and OLD GOLDEN). This is every
accepted proposal running together at its shipped default: `negative_tv_method:
bounded_annuity`, `tv_anchor_policy: operating`, `spread_carrier: technology`,
`brown_discount_spread: 0.01`, `green_discount_spread: 0.0`, `g_real_brown: 0.0`,
`retirement_timing: natural`, `stranding_aware_tv: True`,
`apply_continued_om_shock: True`. It is the reference for every toggle arm R2–R10.

Runtime **263 s**, **30/30** nodes.

> **The node count is 30 on this branch, not 29.** The proposals add a persisted
> stage-4 output (`asset_horizon_attributes`) and its node. Every R1–R10 run below
> is a **30/30** confirmation; R0 and the golden are 29/29. A reader comparing
> "29/29" across the two lineages is comparing different pipelines, not a
> failure.

Shape is otherwise identical: 4,878 companies / 26,033 asset rows / 1,353,716
earnings rows / 52,066 valuation groups.

| Quantity | OLD GOLDEN | R0 | **R1** | Δ vs R0 | Δ vs GOLDEN |
| --- | --- | --- | --- | --- | --- |
| Σ `baseline_npv` | −421.16 bn | −421.16 bn | **−305.46 bn** | +115.71 bn (+27.5%) | +115.71 bn (+27.5%) |
| Σ `latesudden_npv` | −4,401.56 bn | −4,402.95 bn | **−3,714.79 bn** | +688.16 bn (+15.6%) | +686.76 bn (+15.6%) |
| **headline** | −3,980.39 bn | −3,981.79 bn | **−3,409.34 bn** | **+572.45 bn (+14.38%)** | **+571.06 bn (+14.35%)** |
| `npv_change` mean | −1.3967 | −1.3976 | **−1.8928** | | |
| `npv_change` median | −1.5394 | −1.5501 | **−0.7641** | | |
| `npv_change` NaN | 13 | 13 | **14** | +1 | +1 |

Against **R0**: sign flips **120 (104 −→+, 16 +→−)**; **2,068 of 4,878 (42.4%)**
move >10%; median relative move **+0.75%**. Against **GOLDEN** the same figures
hold to three decimals — R0's synthetic-EF contribution is 1.4 bn out of 572 bn,
so the joint-proposals number and the total shift are the same number for
practical purposes.

**Top-3 technology concentration (vs R0):**

| Technology | Δ headline | vs its own R0 level |
| --- | --- | --- |
| **GasCap - w/o CCS** | **+460.55 bn** | +14.94% (of −3,082.59 bn) |
| **CoalCap - w/o CCS** | **+222.83 bn** | +5.52% (of −4,036.29 bn) |
| **WindCap - Onshore** | **−184.74 bn** | −14.08% (of +1,312.25 bn) |

**The proposals shrink the risk signal by 14.4% and move it off renewables onto
fossil.** Both fossil technologies get *less* negative while onshore wind gets
*less* positive — the joint effect redistributes roughly 460 bn from the gas
column and 185 bn out of the wind column. The 104-vs-16 asymmetry in the sign
flips says the same thing: the proposals rescue companies from a negative
headline far more often than they push them into one. Note the mean `npv_change`
ratio moves the *other* way (−1.40 → −1.89) while the median moves sharply toward
zero (−1.55 → −0.76) — a ratio distribution that has become much more
right-skewed, with a small tail of companies whose baseline NPV is near zero
dominating the mean. Read the aggregate absolute headline, not the mean ratio.

### Terminal-value tier census (R1, 52,066 groups)

| stranded | carbontech annuity | bounded negative | perpetuity | no anchor | r ≤ g rejects |
| --- | --- | --- | --- | --- | --- |
| 8,242 | 1,100 | **115** | 16,128 | 26,481 | 0 |

Assignments **before** the operating-anchor override; the override then zeroes
**30,709 of 52,066 groups that stand at zero capacity at the horizon**, leaving
**14,745 groups with a terminal-value row**. Read `perpetuity` and `bounded
negative` as a PAIR per the runbook — the 115 bounded-negative groups are
reclassified out of perpetuity, not lost from coverage.

### Informational note 1 — the D3 census-bucket shift under ruling 15

Carried per the runbook. On the fixture, flipping `negative_tv_method` moved
exactly two groups between the perpetuity and bounded-negative buckets and
changed no other count. At full-universe scale the bounded-negative bucket holds
**115 groups**, against the golden run's **2,699 groups (5.18%) taking a negative
perpetuity**. The two are not comparable head-to-head: the operating anchor
(ruling 11) and the O&M zero-stop (ruling 15) both fire upstream of the tier
assignment and remove most of the population that used to reach a negative
perpetuity at all. R2 measures what the remaining bucket is worth.

### Informational note 2 — NaN-empty-window perpetuity groups

**Count on R1: 0 groups**, as expected. Measured directly: of the 52,066
valuation groups, **zero** have an anchor window (the final
`normalization_window: 3` years) in which every `FCFF` is missing. The hazard is
real in the code — `has_terminal_fcff = final_fcff != 0` and NaN ≠ 0 is `True` in
numpy, so an all-NaN window would pass the test and be handed a perpetuity on a
NaN anchor — but it cannot fire on this data, because the flow-split collapse
upstream sums an all-missing cell to `0.0` (pandas `min_count=0`) before the
window mean is taken. The guard is data-independent in practice, but it rests on
that collapse, not on an explicit check.

### Q2 diagnostic — revenue-to-total-cost ratio per technology (R1, baseline)

| Technology | Revenue (bn) | Total cost (bn) | Ratio | vs R0 |
| --- | --- | --- | --- | --- |
| OilCap - w/o CCS | 343.25 | 1,177.48 | **0.292** | −0.002 |
| SolarCap - CSP | 172.68 | 386.63 | **0.447** | +0.001 |
| BiomassCap - w/o CCS | 133.62 | 217.28 | **0.615** | −0.020 |
| GasCap - w/o CCS | 8,224.97 | 10,411.25 | **0.790** | −0.016 |
| NuclearCap | 2,106.37 | 2,591.71 | **0.813** | −0.025 |
| WindCap - Offshore | 809.43 | 983.25 | **0.823** | −0.000 |
| CoalCap - w/o CCS | 9,006.12 | 9,166.62 | **0.982** | −0.005 |
| SolarCap - PV | 3,722.67 | 3,705.57 | 1.005 | +0.000 |
| HydroCap | 4,225.24 | 4,124.12 | 1.025 | −0.005 |
| WindCap - Onshore | 3,956.70 | 2,252.46 | 1.757 | +0.003 |

> **FLAG — the same 7 of 10 technologies sit below 1 at baseline**, and the
> proposals move the ratios barely at all (largest move: NuclearCap −0.025).
> Revenue and cost both fall by 5–14% while the *ratio* stays nearly invariant.
> Whatever makes most of this fleet look loss-making at baseline is upstream of
> every decision in this batch.
>
> **Attribution corrected by R3.** My first reading credited this level shift to
> the O&M zero-stop (ruling 15). R3 disproves that: setting `retirement_timing:
> deferred_to_window` and changing nothing else reproduces **R0's earnings
> aggregates exactly**, on all ten technologies. So the R0→R1 earnings shift is
> `retirement_timing: natural`, and ruling 15's zero-stop is **inert under the
> deferred-timing regime**. See R3.

---
## R2 — `dcf.negative_tv_method = "perpetuity"` (D3)

**Kind: toggle ablation** vs R1. Reverts the bounded-annuity floor to the
unbounded negative perpetuity. Nested `dcf` key — all 12 keys respecified.
Runtime **259 s**, **30/30**.

| Quantity | R1 (candidate) | R2 | Δ | Δ % |
| --- | --- | --- | --- | --- |
| Σ `baseline_npv` | −305.46 bn | −303.06 bn | +2.39 bn | +0.78% |
| Σ `latesudden_npv` | −3,714.79 bn | −3,714.80 bn | −0.005 bn | −0.000% |
| **headline** | −3,409.34 bn | **−3,411.74 bn** | **−2.398 bn** | **−0.070%** |
| `npv_change` mean | −1.8928 | −1.8991 | | |
| `npv_change` median | −0.7641 | −0.7641 | **0** | |
| `npv_change` NaN | 14 | 14 | 0 | |

Sign flips **2 (0 −→+, 2 +→−)**. Moved >10%: **17 of 4,878 (0.35%)**. Median
relative move **exactly 0.000%**.

**Top-3 technology concentration:** HydroCap **−2.69 bn** (−0.49%), GasCap - w/o
CCS **+0.29 bn** (+0.01%), NuclearCap **−0.005 bn** (−0.001%).

**Census — the pair moves by exactly 115 and nothing else moves:**

| `negative_tv_method` | stranded | annuity | bounded negative | perpetuity | no anchor |
| --- | --- | --- | --- | --- | --- |
| `bounded_annuity` (R1) | 8,242 | 1,100 | **115** | **16,128** | 26,481 |
| `"perpetuity"` (R2) | 8,242 | 1,100 | **0** | **16,243** | 26,481 |

This is the runbook's fixture finding reproduced at full-universe scale: the two
columns move as a PAIR (115 out of bounded-negative, 115 into perpetuity),
stranded/annuity/no-anchor are untouched, and the retirement override zeroes the
same **30,709** groups in both arms. A reader looking only at the perpetuity
column would see it *grow* and conclude coverage improved; it is a
reclassification.

**Verdict: D3 is now a 7-basis-point decision, down from a 5.18%-of-groups one.**
The golden run had 2,699 groups taking a negative perpetuity; on the candidate
branch only **115** groups ever reach that fork, because the operating anchor and
the O&M zero-stop remove the rest upstream. The whole argument between `!= 0` and
`> 0` is now worth **2.4 bn on a −3,409 bn signal**, and it lands almost entirely
on HydroCap rather than on fossil. Note the direction: bounding the negative
makes the signal *smaller*, and it moves the **baseline** level (+2.39 bn) while
leaving the shock level flat to five decimals — the negative perpetuities that
survive are a baseline-side phenomenon.

**Q2 ratios: byte-identical to R1** (all ten technologies, same 7 below 1).
Terminal value does not touch `asset_earnings`, so this is the expected result
and serves as a control on the diagnostic.

---
## R3 — `retirement_timing = "deferred_to_window"` (D9)

**Kind: toggle ablation** vs R1. Flat top-level key, no dcf splat needed. Reverts
to the golden lineage's clamp — no asset retires before the transition window
closes, so everything dated to retire ≤2038 bunches into 2039 (decision D1).
Runtime **262 s**, **30/30**.

| Quantity | R1 (candidate) | R3 | Δ | Δ % |
| --- | --- | --- | --- | --- |
| Σ `baseline_npv` | −305.46 bn | **−60.56 bn** | +244.90 bn | +80.2% |
| Σ `latesudden_npv` | −3,714.79 bn | −4,002.37 bn | −287.57 bn | −7.7% |
| **headline** | −3,409.34 bn | **−3,941.81 bn** | **−532.47 bn** | **−15.62%** |
| `npv_change` mean | −1.8928 | −0.9304 | | |
| `npv_change` median | −0.7641 | −1.3523 | | |
| `npv_change` NaN | 14 | **13** | −1 | |

Sign flips **52 (1 −→+, 51 +→−)** — strongly asymmetric toward *worse*. Moved
>10%: **686 of 4,878 (14.1%)**. Median relative move **exactly 0.000%** — the
majority of companies own nothing that retires inside the window.

**Top-3 technology concentration:** GasCap - w/o CCS **−333.13 bn** (−12.71%),
CoalCap - w/o CCS **−109.36 bn** (−2.87%), NuclearCap **−47.42 bn** (−10.72%).

**The largest single-switch move in the batch so far: 15.6% of the headline.**
And it moves the signal the way A6 did — deferring retirement makes the shock look
*worse*, not better. The two levels move in opposite directions (baseline +245 bn,
shock −288 bn), so this is not a level shift that cancels; it is a genuine
widening of the gap. `retirement_timing` is the decision to watch.

**Finding: `deferred_to_window` reproduces R0's `asset_earnings` EXACTLY.** All
ten technologies match R0's revenue and total-cost aggregates to the last decimal
(e.g. `OilCap - w/o CCS` 359.410188 / 1,224.823962 in both; `GasCap - w/o CCS`
9,553.947568 / 11,857.270548 in both). Two consequences:

1. **The R0→R1 earnings shift is `retirement_timing`, not ruling 15.** The
   candidate branch's 5–14% drop in both revenue and cost across the fleet comes
   from assets retiring at their natural dates instead of bunching at 2039.
2. **Ruling 15's O&M zero-stop is inert under the deferred-timing regime.** R3
   carries the zero-stop fix and R0 does not, and their earnings are identical —
   so under `deferred_to_window` there is no zero-capacity row being charged O&M
   for the fix to catch. The fix only bites once retirement is `natural`. This is
   the informational note the runbook asked to carry, measured rather than
   assumed: ruling 15 and D9 are **coupled**, and ruling 15's value is
   conditional on shipping `natural`.

The `npv_change` NaN count returning to **13** (the golden figure) while R1 shows
**14** dates that extra zero-baseline-NPV company to `natural` timing as well.

**Q2 ratios: identical to R0** (see above) — the 7-below-1 population is
unchanged, but every technology's ratio moves back to its R0 value.

---
## R4 — `dcf.tv_anchor_policy = "raw"` (owner ruling 11)

**Kind: toggle ablation** vs R1. Nested `dcf` key — all 12 respecified. Reverts
the terminal anchor to the pre-proposal form: the raw mean FCFF of the last three
years, decommissioning left inside it, and no zero-capacity-at-horizon override.
Runtime **260 s**, **30/30**.

| Quantity | R1 (candidate) | R4 | Δ | Δ % |
| --- | --- | --- | --- | --- |
| Σ `baseline_npv` | −305.46 bn | −312.43 bn | −6.98 bn | −2.28% |
| Σ `latesudden_npv` | −3,714.79 bn | −3,717.48 bn | −2.69 bn | −0.07% |
| **headline** | −3,409.34 bn | **−3,405.05 bn** | **+4.287 bn** | **+0.126%** |
| `npv_change` mean | −1.8928 | −1.8299 | | |
| `npv_change` median | −0.7641 | −0.7641 | **0** | |
| `npv_change` NaN | 14 | 14 | 0 | |

Sign flips **0**. Moved >10%: **4 of 4,878 (0.08%)**. Median relative move
**exactly 0.000%**.

**Top-3 technology concentration:** CoalCap - w/o CCS **+4.30 bn** (+0.11%),
GasCap - w/o CCS **+0.66 bn** (+0.03%), NuclearCap **−0.57 bn** (−0.13%).

**Census — this is the run that explains R2.**

| Arm | stranded | annuity | bounded negative | perpetuity | no anchor | retirement override |
| --- | --- | --- | --- | --- | --- | --- |
| R1 `operating` | 8,242 | 1,100 | **115** | 16,128 | 26,481 | 30,709 groups zeroed |
| R4 `raw` | 10,291 | 962 | **2,699** | 13,682 | 24,432 | **not applied** |

**The bounded-negative bucket under `raw` is 2,699 — the golden run's negative-
perpetuity count, to the group.** `decision-ablations.md` measured "2,699 groups
(5.18%) take a negative perpetuity today" on the golden; R4 reproduces that number
exactly from a different branch and a different code path. That is a strong
cross-check on both measurements, and it pins the cause: **the operating anchor is
what collapses the D3 population from 2,699 groups to 115** — a 96% reduction —
by excluding decommissioning from the anchor and zeroing retired groups outright.
The `annuity` count also returns to the golden's **962**.

**And yet the headline barely moves: +4.29 bn, 0.13%.** Ruling 11 restructures the
terminal-value census enormously — 2,049 groups move into `stranded`, 2,584 out of
`bounded negative`, 2,446 into `perpetuity` — while changing the aggregate risk
signal by an eighth of a percent. The two provisional figures quoted in the conf
comments (−615 bn fabricated on already-retired assets, −1.26 tn of capitalised
decom) describe gross terminal-value effects that **very largely cancel between
the two pathways**; this batch supersedes them as headline estimates. The net
worth of ruling 11 to the risk signal is **4.3 bn**, and it lands on coal.

**Q2 ratios: identical to R1** — the anchor policy does not touch `asset_earnings`.

---
## R5 — `dcf.spread_carrier = "alignment_type"` + `green_discount_spread = 0.005` (rulings 12 + 13)

**Kind: toggle ablation** vs R1 — but note the runbook's caveat: this arm exists
*only because this fix cycle restored it*. Before that, the pre-ruling behaviour
had been deleted from the tree and this was a branch comparison. Nested `dcf`,
two keys moved, all 12 respecified. Reproduces the pre-ruling-12 behaviour
exactly: brown/green membership decided by `alignment_type` rather than by
`brown_technologies`, and a −50 bps greenium applied. Runtime **258 s**, **30/30**.

| Quantity | R1 (candidate) | R5 | Δ | Δ % |
| --- | --- | --- | --- | --- |
| Σ `baseline_npv` | −305.46 bn | **−123.81 bn** | +181.64 bn | +59.5% |
| Σ `latesudden_npv` | −3,714.79 bn | −3,074.13 bn | +640.66 bn | +17.2% |
| **headline** | −3,409.34 bn | **−2,950.32 bn** | **+459.02 bn** | **+13.46%** |
| `npv_change` mean | −1.8928 | −1.1935 | | |
| `npv_change` median | −0.7641 | −0.7641 | ~0 | |
| `npv_change` NaN | 14 | 14 | 0 | |

Sign flips **16, all one way (16 −→+, 0 +→−)**. Moved >10%: **1,167 of 4,878
(23.9%)**. Median relative move **exactly 0.000%**.

**Top-3 technology concentration — every one of them is a renewable, and every
one moves up:**

| Technology | Δ headline | vs its own R1 level |
| --- | --- | --- |
| **WindCap - Onshore** | **+190.83 bn** | +16.92% (of +1,127.51 bn) |
| **SolarCap - PV** | **+133.65 bn** | +14.36% (of +930.80 bn) |
| **HydroCap** | **+71.85 bn** | +13.02% (of +551.75 bn) |

**This is the second-largest arm in the batch (13.5%), and it is the clearest
vindication of a ruling.** Rulings 12 and 13 moved the discount spread and the
terminal growth rate off `alignment_type` and onto `brown_technologies` on the
argument that alignment describes an asset's *trajectory*, not what it burns, and
so misfired in both directions. R5 measures exactly that misfire: switching back
hands **459 bn** to the risk signal, and the entire top-3 is onshore wind, solar
PV and hydro — three technologies that burn nothing. The 16-vs-0 sign flip
asymmetry is the same story with no counter-examples: no company gets worse.

Read the direction carefully. Under the old carrier the signal is **smaller**
(−2,950 bn vs −3,409 bn), because renewables misclassified `misaligned_high_
carbon` were paying a fossil penalty and growing at the fossil 0% — depressing
their *baseline* value and so shrinking the measured gap. Ruling 12/13 removes
that, and the fleet's clean assets get their 20× terminal multiple back. **Note
the census is byte-identical to R1** (8,242 / 1,100 / 115 / 16,128 / 26,481, same
30,709 override): the carrier changes rates and growth, not tier membership.

**Q2 ratios: identical to R1** — discount rates do not touch `asset_earnings`.

---
## R6 — `dcf.brown_discount_spread = 0.0` (the spread's own magnitude)

**Kind: toggle ablation** vs R1. Nested `dcf`, all 12 respecified. Turns the
+100 bps carbon risk premium off entirely, leaving every asset on the 7% base
rate. Runtime **259 s**, **30/30**.

| Quantity | R1 (candidate) | R6 | Δ | Δ % |
| --- | --- | --- | --- | --- |
| Σ `baseline_npv` | −305.46 bn | −412.36 bn | −106.90 bn | −35.0% |
| Σ `latesudden_npv` | −3,714.79 bn | −4,586.70 bn | −871.91 bn | −23.5% |
| **headline** | −3,409.34 bn | **−4,174.34 bn** | **−765.00 bn** | **−22.44%** |
| `npv_change` mean | −1.8928 | −1.9505 | | |
| `npv_change` median | −0.7641 | −0.7906 | | |
| `npv_change` NaN | 14 | 14 | 0 | |

Sign flips **8 (2 −→+, 6 +→−)**. Moved >10%: **2,520 of 4,878 (51.7%)** — over
half the universe. Median relative move **−10.12%**, the first arm in the batch
with a materially non-zero median.

**Top-3 technology concentration — all three fossil, all three worse:**

| Technology | Δ headline | vs its own R1 level |
| --- | --- | --- |
| **CoalCap - w/o CCS** | **−423.26 bn** | −11.10% (of −3,813.46 bn) |
| **GasCap - w/o CCS** | **−317.26 bn** | −12.10% (of −2,622.03 bn) |
| **OilCap - w/o CCS** | **−24.49 bn** | −13.78% (of −177.76 bn) |

**The largest single-switch move in the batch: 22.4%, and its sign is
counter-intuitive.** Removing the carbon risk *penalty* makes fossil assets look
**worse**, not better, and grows the measured risk signal by 765 bn. Both levels
fall together.

**The Q2 diagnostic explains why, and this is the batch's most important
cross-reading.** `CoalCap` runs a revenue-to-cost ratio of **0.982**, `GasCap`
**0.790**, `OilCap` **0.292** — all three are net cash-flow-*negative* at baseline.
A discount rate applied to a stream of negative cash flows works backwards from
the intuition: a *higher* rate shrinks the present value of losses and makes the
asset look better; removing the +100 bps premium therefore stops flattering
exactly the assets it was meant to penalise. On this fleet the brown spread has
been **reducing** measured fossil risk by ~765 bn, not adding to it.

That is a finding the owners should see before signing off on `brown_discount_
spread: 0.01`. The Bolton & Kacperczyk grounding for the premium is an equity-
returns argument about firms with positive earnings; applied to a modelled asset
stack where the three fossil technologies do not cover their costs, the mechanism
inverts. It does not make the parameter wrong — but its sign convention is doing
the opposite of what its comment in `conf/base` describes, and the 22.4% is the
largest number in this batch.

**Census: byte-identical to R1** (8,242 / 1,100 / 115 / 16,128 / 26,481, 30,709
override) — the spread moves rates, not tiers. **Q2 ratios: identical to R1.**

---
## R7 — uniform terminal growth, `terminal_value.g_real_brown = 0.02` (ruling 13's magnitude)

**Kind: toggle ablation** vs R1. Nested `dcf` **and** nested `terminal_value` —
all 12 top-level keys plus all 5 `terminal_value` sub-keys respecified. Sets the
brown growth rate equal to the green one, removing the growth split entirely.
Runtime **263 s**, **30/30**.

| Quantity | R1 (candidate) | R7 | Δ | Δ % |
| --- | --- | --- | --- | --- |
| Σ `baseline_npv` | −305.46 bn | −304.77 bn | +0.68 bn | +0.22% |
| Σ `latesudden_npv` | −3,714.7940797923 bn | **−3,714.7940797923 bn** | **exactly 0** | 0.00% |
| **headline** | −3,409.34 bn | **−3,410.02 bn** | **−0.684 bn** | **−0.020%** |
| `npv_change` mean | −1.8928 | −2.1168 | | |
| `npv_change` median | −0.7641 | −0.7641 | **0** | |
| `npv_change` NaN | 14 | 14 | 0 | |

Sign flips **0**. Moved >10%: **0 of 4,878**. Median relative move **exactly
0.000%**. Not a single company moves by more than a tenth.

**Top-3 technology concentration:** CoalCap - w/o CCS **−0.62 bn** (−0.016%),
GasCap - w/o CCS **−0.06 bn** (−0.002%), everything else **exactly 0.000 bn**.

**The smallest arm in the batch — two basis points — and the shock pathway does
not move at all.** Σ`latesudden_npv` is identical to R1 to thirteen significant
figures, so the growth split is a **baseline-only** parameter on this universe.
The reason is visible in R1's census: of 52,066 groups, **30,709 stand at zero
capacity at the horizon** and are zeroed by the operating anchor, and 8,242 more
are stranded. Under the shock pathway essentially no brown asset survives to
collect a terminal perpetuity, so the rate at which brown terminal cash flows
would have grown is moot.

**Implication for ruling 13.** The ruling tied the growth carrier to the discount
carrier deliberately, so that an asset cannot be brown for its rate and green for
its growth. That coupling is sound, but the *growth* leg carries almost none of
the weight: R5 (carrier moved for both legs) is worth **459 bn** and R7 (growth
leg alone, held at uniform) is worth **0.68 bn**. Essentially all of R5's 459 bn
is the discount-spread leg. The `12.5× vs 20×` multiple range quoted in the conf
comment is real per-asset arithmetic, but it applies to a population the
operating anchor has already largely emptied.

**Census: byte-identical to R1. Q2 ratios: identical to R1.**

---
## R8 — `dcf.stranding_aware_tv = false` (A5 re-measured on the candidate branch)

**Kind: toggle ablation** vs R1. Nested `dcf`, all 12 respecified. Removes the
three-tier Gourdel terminal value, leaving one Gordon perpetuity for every asset.
Runtime **259 s**, **30/30**.

| Quantity | R1 (candidate) | R8 | Δ | Δ % |
| --- | --- | --- | --- | --- |
| Σ `baseline_npv` | −305.46 bn | −327.06 bn | −21.60 bn | −7.07% |
| Σ `latesudden_npv` | −3,714.79 bn | −3,752.81 bn | −38.02 bn | −1.02% |
| **headline** | −3,409.34 bn | **−3,425.75 bn** | **−16.42 bn** | **−0.482%** |
| `npv_change` mean | −1.8928 | −1.4711 | | |
| `npv_change` median | −0.7641 | −0.7641 | **0** | |
| `npv_change` NaN | 14 | 14 | 0 | |

Sign flips **9 (5 −→+, 4 +→−)** — near-symmetric. Moved >10%: **351 of 4,878
(7.2%)**. Median relative move **exactly 0.000%**.

**Top-3 technology concentration:** CoalCap - w/o CCS **−47.43 bn** (−1.24%),
WindCap - Offshore **+20.74 bn** (**+35.81%** of a small +57.93 bn base),
SolarCap - PV **+6.42 bn** (+0.69%).

**Census — the tiers empty and the bounded annuity catches what falls out:**

| Arm | stranded | annuity | bounded negative | perpetuity | no anchor |
| --- | --- | --- | --- | --- | --- |
| R1 `True` | 8,242 | 1,100 | 115 | 16,128 | 26,481 |
| R8 `false` | **0** | **0** | **8,057** | 17,528 | 26,481 |

**This is the A5/D3 interaction the runbook insisted must be taken together, now
measured on the candidate branch — and the proposals have defused it.** On the
golden run, switching stranding off moved the baseline level by **−1,048.53 bn
(−248.96%)**, because with no abandonment option a permanently loss-making asset
took an unbounded negative perpetuity. On the candidate branch the same switch
moves the baseline level by **−21.60 bn (−7.07%)** — a **48× smaller** exposure.
The census says why: the 8,242 groups that lose their `stranded` tier do not fall
into an unbounded perpetuity, they fall into the **bounded negative** bucket,
which grows 115 → 8,057. `negative_tv_method: "bounded_annuity"` is now the
backstop that `stranding_aware_tv` used to be the only guard for.

Two consequences for the decision:

1. **A5's headline finding survives, its level finding does not.** The headline
   move is −0.48% here against A5's +0.55% on the golden — same order, opposite
   sign, both tiny. The tiers still barely touch the risk signal.
2. **D3 and A5 are no longer jointly load-bearing.** The runbook's warning —
   "select A5's alternative and the negative perpetuity becomes unbounded" — is
   **no longer true on this branch**, provided `negative_tv_method` stays at
   `bounded_annuity`. It becomes true again if R2's arm is chosen: `stranding_
   aware_tv: false` **and** `negative_tv_method: "perpetuity"` together would
   restore the unbounded exposure. That pair is the one combination in this batch
   that should not be selected together, and it is the cross-cell worth running
   if the owners want it bounded rather than argued.

**Q2 ratios: identical to R1** — terminal value does not touch `asset_earnings`.

---
## R9 — `apply_continued_om_shock = false` (the owner-named O&M arm)

**Kind: toggle ablation** vs R1. Flat top-level key, no dcf splat. Stops charging
continued O&M on the shock pathway. Runtime **260 s**, **30/30**.

| Quantity | R1 (candidate) | R9 | Δ | Δ % |
| --- | --- | --- | --- | --- |
| Σ `baseline_npv` | −305.45612614 bn | **−305.45612614 bn** | **exactly 0** | 0.00% |
| Σ `latesudden_npv` | −3,714.79 bn | −3,879.88 bn | −165.09 bn | −4.44% |
| **headline** | −3,409.34 bn | **−3,574.42 bn** | **−165.09 bn** | **−4.84%** |
| `npv_change` mean | −1.8928 | −1.7982 | | |
| `npv_change` median | −0.7641 | −0.7804 | | |
| `npv_change` NaN | 14 | 14 | 0 | |

Sign flips **92 (32 −→+, 60 +→−)**. Moved >10%: **1,212 of 4,878 (24.8%)**.
Median relative move **+3.11%**.

**Top-3 technology concentration:**

| Technology | Δ headline | vs its own R1 level |
| --- | --- | --- |
| **WindCap - Offshore** | **−106.37 bn** | **−183.62%** — the column flips sign, +57.93 bn → −48.44 bn |
| **GasCap - w/o CCS** | −103.89 bn | −3.96% |
| **CoalCap - w/o CCS** | **+82.77 bn** | +2.17% |

**A clean shock-side parameter, worth 4.8% of the headline.** Σ`baseline_npv` is
identical to R1 to eight decimal places — as designed, the switch is named
`..._shock` and touches only that pathway. Turning continued O&M off makes the
shock look **worse** (−165 bn), which is the opposite of the naive reading:
removing a cost should raise value. It does raise the shock pathway's costs-side
arithmetic for retiring assets, but the dominant effect is on assets whose
capacity is shed under the shock — they stop carrying the O&M that kept the
retirement schedule economic, and the resulting cash-flow path is worse, not
better.

**The notable row is offshore wind flipping sign.** `WindCap - Offshore` is the
only technology in the batch whose headline column changes sign on a single
toggle, +57.93 bn → −48.44 bn. It also moved +35.8% under R8. Offshore wind is a
small, high-CapEx, high-O&M column and it is the most switch-sensitive technology
in the entire suite — worth naming to the owners, because a decision taken for
reasons unrelated to wind will move offshore wind's published number by more than
100%.

**Census: 8,219 stranded / 1,123 annuity / 115 bounded negative / 16,128
perpetuity / 26,481 no anchor** — the only arm besides R4 and R8 to move tier
membership at all, and it moves it slightly (23 groups shift from `stranded` to
`carbontech annuity`, because without the continued O&M charge those groups no
longer fail the three-consecutive-loss-year test).

**Q2 ratios: identical to R1** — correctly, since the diagnostic is measured on
the **baseline** trajectory and this parameter is shock-only.

---
## R10 — `ownership_aggregation = "sum"` (A1) — ATTEMPTED ONCE, DISK-BLOCKED AGAIN

**Kind: toggle ablation** vs R1 — in principle. **No NPV numbers obtainable.**
Flat top-level key, no dcf splat. Attempted exactly once as briefed, with an
aggressive preflight clean (5.5 GB free at launch, well above the 2.5 GB floor).

**Outcome: terminated by the disk guard at 21 of 30 nodes after ~39 minutes**,
with **259 MB** left on a 228 GB volume. The previous attempt recorded in
`decision-ablations.md` died at 17/29 after 43 min with `[Errno 28] No space left
on device`; this attempt got **four nodes further** on the candidate branch before
hitting the same wall. It was stopped deliberately rather than allowed to run to
`Errno 28`, per the brief's instruction to stop rather than fill the disk — the
volume was descending roughly 1.4 GB per minute at the end. Not retried.

**What the attempt did measure — the operational cost, at full-universe scale:**

| Output | `tier_filter` (R1) | `sum` (R10, partial) | Inflation |
| --- | --- | --- | --- |
| `asset_trajectories.csv` | 550.4 MB | **3,307.4 MB** | **6.01×** |
| `company_trajectories.csv` | 251.1 MB | **664.0 MB** | **2.64×** |
| `frozen_capacity_at_retirement.csv` | 11.9 MB | **98.1 MB** | **8.25×** |
| assets entering `compute_asset_baselines` | 21,821 | **148,843** | **6.82×** |
| runtime to the failure point | 263 s for all 30 nodes | **~2,340 s for 21** | **~9×+** |
| **written before dying** | 1.7 GB complete | **3.8 GB, incomplete** | |

These confirm the runbook's mechanism figures from a second, independent
direction: the 6.82× asset-baseline inflation brackets the 6.43× owner-asset-year
row figure measured in-process on `filter_companies`, and the 2.64×
company-trajectory inflation is within 2% of the 2.68× ownership-weighted
exposure ratio. **A1's mechanism is now measured twice, by two different methods,
in agreement.** What is still missing, and remains missing, is the NPV delta.

**A1 is an infrastructure problem, not a modelling one.** Getting it would need
roughly **12–14 GB** of free space for `data/07_model_output` alone (extrapolating
the three written tables plus `asset_earnings` and `yearly_npv_trajectories` at
the same ratio), against a volume that has been sitting at 97–100% full for the
whole batch. Nothing about the model prevents the measurement. Options, cheapest
first: point the catalog at an external volume for one run; write parquet instead
of CSV for the three large intermediates (likely a 3–5× saving on its own); or
free ~15 GB on the system volume. All three are out of scope for a batch briefed
as "no commits to src/conf".

> **Disk note for whoever runs this next.** Free space fell from 6.6 GB to 3.8 GB
> over the ten completed runs even though `data/07_model_output` was cleaned
> before every one, so something outside this batch was also consuming the volume
> during the session. Budget for that drift: the batch's own steady-state
> footprint is ~1.7 GB per run and it cleans up after itself.

---
## R11 — `decom_cost_fraction_of_capex = 0.15` (calibration arm, 2026-09-04)

**Kind: toggle ablation** against R1. Added after the batch, on the owner's
instruction, once the baseline cash-flow decomposition (below) showed where the
sub-1 coverage ratios come from. The parameter (`d7219b8`) rewrites the delivered
`scrap_usd_per_mw = -capital_cost/2` as `-(0.15 × capex_usd_per_mw)` once, where
the scenario surface enters the run, so BOTH consumers of that column — the
in-window decommissioning charge and the terminal value's decommissioning floor —
price retirement at 15% of new-build cost instead of 50%. Default `null` keeps
the delivered convention; fixture pins are byte-identical under it.

Runtime **272 s**, **30/30** nodes, 4,878 companies, 52,066 valuation groups,
0 NaN-empty-window groups.

### Why this arm exists — the baseline cash-flow decomposition (golden snapshot)

At the *operating* level (revenue − fuel − O&M − carbon) only three technologies
fail to cover cost at baseline: `OilCap` (0.33), `BiomassCap` (0.83), `GasCap`
(0.93). The other four sub-1 technologies in the Q2 table (`SolarCap - CSP`,
`WindCap - Offshore`, `NuclearCap`, `CoalCap`) are pushed under by the **capex
layer** alone: ~9.7 tn USD over the window on the golden lineage, roughly half
replacement CapEx (2%/yr of year-t new-build cost on standing capacity) and
half decommissioning at capex/2. Both switches were OFF in December 2025
(baseline +2.3 tn); they are the entire swing to a negative baseline. Underneath,
WITCH prices are the low outlier among providers (CHN coal power 2030: WITCH
$25.3/MWh vs MESSAGE $34.5, REMIND $72.8, IMAGE $76.8) and the data gives gas a
zero spark spread (price $58.1 vs fuel-in $59.4), so margins sit at zero by
construction before any capex is charged.

### Headline and levels

| Metric | R1 (decom 50%) | R11 (decom 15%) | Δ |
| --- | --- | --- | --- |
| Σ baseline NPV | −305.46 bn | **+901.37 bn** | **+1,206.82** |
| Σ late&sudden NPV | −3,714.79 bn | −2,220.69 bn | +1,494.10 |
| Headline (Σ ls − Σ base) | −3,409.34 bn | **−3,122.06 bn** | **+287.28 (+8.43%)** |
| `npv_change` median / mean | −0.764 / −1.893 | −0.817 / −1.778 | −0.053 / +0.115 |
| `npv_change` NaN | 14 | 14 | 0 |
| Sign flips (of 4,878) | — | **57** (54 neg→pos, 3 pos→neg) | |
| Companies moved > 10% | — | 627 (12.9%); median relative move +1.75% | |
| Capex layer, baseline, undiscounted | 9,378 bn | **6,093 bn** | −3,285 |
| Fleet baseline FCFF, undiscounted | (golden lineage: −2,383 bn) | **+970 bn** | |

Top technology moves on the signal: `WindCap - Offshore` +121.68 bn (+210% of a
small +57.9 base), `CoalCap - w/o CCS` +85.52 bn (+2.24%), `GasCap - w/o CCS`
+79.48 bn (+3.03%).

### Q2 diagnostic — coverage ratio per technology (baseline; R1 → R11)

| Technology | Revenue (bn) | Capex layer R1 → R11 (bn) | Ratio R1 | Ratio R11 |
| --- | --- | --- | --- | --- |
| OilCap - w/o CCS | 343.25 | 119.99 → 69.80 | 0.292 | **0.304** |
| SolarCap - CSP | 172.68 | 265.79 → 120.73 | 0.447 | **0.715** |
| BiomassCap - w/o CCS | 133.62 | 57.00 → 25.98 | 0.615 | **0.717** |
| WindCap - Offshore | 809.43 | 487.57 → 461.35 | 0.823 | **0.846** |
| GasCap - w/o CCS | 8,224.97 | 1,468.20 → 740.47 | 0.790 | **0.849** |
| NuclearCap | 2,106.37 | 956.81 → 546.17 | 0.813 | **0.966** |
| CoalCap - w/o CCS | 9,006.12 | 1,289.64 → 664.71 | 0.982 | **1.054** |
| HydroCap | 4,225.24 | 1,933.38 → 1,619.48 | 1.025 | **1.109** |
| SolarCap - PV | 3,722.67 | 1,572.07 → 974.06 | 1.005 | **1.198** |
| WindCap - Onshore | 3,956.70 | 1,227.61 → 870.10 | 1.757 | **2.088** |

**Below 1 at baseline: 7 → 6.** `CoalCap` crosses (0.988 → 1.054); `NuclearCap`
reaches 0.966. The three operating-level losers (`OilCap`, `BiomassCap`,
`GasCap`) and the two capex-heavy renewables (`SolarCap - CSP`, `WindCap -
Offshore`) remain below 1 — decommissioning was never their problem.

### Baseline NPV levels per technology (bn, discounted)

| Technology | R1 | R11 | Δ |
| --- | --- | --- | --- |
| GasCap - w/o CCS | −985.8 | −684.2 | +301.6 |
| CoalCap - w/o CCS | −49.0 | **+200.2** | +249.2 |
| NuclearCap | −262.2 | −49.8 | +212.4 |
| HydroCap | 135.5 | 276.4 | +141.0 |
| SolarCap - PV | 286.8 | 419.7 | +132.9 |
| WindCap - Onshore | 1,104.0 | 1,196.9 | +92.8 |
| SolarCap - CSP | −53.4 | −17.5 | +35.9 |
| OilCap - w/o CCS | −372.9 | −353.6 | +19.3 |
| BiomassCap - w/o CCS | −47.6 | −33.5 | +14.1 |
| WindCap - Offshore | −60.9 | −53.2 | +7.7 |

### The company-majority test — NOT met by this arm

The owner's stated target is a baseline in which the high majority of firms are
reasonably profitable. Under R11 **65.8% of companies still carry a negative
baseline NPV** (R1: 70.7%); the median company moves from −89.6 mn to −49.0 mn.
By each company's dominant technology (largest absolute NPV footprint):

| Dominant technology | Companies | Baseline-negative share | Median baseline NPV (mn) |
| --- | --- | --- | --- |
| GasCap - w/o CCS | 1,706 | **77.0%** | −95.7 |
| CoalCap - w/o CCS | 1,576 | **75.3%** | −114.7 |
| WindCap - Onshore | 462 | 5.4% | +426.5 |
| BiomassCap - w/o CCS | 341 | **88.9%** | −36.4 |
| HydroCap | 272 | 24.6% | +42.7 |
| SolarCap - PV | 261 | 41.8% | +10.0 |
| OilCap - w/o CCS | 161 | **100.0%** | −364.4 |
| WindCap - Offshore | 53 | 41.5% | +42.3 |
| NuclearCap | 37 | 43.2% | +226.2 |
| SolarCap - CSP | 9 | 77.8% | −77.8 |

Gas-, coal-, biomass- and oil-dominant companies are 3,784 of 4,878 (77.6%) of
the universe, and three-quarters or more of each group stay negative. `CoalCap`
turns positive in aggregate (+200 bn) while 75% of coal companies do not: the
aggregate is carried by a few large positive owners. Their negativity is
operating-level (WITCH price level, zero spark spread) plus replacement CapEx,
which this arm does not touch. **The decom calibration moves the fleet
aggregate; it does not move the company majority.** The next levers are
`replacement_capex_rate` (already a parameter; the conf's own growth-capex
comment argues IAM O&M bundles annualised capital, in which case 2%/yr
double-counts) and the provider price stance. Neither is measured here.

### Housekeeping

`data/07_model_output` now holds R11's outputs, not the golden configuration's;
`tests/golden/test_golden.py::test_outputs_match_golden` is not meaningful until
a golden-config run is repeated. Metrics and per-technology tables are in
`scratchpad/runs/R11/` alongside R1–R10.

---
## R12–R14 — replacement CapEx: switched off, then deleted (owner ruling 2026-09-04)

**Ruling.** "Drop the replacement rate altogether if O&M covers it. The only way
we could consider it is if the rate is variable per technology — but it is much
better to drop it." Replacement CapEx was the 2%/yr roll-over charge on a real
asset's standing capacity, priced at the year's new-build cost:
`replacement_t = 0.02 × K_t × capex_t` on every non-decline year. The parameters
file justified keeping growth CapEx OFF with "IAM O&M already bundles annualized
capital costs"; the same reasoning applies to replacement, and the delivered O&M
runs 1.8–5.9% of build cost per year (PV 5.9% against ~1–2% for pure fixed O&M),
which supports the bundling reading. Kept: growth CapEx (off) and decommissioning.

**Three measurements, one proof.** R12 switches the charge off at the delivered
50% decom (isolates replacement alone); R13 switches it off at decom 15% (the
ruled configuration); R14 runs the tree with the charge **deleted from the code**
(`afa1bd6`: parameter, constant, `roll_over_cap` flow, `replace_capex` column, the
identity validator's roll-over term) and must reproduce R13 exactly.

Runtimes R12 266 s, R13 288 s, R14 260 s; all **30/30**, 4,878 companies,
52,066 valuation groups, 0 NaN-empty-window groups.

### The 2×2 — replacement × decommissioning (full universe, bn USD)

| | Replacement **on** (2%/yr) | Replacement **off** |
| --- | --- | --- |
| **Decom 50%** (delivered) | **R1** — Σ base -305, Σ ls -3,715, signal **-3,409.34** | **R12** — Σ base 2,462, Σ ls -1,154, signal **-3,616.60** (-207.27, -6.08% vs R1) |
| **Decom 15%** | **R11** — Σ base 901, Σ ls -2,221, signal **-3,122.06** (+287.28, +8.43% vs R1) | **R13** — Σ base 3,667, Σ ls 340, signal **-3,327.32** (+82.02, +2.41% vs R1) |

**Removing replacement CapEx makes the risk signal *larger* by ~6%** (R12 vs R1
-207.27 bn; R13 vs R11 -205.26 bn — the same size at either decom
rate, so the two levers are close to additive). The mechanism: the charge is
levied on standing capacity in *both* pathways, and the shock pathway sheds
fossil capacity earlier, so it was paying less replacement than the baseline.
Removing it therefore lifts the baseline more than the shock, and the gap
widens. Sign flips R12 vs R1: 56 (5 neg→pos, **51 pos→neg**); 593 companies
(12.2%) move more than 10%. Top technology moves: `WindCap - Offshore` −90.7 bn,
`GasCap` −48.6 bn, `SolarCap - PV` −27.4 bn.

**The ruled configuration (R13) leaves the signal nearly where R1 had it**
(+82.02 bn, +2.41%) while transforming the levels: the
baseline fleet goes from −305 bn to **+3,667 bn** and the late&sudden
pathway from −3,715 bn to **+340 bn** — the shock pathway is positive
in aggregate for the first time. Median `npv_change` moves −0.764 → -0.898
(the ratio's denominator grew); 41 sign flips vs R1 (26 neg→pos, 15 pos→neg),
827 companies (17.0%) moved more than 10%.

### Q2 diagnostic — coverage ratio per technology (baseline)

| Technology | Ratio R1 | Ratio R11 | Ratio R12 | Ratio R13 |
| --- | --- | --- | --- | --- |
| OilCap - w/o CCS | 0.292 | 0.304 | 0.304 | 0.318 |
| BiomassCap - w/o CCS | 0.615 | 0.717 | 0.653 | 0.770 |
| GasCap - w/o CCS | 0.790 | 0.849 | 0.824 | 0.889 |
| SolarCap - CSP | 0.447 | 0.715 | 0.526 | 0.944 |
| CoalCap - w/o CCS | 0.982 | 1.054 | 1.027 | 1.106 |
| NuclearCap | 0.813 | 0.966 | 0.948 | 1.163 |
| SolarCap - PV | 1.005 | 1.198 | 1.246 | 1.558 |
| WindCap - Offshore | 0.823 | 0.846 | 1.518 | 1.597 |
| HydroCap | 1.025 | 1.109 | 1.601 | 1.817 |
| WindCap - Onshore | 1.757 | 2.088 | 2.577 | 3.359 |

Below 1 at baseline: R1 7, R11 6, R12 5, **R13 4** — under the ruled
configuration only the three operating-level losers (`OilCap` 0.318, `BiomassCap`
0.770, `GasCap` 0.889) and `SolarCap - CSP` (0.944) remain below cost coverage.

### The company-majority test across the 2×2

| Run | Baseline-negative companies | Median company baseline NPV | gas | coal | biomass | oil | PV | hydro | nuclear |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R1 | 70.4% | −89.6 mn | 80.3% | 77.2% | 93.2% | 100% | 52.7% | 36.1% | 72.5% |
| R11 | 65.8% | −49.0 mn | 77.0% | 75.3% | 88.9% | 100% | 41.8% | 24.6% | 43.2% |
| R12 | 62.9% | −38.3 mn | 77.4% | 75.9% | 87.7% | 100% | 28.1% | 3.0% | 38.1% |
| **R13** | **57.8%** | **−12.0 mn** | 70.3% | 73.6% | 87.9% | 98.1% | **9.3%** | **1.0%** | 24.4% |

(Per-technology columns: share of companies with a negative baseline NPV among
those whose dominant technology — largest absolute NPV footprint — is that one.)

Under the ruled configuration the non-fossil universe is now mostly profitable
at baseline (PV 9%, hydro 1%, onshore wind ~5%, nuclear 24% negative). The
fossil-dominant companies — gas, coal, biomass, oil, 78% of the universe by count
— remain 70–98% negative. Their shortfall was never the capex layer: it is the
operating margin under WITCH's prices (China coal power at $25/MWh, a zero spark
spread for gas, oil out of merit at $120/MWh fuel cost). The target "high
majority reasonably profitable in baseline" is therefore now a **revenue-side**
question — provider price level, spark spread, peak/capacity revenue — not a
cost-side one. Nothing below measures that.

### R1 → R13 by technology and by region (bn USD, discounted)

The signal barely moves anywhere; the levels move everywhere. Under R13 the
only baseline-negative blocks left are China (`CHN` −64, `R10CHINA+` −105,
`R10INDIA+` −7) and, by technology, gas, oil and biomass — which is the same
finding as the company-majority table read geographically: WITCH prices China's
electricity at coal's marginal cost, and China is where the fossil fleet is.

| technology | Σ base R1 | Σ base R13 | Δ base | signal R1 | signal R13 | Δ signal | Δ signal % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CoalCap - w/o CCS | -49.0 | 499.7 | +548.7 | -3,813.5 | -3,749.8 | +63.6 | +1.7% |
| GasCap - w/o CCS | -985.8 | -413.8 | +572.0 | -2,622.0 | -2,591.1 | +30.9 | +1.2% |
| OilCap - w/o CCS | -372.9 | -322.9 | +50.0 | -177.8 | -171.3 | +6.5 | +3.6% |
| BiomassCap - w/o CCS | -47.6 | -23.6 | +24.0 | -14.1 | -11.7 | +2.3 | +16.6% |
| WindCap - Offshore | -60.9 | 169.4 | +230.3 | 57.9 | 88.9 | +31.0 | +53.5% |
| SolarCap - CSP | -53.4 | 3.4 | +56.8 | 107.8 | 103.2 | -4.6 | -4.3% |
| NuclearCap | -262.2 | 201.8 | +464.0 | 442.2 | 453.7 | +11.5 | +2.6% |
| HydroCap | 135.5 | 1,165.6 | +1,030.2 | 551.7 | 545.1 | -6.6 | -1.2% |
| SolarCap - PV | 286.8 | 781.2 | +494.4 | 930.8 | 881.8 | -49.0 | -5.3% |
| WindCap - Onshore | 1,104.0 | 1,606.0 | +501.9 | 1,127.5 | 1,123.9 | -3.7 | -0.3% |

| scenario_geography | Σ base R1 | Σ base R13 | Δ base | signal R1 | signal R13 | Δ signal | Δ signal % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CHN | -915.3 | -64.4 | +851.0 | -2,000.6 | -1,955.5 | +45.1 | +2.3% |
| IND | 157.8 | 381.9 | +224.1 | -554.6 | -552.0 | +2.5 | +0.5% |
| R10AFRICA | -108.9 | 27.5 | +136.3 | -529.0 | -548.5 | -19.5 | -3.7% |
| R10MIDDLE_EAST | 345.8 | 680.9 | +335.2 | -266.3 | -279.7 | -13.4 | -5.0% |
| R10REST_ASIA | 62.4 | 208.8 | +146.5 | -219.2 | -222.9 | -3.7 | -1.7% |
| IDN | 17.4 | 44.2 | +26.8 | -140.0 | -139.0 | +1.0 | +0.7% |
| R10CHINA+ | -173.8 | -105.1 | +68.7 | -102.7 | -107.4 | -4.7 | -4.6% |
| R10PAC_OECD | 127.3 | 304.6 | +177.3 | -74.1 | -68.2 | +5.9 | +8.0% |
| R10INDIA+ | -59.9 | -7.0 | +52.9 | -58.8 | -57.1 | +1.8 | +3.0% |
| ZAF | -15.7 | 12.7 | +28.4 | -37.6 | -34.0 | +3.6 | +9.6% |
| MEX | 15.2 | 59.5 | +44.2 | -20.3 | -18.2 | +2.1 | +10.5% |
| Global | -0.0 | -0.0 | +0.0 | -0.1 | -0.1 | +0.0 | +2.5% |
| R10NORTH_AM | -0.1 | 0.0 | +0.1 | -0.0 | -0.0 | -0.0 | -1.5% |
| R10EUROPE | 6.2 | 118.3 | +112.1 | -8.0 | 0.4 | +8.4 | +105.1% |
| R10LATIN_AM | 17.2 | 154.6 | +137.4 | 17.0 | 11.5 | -5.5 | -32.4% |
| BRA | -49.5 | 138.0 | +187.4 | 6.5 | 23.0 | +16.5 | +253.4% |
| CAN | 33.8 | 139.2 | +105.3 | 41.1 | 41.3 | +0.1 | +0.3% |
| EU | 8.5 | 403.7 | +395.3 | 26.5 | 60.7 | +34.2 | +128.8% |
| R10REF_ECON | 145.1 | 393.7 | +248.6 | 127.7 | 134.6 | +6.9 | +5.4% |
| USA | 80.9 | 775.7 | +694.8 | 383.2 | 383.9 | +0.7 | +0.2% |

### R14 — the deletion changes nothing beyond the switch

| Output | Rows | Max abs diff vs R13 | Identical rows |
| --- | --- | --- | --- |
| company_npv | 4,878 | 0 | 4,878 |
| company_technology_npv | 7,527 | 0 | 7,527 |

Headline R13 -3,327.3161 vs R14 -3,327.3161; Σ baseline 3,666.9667 vs 3,666.9667;
Q2 table max abs diff 0. The output schema is unchanged (`replace_capex`
was never written to `asset_earnings`), so the fixture's schema pins stay green;
the value pins stay strict-xfail with the removal named as their sixth mover.

### Housekeeping

`data/07_model_output` holds R14's outputs. The golden compare remains
inapplicable until the golden is re-pinned to the configuration the owners sign
off. The former `test_replacement_rate_scenario_alignment.py` lives on as
`test_om_bundles_capital_evidence.py` (renamed, not deleted), keeping the
data-side reasoning for the ruling under test.

---
## P — provider sensitivity under the ruled configuration (2026-09-04)

**Question (owner):** the baseline-profitability finding was established on
WITCH — is it provider-specific, and what happens on the other providers? Seven
runs of the identical tree (`d75bd8b`: replacement removed, decom 15%) on each
provider's own valid pair from the 2026-09-01 extract. Coverage differs by
provider (12–28 geographies, 12–19 technologies), so the company universe is
not identical run to run — companies and asset rows are reported per run. Only
MESSAGE is a strict like-for-like on scenario design.

| Provider | Pair (baseline → target) | Companies | Asset rows | Σ base (bn) | Σ ls (bn) | Signal (bn) | Signal / |base| | Baseline-negative cos | Median co. base (mn) | Techs < 1 | Note |
| --- || --- || --- || --- || --- || --- || --- || --- || --- || --- || --- || --- |
| WITCH | EN_NoPolicy → EN_NPi2020_500 | 4,878 | 26,033 | 3,667 | 340 | **-3,327** | -91% | **57.8%** | -12.0 | 4 | R14 — the reference |
| MESSAGE | EN_NoPolicy → EN_NPi2020_500 | 4,830 | 23,128 | -2,432 | -20,065 | **-17,632** | -725% | **50.2%** | -0.8 | 4 | like-for-like ENGAGE pair |
| AIM | EN_INDCi2100 → EN_NPi2020_500f | 4,660 | 19,473 | 46,192 | 43,479 | **-2,713** | -6% | **0.1%** | 3,393.6 | 0 | documented AIM equivalent; INDC baseline; **target carbon price is 0 in the extract** |
| REMIND | EN_NoPolicy → SusDev_SSP2-PkBudg900 | 4,696 | 19,284 | 3,329 | 296 | **-3,033** | -91% | **56.6%** | -24.0 | 4 | 900 Gt budget, different project family |
| IMAGE | EN_NoPolicy → CO_2Deg2020 | 4,690 | 19,342 | 20,917 | 4,823 | **-16,095** | -77% | **19.6%** | 476.4 | 2 | 2 °C, different family |
| POLES | EN_INDCi2100 → EN_NPi2020_500 | 4,705 | 18,271 | 18,045 | -60,151 | **-78,196** | -433% | **13.8%** | 592.8 | 1 | **carbon column 5,503–10,698 USD/t — units or extrapolation defect** |
| GEME3 | EN_INDCi2100 → EN_NPi2020_500 | 4,340 | 12,730 | 7,047 | 8,234 | **1,187** | +17% | **49.8%** | 0.0 | 3 | baseline carries a non-zero carbon price (13–19 USD/t) |

### Q2 coverage ratio per technology (baseline)

| Technology | WITCH | MESSAGE | AIM | REMIND | IMAGE | POLES | GEME3 |
| --- || --- || --- || --- || --- || --- || --- || --- |
| BiomassCap - w/o CCS | 0.77 | 0.43 | 3.10 | 0.96 | 1.12 | 1.25 | 0.95 |
| CoalCap - w/o CCS | 1.11 | 1.04 | 3.54 | 1.12 | 2.93 | 1.27 | 1.44 |
| GasCap - w/o CCS | 0.89 | 0.40 | 3.03 | 0.69 | 0.98 | 1.22 | 0.80 |
| GeothermalCap | — | 0.83 | 25.00 | 3.90 | — | 2.56 | 2.60 |
| HydroCap | 1.82 | 1.74 | 24.21 | 3.35 | 14.39 | 7.42 | 4.46 |
| NuclearCap | 1.16 | 1.53 | 4.64 | 2.24 | 3.92 | 8.44 | 2.52 |
| OilCap - w/o CCS | 0.32 | 0.18 | 1.71 | 0.37 | 0.58 | 0.71 | 0.33 |
| SolarCap - CSP | 0.94 | — | — | 4.28 | — | — | — |
| SolarCap - PV | 1.56 | 6.13 | — | 0.80 | — | 2.65 | — |
| WindCap - Offshore | 1.60 | 1.42 | — | — | 2.25 | 2.93 | — |
| WindCap - Onshore | 3.36 | 2.56 | 7.41 | — | 3.69 | 8.13 | — |

### Reading

- **The data level decides baseline profitability, not the model.** 2030
  median regional power price: WITCH $41, MESSAGE $31, REMIND $73, IMAGE $80,
  AIM/CGE $134/MWh. Coal-dominant companies are 74% negative under WITCH, 7%
  under REMIND, 0% under IMAGE and AIM. The universe goes from 58% negative
  (WITCH) to 0.1% (AIM) on the same assets and code.
- **Gas is out of merit under every low-price provider** (WITCH 70%, REMIND 97%
  of gas-dominant companies negative) because the model pays every technology
  the regional annual-average price; gas earns above-average capture prices in
  reality. **Oil and biomass are negative under every provider** — structurally
  out of merit on energy-only economics.
- **The signal is dominated by the carbon-price path × how much unabated coal the
  pathway keeps running.** MESSAGE (carbon to $1,070/t, Chinese unabated coal
  flat to 2050) gives −17.6 tn, −18.1 tn of it in China; the model has no
  in-window shutdown, so plants run and pay. IMAGE (to $882/t, coal to zero)
  gives −16.1 tn. GEM-E3's signal is **positive** (+1.2 tn): its target's power
  price doubles in 2030 while the coal pathway is the same in both scenarios.
  POLES's −78 tn is the carbon-column defect, not a result.
- **Extract-quality flags for the marts:** AIM/CGE target carbon price 0
  everywhere; POLES carbon 5,503–10,698 USD/t; GEM-E3 non-zero baseline carbon;
  MESSAGE `CoalCap - w/o CCS` pathway flat under a 500 Gt budget.

### The fix, by layer (assessment put to the owner)

1. **Coal-dominant companies (32% of the universe): provider price level.**
   Choose the pair deliberately (IMAGE: 20% negative, carbon-driven shock;
   REMIND: WITCH-sized signal with coal healthy). No code.
2. **Gas-dominant (35%): price structure.** A per-technology capture-price
   factor on the revenue line (`Q × price × factor[technology]`), literature-
   sourced (gas ~1.1–1.3, PV/wind ~0.7–0.9), held constant across pathways and
   said so. One parameter table, one multiplication, measurable in one arm.
3. **Oil- and biomass-dominant (10%): out of merit everywhere.** Decide
   explicitly: exclude from the valued universe with a documented reason
   (recommended) or a cost-recovery floor.

Not recommended: a flat price uplift to calibrate margins.

---
## December table completion

> **Scope note on the row numbering.** The brief asked for rows **1–15**. The
> December table in `adjustments-vs-december-2025.md` has **11 rows**, not 15 —
> rows 12–15 do not exist in that document. The 1–15 numbering appears to conflate
> the adjustment rows with the owner **rulings** 11–15 referenced in the runbook
> addendum, which are a separate sequence. Both are mapped below: the eleven real
> adjustment rows first, then the proposals and rulings, which are not December
> rows at all because the December model predates them.

### The eleven December adjustment rows

| # | Adjustment | Measured number | Measurement kind | Source |
| --- | --- | --- | --- | --- |
| 1 | Replacement CapEx (`include_replacement_capex`) | headline **−88.3 bn (+2.22%)** on the golden; on the candidate, switching it **off** moves the signal **-207.27 bn (-6.08%)** and Σ baseline NPV −305 → +2,462 bn (R12). **DELETED from the code 2026-09-04 by owner ruling; R14 ≡ R13** | toggle ablation vs GOLDEN; toggle ablation vs R1 | A2, prior batch; **R12 — re-measured; R14 — deletion proof** |
| 2 | Decommissioning costs (`include_decom_costs`) | headline **−524.0 bn (+13.17%)** for the switch; **calibration at 15% of build cost (R11): signal +287.3 bn (+8.43%) vs R1, Σ baseline NPV −305 → +901 bn, 65.8% of companies still baseline-negative** | toggle ablation vs GOLDEN; calibration arm vs R1 | A3, prior batch; **R11 — calibration newly measured** |
| 3 | Price ramp (`price_ramp`) | headline **−1,434.3 bn (+36.03%)** | toggle ablation vs GOLDEN | A4, prior batch — **not re-measured here** |
| 4 | Stranding-aware terminal value (`dcf.stranding_aware_tv`) | **−16.42 bn (−0.482%)** on the candidate branch; −22.1 bn (+0.55%) on the golden | toggle ablation vs R1 | **R8 — re-measured** |
| 5 | Perpetuity anchor (`!= 0` vs `> 0`, D3) | **−2.40 bn (−0.070%)**; bucket 2,699 → **115** groups | toggle ablation vs R1 | **R2 — NPV number newly obtained** |
| 6 | Ownership aggregation (`ownership_aggregation`) | **NPV delta still not obtainable.** Mechanism corroborated: 6.82× asset inflation, 2.64× company-trajectory inflation | toggle ablation, **failed on disk** | **R10 — attempted once, killed at 21/30** |
| 7 | MCPR (merit-order clearing-price adjustment) | **net zero vs December** — retired before consolidation, never shipped | not measurable (no arm; code path removed) | decided 2026-09-01 |
| 8 | **Synthetic-asset EF inheritance** | **headline −1.397 bn (−0.035%)**; Σ baseline **exactly unchanged**; 100% of it on `OilCap - w/o CCS` | **branch comparison** (R0 vs GOLDEN) | **R0 — THE MISSING CELL, NOW FILLED** |
| 9 | Retirement mechanism + alignment-year floor | **−532.47 bn (−15.62%)** for the `deferred_to_window` arm; A6's off-bound remains −1,834.2 bn (−46.08%) | toggle ablation vs R1 | **R3 — first config-arm number for this row** |
| 10 | EF forward-fill (Q3) | **inert — 0 fillable gaps**; superseded by row 8 | not measurable (choice changes no number) | prior batch |
| 11 | Validation / hardening / golden gate | **no model-number impact by construction** | not measurable (pins byte-identical) | prior batch |

**Rows newly filled by this batch: 8 (the brief's target), 5, and 9.** Row 4 was
re-measured on the candidate branch and its magnitude changed materially. Row 6
remains the only row in the December table with no NPV number, for the second
time, and for the same reason both times.

### The proposals and owner rulings — not December rows

The December model predates every one of these, so they have no December
behaviour to be an adjustment *from*. They are the delta between the golden
lineage and the candidate configuration.

| Item | Measured number | Measurement kind |
| --- | --- | --- |
| **All proposals jointly** (the candidate configuration) | **+572.45 bn (+14.38%)** vs R0; +571.06 bn (+14.35%) vs GOLDEN | **branch comparison** (R1) |
| Ruling 11 — `tv_anchor_policy: operating` | **+4.29 bn (+0.126%)** | toggle ablation (R4) |
| Rulings 12 + 13 — `spread_carrier: technology` (both legs) | **+459.02 bn (+13.46%)** | toggle ablation (R5) |
| Ruling 13 — the growth leg **alone** (`g_real_brown`) | **−0.68 bn (−0.020%)** | toggle ablation (R7) |
| The brown spread's own magnitude (`brown_discount_spread`) | **−765.00 bn (−22.44%)** — largest in the batch | toggle ablation (R6) |
| Ruling 14 — `dynamic_marginal_ef` deletion | **0 by construction** — the branches coincide on today's inputs; the column never arrives and the marginal EF is 0 either way | **branch comparison only** (no arm exists) |
| Ruling 15 — the O&M zero-stop | **inert under `deferred_to_window`; entangled with D9 under `natural`.** R3 reproduces R0's earnings exactly *with* the fix applied, proving the fix changes nothing in the deferred regime | **branch comparison only** (bug-class fix, deliberately no arm) |
| D9 — `retirement_timing` | **−532.47 bn (−15.62%)** | toggle ablation (R3) |
| `apply_continued_om_shock` (the owner-named O&M arm) | **−165.09 bn (−4.84%)** | toggle ablation (R9) |
| C2 — past-lifetime exit | **no separate number; bounded by R2's −2.40 bn**, inside which it rides | **branch comparison only** (rides inside `negative_tv_method`) |

### What the batch says about the candidate configuration

1. **The proposals shrink the risk signal by 14.4%** and move it off renewables
   onto fossil (gas +461 bn, coal +223 bn, onshore wind −185 bn).
2. **Three arms dominate everything else**: the brown discount spread (22.4%),
   retirement timing (15.6%) and the spread carrier (13.5%). Every other
   toggle in the suite is under 5%, and five of them are under 0.5%.
3. **The terminal-value machinery is nearly headline-neutral.** R2, R4, R7 and R8
   together span 0.02%–0.48% each. They restructure the tier census enormously —
   R4 moves 2,584 groups out of the bounded-negative bucket alone — while the
   aggregate risk signal barely notices, because terminal-value effects are
   charged in both pathways and cancel. The provisional −615 bn and −1.26 tn
   figures quoted in `conf/base` for ruling 11 are gross, one-sided numbers;
   **this batch supersedes them with a net +4.29 bn.**
4. **The brown discount spread's sign is inverted on this fleet** and should be
   reviewed before sign-off. See R6 read together with the Q2 diagnostic.
5. **Ruling 15's value is conditional on shipping `retirement_timing: natural`.**
   If the owners choose `deferred_to_window`, ruling 15 buys nothing.
6. **`stranding_aware_tv: false` and `negative_tv_method: "perpetuity"` must not
   be selected together** — separately they are worth −16.4 bn and −2.4 bn, but
   together they restore the unbounded negative perpetuity that the golden run
   carried on 2,699 groups.

### Not done, deliberately

**The golden was NOT re-pinned.** `tests/golden/snapshots/` still holds the
`015a861` snapshots and their original manifest. `test_outputs_match_golden` will
report drift against any of R0–R9 until the owners sign off on a final
configuration and the baseline is re-pinned with
`pin_golden.py --require-sha <run sha>`. No `src/` or `conf/` file was modified or
committed by this batch; the only file committed is this one.
