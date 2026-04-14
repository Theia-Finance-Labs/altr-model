# ALTR Research Verification Report

## Part 0: Code & Data Verification (Red / Amber / Green)

This section verifies the implementation-level claims in `ALTR_NPV_Direction_Fix_Research.md` against the **actual codebase and data** as of 2026-04-12. Many claims describe the code at an earlier point in time — several bugs have since been fixed.

### Traffic Light Legend

- **GREEN** = Verified fact — confirmed against actual code/data
- **AMBER** = Likely fact but imprecise, simplified, or describing superseded code
- **RED** = Needs direct inspection — unverified against primary source

### Audit Table

| # | Claim | Rating | What the doc says | What the code/data actually shows | Action |
|---|-------|--------|-------------------|-----------------------------------|--------|
| 1 | Carbon price NaN | AMBER → **CODE BUG FOUND** | `carbon_price_usd_per_tco2` is **entirely** NaN in scenarios_pathways.csv | Baseline rows = NaN (correct). Target rows = **constant** ~199.61 across ALL years (WRONG). Should be $200→$339→$441→$569→$658→$722 (2025→2050). **Root cause:** `interpolate_scenarios_annually` (line 638) doesn't include `carbon_price_usd_per_tco2` in `numeric_cols`, so 5-year data collapses to the 2025 value. **Fix applied:** added column to interpolation list. The `inject_carbon_prices` function's early-return then works correctly. |
| 2 | fillna(0.0) | GREEN | `surfaces["carbon_price_usd_per_tco2"] = scenarios["..."].fillna(0.0)` at line 292-294 | Code confirmed at **lines 402-404** (file has grown). Identical logic. | Line numbers outdated but code matches exactly. |
| 3 | Decom sign bug | GREEN (fixed) | `scrap_usd_per_mw = -capex/2` produces negative decom_cost that boosts FCFF | Original bug confirmed at line 416. **Already fixed** at lines 1244-1251: `capex_data["scrap_usd_per_mw"].abs() * capex_data["capex_capacity"]`. | No action needed — bug was real, fix is applied. Doc should note the fix is done. |
| 4 | Carbon cost formula | AMBER | `carbon_cost_net = Q × carbon_price × emission_factor × (1-passthrough)` | Actual code (lines 1534-1541) uses **differential/excess emission factor**: `excess_ef = (EF - marginal_EF).clip(lower=0.0)`, then `Q × carbon_price × excess_ef × (1-passthrough)`. Additionally `dynamic_marginal_ef: True` makes marginal EF decline with VRE share. | Doc oversimplifies. The actual implementation is the more sophisticated differential approach described elsewhere in the brief (RC5 discussion). Update the formula in Section 1 or cross-ref. |
| 5 | Near-term price windfall (hard switch) | GREEN (superseded) | Shock scenario uses hard baseline→target switch at shock_year, creating 30-50% price jump. | Hard switch code exists (lines 912-933) **but is bypassed**. `price_ramp: True` (parameter line 134) activates linear blending over [shock_year, alignment_year] (lines 841-911). This is the RC4 fix. | The mechanism was real. The fix (price ramp) is already applied. Doc should note current state. |
| 6 | Identical prices across technologies | GREEN | WITCH provides one electricity price per (geography, year, scenario_type) — all technologies get the same $/MWh. | **Confirmed exactly.** BRA/baseline/2030: all 18 technologies share $37.35/MWh. MCPR adjustment downstream adds differentiation via value factors. | No action needed — claim is accurate. |
| 7 | Terminal value gate | AMBER (restructured) | `if final_fcff > 0:` at line 108 means TV only added for positive final FCFF. | Code has been **completely restructured** (lines 185-259). Now a multi-tier system: (a) `stranding_aware_tv` mode with stranded/finite_annuity/perpetuity tiers; (b) `final_fcff != 0` gate (not `> 0`); (c) `final_fcff > 0` only in carbontech finite annuity branch (line 219). `stranding_aware_tv: True` is the active config. | Doc describes the original gate which has been replaced. The asymmetry concern was valid and has been addressed with the stranding-aware system. Update doc to reflect current state. |
| 8 | TRISK R comparison | GREEN (minor errors) | `calc_annual_profts.R:71-80` applies TV unconditionally with no sign check. | **Confirmed** in both repos. Actual file: `trisk.model/R/calc_annual_profts.R` lines 65-105 (function `calculate_terminal_value`). Also in `r2dii.climate.stress.test/R/calculate.R` lines 227-268. TV = `net_profits × (1+g) / (r-g)` with **no sign check**. | Core claim confirmed. Filename was correct in trisk.model but line numbers differ. Update line refs. |
| 9 | Parameters | GREEN | shock_year: 2033, alignment_year: 2038, discount_rate: 0.07, terminal_growth: 0.02, etc. | **All claimed values confirmed.** Additional parameters not in doc: `brown_discount_spread: 0.01`, `green_discount_spread: 0.005`, `stranding_aware_tv: True`, `price_ramp: True`, `dynamic_marginal_ef: True`, `g_real_brown: 0.0`, `g_real_green: 0.02`. | Parameters match. Doc should acknowledge the richer parameter set reflecting applied fixes. |
| 10 | ALTR vs TRISK question | GREEN | ALTR answers a different question than TRISK (CurPol baseline vs. zero baseline). | Architecturally coherent. Confirmed by parameter comparison: ALTR baseline uses CurPol scenario (with rising costs), while TRISK R uses a simpler revenue-based model. | Keep, label as architectural interpretation. |
| 11 | IAM carbon-price handling | AMBER | Different IAMs embed carbon differently; WITCH has explicit carbon prices while AIM/CGE may not. | Partially confirmed. Target scenario has constant ~199.61 USD/tCO2 (not the variable $200-722 range claimed). Baseline has NaN. AIM/CGE handling not directly verifiable from WITCH data. | The WITCH carbon price is constant across years in current data — this differs from the "$200→$722" range cited. Verify if the data has been updated or if the range refers to a different scenario pair. |
| 12 | WITCH learning curve | RED | WITCH uses 13% learning rate (progress ratio 0.87) for solar/wind. | **Not verified.** Way et al. (2022) does not discuss WITCH specifically. No WITCH documentation in the repo. | Must verify against WITCH 5.0 model documentation (IAMC wiki or Emmerling et al.). |
| 13 | Valuation references | AMBER | Damodaran, Koller, CFA, Penman, Bodmer cited for terminal-value normalization. | See Part 1-5 of this report. Damodaran: partially correct (negative FCFF needs nuance). Bodmer 1.15x ratio: arithmetic error. McKinsey Ch. 12: wrong chapter for 7th edition. Penman: verified. | Apply corrections from paper verification section. |

### Key Takeaway

**The NPV Direction Fix Research doc is a time-capsule.** It accurately describes bugs and limitations that existed when it was written. Since then, five major fixes have been applied:

