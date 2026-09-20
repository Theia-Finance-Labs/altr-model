# ALTR open methodological decisions — one-switch ablations against the pinned golden baseline

**Baseline** `tests/golden/snapshots/` (model run `015a861`, `conf/full` env, WITCH
`AR6_WITCH 5.0_EN_NoPolicy` → `AR6_WITCH 5.0_EN_NPi2020_500`, whole universe, no company filter).
**Worktree** `/Users/jakub/Documents/repos/altr-model-migration` @ `feat/consolidation-followups` `d9f37da`.
Nothing was committed, pushed, or re-pinned; no tracked file was modified; the golden snapshots were not touched.

**Golden reference levels** — 4,878 companies / 26,033 asset rows / 52,066 valuation groups:

| Quantity | Golden value |
| --- | --- |
| Σ `baseline_npv` | **−421.16 bn USD** |
| Σ `latesudden_npv` | **−4,401.56 bn USD** |
| Σ shock − baseline, absolute — *the headline risk signal* | **−3,980.39 bn USD** |
| per-company `npv_change` (a **ratio**, `(ls−base)/\|base\|`) | mean −1.3967, median −1.5394, 13 NaN |
| Σ `capex_total` | baseline 9,650.07 bn / late&sudden 9,477.17 bn |

> `npv_change` in the outputs is a **relative ratio**, not a difference. Both are reported
> throughout: the aggregate absolute USD move, and the distribution of the per-company ratio.

**Headline ranking — how much each switch moves the risk signal** (Σ shock−baseline vs golden −3,980.39 bn):

| Rank | Switch | Δ headline | Δ % |
| --- | --- | --- | --- |
| 1 | **A6** retirement off | −1,834.19 bn | **−46.08%** (signal *grows*) |
| 2 | **A4** `price_ramp: false` | +1,434.27 bn | **+36.03%** |
| 3 | **A3** `include_decom_costs: false` | +524.02 bn | +13.17% |
| 4 | **A2** `include_replacement_capex: false` | +88.34 bn | +2.22% |
| 5 | **A5** `stranding_aware_tv: false` | +22.09 bn | +0.55% |
| — | **A1** `ownership_aggregation: sum` | not obtainable (disk) — universe inflates 6.43× in rows, 2.68× in ownership-weighted exposure | |

Note the split between *levels* and the *difference*: A2, A3, A5 and A6 each move the aggregate
NPV levels by hundreds of percent while moving the headline signal by 0.5–13% (A6 excepted),
because they are charged in both pathways and largely cancel. A4 is the reverse — it leaves the
baseline pathway untouched (Δ exactly 0) and moves only the shock side.

---

## Decision table