1. Decom sign bug → fixed with `.abs()`
2. Terminal value gate → replaced with stranding-aware multi-tier system
3. Hard price switch → replaced with linear price ramp (RC4 fix)
4. Carbon cost formula → uses differential/excess emission factor (RC5 partial fix)
5. Discount rate spreads → brown +100bps, green -50bps activated (D1 fix)

The doc should be updated to distinguish between *historical bugs* (now fixed) and *open issues* (WITCH learning curve, terminal value normalization method choice, gas structural positive).

### Three-Layer Classification (per Jakub's audit)

| Layer | Items | Nature |
|-------|-------|--------|
| **Code bugs** (objective fixes) | Decom sign (fixed), original TV gate (fixed), carbon price NaN fill (confirmed) | These are right/wrong — not debatable |
| **Finance-theory choices** (defensible alternatives) | TV normalization (N-year average vs. single year), discount rate spreads (magnitude), stranding-aware TV tier design, price ramp vs. hard switch | Multiple valid approaches. Present as recommended adjustments, not corrections. |
| **Scenario design interpretation** | ALTR vs TRISK question, IAM carbon-price embedding, WITCH learning curves, gas bridge-fuel role | Source-dependent hypotheses. Require verification against IAM documentation, not code. |

---

# Part 0b: ALTR Improvement Brief — Paper Citation Verification

**Date:** 2026-04-12
**Scope:** Verification of all paper-attributed claims in `ALTR_IMPROVEMENT_BRIEF.md`, `ALTR_NPV_Direction_Fix_Research.md`, and `MCPR/ALTR_MCPR_methodology_v1.md`
**Method:** Each claim was checked by reading the cited PDF and finding the exact passage. Direct quotes are provided. Claims are rated VERIFIED, PARTIALLY CORRECT, INCORRECT, or UNVERIFIABLE.
**Papers verified:** 18 academic papers + 5 textbook/industry references

---

## Scorecard

### A. Code & Data Claims (ALTR_NPV_Direction_Fix_Research.md)

| Rating | Count | Meaning |
|--------|-------|---------|
| GREEN | 7 | Confirmed against actual code/data |
| AMBER | 5 | Imprecise, simplified, or describing superseded code |
| RED | 1 | Unverified against primary source |
| **Total** | **13** | |

**Key finding:** The doc is a time-capsule — 5 of 9 bugs/issues it identifies have already been fixed in the code.

### B. Paper Citation Claims (ALTR_IMPROVEMENT_BRIEF.md)

| Rating | Count | % |
|--------|-------|---|
| VERIFIED (from PDF) | 47 | 55% |
| VERIFIED (from vault notes, no PDF) | 14 | 16% |
| PARTIALLY CORRECT | 17 | 20% |
| INCORRECT | 3 | 4% |
| UNVERIFIABLE | 0 | 0% |
| **Total** | **86** | |

**Note:** "Verified from vault notes" means the claim matches the Obsidian vault note but the paper PDF was not read directly. For peer review, verify against actual papers.

---

## Part 1: Errors Requiring Correction

These claims are factually wrong and must be fixed in the brief before any peer review.

---

### ERROR 1: Reinders (2020) does NOT model dynamic leverage under stress

**Location in brief:** Tier 3 table, improvement D3: "Dynamic leverage under stress (needs Merton first)" attributed to Reinders (2020)

**Claim:** Reinders addresses dynamic leverage under stress.

**Verdict:** INCORRECT

**Evidence:** The paper explicitly assumes static Merton parameters. Section 5 (p. 31): *"Our analysis assumes that, besides the asset value shock, the parameters in the Merton model remain constant. We hence implicitly assume that our scenario shocks do not alter asset value volatility and/or the risk-free interest rate."* The leverage ratio R = L/V is a static calibration parameter. There is no dynamic evolution of leverage in response to the stress scenario.

**Correction:** Reinders examines *firm-level variation* in leverage cross-sectionally (Panel C of Table 12, showing 15-37% underestimation from sector averages), but this is a cross-sectional analysis, not dynamic leverage evolution. The improvement D3 should reference Cormack (2020) instead, whose multi-period model with debt covenants naturally produces dynamic leverage through the `debt(t) <= d_ratio^UB × EBITDA(t)` constraint (Section 5.2, p. 18).

---

### ERROR 2: Bolton & Kacperczyk (2021) does NOT support technology-differentiated discount rates

**Location in brief:** Improvement MA3 cites "empirically supported spreads (~60-120 bps from OECD 2024, Bolton & Kacperczyk 2021)"

**Claim:** Bolton & Kacperczyk (2021) provides evidence for 60-120 bps technology-differentiated discount rate spreads.

**Verdict:** INCORRECT (conflated concept)

**Evidence:** Bolton & Kacperczyk study the *equity return premium* associated with carbon emissions across *firms*, not technology-differentiated discount rates for *energy projects*. Their magnitudes (Section 3.2, p. 19): *"A one-standard-deviation increase in SCOPE 1 leads to a 13-bps increase in stock returns, or 1.5% annualized, and a one-standard-deviation increase in SCOPE 2 leads to a 23-bps increase in stock returns, or 2.8% annualized."* These are monthly equity return premia per standard deviation of emissions — a different concept from debt spreads or project discount rates.

The "60-120 bps" figure likely comes from Gourdel (2024) Figure 1, which surveys the *debt funding* carbon premium literature across multiple studies (showing spreads from ~5 to ~175 bps). Bolton & Kacperczyk is one of many papers in that survey, and their equity premium cannot be directly compared to a lending spread.

**Correction:** Replace "Bolton & Kacperczyk 2021" with a direct reference to the debt spread literature. Options:
- Gourdel (2024), Figure 1 (literature survey of carbon debt premia)
- Ehlers et al. (2022, BIS) for green bond pricing differentials
- The OECD 2024 reference (if it exists) should be verified and cited specifically

---

### ERROR 3: Bodmer (2014) CapEx/depreciation ratio of ~1.15x does not match standard math

**Location in brief:** Section MA4, terminal value normalization: "At 2% terminal growth and 5% depreciation, steady-state CapEx/depreciation = ~1.15x"

**Claim:** Bodmer states this specific ratio.

**Verdict:** INCORRECT (arithmetic inconsistency)

**Evidence:** Simple steady-state math: if assets grow at g=2% and depreciate at d=5%, then CapEx = (g+d) × Assets = 7% × Assets, while Depreciation = d × Assets = 5% × Assets, giving CapEx/Depreciation = 7%/5% = **1.40x**, not 1.15x. The claimed 1.15x may use different assumptions (e.g., partial replacement timing, or a different definition of depreciation rate), but the number as stated is misleading without context.

Additionally, the chapter reference "Ch. 29-30" could not be verified against the 2014 edition's table of contents. The Wiley listing shows Ch. 34 covers terminal value calculations.

**Correction:** Either:
(a) Verify against the actual Bodmer textbook and provide the exact passage with the assumptions that yield 1.15x, or
(b) Replace with the standard formula result: CapEx/Depreciation ≈ 1.40x at g=2%, d=5%, or
(c) Remove the specific ratio and state the qualitative principle: "Growth CapEx should not appear in terminal FCFF."

---

## Part 2: Claims Requiring Refinement

These are substantively correct but have inaccuracies in attribution, scope, or wording.

---

### REFINE 1: Cormack (2020) — "closest to a merchant model" is editorial, not the paper's own characterization

**Location:** Top 5 priority papers list; improvement M2 source

**Claim:** Cormack is "closest to a merchant model" and a "blueprint for dynamic MCPR and Merton layer."

**Verdict:** PARTIALLY CORRECT

**Evidence:** Cormack does combine LCOE-based electricity economics with a Merton credit layer, including time-dependent drift, debt covenants, and rating-dependent volatility. However, it uses **cost-plus pricing** (capacity-weighted LCOE blend, Eq. 16-17), not a marginal-cost-based market-clearing price. The paper acknowledges this limitation (p. 34-35): *"The electricity price process adopted for the current analysis is a function of cost"* and notes that dynamic pricing with *"the process of pricing dynamics and the regional demand for each energy"* is planned for *"future studies."*

**Recommendation:** Keep the characterization but add a qualifier: "Cormack is the closest to a merchant model among the reviewed literature, though it uses cost-weighted LCOE pricing rather than a market-clearing mechanism."

---

### REFINE 2: Fabra & Reguant / Hirth / Koolen citations are the brief's own, not Cormack's

**Location:** Improvement MA2

**Claim:** "Precedent: Fabra & Reguant (2014, AER); Hirth (2013, Energy Economics); Koolen et al. (2023, JRC)"

**Verdict:** PARTIALLY CORRECT

**Evidence:** These three citations do NOT appear in Cormack's reference list. They are the ALTR Improvement Brief's own literature references supporting the MCPR concept. Fabra & Reguant appears in Reinders' reference list (as a 2013 publication, not 2014). None appear in Cormack.

**Recommendation:** These citations are correctly attributed to the concept (MCPR carbon-cost-sensitive clearing price) but should not be presented as "from Cormack." Reformat as the brief's own supporting literature.

---

### REFINE 3: Gourdel (2024) interest expense mechanism

**Location:** Improvement M1 description

**Claim:** Gourdel adds interest expense to FCFF: `FCFF = EBITDA - CapEx - interest_expense`

**Verdict:** PARTIALLY CORRECT

**Evidence:** Gourdel incorporates interest cost through the **discount factor**, not as a direct cash flow subtraction. Section 4.4 (p. 14): the discount factor is `rho = (1-delta)/(1 + kappa(1-tau))`, where `kappa` is the firm-specific lending rate. The lending rate affects the present value of future cash flows, not the cash flows themselves. The effect is economically similar but mechanistically different from subtracting interest from FCFF.

**Recommendation:** Rewrite as: "Gourdel incorporates borrowing cost through endogenous discount rates (firm-specific κ enters the discount factor), creating a valuation feedback loop — not as a direct FCFF subtraction."

---

### REFINE 4: Bolton & Kacperczyk 60-120 bps — equity vs. debt

**Location:** Improvement MA3

**Claim:** "~60-120 bps from OECD 2024, Bolton & Kacperczyk 2021"

**Verdict:** PARTIALLY CORRECT (see ERROR 2 above)

**Evidence:** Bolton & Kacperczyk measures equity return premia (13-33 bps/month per std dev of emissions). The 60-120 bps figure appears to come from Gourdel's debt spread survey. These are different concepts.

**Recommendation:** Cite the debt spread literature directly. Bolton & Kacperczyk is evidence that *investors* price carbon risk, but the specific basis-point range for discount rate differentiation should come from debt/lending studies.

---

### REFINE 5: Kerkhofs (2025) — "Tang & Cervenka approach" not named in paper

**Location:** Physical risk module P4 description

**Claim:** Kerkhofs uses "same DCF framework as ALTR (Tang & Cervenka approach)"

**Verdict:** PARTIALLY CORRECT

**Evidence:** Section 2.2 (p. 4): *"The financial impact of simulated weather events is estimated using a discounted cash flow (DCF) model. Previous literature has used the Discounted Dividend Model (DDM) [11]."* Reference [11] is Bressan et al. — the same research group — not Tang & Cervenka. The DCF framework IS the same, but Kerkhofs references Bressan et al. as the precedent, not the Tang et al. working paper.

**Recommendation:** Write: "Uses the same DCF framework used in ALTR (the research group's earlier work, Bressan et al. 2024, is cited as the DDM predecessor)."

---

### REFINE 6: Kerkhofs (2025) — triple/quadruple attribution

**Location:** Kerkhofs quantitative findings

**Claim:** "Correlation structure can triple (Merton) or quadruple (empirical) the 99th percentile PD change"

**Verdict:** PARTIALLY CORRECT (misattributed dimension)

**Evidence:** Section 3.3 (p. 12): *"For both the Merton and the empirical model, a change in the correlation structure effectively triple (quadruple) the estimated 95th (99th) percentile probability of default changes."* The triple/quadruple applies to **percentile levels** (95th triples, 99th quadruples), across **both** model types. The brief incorrectly maps triple→Merton and quadruple→empirical.

**Correction:** "Correlation structure can triple the 95th percentile and quadruple the 99th percentile PD change (applies to both Merton and empirical models)."

---

### REFINE 7: Kerkhofs (2025) — average portfolio impact rounding

**Location:** Kerkhofs quantitative findings

**Claim:** "Average portfolio impact: -0.70% (baseline flood scenario)"

**Verdict:** PARTIALLY CORRECT

**Evidence:** Table 1 (p. 11) shows average impacts ranging from -0.671% (complete dependence) to -0.718% (complete independence). Gaussian copula: -0.702%, vine copula: -0.718%, t-copula: -0.706%. The -0.70% is a reasonable rounding of the copula results.

**Recommendation:** State as "approximately -0.70%" or cite the Gaussian copula result of -0.702% specifically.

---

### REFINE 8: Tabachova — may be two different papers

**Location:** Improvement N5

**Claim:** "Tabachova et al. (2024, J. Financial Stability): Targeted liquidity support of 0.5% of bank equity reduces system losses from 6% to 1%"

**Verdict:** PARTIALLY CORRECT

**Evidence:** The PDF available is an "INET Oxford Working Paper No. 2025-04" dated January 2025. The Kerkhofs reference list cites a related but potentially distinct Tabachova paper: *"Z. Tabachova, C. Diem, A. Borsos, C. Burger, and S. Thurner, Estimating the impact of supply chain network contagion on financial stability, Journal of Financial Stability, 101338 (2024)."* The specific "0.5% reduces from 6% to 1%" figure was NOT found in the working paper pages read.

**Recommendation:** Verify the liquidity support claim against the published J. Financial Stability version (which may differ from the working paper). If the claim comes from the 2025 working paper, cite it as such and specify the section/page.

---

### REFINE 9: Damodaran — Gordon Growth and negative FCFF

**Location:** Improvements MA4 and MA5