| id | What it decides | Baseline choice (shipped) | Alternative tested | Measured incremental impact on the golden run | Who argued what | What the choice trades off |
| --- | --- | --- | --- | --- | --- | --- |
| **A1** | How several stakes one company holds in one asset-year are combined | `ownership_aggregation: tier_filter` — select the `ownership_type` rung, then consolidate within it | `sum` — total every tier, direct + equity | **NPV deltas not obtainable.** The full-universe `sum` run reached 17/29 tasks in 43 min (2,588 s) then died: `[Errno 28] No space left on device` writing `asset_trajectories.csv`. Measured the mechanism directly on the full ownership input instead (`filter_companies`, both modes, real `companies_ownerships.csv`, 1,075,973 raw rows = 908,842 equity + 167,131 direct): owner-asset-year rows **167,131 → 1,074,916 = 6.432×**; companies **4,899 → 7,752 = 1.582×**, of which **2,853 are equity-only holders that `tier_filter` drops entirely**; Σ`ownership_percentage` **14,840,331 → 39,768,405 = 2.680×** (mean stake 88.79% → 37.00%). Asset count is identical (21,821) — the inflation is entirely in *how many owners claim each asset*. Absolute outputs scale with the 2.68× ownership-weighted exposure; the 2.2× quoted from the fixture **understates full-universe behaviour by ~3×** | Handover/**Jakub** = tier_filter (tiers are alternative *views* of the same capacity, so summing double-allocates a plant). **Bertrand** = sum every holding, no `ownership_type` key; also TRISK's reading. Owner ruled 2026-09-01: a **parameter**, not a winner; default `tier_filter` | Comparability against the validated baseline and last year's published results, versus lining up with a TRISK run. Two runs on different readings cannot be compared on absolute numbers at all. Also an operational cost the clash report does not mention: on the full universe `sum` is a different class of run — it exhausted available disk after 43 min, ~9× the baseline's 4.6 min before it even failed |
| **A2** | Whether routine capital-maintenance CapEx is charged at all | `include_replacement_capex: True` (2%/yr on installed capacity) | `false` — term off entirely (`main`'s old default) | Σbase **−421.16 → +2,292.74 bn** (Δ **+2,713.90 bn, +644.4%** — portfolio flips value-positive). Σls **−4,401.56 → −1,599.32 bn** (Δ +2,802.24 bn, +63.7%). **Headline −3,980.39 → −3,892.06 bn (Δ +88.34 bn, only +2.22%)**. Σcapex base 9,650.07 → 4,793.11 bn (−50.3%). 78 sign flips (40 −→+, 38 +→−); **4,468/4,865 companies (91.8%) move >10%**; median rel −25.2%. Concentration: SolarCap-PV +157.89 bn (+16.3%), SolarCap-CSP +123.39 bn (+1262.1%), WindCap-Offshore −75.41 bn (−125.3%); fossil barely moves (CoalCap −0.61%, GasCap −2.16%). 256 s, **29/29** | Handover/**Jakub** = charge on *installed* capacity every year (utility convention, EPRI/Lazard), switch ON. **Bertrand** = capitalise a fraction of *growth* only (a flat coal plant costs nothing to keep running); on `main` the switch ships **OFF** | Halves total CapEx and moves both *levels* enormously, but almost cancels out of the *difference* — it is charged in both pathways. Buys a consistent "keeping a plant alive costs money" story alongside continued O&M; costs the ability to read absolute NPV levels as comparable to `main`. Note the impact lands on renewables, not fossil — the opposite of where a transition-risk reader would look for it |
| **A3** | Whether retiring capacity is charged demolition/site-restoration cost | `include_decom_costs: True` (`abs(scrap_usd_per_mw)`, a positive outflow) | `false` — term off entirely (`main`'s old default) | Σbase **−421.16 → +1,717.08 bn** (Δ +2,138.25 bn, +507.7%). Σls **−4,401.56 → −1,739.29 bn** (Δ +2,662.27 bn, +60.5%). **Headline −3,980.39 → −3,456.37 bn (Δ +524.02 bn, +13.17%)**. Σcapex base → 4,856.96 bn, ls → 4,199.74 bn. 106 sign flips, strongly asymmetric (**98 −→+**, 8 +→−); 4,127 (84.8%) move >10%; median rel −24.8%. Concentration: WindCap-Offshore +159.36 bn (+264.8%), SolarCap-CSP +110.11 bn (+1126.3%), CoalCap +108.49 bn (+2.69%), GasCap +73.71 bn (+2.39%). 258 s, **29/29** | Handover/**Jakub** = `abs(scrap)` charged as an outflow, switch ON. **Bertrand** = signed `scrap_usd_per_mw` (arrives negative, so retiring a plant *pays* its owner), switch OFF on `main` | ~6× more of the headline signal than A2 (13.2% vs 2.2%), because retirement is concentrated in the shock pathway rather than symmetric. Turning it off makes the aggregate baseline portfolio value-positive and pushes 98 companies from risk-negative to risk-positive — the asymmetry (98 vs 8) is the tell that this term is doing shock-specific work |
| **A4** | How the late & sudden pathway picks up the target scenario's price surfaces | `price_ramp: True` — linear blend across [2033, 2038] | `false` — hard switch at `shock_year` | Σbase **unchanged (Δ exactly 0)** — the ramp touches only the shock pathway. Σls **−4,401.56 → −2,967.29 bn** (Δ +1,434.27 bn, +32.6%). **Headline −3,980.39 → −2,546.12 bn (Δ +1,434.27 bn, +36.03%)**. Mean `npv_change` **−1.3967 → +0.1004 (flips positive)**; median −1.5394 → −0.8308. **286 sign flips (232 −→+)** — the most of any ablation; 4,218 (86.7%) move >10%; median rel **+49.9%**. Σcapex essentially unchanged (ls −0.18%). Concentration is violent and opposed: **CoalCap +3,028.30 bn (+75.0%)** against **GasCap −2,044.06 bn (−66.3%)**, OilCap −113.55 bn (−60.0%) | Handover/**Jakub** = linear blend; the hard switch hands the shock pathway a near-term price windfall (target prices sit 30–50% above baseline at the shock year), so fossil assets can *gain* value under a climate shock. **Bertrand** = hard switch at `shock_year` | The largest lever on the headline number after A6, and the only one that flips the *sign of the aggregate mean* risk signal. The coal-vs-gas split is the windfall artefact made visible: under the hard switch coal gains 3.0 tn while gas loses 2.0 tn. Blending removes it; the hard switch is the more literal reading of "sudden". The ramp is also what makes D4 bite. 275 s, **29/29** |
| **A5** | Whether terminal value is tiered by stranding, or one perpetuity for every asset | `dcf.stranding_aware_tv: True` — stranded→TV 0, declining-but-profitable carbontech→finite annuity, else perpetuity | `false` — single Gordon-growth perpetuity | Σbase **−421.16 → −1,469.70 bn** (Δ **−1,048.53 bn, −248.96%**). Σls **−4,401.56 → −5,428.00 bn** (Δ −1,026.44 bn, −23.32%). **Headline −3,980.39 → −3,958.30 bn (Δ +22.09 bn, +0.55% — the SMALLEST headline move of any switch)**. Σcapex **identical** to golden in both pathways (terminal value does not touch CapEx). 80 sign flips (58 −→+, 22 +→−); 2,254 (46.3%) move >10%; median rel −0.87%. Concentration: SolarCap-PV +249.41 bn (+25.8%), SolarCap-CSP +126.22 bn (+1291.1%), CoalCap −176.99 bn (−4.4%), GasCap −127.30 bn (−4.1%), OilCap −39.88 bn (−21.1%). 307 s, **29/29** | Handover/**Jakub** = three tiers (Gourdel 2024). **Bertrand** = one Gordon perpetuity | Removing the tiers costs ~1.05 tn on the baseline level and ~1.03 tn on the shock level — and those nearly cancel, so the risk *signal* barely notices. The tiers are therefore doing almost nothing to the headline and a great deal to the levels. Their real function is bounding D3: with tiers off there is no abandonment option, so a permanently loss-making asset takes an unbounded negative perpetuity — which is exactly where the −249% baseline move comes from |
| **A6** | Whether retirement is applied to either pathway (bounds the whole retirement mechanism, incl. the 2039 cliff) | `apply_retirement_baseline: True` **and** `apply_retirement_shock: True` | both `false` | Σbase **−421.16 → +1,733.45 bn** (Δ +2,154.62 bn, +511.6%). Σls **−4,401.56 → −4,081.13 bn** (Δ +320.43 bn, +7.28%). **Headline −3,980.39 → −5,814.58 bn (Δ −1,834.19 bn, −46.08% — the signal gets 46% BIGGER; the only switch that grows it)**. Σcapex base 9,650.07 → 6,939.98 bn, ls 9,477.17 → 7,362.83 bn. 149 sign flips, asymmetric the other way (45 −→+, **104 +→−**); 2,382 (49.0%) move >10%; **median rel exactly 0** — half the universe is untouched. Concentration is broad and non-fossil: GasCap −791.65 bn (−25.7%), WindCap-Onshore −514.23 bn (−39.2%), SolarCap-PV −204.17 bn (−21.1%), HydroCap −181.10 bn (−30.4%), NuclearCap −119.54 bn (−29.8%); **CoalCap only −1.79%**. 270 s, **29/29** | No recorded Jakub-vs-Bertrand clash — the retirement mechanism and its floor are shipped behaviour on both lineages (`methodology_notes.md`, "The retirement floor"). This ablation is a **bound**, not a contested option | Retirement currently *dampens* the measured risk signal by ~46%: switching it off makes the shock look worse, not better. It simultaneously makes the baseline portfolio value-positive. Half of companies are unaffected at all, so the effect is concentrated in the retiring half — and it lands on gas, wind and hydro rather than coal, which is not where a retirement story would be expected to bite |
| **D1** | The 2039 retirement bunching — `eff_retirement` clamped to `alignment_year + 1` (`_allocation_nodes.py:492-499`) | Clamp ON: no asset retires before the transition window closes, so every asset dated to retire ≤2038 bunches into 2039 | No toggle. A6 bounds it | Measured on the golden run, capex_total across both trajectories: **624.59 bn (2038) → 2,754.65 bn (2039) → 615.21 bn (2040)** — a **+341%** one-year spike. Capacity **20,017.5 → 17,854.4 GW, −10.81%** combined; **−12.98%** on the baseline trajectory alone (10,080.0 → 8,771.3 GW). **A6 bound:** spike collapses to **754.66 bn (−72.6%)** and the cliff **inverts to +0.32%** (20,017.5 → 20,080.6 GW). The residual 2039 bump is **shock-side only** (latesudden 377.0 → 499.0 bn while baseline runs smooth 247.6 → 255.7), so it is an `alignment_year` artefact, not retirement | Documented as deliberate in the handover lineage: the floor exists so retirement never removes capacity the shock has not yet had a chance to act on. The Q4-2 correction records that every consumer must apply the same clip — one did not, and was fixed | A single synthetic year absorbs every deferred retirement, so 2039 is not a meaningful year in any output that reads capex or capacity by year. Removing the floor would let the fleet shrink for reasons unrelated to the shock; keeping it concentrates a decade of retirements into one bar. A6 shows ~73% of the spike is the floor's doing and the rest is the alignment year |
| **D2** | Emission-factor forward-fill vs zero-fill (Q3) | ffill on `ASSET_SERIES_KEYS` in `validate_asset_trajectories` (`calculate_asset_earnings/nodes.py:129-133`) before `compute_ops_block`'s `fillna(0.0)` | No ffill — missing EF falls through to `fillna(0.0)` | **The fill is inert on this universe.** Of **52,066** asset series reaching the earnings stage, **0 have a forward-fillable EF gap** (0 fillable rows). Raw stage-1 input is EF-complete: **0 nulls** across 174,568 rows / 21,821 assets. The only EF nulls in `asset_trajectories` are **9,412 rows (0.70%), flat across every year 2025–2050** — i.e. **whole series**, which ffill cannot fill. **All 9,412 are synthetic assets: 181 distinct ids, BiomassCap - w/o CCS (7,748 rows) + OilCap - w/o CCS (1,664 rows).** They are non-renewable, so the renewable-zeroing rule does not claim them, and they reach `fillna(0.0)` | Handover/**Jakub** = ffill on `(asset_id, technology)`. **Bertrand** = no ffill, zero-fill. Shipped = ffill on **Bertrand's stricter** `ASSET_SERIES_KEYS` grain — the report explicitly records this as "a case where your convention is the stricter one and we followed it" | The Q3 decision as framed decides nothing here, and choosing either option changes no number. What actually bites is the **zero-fill fallback** it sits in front of: 181 synthetic biomass and oil top-up assets are priced as emitting nothing and pay **no carbon cost** in either pathway. That is a live modelling choice hiding behind an inert one, and it flatters exactly the technologies a transition shock should penalise |
| **D3** | Perpetuity anchor `final_fcff != 0` vs `> 0` (`calculate_asset_and_company_npv/nodes.py:300`) | `has_terminal_fcff = final_fcff != 0` — a loss-making asset that fails the stranding test takes a **negative** perpetuity | `final_fcff > 0` — floor terminal value at zero | Of 52,066 valuation groups in the golden run: stranded (TV=0) **14,552 (27.9%)**, finite annuity **962 (1.8%)**, perpetuity **16,381 (31.5%)**, no terminal value (`final_fcff == 0`) **20,171 (38.7%)**. **2,699 groups (5.18%) take a negative perpetuity today**, carrying **−292.96 bn** of summed normalised terminal FCFF (capitalised at r−g, so the terminal-value effect is an order of magnitude larger). Split **1,369 late&sudden vs 1,330 baseline** — near-symmetric — and only **5.8% carbontech**. A5 quantifies the interaction: removing the stranding tiers moves the baseline level by **−249%** and the shock level by −23%, i.e. the unbounded negatives land on both sides | Handover/**Jakub** = `!= 0`; an asset losing money at the horizon is worth less than nothing, and flooring at zero flatters the shock world where the losses are. **Bertrand** = `> 0`, explicitly: the positive test "is what keeps a loss-making asset from being handed a negative perpetuity" | The near-symmetric 1,369/1,330 split is evidence *against* the "it flatters the shock world specifically" argument on this data — the negative perpetuities land almost equally on both pathways, so flooring at zero would lift both and the risk signal would barely move. Exposure is bounded while `stranding_aware_tv` is on, because the stranding tier catches the worst cases first; select A5's alternative and the negative perpetuity becomes unbounded. The two decisions must be taken together, not separately |
| **D4** | Ramped rows carry `scenario_type = baseline` (Q2-1) | Ramped pathway keeps the **baseline** scenario name and `scenario_type`, because its surface is a mixture of both | No toggle (a consequence of `price_ramp: True`) | **Proven inert on shipped defaults.** `scenario_type` has exactly **one** distinct value — `baseline` — across all **1,353,716** golden `asset_earnings` rows. `scenario_type` selects the discount rate, so both worlds take `discount_rate_baseline`: **`baseline_discount_rate == latesudden_discount_rate` on all 26,033 asset rows and all 4,878 companies — 0 differ.** Rates vary only by `alignment_type` (0.08 carbontech = 0.07+100bps; 0.065 greentech = 0.07−50bps). **`dcf.discount_rate_shock` is fully inert**, and A4 (`price_ramp: false`) is what makes it live again | Handover/**Jakub** = ramp, labelled `baseline` because no third label exists. **Bertrand** = hard switch, honest labels. Report flags it **DECIDE**: "if you ever set them apart, the ramp will silently neutralise the difference" | A configuration key that reads as live is silently dead: raising `discount_rate_shock` to price transition risk into the rate changes **nothing** under shipped defaults, with no error or warning. Anyone grouping outputs by `scenario_type` also gets a single-valued column. The failure mode is silent in both directions — the key appears to work, and the column appears to discriminate |
| **D5** | *(new finding, not in the clash report)* Ungrouped frame-wide `.ffill()` at `_asset_preparation.py:280-306` | Frame is sorted by `group_cols + ["year"]` then **`.ffill()` is applied to the whole frame, not per group** — `group_cols = [company_id, asset_id, scenario_geography, sector, technology]` | Grouped fill (`groupby(group_cols).ffill()`) | **Leakage is structurally possible and does occur, but only on metadata.** A frame-wide ffill crosses an asset-series seam whenever a group's *first* row is NaN. Horizon-extension rows are always trailing, so they correctly inherit their own asset — the exposure is leading gaps only. Measured on the staged input (174,568 rows / 21,821 assets): `emission_factor` **0**, `capacity_factor` **0**, `asset_name` **0**, `country_name` **0** — no leakage on anything numerically load-bearing. But `latitude` **24 NaN rows across 3 assets, all leading**; `longitude` **24 / 3, all leading**; `country_iso2` **120 / 15, all leading**. So **18 distinct assets currently inherit a neighbouring asset's geographic metadata**, and `country_iso2` leaks while its paired `country_name` does not | Not raised by either lineage — surfaced by this session's ablation work | Zero NPV impact today, because the columns that leak are reporting metadata and the columns that matter happen to be complete. It is a **latent** defect: the first input arriving with a leading-NaN `capacity_factor` or `emission_factor` silently adopts an unrelated asset's value, with no warning, and the failure would be invisible in every output. The cost of the current form is that its safety is a property of the data, not of the code |

---

## D2 resolved 2026-09-02 — synthetic top-ups inherit their fleet's emission factor

The owner took D2's real question — not the inert ffill-vs-zero-fill choice, but
the zero-fill fallback behind it — and ruled on it. The 181 synthetic assets no
longer burn free.

**The rule as shipped.** Per synthetic asset and per year, the emission factor is
the **capacity-weighted mean EF of the company's own real assets in the same
(sector, technology, scenario_geography) group**. Where the company has no real
asset in that group the fallback chain runs: (1) all real assets in that
**technology × geography**, (2) the **technology** as a whole, (3) only then zero,
logging a WARNING naming the technology. A year in which the weighting basis
carries no capacity — every real asset in the group retired or standing at
zero — takes the group's **nearest available year** (forward-fill, then
backward-fill, within the constructed EF series).

Implemented in `combine_asset_allocation_branches`
(`allocate_company_trajectories_to_assets/nodes.py`), immediately after the merge
that leaves synthetics with a null EF — the same place the pre-existing renewable
zero-fill sits. That renewable rule **runs first and is untouched**: renewable
synthetics keep their explicit zero rather than inheriting one, so the change
lands only on the population D2 named.

**One interpretive choice, recorded.** The spec says "weight by the same year's
capacity" without naming which capacity. The shipped weight is **BAU capacity**
(`asset_baseline_trajectory`), not post-shock capacity. The EF column is
single-valued per asset-year and is read by both pathways, so weighting it by a
shocked capacity would make the *baseline's* carbon cost a function of the shock.

**Measured impact — fixture slice.** The committed fixture holds 52 synthetic
`OilCap - w/o CCS` rows, which now carry **EF 0.842126** inherited from the real
OilCap fleet. One pinned value moves: company `CN_6488161088428600082`'s
late-and-sudden NPV, **−71,108,467,857.10 → −71,117,122,653.48**, a change of
**−8,654,796.38 (−0.0122%)**. Every baseline pin, every asset-level pin, both row
counts and all three FCFF pins are unchanged.

**Only the shock pathway can move.** A synthetic top-up's baseline capacity is
zero by construction (`asset_baseline_trajectory = 0` at creation), so it has no
baseline production for the new emission factor to act on. The adjustment
therefore widens the shock-minus-baseline gap rather than shifting both sides —
which is the direction D2 argued was missing.

**Full-universe delta: not yet measured.** Re-running `--env full --tags altrisk`
and re-pinning the golden snapshots is blocked on the same constraint that killed
A1 (see *Method, caveats, and run failures* below): the volume now sits at
**~0.42 GB free** and `data/07_model_output` needs an estimated **~1.8 GB**
(≈0.50 GB `asset_earnings`, ≈0.52 GB `asset_trajectories`, ≈0.49 GB
`yearly_npv_trajectories`, plus the company-level tables). The golden snapshots in
`tests/golden/snapshots/` are still pinned to `015a861` and therefore **predate
this change** — `test_outputs_match_golden` will report drift on the affected
technologies until the run is done and the baseline re-pinned with
`pin_golden.py --require-sha <run sha>`.

---

## Detail: A6 and the 2039 capex spike

Capex (bn USD, both trajectories summed) and total capacity (GW):

| Year | Golden capex | Golden cap GW | Golden cap %chg | **A6** capex | **A6** cap GW | **A6** cap %chg |
| --- | --- | --- | --- | --- | --- | --- |
| 2037 | 611.04 | 19,567.55 | +2.36% | 611.04 | 19,567.55 | +2.36% |
| 2038 | 624.59 | 20,017.53 | +2.30% | 624.59 | 20,017.53 | +2.30% |
| **2039** | **2,754.65** | **17,854.39** | **−10.81%** | **754.66** | **20,080.61** | **+0.32%** |
| 2040 | 615.21 | 18,189.09 | +1.87% | 487.27 | 20,632.37 | +2.75% |
| 2041 | 585.90 | 18,634.51 | +2.45% | 488.60 | 21,307.58 | +3.27% |

**Answer to the A6 sub-question: yes, the 2039 spike disappears** — 2,754.65 → 754.66 bn (−72.6%), and the capacity cliff is eliminated entirely (−10.81% → +0.32%). The residual 2039 bump lives **only in the shock pathway** (late&sudden capex 377.0 → 499.0 bn while baseline runs smoothly 247.6 → 255.7 bn), which dates it to `alignment_year = 2038` rather than to retirement.

---

## Method, caveats, and run failures

**Comparator provenance.** Mid-session `pandas.read_parquet` began failing — the golden parquets were readable at 11:51 and not at 12:03. Cause identified: a **concurrent session committed `486e654` at 12:01:36**, which moves `pyarrow` from the main dependency group to the dev group ("Runtime code is CSV-only"); a `uv sync` then removed it from `.venv`. Rather than mutate the project environment, comparisons run against **byte-identical CSV copies** of the golden run's own `data/07_model_output` outputs, captured before the first ablation overwrote them. The comparator was validated against the untouched golden outputs first: **max abs diff exactly 0.0** on `baseline_npv`, `latesudden_npv` and `npv_change`, and the CSV reference reproduces the parquet aggregates to 7 significant figures.

**HEAD moved during the session — the results are still valid.** The brief pinned this worktree at `d9f37da`; it now sits at `486e654`, two commits later (`c0f2f15` docs, `486e654` the Dependabot/dev-group fix above). Neither was made by this session. **`git diff d9f37da..HEAD -- src/ conf/` is empty**: the model code and every parameter file are byte-identical to the pinned baseline commit, so all ablations below were run against the same model the golden snapshots were pinned from. The working tree is clean (`git status --porcelain` empty), nothing was committed or pushed, and the golden snapshots retain their original 11:06 timestamps.

**kedro `--params` caveat (cost one failed run).** `--params dcf.stranding_aware_tv=false` **replaces the entire `dcf` block** rather than deep-merging into it, so all 11 sibling `dcf` keys vanish and the run dies in 2 s with `ValueError: Pipeline input(s) {'params:dcf.terminal_value.g_real_green', ...} not found in the DataCatalog`. `KedroContext.params` uses `_update_nested_dict`, which *does* deep-merge, but the merge does not survive the config-loader path for this key. **A5 therefore respecifies the whole `dcf` subtree** with only `stranding_aware_tv` flipped. Flat top-level keys (A2, A3, A4, A6) are unaffected. Anyone overriding a nested key on this kedro version (0.19.15) must pass its whole parent block.

**A1 is disk-blocked, not logic-blocked — and could not be subset either.** `ownership_aggregation=sum` ran 43 min (2,588 s), reached 17/29 tasks, and died writing `asset_trajectories.csv` with `[Errno 28] No space left on device`; the volume sits at 99–100% with ~1–2 GiB free and `sum` inflates every intermediate. The intended fallback — re-running both arms on a 400-company stratified subset — proved **impossible without modifying the repo**: kedro's `--params` splits its value on commas (`split_string`) before OmegaConf parses it, so a multi-element `company_ids=[A,B,C]` list cannot be expressed on the command line at all (it fails with ``Item `B` must contain a key and a value``), and the only alternatives were writing a new `conf/` environment or a `--conf-source` tree — both excluded by the read-only-to-git constraint.

**What A1 was measured with instead.** `filter_companies` was called directly, in-process, on the real full `companies_ownerships.csv` under both modes. This is a **full-universe** measurement of the switch's mechanism, not a sampled proxy, and it captures the effect a company-id subset structurally could not have seen: `sum` *adds* 2,853 equity-only companies that `tier_filter` drops, so any subset selected by `company_id` from the golden (`tier_filter`) run would have excluded that entire population by construction. What it does **not** give is NPV deltas — A1's rows in the ranking table above are therefore blank, and the 6.43× / 2.68× figures describe the input universe, not the valuation. Absolute outputs scale with ownership-weighted exposure (2.68×) only to the extent that NPV is linear in stake size, which it is for revenue and cost but not through the terminal-value tiers.

**Scope note.** A2, A3, A4, A5 and A6 are **full-universe runs compared directly against the golden baseline** — no subsetting, no scaling, no caveat beyond the comparator provenance above. Only A1 lacks a run-based number.

**Run ledger.** A2 256 s **29/29** ✓; A3 258 s **29/29** ✓; A4 275 s **29/29** ✓; A5 307 s **29/29** ✓ (second attempt); A6 270 s **29/29** ✓ — all compared. A1 failed at 17/29 after 2,588 s (disk exhaustion). A5's first attempt failed at 0/29 in 2 s (params defect above) and a later re-run was killed mid-flight when the machine slept; the run reported here is a clean 29/29. Two infrastructure interruptions (a network drop and a machine sleep) killed in-flight runs; those were restarted rather than reported as model behaviour.

**`npv_change` NaN count is stable at 13** in the golden run and in every completed ablation — the zero-baseline-NPV companies, correctly `NaN` rather than `±inf`.