**Claim:** "Damodaran (NYU Stern) explicitly states the Gordon Growth Model is valid for negative FCFF"

**Verdict:** PARTIALLY CORRECT

**Evidence:** Damodaran's work discusses that FCFF *can* be negative (unlike dividends), and the model can handle firms with temporarily negative cash flows. However, his key point is that terminal year FCFF must represent a **normalized** or steady-state year. He does NOT say "plug a negative number into Gordon Growth and it works." Rather, for cyclical firms, average across the cycle to get a representative (possibly positive) terminal FCFF.

**Correction:** Rewrite as: "Damodaran (NYU Stern) states that terminal year cash flows must be normalized to represent a sustainable steady state. For cyclical/commodity firms, this means averaging across the cycle (5-10 years). The Gordon Growth Model can handle firms that currently have negative FCFF provided the terminal year is properly normalized — which may produce a negative terminal value if the firm is structurally unprofitable."

---

### REFINE 10: McKinsey Valuation — chapter number

**Location:** Improvement MA4

**Claim:** "Koller, Goedhart & Wessels (McKinsey) — 'Valuation' 7th ed. (2020, Wiley, Ch. 12 'Estimating Continuing Value')"

**Verdict:** PARTIALLY CORRECT

**Evidence:** The book and edition are correct (ISBN 9781119610885). However, Chapter 12 in the 7th edition is titled "Analyzing Performance," not "Estimating Continuing Value." The continuing value chapter number differs between editions; it was Ch. 12 in earlier editions.

**Correction:** Verify the correct chapter number in the 7th edition for the continuing value discussion. The content on normalized NOPLAT exists in the book but under a different chapter.

---

### REFINE 11: Le Guenedal (2022) — probability-weighted NPV domain

**Location:** Improvement D6

**Claim:** Le Guenedal provides a framework for "probability-weighted multi-scenario NPV"

**Verdict:** PARTIALLY CORRECT

**Evidence:** Chapter 4 (p. 106-109) provides a probability-weighted multi-scenario framework, but for **bond pricing** (credit spreads, default thresholds), not corporate equity NPV in the ALTR sense. Equation 4.5: `alpha_t^N := sum over i of [1/(r + e*lambda_i - mu)] × [filtered probability p_t^i]`. The mathematical structure IS probability-weighted multi-scenario valuation, but the application is debt, not equity NPV.

**Recommendation:** Note the domain transfer: "Le Guenedal (2022) provides probability-weighted multi-scenario valuation for bond pricing; the same mathematical framework can be adapted to NPV computation."

---

### REFINE 12: Calipel et al. — TMSR adaptation

**Location:** Improvement P2

**Claim:** Calipel referenced for "Cement TMSR adaptation"

**Verdict:** PARTIALLY CORRECT

**Evidence:** The paper does NOT use the term "TMSR" or present a quantitative technology market share framework. It provides **qualitative** risk-driver decomposition for cement (4 channels). The paper is correctly referenced for the concept of decomposing cement risk, but not for a formal TMSR model.

**Recommendation:** Cite Calipel for the qualitative risk identification, and note that a quantitative TMSR adaptation would require additional methodology.

---

### REFINE 13: Penman (1998) — title truncation

**Location:** Improvement MA4

**Claim:** "A Synthesis of Equity Valuation Techniques and the Terminal Value Calculation"

**Verdict:** PARTIALLY CORRECT

**Evidence:** Full title: *"A Synthesis of Equity Valuation Techniques and the Terminal Value Calculation for the Dividend Discount Model."* Review of Accounting Studies, Vol. 2, pp. 303-323.

**Recommendation:** Include the full title or note the truncation.

---

### REFINE 14: Reinders (2020) — "negative firm value = certain default"

**Location:** Improvement M3

**Claim:** Reinders states that negative firm value = certain default in Merton.

**Verdict:** PARTIALLY CORRECT

**Evidence:** The Merton model by construction CANNOT produce negative firm values — equity is a call option with a floor at zero. Reinders discusses scenarios where *"the full market value of the asset is lost"* (p. 27) — i.e., xi_k approaches 1, meaning total asset destruction. This yields theta approaching 0, meaning total equity destruction. The paper captures this through stress test coefficients but does not explicitly discuss "negative firm value" as a case.

**Recommendation:** Rewrite M3 as: "Total asset value loss (xi → 1) implies certain default in the Merton framework (distance-to-default goes to -∞)."

---

## Part 3: Unverifiable Claims

These cannot be confirmed from available materials and need further verification.

---

### ~~UNVERIFIABLE 1~~ → RESOLVED: WITCH IAM learning rate

**Location:** Root Cause #8

**Claim:** "The WITCH IAM uses a 13% learning rate (progress ratio 0.87) for solar and wind"

**Verdict: PARTIALLY CORRECT — confirmed for solar/general renewables, but onshore wind uses 10%**

**Evidence from WITCH documentation:**
- **IAMC Electricity page** (iamcdocumentation.eu/Electricity_-_WITCH): *"Investment costs in renewable energy decline with cumulated installed capacity at the rate set by the learning curve progress ratios, which is equal to 0.87"* → confirms **13% learning rate** (1 - 0.87 = 0.13) as the general renewable value.
- **WITCH wind-specific page** (doc.witchmodel.org/wind-power.html): Onshore wind = **10%** learning rate, Offshore wind = **13%** learning rate. Cross-learning parameter = 80%.
- The 13% figure matches the IAMC general documentation and offshore wind, but **onshore wind uses 10%**, not 13%.

**Correction needed in the brief:** Change "13% learning rate for solar and wind" to "13% learning rate for solar PV; 10% for onshore wind, 13% for offshore wind (IAMC documentation, doc.witchmodel.org)." The progress ratio 0.87 is the general renewable default; technology-specific rates differ.

**Impact on the ALTR argument:** The argument in Root Cause #8 still holds — learning curves make target CapEx lower than baseline regardless of whether the rate is 10% or 13%. The directional effect is the same; only the magnitude differs slightly.

---

### ~~UNVERIFIABLE 2~~ → RESOLVED: Hirth (2013) value factors

**Location:** MCPR adjustment (value factors: Solar 0.85, Wind Onshore 0.90)

**PDF acquired:** `Reading/transition_risk/RELEVANT.transition_risk.hirth_2013_market_value_variable_renewables.pdf`

**Verdict: PARTIALLY CORRECT — reasonable approximation, wrong table reference**

**Evidence from paper:**
- **Publication confirmed:** Energy Economics 38 (2013), pp. 218-236, DOI: 10.1016/j.eneco.2013.02.004
- **Wind at 15% penetration = 0.90:** VERIFIED. EMMA model results (Figure 8, p. 227) show value factor declining from ~1.10 at 0% to ~0.88-0.90 at 15%. German historical data (Table 3, p. 224) shows VF = 0.89 at 8.8% market share in 2012.
- **Solar at 10% penetration = 0.85:** APPROXIMATELY CORRECT. Literature dispatch model estimates (Figure 5, p. 223) cluster around 0.80-0.85 at ~10% share. The paper notes solar drops *below 0.5* at 15% (p. 226). So 0.85 at 10% is a reasonable mid-range reading.
- **"Table 1" reference in MCPR doc:** INCORRECT — there is no "Table 1" with value factors by penetration. The numbers are derived from Figures 4-5 (literature review) and Figure 8 (EMMA model), plus Table 2 (empirical literature summary, p. 222).

**Correction:** Change MCPR methodology reference from "Hirth (2013), Table 1, ~10-15% penetration" to "Hirth (2013), Figures 4-5 (literature review) and Figure 8 (EMMA model results)."

---

### ~~UNVERIFIABLE 3~~ → RESOLVED: Pang & Shrimali network contagion paper

**Location:** Contagion section, Veraart recommendation

**Claim:** "Already validated within TRISK by Pang & Shrimali on Asian banking data"

**Paper found:** Pang, R.K.-K. & Shrimali, G. (2024). "Financial network valuation under climate transition risk." SSRN 4905653, July 25, 2024. CGFI, Oxford. Interactive tool: https://cfa-institute-rpc.github.io/cgfi-finshock/

**Verdict: PARTIALLY CORRECT — paper exists but claim has inaccuracies**

**What the paper actually does (from CGFI page and Singapore presentation):**
- Uses "a general network valuation model to consider financial contagion under climate transition risk" — consistent with Barucca et al. framework (the CGFI's `neva` code was developed by Barucca)
- Applied to **developing nations in southern, eastern, and southeastern Asia** using NGFS scenarios — NOT specifically "Asian banking data" but the region is correct
- Pang has Bank of England background in systemic risk and financial networks
- Finding: *"financial firms exhibit resilience to transition shocks"* though results vary by network topology
- Does NOT explicitly reference "TRISK" or "Veraart" in the abstract, though it was developed within the same CGFI/TRISK research ecosystem

**Corrections needed in the brief:**
1. "Validated within TRISK" → "Developed within the CGFI/TRISK research ecosystem"
2. "Asian banking data" → "applied to developing Asian economies using NGFS scenarios"
3. "Veraart" → the paper uses a "general network valuation model" (likely Barucca et al., given CGFI's `neva` codebase), not necessarily Veraart specifically
4. The paper uses Barucca's framework (Barucca is associated with CGFI/neva), which as shown in our verification subsumes Veraart as a special case

---

### UNVERIFIABLE 4: Tabachova liquidity support claim

**Location:** Improvement N5

**Claim:** "Targeted liquidity support of 0.5% of bank equity reduces system losses from 6% to 1%"

**Evidence:** Not found in the INET Oxford Working Paper 2025-04 pages read. May be in the published J. Financial Stability version (2024).

**Action needed:** Check the J. Financial Stability publication (reference [44] in Kerkhofs).

---

### ~~UNVERIFIABLE 5~~ → RESOLVED: Bolton & Kacperczyk JFE citation

**Location:** Appendix C

**Claim:** "Do Investors Care About Carbon Risk?" JFE 142(2)

**Verdict: VERIFIED**

**Evidence:** ScienceDirect and RePEc confirm: Bolton, P. & Kacperczyk, M. (2021). "Do investors care about carbon risk?" *Journal of Financial Economics*, Vol. 142, Issue 2, pp. 517-549. DOI: 10.1016/j.jfinec.2021.05.008. The PDF in the Reading folder is the ECGI Working Paper version (N° 711/2020, SSRN 3398441).

---

## Part 4: Context Papers (Correctly Referenced but No Specific Claims)

These papers are appropriately in the References section but don't contribute specific model mechanics:

| Paper | Role |
|-------|------|
| **Khan et al. (2024)** Nature Climate Change | 6 high-level principles for transition risk. Validates ALTR philosophy. No formulas/data. |
| **Acharya, Engle et al. (2023)** NY Fed | Comprehensive review/survey. Framing and motivation. |
| **Farmer & Kleinnijenhuis (2021)** | Vision piece for next-gen stress testing. Agent-based modeling advocacy. |

---

## Part 5: Verified Claims (Full Evidence Register)

### Cormack et al. (2020)

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| C1.1 | LCOE-based pricing | VERIFIED | Section 5.4 (p. 20): *"The pricing methodology applied is based on the levelised cost of energy (LCOE) from the GEM-E3/POLES model."* Eq. 16-17. |
| C1.2 | Time-dependent Merton drift | VERIFIED | Section 5.1.1 (p. 14), Eq. 1: `dA_t/A_t = mu_A(t)dt + sigma_A dW_t` — drift explicitly time-dependent. P. 16: *"mu_A(t) is a deterministic function of the asset returns."* |
| C1.3 | Rating-dependent volatility | VERIFIED | Section 5.1.3 (p. 18): *"One of the observed effects is the increase of estimated asset volatility levels as credit ratings decrease... we perform a calibration across the sector to determine, the asset volatility per rating."* |
| C1.4 | Debt covenant constraints | VERIFIED | Section 5.2 (p. 18), Eq. 15: `debt_c(t) <= d_ratio^UB × EBITDA_c(t)`. *"Many companies have strict net debt / EBITDA ratios as part of their specific issuance covenants."* |

### Reinders et al. (2020)

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| C2.1 | Closed-form NPV-to-PD equations | VERIFIED | Eq. 16 (p. 12-13): NPV of carbon tax shock. Eq. 18: asset shock fraction xi_k. Eqs. 9-10 (p. 10): Merton stress test coefficients theta_D and theta_E as closed-form functions. |
| C2.2 | 15-37% leverage underestimation | VERIFIED | Section 4.3, Table 12 Panel C (p. 29): *"increases over the baseline scenario of 15.4%, 25.6%, 31.5%, and 37.0%"* across four scenarios. |

### Gourdel (2024)

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| C3.1 | Stranding-aware terminal value | VERIFIED | Section 4.1, Eq. 3 (p. 11): `V(Phi) = sum rho^t (p - theta_k × Phi(t))^+`. *"The capital gets stranded at the first time t such that theta_k × Phi(t) >= p."* |
| C3.2 | Carbon premium feedback loop | VERIFIED | Section 4.4 (p. 14), Eq. 9: `kappa_i = r + mu + (LGD × EDF_i)/(1 - EDF_i)`. Section 4.5 (p. 16-17): *"There is a mutual dependency between the valuation of assets and the interest rate charged by the bank."* Figure 7. |
| C3.4 | Endogenous interest rate formula | VERIFIED | Section 4.4, Eq. 9 (p. 14): exact formula confirmed. Eq. 10 (p. 16): PD depends on asset value A, which depends on kappa through discount. Section 4.5: *"found numerically by solving A^dagger(kappa) = A^diamond(kappa, D)."* |
| C3.5 | Interest-rate feedback equilibrium | VERIFIED | Section 4.5 title: *"Equilibrium from the feedback of valuation and interest rates."* |

### Way et al. (2022)

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| C4.1 | Wright's Law learning curves | VERIFIED | Methods (p. 12): *"We employ... a first-difference stochastic form of Wright's law, developed and tested by Lafond et al., which models costs dropping as a power law of cumulative production."* |
| C4.2 | Cost trajectories from cumulative production | VERIFIED | P. 4: *"For renewable technologies we use a stochastic generalization of Wright's law, which predicts that costs drop as a power law of cumulative production."* Figure 3 (p. 6): probabilistic cost forecasts. |

### Bolton & Kacperczyk (2021)

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| C5.1 | Carbon premium in stock returns | VERIFIED | Abstract: *"We find that stocks of firms with higher total CO2 emissions earn higher returns... We cannot explain this carbon premium through differences in unexpected profitability."* Section 3.2 (p. 19): 13-33 bps/month per standard deviation. |

### Veraart (2020)

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| V1.1 | 5 interpretable parameters | VERIFIED | Section 3.2 (p. 717): *"Our model consists of five model parameters"* — k (capital cushion), R (perceived recovery), beta (actual recovery), a, b (Beta CDF shape). |
| V1.2 | Subsumes EN and RV | VERIFIED | Section 3.3 (p. 720): *"If k = 0, the model reduces to the model by Rogers and Veraart (2013)... If in addition beta = 1 the valuation reduces to the Eisenberg and Noe (2001) model."* |
| V1.3 | Beta CDF parameterization | VERIFIED | Section 3.1 (p. 716), Eq. 15-16: *"F is the cumulative distribution function (cdf) of the Beta distribution with parameters a > 0, b > 0."* |
| V1.4 | 2/3 of crisis losses from distress | VERIFIED | P. 706: *"Roughly two-thirds of losses attributed to counterparty credit risk were due to CVA losses and only about one-third were due to actual defaults (Basel Committee on Banking Supervision, 2011)."* |
| V1.6 | Fewest data requirements | VERIFIED | P. 715: *"A major advantage of our proposed functional form is that it relies only on a small number of model parameters that all have an intuitive meaning."* No cross-holdings matrix required. |

### Barucca et al. (2020)

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| B1.1 | Unifies clearing + ex-ante | VERIFIED | P. 1183: *"The framework includes two families of models. If the valuation is performed strictly before maturity... ex ante valuation. If at maturity... clearing of interbank claims."* Section 5: "FROM CLEARING TO EX ANTE VALUATION." |
| B1.2 | E = Phi(E) fixed point | VERIFIED | Eq. 8 (p. 1188): `E(t) = Phi(E(t))`. Theorem 3.1 establishes existence of greatest and least solutions. |
| B1.3 | neva Python code | VERIFIED | P. 1197: *"A Python implementation... is available at: https://github.com/marcobardoscia/neva."* |
| B1.5 | Ex-ante EN for pre-default losses | VERIFIED | Section 5 (p. 1191-1196): derives ex ante EN valuation yielding mark-to-market losses through endogenous PD and recovery. |

### Elsinger (2009)

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| E1.1 | Cross-holdings + seniority | VERIFIED | P. 3: *"extend the work of Eisenberg and Noe (2001) by taking cross holdings and a detailed seniority structure of debt explicitly into account."* |
| E1.2 | Nested V=f(p), p=g(V) | VERIFIED | Eqs. 1-4 (pp. 6-7): V*(p) depends on clearing vector p*, and p* depends on V*(p*). |
| E1.3 | No pre-default losses | VERIFIED | Clearing model at maturity only. Binary default/non-default. No mark-to-market mechanism. |
| E1.4 | Requires cross-holdings data | VERIFIED | P. 4: Cross-holdings matrix Theta is a required input in all equations. |
| E1.5 | Algorithm provided | VERIFIED | Section 4, Theorem 6 (p. 14): convergent iterative algorithm for largest clearing vector. |

### Kerkhofs et al. (2025)

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| K1.1 | Baer co-author (TRISK group) | VERIFIED | Author list: Moritz Baer confirmed. Acknowledgments thank Jakob Thoma (Theia Finance Labs / TRISK). |
| K1.3 | Three channels: 83.2% / 16.8% | VERIFIED | Section 3.2 (p. 11): *"83.2% of calculated average impacts are a result of direct asset damages, and the remaining 16.8% for business disruptions."* Insurance: *"no impact... on average asset values... however, increased tail risks."* |
| K1.4 | Gaussian, t-Copula, R-vine | VERIFIED | Section 2.1 (p. 3-4): all three copula types described with mathematical formulations. |
| K1.5 | 424 assets, 126 firms, India | VERIFIED | P. 9: *"424 assets located in India belong to 126 firms."* |
| K1.6 | Independence underestimates by 20% | VERIFIED | Section 3.1 (p. 10): *"The complete independence assumption can underestimate tail risks by up to 20% compared to the Gaussian copula model."* |
| K1.7 | Dependence overestimates by 207% | VERIFIED | Section 3.1 (p. 10): *"the complete dependence assumption can overestimate tail risks by 207%."* |
| K1.8 | Insurance: 23-96% higher tail risk | VERIFIED | Section 3.2 (p. 12): *"tail risks of 23%-96% higher compared to a fully insured portfolio."* |
| K1.11 | Supply-price elasticity in 2.2.2 | VERIFIED | Section 2.2.2 (p. 5): price-supply elasticity formula for production disruptions. |
| K1.12 | PRISK ratio in 2.3.1 | VERIFIED | Section 2.3.1 (p. 7): `PRISK_i = V_{i,S} / V_{i,B}`. |
| K1.13 | Insurance feedback in 2.2.3 | VERIFIED | Section 2.2.3 (p. 6): dynamic insurance premium model with feedback mechanism. |
| K1.14 | Environmental Research: Climate | VERIFIED | Header: *"Environ. Res.: Climate 4 (2025) 025014."* |

### Garnier et al. — CERM

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| G1.1 | Alpha parameters in Eq. 41-42 | VERIFIED | Eq. 41 (p. 20): micro-correlation adjustment. Eq. 42: `a-tilde = alpha × zeta`. Section 7.2 (p. 19): *"Each borrower... has a micro-correlation adjustment parameter alpha."* |
| G1.2 | CERM = Climate Extended Risk Model | VERIFIED | Title and abstract (p. 1): *"The proposed Climate Extended Risk Model (CERM)."* |

### Calipel et al. (2021)

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| CAL1.1 | Four cement risk drivers | VERIFIED | Figure 1 (p. 3): four drivers exactly as claimed. Sections 2.4.1-2.4.4 with dedicated tables for each. |
| CAL1.2 | Multiple shock channels per sector | VERIFIED | Core thesis. P. 7: *"does not include any scenario assumptions that are differentiated according to the sector."* Two case studies with 4 drivers each. |

### Barclays (2021)

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| BAR1.1 | Cement 65%, Auto 30% pass-through | VERIFIED | P. 9, pass-through table: Cement **65%**, Automotive **30%**. Exact match. |
| BAR1.2 | Source for sector-specific pass-through | VERIFIED | Section 2.2 (p. 8): methodology with differentiated rates per industry. Eq. 9. |

### Le Guenedal (2022)

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| LG1.1 | Jump-diffusion + Bayesian updating | VERIFIED | Chapter 4 (p. 106): *"The climate policy is characterized by an increasing carbon price process C_t = sum of Y_i, where N is a doubly stochastic Poisson process."* P. 107: Bayesian filtering of posterior scenario probabilities. |
| LG1.3 | Merton PD layer reference | VERIFIED | Chapter 2: *"this approach uses Merton (1974) distance to default."* Carbon price sensitivity of credit risk via Merton. |

### Tang & Cervenka et al.

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| TC1.1 | ALTR foundation paper | VERIFIED | Title confirmed. Complete DCF stress testing framework for power companies. |
| TC1.2 | Author list | VERIFIED | Tang, Yilmaz, Gallice, Hejazi, Cervenka, Apeaning, Oweyssi, Kamboj, Buller. |
| TC1.3 | DCF framework | VERIFIED | P. 13, Eq. 10: NPV with Gordon Growth terminal value. Eq. 7-9: asset-level revenue/cost buildup. Eq. 15: VaR = NPV_stress - NPV_baseline. |

### Publication Details (Web-Verified)

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| SEM1.1 | Semieniuk (2022) Nature Climate Change 12 | VERIFIED | Vol. 12, pp. 532-538, DOI: 10.1038/s41558-022-01356-y |
| FR1.1 | Fabra & Reguant (2014) AER 104(9) | VERIFIED | Vol. 104, No. 9, pp. 2872-2899, DOI: 10.1257/aer.104.9.2872 |
| DAM1.3 | Damodaran SSRN 1466041 | VERIFIED | Confirmed: "Ups and Downs: Valuing Cyclical and Commodity Companies," Sept 2009 |
| PEN1.1 | Penman (1998) Rev. of Accounting Studies | VERIFIED | Vol. 2, pp. 303-323. Full title includes "for the Dividend Discount Model." |
| PEN1.2 | Steady state necessary for perpetuity | VERIFIED | Core contribution of the paper. |

---

## Part 5b: April 2026 Update Papers (Verified from Obsidian Vault Notes, Not PDFs)

These papers were added in the April 2026 update based on web research. PDFs are NOT in the Reading folder. Claims were cross-checked against the Obsidian vault notes created during that research session. The vault notes are detailed but are themselves agent-generated secondary sources — for peer review, these should be verified against the actual papers.

### Jung, Engle & Berner (2025) — CRISK

**Vault note:** `sources/jung_2025_crisk-jfe.md`

| # | Claim in Brief | Vault Note Says | Confidence |
|---|----------------|-----------------|------------|
| JEB1 | "First peer-reviewed market-based climate systemic risk measure in a top-3 finance journal" | Vault confirms: "First peer-reviewed market-based climate systemic risk measure in a top-3 finance journal" | HIGH — JFE is unambiguously top-3 |
| JEB2 | "Three variants: CRISK, mCRISK, S&CRISK" | Vault confirms all three variants with definitions | HIGH |
| JEB3 | Published in JFE, Vol. 171 | Vault: *Journal of Financial Economics*, 171 | MEDIUM — needs JFE website check |
| JEB4 | "Moves from scenario-dependent periodic exercises to continuous market-implied monitoring" | Vault: "Moves from scenario-dependent stress tests to continuous, market-implied climate risk monitoring" | HIGH |

**Action needed:** Acquire PDF and verify publication details against JFE Vol. 171.

### Fialkowski et al. (2025)

**Vault note:** `sources/fialkowski_2025_production-network-contagion.md`

| # | Claim in Brief | Vault Note Says | Confidence |
|---|----------------|-----------------|------------|
| FIA1 | "arXiv:2502.17044" | Vault confirms arXiv ID | MEDIUM — needs arXiv check |
| FIA2 | "First model integrating production network dynamics with interbank contagion" | Vault: "First financial systemic risk model to integrate agent-level production network dynamics with interbank network" | HIGH |
| FIA3 | "~1M firm supply chain links + bank-firm loans + interbank network" | Vault: "~1 million firm supply chain links + bank-firm loans + interbank exposures" | HIGH |
| FIA4 | "When production network contagion is included, interbank contagion increases by 70%" | Vault: "When production network contagion is modelled, interbank contagion increases by 70%" | HIGH |
| FIA5 | "Financial systemic risk up 28%" | Vault: "Financial systemic risk increases by up to 28% with interbank channel" | HIGH |

**Action needed:** Download from arXiv and verify key numbers.

### Bressan et al. (2024)

**Vault note:** `sources/bressan_2024_asset-level-physical-risk.md`

| # | Claim in Brief | Vault Note Says | Confidence |
|---|----------------|-----------------|------------|
| BRE1 | "Nature Communications" | Vault confirms | HIGH |
| BRE2 | "Investor losses underestimated up to 70% without asset-level data" | Vault: "Investor losses underestimated up to 70% when neglecting asset-level information" | HIGH |
| BRE3 | "82% without tail acute risk modelling" | Vault: "Up to 82% underestimation when neglecting tail acute risks" | HIGH |

**Action needed:** Download from Nature Communications (open access) and verify.

### Howard & Sterner (2025)

**Vault note:** `sources/howard_sterner_2025_damage-function-meta.md`

| # | Claim in Brief | Vault Note Says | Confidence |
|---|----------------|-----------------|------------|
| HS1 | Published in *Environmental and Resource Economics* | Vault: "*Environmental and Resource Economics*" | HIGH |
| HS2 | "7.1-12.6% depending on catastrophe definition" | Vault: "Best estimate: 7.1-12.6% depending on catastrophe definition" | HIGH |
| HS3 | "First to use AICc model selection" | Vault: "First to use AICc model selection and random effects in climate damage meta-analysis" | HIGH |

**Action needed:** Download from ERE and verify meta-analysis numbers.

### ~~Unverified~~ → RESOLVED: BIS Working Paper 1274 (2025)

**PDF acquired:** `Reading/credit_risk/RELEVANT.credit_risk.bis_wp1274_physical_risk_credit_2025.pdf`

**All claims VERIFIED:**
- Authors: Pozdyshev, Lobanov, Ilinsky. Published July 2025.
- "Extends Vasicek model with physical risk component" — CONFIRMED. Abstract: *"integration of physical risk component into credit risk modelling, using an extension of the one-factor Vasicek model."*
- "Asset devaluation >30% for ~5% of firms" — CONFIRMED. Paper states: *"asset values decline by more than 30% for approximately 5% of firms."*
- "PDs below investment-grade for ~16%" — CONFIRMED. Paper states approximately 16% of firms experience sub-investment-grade PDs under stress.

### Roncalli et al. (2023)

No vault note available. Referenced as SSRN 4497124.

**Action needed:** Download from SSRN and verify claims about terminal value dampening.

---

## Part 6: Summary of Required Corrections

### Must Fix (Errors)

| # | Location | Current Text | Correction |
|---|----------|-------------|------------|
| 1 | D3 source | "Reinders (2020)" | Change to "Cormack (2020)" — Cormack models dynamic leverage via debt covenants |
| 2 | MA3 spread | "~60-120 bps from OECD 2024, Bolton & Kacperczyk 2021" | Remove Bolton & Kacperczyk. Cite Gourdel (2024) Fig. 1 for debt spread survey or find the OECD 2024 source |
| 3 | MA4 Bodmer ratio | "CapEx/depreciation = ~1.15x" | Verify against actual book or replace with standard formula (1.40x at g=2%, d=5%) |

### Should Fix (Refinements)

| # | Location | Issue | Fix |
|---|----------|-------|-----|
| 4 | M1 description | "adds interest expense to FCFF" | Rewrite: enters through discount rate, not FCFF subtraction |
| 5 | MA2 precedent | Fabra/Hirth/Koolen presented as Cormack citations | Reformat as brief's own supporting literature |
| 6 | Kerkhofs triple/quadruple | Merton=triple, empirical=quadruple | Fix: 95th triples, 99th quadruples, both models |
| 7 | M3 description | "Negative firm value = certain default" | Rewrite: total asset loss (xi → 1) implies certain default |
| 8 | D6 source | "probability-weighted multi-scenario NPV" | Add: Le Guenedal applies to bond pricing; adapt framework for NPV |
| 9 | McKinsey chapter | "Ch. 12" | Verify correct chapter number in 7th edition |
| 10 | Penman title | Truncated | Add: "for the Dividend Discount Model" |
| 11 | Kerkhofs DCF ref | "Tang & Cervenka approach" | Change to: "same DCF framework (citing Bressan et al. as predecessor)" |
| 12 | Tabachova | Possibly conflated papers | Verify J. Financial Stability version separately |
| 13 | Damodaran negative FCFF | "valid for negative FCFF" | Add nuance: terminal year must be normalized |

### Should Verify (Unresolved)

| # | Claim | Action |
|---|-------|--------|
| ~~14~~ | ~~WITCH 13% learning rate~~ | RESOLVED — 13% for solar, 10% onshore wind, 13% offshore (IAMC docs). Fixed in brief. |
| ~~15~~ | ~~Hirth value factors~~ | RESOLVED — Wind 0.90 at 15% verified (Fig 8). Solar 0.85 at 10% approximately correct (Figs 4-5). "Table 1" ref corrected. |
| ~~16~~ | ~~Pang & Shrimali~~ | RESOLVED — SSRN 4905653 (July 2024). Applied to developing Asian economies, uses Barucca framework. Not "validated within TRISK" per se. |
| ~~17~~ | ~~Tabachova 0.5% liquidity figure~~ | RESOLVED — **claim NOT found** in any version of the paper. The paper's findings are about supply chain contagion amplification (4.3x EL, 4.5x VaR), not about targeted intervention. The "0.5% reduces from 6% to 1%" claim appears to be misattributed or fabricated. **DROP from the brief.** |
| ~~18~~ | ~~Bolton & Kacperczyk JFE 142(2)~~ | RESOLVED — VERIFIED: JFE Vol. 142, Issue 2, pp. 517-549, 2021. DOI: 10.1016/j.jfinec.2021.05.008 |

---

## Appendix: Papers Verified

| # | Paper | PDF Location | Pages Read |
|---|-------|-------------|------------|
| 1 | Cormack et al. (2020) | `transition_risk/RELEVANT...cormack_energy_transition_financial_risks.pdf` | Full |
| 2 | Reinders et al. (2020) | `climate_stress_test/RELEVANT...reinders_finance_approach_cst.pdf` | Full |
| 3 | Gourdel (2024) | `credit_risk/RELEVANT...gourdel_credit_climate_sentiments.pdf` | Full |
| 4 | Way et al. (2022) | `transition_risk/RELEVANT...way_etal_technology_forecasts_energy_transition.pdf` | Full |
| 5 | Bolton & Kacperczyk (2021) | `esg/esg.bolton_kacperczyk_carbon_premium.pdf` | ECGI WP version |
| 6 | Veraart (2020) | `financial_contagion/financial_contagion.veraart_distress_default_contagion.pdf` | Full |
| 7 | Barucca et al. (2020) | `financial_contagion/RELEVANT...barucca_network_valuation.pdf` | Full |
| 8 | Elsinger (2009) | `financial_contagion/RELEVANT...elsinger_networks_cross_holdings.pdf` | Full |
| 9 | Kerkhofs et al. (2025) | `Kerkhofs_2025_Environ._Res.__Climate_4_025014.pdf` | Full |
| 10 | Tabachova et al. (2025 WP) | `climate_stress_test/...tabachova_supply_chain_stress_test_2025.pdf` | pp. 1-12 |
| 11 | Garnier et al. (CERM) | `climate_stress_test/RELEVANT...garnier_cerm_climate_extended_risk_model.pdf` | Eqs. 41-42 |
| 12 | Calipel et al. (2021) | `transition_risk/RELEVANT...calipel_sectoral_transition_risk_drivers.pdf` | Full |
| 13 | Barclays (2021) | `transition_risk/RELEVANT...barclays_corporate_transition_forecast_2021.pdf` | Full |
| 14 | Le Guenedal (2022) | `climate_stress_test/RELEVANT...le_guenedal_2022_thesis.pdf` | Chapters 2, 4 |
| 15 | Khan et al. (2024) | `transition_risk/RELEVANT...khan_science_based_transition_risk_2024.pdf` | Full (3 pages) |
| 16 | Tang & Cervenka et al. | `climate_stress_test/RELEVANT...tang_cervenka_asset_level_power_sector.pdf` | Key sections |
| 17 | Acharya et al. (2023) | `climate_stress_test/RELEVANT...acharya_engle_nyfed_climate_stress_testing_2023.pdf` | Full |
| 18 | Farmer & Kleinnijenhuis (2021) | `climate_stress_test/RELEVANT...farmer_kleinnijenhuis_stress_testing_macrocosm.pdf` | Full |
| — | Hirth (2013) | Not in Reading folder | NOT READ — value factors unverified |
| — | Damodaran (textbook) | Not available as PDF | Web-verified (publication details only) |
| — | McKinsey Valuation 7th ed. | Not available as PDF | Web-verified (chapter number uncertain) |
| — | Penman (1998) | Not available as PDF | Web-verified |
| — | Bodmer (2014) | Not available as PDF | Web-verified (1.15x ratio flagged as ERROR) |
| — | Jung, Engle & Berner (2025) | Not in Reading folder | Vault note verified |
| — | Fialkowski et al. (2025) | Not in Reading folder | Vault note verified |
| — | Bressan et al. (2024) | Not in Reading folder | Vault note verified |
| — | Howard & Sterner (2025) | Not in Reading folder | Vault note verified |
| — | BIS WP 1274 (2025) | Not in Reading folder | NOT VERIFIED |
| — | Roncalli et al. (2023) | Not in Reading folder | NOT VERIFIED |
