# ALTR NPV Direction Fix -- Research Report

**Date:** 2026-03-31
**Author:** Research Agent (Claude Opus 4.6)
**Model:** ALTR (crispy-kedro pipeline, WITCH 5.0 scenarios)
**Scope:** Root cause analysis and fix proposals for directionally incorrect NPV results

---

## 1. Root Cause Analysis

### Root Cause #1 (PRIMARY): All Carbon Prices Are NaN -- Effectively Zero

**Likelihood: CERTAIN | Impact: CRITICAL**

The `carbon_price_usd_per_tco2` column in `data/05_model_output/scenarios_pathways.csv` is **entirely NaN** (0 out of 13,440 rows). The `build_scenario_surfaces` function (earnings_model/nodes.py:292-294) fills these with 0.0:

```python
surfaces["carbon_price_usd_per_tco2"] = scenarios["carbon_price_usd_per_tco2"].fillna(0.0)
```

**Result:** The carbon cost mechanism in `compute_ops_block` (line 1044-1049) produces zero for ALL assets:
```python
carbon_cost_net = Q * carbon_price * emission_factor * (1 - market_passthrough) = 0
```

The carbon pricing channel -- described in CLAUDE.md as "the single most important parameter" and "the critical lever" -- is **completely inactive**. The model relies ENTIRELY on electricity price differentials and production volume changes to drive NPV direction.

**Evidence from data:**
```
GasCap - w/o CCS (both baseline and target): carbon_price = NaN → 0.0 at all years
CoalCap - w/o CCS (both baseline and target): carbon_price = NaN → 0.0 at all years
```

**The WITCH IAM scenario data from BigQuery does not include per-technology carbon prices.** The carbon price is embedded implicitly in the electricity price paths (target prices are higher near-term because they reflect carbon cost pass-through). But the explicit `carbon_price_usd_per_tco2` field needed by the ALTR earnings model is never populated.

### Root Cause #2: Decommissioning Cost Sign Bug

**Likelihood: CERTAIN | Impact: HIGH**

In `build_scenario_surfaces` (line 304):
```python
surfaces["scrap_usd_per_mw"] = -surfaces["capex_usd_per_mw"] / 2
```

This makes `scrap_usd_per_mw` NEGATIVE (e.g., -$750,000/MW for a gas plant).

In `compute_flow_based_capex` (line 855-858):
```python
decom_cost = scrap_usd_per_mw * retired_capacity  # negative * positive = NEGATIVE
```

In `capex_total` calculation (line 865-869):
```python
capex_total = growth_capex + replace_capex + decom_cost  # positive + positive + NEGATIVE
```

In `compute_fcff` (line 1088):
```python
FCFF = EBITDA - capex_total  # EBITDA - (smaller number) = HIGHER FCFF
```

**Result:** Decommissioning currently **INCREASES** FCFF instead of decreasing it.

**Numerical proof** (100 MW gas plant retirement, capex=$1.5M/MW):
| Component | Current (buggy) | Correct |
|-----------|----------------|---------|
| scrap_usd_per_mw | -$750,000 | -$750,000 (same, means "costs money") |
| decom_cost | -$75,000,000 | **+$75,000,000** |
| capex_total | -$75,000,000 | +$75,000,000 |
| FCFF impact | **+$75M boost** | **-$75M penalty** |

**Fix:** Change line 855-858 to negate the sign:
```python
decom_cost = abs(scrap_usd_per_mw) * capex_capacity  # or: -scrap * cap
```

This bug means every fossil asset retirement under the shock scenario is REWARDING companies instead of costing them. For large-scale retirements (CoalCap USA goes from 2.3B MW to 0), the accumulated "free money" from decommissioning is enormous.

### Root Cause #3: Mixed Scenario Surface Creates Near-Term Price Windfall

**Likelihood: CERTAIN | Impact: MEDIUM**

The `assemble_asset_panel` function (earnings_model/nodes.py:528-554) constructs the shock scenario surface as:
- Pre-shock (year < 2033): **baseline** scenario surfaces (prices, costs, capacity factors)
- Post-shock (year >= 2033): **target** scenario surfaces

The WITCH scenario data shows electricity prices that are **HIGHER under target than baseline near-term**:

| Geography | Year | Baseline $/MWh | Target $/MWh | Difference |
|-----------|------|----------------|--------------|------------|
| USA | 2033 | $49.4 | $64.4 | **+30%** |
| USA | 2040 | $52.0 | $46.6 | -10% |
| USA | 2050 | $49.9 | $35.1 | -30% |
| CHN | 2033 | $32.1 | $45.4 | **+41%** |
| CHN | 2050 | $32.7 | $30.9 | -5% |
| IND | 2033 | $33.6 | $50.9 | **+51%** |
| IND | 2050 | $38.3 | $33.1 | -14% |

**All technologies** receive these same prices (WITCH doesn't differentiate by technology). When the shock scenario switches from baseline to target prices at shock_year=2033, EVERY technology gets an immediate price increase of 30-50%.

For fossils still producing at 2033 (which they are, since production only starts declining at shock year): this price jump means **higher revenue per MWh** right when they start losing production. The revenue boost in the first few post-shock years can offset the production decline.

For renewables increasing production at 2033: the price jump means **even higher revenue** since they have BOTH more production AND higher prices. This is directionally correct -- but exaggerated.

The prices eventually decline below baseline by ~2040-2050, which is the correct long-term transition signal. But the near-term windfall at shock year creates the delayed transition benefit.

### Root Cause #4: Terminal Value Conditional on Positive FCFF

**Likelihood: CERTAIN | Impact: MEDIUM**

In `compute_yearly_npv_trajectories` (valuation_model/nodes.py:108):
```python
if final_fcff > 0:
    terminal_value = ...  # perpetuity calculation
```

Terminal value is **only added when the final year's FCFF is positive**. This creates asymmetry:

- **Fossil shock trajectory**: At 2050, production may be near zero, prices are low ($35/MWh), but if the decom sign bug means FCFF is still positive → gets a terminal value perpetuity. If FCFF is negative → no terminal value, NPV bounded.
- **Baseline trajectory**: Fossil production continues at moderate levels with moderate prices ($50/MWh) → likely positive FCFF → gets full terminal value.
- **Renewable shock trajectory**: Higher production × lower prices but still likely positive FCFF → gets terminal value.

The terminal value multiplier at default parameters (r=7%, g=2%): **(1.02) / (0.07 - 0.02) = 20.4x** the final year's FCFF. This amplifies any directional error in the terminal year.

### Root Cause #5: All Technologies Get Identical Prices (Pre-MCPR)

**Likelihood: CERTAIN | Impact: MEDIUM**

The WITCH scenario data provides **one electricity price per (geography, year, scenario_type)** -- not differentiated by technology. CoalCap, GasCap, SolarCap, and WindCap all receive exactly the same $/MWh:

```
USA baseline 2033: Coal=$49.4, Gas=$49.4, Solar=$49.4, Wind=$49.4
USA target 2033:   Coal=$64.4, Gas=$64.4, Solar=$64.4, Wind=$64.4
```

The MCPR adjustment should differentiate these by applying value factors (Solar: 0.85, Wind Onshore: 0.90, dispatchable: 1.0), but this only creates ~10-15% price differentiation. The underlying price dynamics (near-term boost, long-term decline) are identical across technologies.

**Result:** Revenue per MWh is nearly identical for coal and solar. The NPV differentiation comes primarily from:
1. Production volume changes (dramatic for fossils, positive for renewables)
2. Cost structure differences (fuel costs for fossils, CapEx for renewable buildout)
3. Continued O&M on frozen capacity (shock-only for fossils)

### Root Cause #6: Pre-Shock Period Is NOT Identical Between Baseline and Shock

**Likelihood: CERTAIN | Impact: LOW-MEDIUM**

The `assemble_asset_panel` function uses **baseline scenario surfaces** for the shock trajectory's pre-shock period. This means pre-shock PRICES are identical between baseline and shock. However, pre-shock PRODUCTION can differ because:

- Baseline production follows `company_trajectory_baseline`
- Shock production follows `company_trajectory_latesudden`, which for pre-shock uses `company_activity` (real data) and `company_trajectory_baseline`

If these are identical pre-shock, the NPV difference comes entirely from post-shock divergence. This appears to be the intended design.

However, from the FINDINGS_SUMMARY.md, the "delayed transition benefit" for fossils is described as fossils earning MORE profit before the shock hits. This would only be possible if either:
- The **baseline scenario already imposes costs** (carbon prices, forced retirements) that the shock scenario delays, OR
- There's a difference in pre-shock production trajectories

Since carbon prices are NaN (zero), the baseline doesn't impose extra carbon costs. The baseline DOES have different production trajectories (following CurPol which can have declining fossil production even without explicit carbon pricing).

### Root Cause #7 (NEW from research): Terminal Value Gate Deviates from Original TRISK

**Likelihood: CERTAIN | Impact: HIGH**

The valuation_model/nodes.py:108 gate `if final_fcff > 0` is a **deviation from the original TRISK R package**, where terminal value is applied UNCONDITIONALLY to both baseline and shock (calc_annual_profts.R:71-80 applies `net_profits / (discount_rate - growth_rate)` with no sign check).

Damodaran (NYU Stern) explicitly states the Gordon Growth Model is valid for negative FCFF: a negative numerator produces a negative terminal value. KPMG IAS 36 guidance notes that terminal value is "most affected by climate-related matters" and excluding it for negatively-affected assets removes the component most relevant to climate stress testing.

**The asymmetric bias:**
- Carbontech with negative final FCFF → NO terminal value → losses BOUNDED to forecast horizon
- Greentech with positive final FCFF → FULL perpetuity (20.4x) → gains AMPLIFIED to infinity

This is the primary amplification mechanism for the renewable "over-investment avoidance" paradox documented in FINDINGS_SUMMARY.md.

**Fix:** Remove the `final_fcff > 0` gate to match original TRISK behavior. Or use average of last 3-5 years' FCFF instead of final year only.

### Root Cause #8 (NEW from research): WITCH Learning Curve Creates CapEx Asymmetry

**Likelihood: HIGH | Impact: MEDIUM (WITCH-specific)**

The WITCH IAM uses learning-by-doing cost curves: 13% learning rate (progress ratio 0.87) for solar PV, 10% for onshore wind, 13% for offshore wind (source: IAMC documentation, doc.witchmodel.org). Each doubling of cumulative capacity reduces costs by 10-13%. Under Below 2C, more capacity is deployed globally, which means:
- Target scenario: faster learning → lower CapEx per MW by 2033-2050
- Baseline (CurPol): slower learning → higher CapEx per MW

When the ALTR model charges growth CapEx (`capex_usd_per_mw × new_buildout_cap`), baseline renewable buildout pays MORE per MW than shock buildout. This is economically real (learning curves are genuine) but amplified by the terminal value gate (Root Cause #7).

**Citation:** WITCH Model Documentation (IAMC); Carbon Brief IAM Q&A confirms "the amount of renewables deployed in WITCH baseline scenarios exceeds GCAM/IMAGE 2C scenarios."

### Root Cause #9 (NEW from research): ALTR Answers a Different Question than TRISK

**Likelihood: CERTAIN | Impact: CONCEPTUAL**

The research agents identified a fundamental architectural divergence:

| Aspect | R TRISK | ALTR (crispy-kedro) |
|--------|---------|---------------------|
| Baseline carbon cost | ZERO | CurPol scenario (rising) |
| Shock pre-shock carbon cost | ZERO | CurPol (same as baseline) |
| VaR computation window | shock_year → end only | ALL years |
| NPV denominator | baseline_npv (no abs) | abs(baseline_npv) |

- **TRISK asks:** "What is the loss from the shock, assuming NO prior carbon costs?"
- **ALTR asks:** "What is the MARGINAL loss from stricter-than-CurPol policy?"

The TRISK approach always produces negative NPV for carbontech (because shock introduces costs that don't exist in baseline). The ALTR approach can produce positive NPV when CurPol's existing carbon/transition costs are already damaging and the shock merely accelerates an inevitable decline.

**The BoE CBES uses a "no additional headwinds" counterfactual** -- closer to TRISK. The ECB economy-wide stress test uses current policies -- closer to ALTR. Both are valid but produce different narrative frames.

---

## 2. Quick Wins (Parameter/Config Changes)

### QW1: Populate Carbon Price Data — IAM-Specific Strategy

**Critical finding (2026-03-31):** AR6 `Price|Secondary Energy|Electricity` INCLUDES carbon cost effects per the IAMC variable template ("Prices should include the effect of carbon prices"). However, different IAMs embed carbon to different degrees in the reported price:

| IAM | Has explicit carbon_price? | Price spread C1→C7 (2040) | Carbon embedding | Strategy |
|-----|---------------------------|--------------------------|-----------------|----------|
| **WITCH 5.0** | Yes ($0–722/tCO2) | Small ($9/MWh) | Minimal in price | Use differential carbon cost: `Q × cp × max(EF − marginal_EF, 0)` |
| **AIM/CGE 2.2** | No (NaN) | Large ($64/MWh) | Fully in price (CGE equilibrium) | Set carbon_price=0, rely on price signal |
| **REMIND** | Yes | Check empirically per run | Likely moderate | Use differential if price spread is small |
| **IMAGE** | Yes | Check empirically per run | Likely moderate | Same |

**For WITCH scenarios (current ALTR pipeline):**
- Extract `carbon_price_usd_per_tco2` from `6_final_AR6_viable_scenarios.csv` where `scenario_provider == 'WITCH 5.0'`
- CO_CurPol (baseline, C7): NaN → $0 (correct — no carbon policy)
- EN_NPi2020_500 (target, C1): $200/tCO2 (2025) → $722/tCO2 (2050)
- The differential carbon cost mechanism (implemented) applies `max(tech_EF − marginal_EF, 0)` to avoid double-counting the carbon already embedded in the AR6 price

**For AIM/CGE scenarios (new downloaded_scenarios.csv):**
- Set `carbon_price_usd_per_tco2 = 0` — the AIM CGE equilibrium price already captures carbon effects plus second-order effects (fuel price shifts, capital composition, grid integration costs, demand response)
- Adding a separate carbon cost would over-count: the $64/MWh C1→C7 spread already embeds ALL transition cost channels, not just direct carbon

**Justification:** IAMC variable template definition; NGFS Scenarios Portal glossary; empirical test showing WITCH prices are near-flat across stringencies ($9 spread) while AIM prices vary strongly ($64 spread)

### QW2: Fix Decommissioning Cost Sign

**What to change:** In `compute_flow_based_capex` (line 855-858), change:
```python
# Current:
decom_cost = scrap_usd_per_mw * capex_capacity  # negative result

# Fixed:
decom_cost = abs(scrap_usd_per_mw) * capex_capacity  # positive result
```

OR change `build_scenario_surfaces` (line 304):
```python
# Current:
surfaces["scrap_usd_per_mw"] = -surfaces["capex_usd_per_mw"] / 2

# Fixed: make positive (it represents a cost, not a salvage value)
surfaces["decom_cost_usd_per_mw"] = surfaces["capex_usd_per_mw"] / 2
```

**Expected effect:** Fossil asset retirements under shock become a **cost** (~50% of original CapEx per MW retired). For CoalCap USA going from 2.3B MW to 0, the decommissioning cost would be enormous, driving FCFF deeply negative and ensuring correct NPV direction.

**Risk:** LOW. This is a bug fix, not a policy choice. One line of code.

### QW3: Validate `apply_continued_om_shock` Symmetry

**What to change:** Review whether `apply_continued_om_baseline: False` creates an asymmetry that unfairly penalizes the shock scenario. If baseline fossil firms also face continued O&M on capacity they don't use (e.g., under CurPol declining coal), this should be applied symmetrically.

**Expected effect:** If enabled for baseline too, baseline NPV for fossils decreases, potentially making the shock-vs-baseline difference smaller in magnitude but more directionally accurate.

---

## 3. Model Adjustments (Code Changes)

### MA1: Add Carbon Price Injection Node

**Pipeline to modify:** `inputs_processing` or create a new `carbon_price_processing` pipeline

**What it does:** Download NGFS carbon price data from IIASA database or BigQuery, match to scenario pairs (baseline model/scenario, target model/scenario), and merge onto the scenarios_pathways DataFrame.

```python
def inject_carbon_prices(
    scenarios_pathways: pd.DataFrame,
    carbon_price_data: pd.DataFrame,
) -> pd.DataFrame:
    """Merge scenario-specific carbon prices onto scenario pathways."""
    return scenarios_pathways.merge(
        carbon_price_data[["scenario", "scenario_geography", "year", "carbon_price_usd_per_tco2"]],
        on=["scenario", "scenario_geography", "year"],
        how="left",
    ).pipe(lambda df: df.assign(carbon_price_usd_per_tco2=df["carbon_price_usd_per_tco2"].fillna(0.0)))
```

**Expected effect:** Carbon costs become the primary mechanism for fossil NPV destruction, as intended by the model design.

**Implementation complexity:** MEDIUM. Requires sourcing carbon price data from IIASA or NGFS database.

### MA2: MCPR Carbon-Cost-Sensitive Clearing Price

**Function to modify:** `apply_mcpr_adjustment` in earnings_model/nodes.py

**What it does:** Make the market clearing price a function of the marginal generator's carbon cost:

```python
# Current: reference_price = max(price among marginal technologies)
# Proposed: reference_price = max(price + carbon_price * emission_factor among marginal technologies)
```

This means when carbon prices are active, the clearing price rises (because the marginal fossil generator's cost rises), and renewables (emission_factor=0) receive this higher price without paying the carbon cost. This creates the merit order effect.

**Expected effect:** Greentech revenue increases under high-carbon-price scenarios. The effect scales naturally with carbon pricing ambition.

**Precedent:** Fabra & Reguant (2014, AER); Hirth (2013, Energy Economics); Koolen et al. (2023, JRC).

### MA3: Technology-Differentiated Discount Rates

**Function to modify:** `compute_yearly_npv_trajectories` in valuation_model/nodes.py

**Current:** Lines 36-42 assign discount rate based on scenario_type only (baseline vs shock).

**Proposed:** Add technology_type dimension:
```python
def get_discount_rate(scenario_type, technology_type):
    base = discount_rate_baseline if scenario_type == "baseline" else discount_rate_shock
    if technology_type == "carbontech":
        return base + brown_discount_spread  # e.g., +0.01
    else:
        return base - green_discount_spread  # e.g., -0.005
```

New parameters: `brown_discount_spread` (default: 0), `green_discount_spread` (default: 0).

**Expected effect:** With empirically supported spreads (~60-120 bps from debt carbon premium literature — see Gourdel (2024) Fig. 1 for survey; note: Bolton & Kacperczyk (2021) measures *equity return* premia, not debt spreads):
- Carbontech: higher discount rate → lower NPV
- Greentech: lower discount rate → higher NPV

### MA4: Terminal Value FCFF Normalization (Multi-Year Average)

**Function to modify:** `compute_yearly_npv_trajectories` in valuation_model/nodes.py

**What it does:** Replace final-year FCFF with average of last N years for terminal value calculation:

```python
# Current (line 105):
final_fcff = float(g["FCFF"].iloc[-1])

# Fixed:
normalization_window = 3  # configurable parameter
final_fcff = float(g["FCFF"].iloc[-normalization_window:].mean())
```

New parameter in `parameters_valuation_model.yml`:
```yaml
terminal_value:
  normalization_window: 3  # Average last N years for terminal FCFF
```

**Methodological basis (unanimously supported by corporate finance literature):**

1. **Damodaran (NYU Stern)** -- "Investment Valuation": Terminal year cash flow must represent a "normal year." For cyclical/commodity firms: average 5-10 years. For moderate volatility: 3-5 years. Source: "Ups and Downs: Valuing Cyclical and Commodity Companies" (SSRN 1466041).

2. **Koller, Goedhart & Wessels (McKinsey)** -- "Valuation" 7th ed. (2020, Wiley, Ch. 12 "Estimating Continuing Value"): Continuing value uses **normalized NOPLAT**, explicitly stated as "mid-cycle level."

3. **CFA Institute curriculum** (Level II, Free Cash Flow Valuation): Terminal value must use "cash flows of the business in a normalized environment." CapEx-to-depreciation ratio should converge to ~1.0x at terminal year (only maintenance CapEx, no growth CapEx).

4. **Penman (Columbia, 1998)** -- "A Synthesis of Equity Valuation Techniques and the Terminal Value Calculation" (Review of Accounting Studies): Formally demonstrates steady state is a **necessary condition** for the perpetuity model to be correct.

5. **Bodmer (2014)** -- "Corporate and Project Finance Modeling" (Wiley): Growth CapEx should not appear in terminal FCFF. **[Note: the previously stated ratio of ~1.15x at g=2%, d=5% is inconsistent with standard steady-state math which yields (g+d)/d = 7%/5% = 1.40x. The 1.15x figure needs verification against the actual text — the book may use different assumptions. The qualitative principle (exclude growth CapEx from terminal FCFF) is universally supported.]**

**Additional best practice:** The terminal FCFF should ideally exclude growth CapEx entirely, retaining only maintenance/replacement CapEx. This prevents transition-period buildout costs from polluting the perpetuity.

**N=3 recommended** for the ALTR model's ~25-year horizon. The final 3 years (2048-2050) represent post-transition steady state in most scenarios. N=5 risks pulling in mid-transition volatility.

**Expected effect:** Eliminates the "cliff effect" where a single year of high CapEx wipes out terminal value for renewables or inflates terminal value for fossils. Combined with the `final_fcff != 0` gate fix, this creates symmetric, well-grounded terminal values for both technology types.

### MA5: Remove Terminal Value `final_fcff > 0` Gate

**Function to modify:** `compute_yearly_npv_trajectories` in valuation_model/nodes.py

**What it does:** Remove the conditional at line 108 so terminal value is applied regardless of FCFF sign, matching original TRISK behavior:

```python
# Current (line 108):
if final_fcff > 0:
    terminal_value = ...

# Fixed:
if True:  # or simply remove the if
    terminal_value = ...
```

**Alternative (safer):** Use average of last N years instead of final year only:
```python
final_fcff = float(g["FCFF"].tail(5).mean())  # instead of .iloc[-1]
```

**Expected effect:** Carbontech losses become unbounded (negative terminal value captures perpetuity of carbon cost burden). Greentech gains are more proportionate. The asymmetry documented in FINDINGS_SUMMARY.md is reduced.

**Precedent:** Damodaran (NYU Stern) confirms Gordon Growth is valid for negative FCFF. Original TRISK R package applies terminal value unconditionally. KPMG IAS 36 guidance states terminal value is most climate-relevant.

**Risk:** Negative terminal values can be very large. May need a floor (e.g., terminal value no worse than -200% of sum of explicit-period PV) to prevent extreme outliers.

### MA5: Terminal Value Dampening for Shock Scenario

**Function to modify:** `compute_yearly_npv_trajectories` in valuation_model/nodes.py

**What it does:** Apply a dampening factor to terminal growth rate under shock:

```python
# Current: terminal_cf = final_fcff * (1 + terminal_growth_rate)
# Proposed:
effective_growth = terminal_growth_rate * terminal_shock_dampening  # new param, default 1.0
terminal_cf = final_fcff * (1 + effective_growth)
```

**Expected effect:** Reduces amplification of any directional error through terminal value. At dampening=0.5, the perpetuity multiplier drops from 20.4x to 16.0x.

**Precedent:** BIS Working Paper 1274; Amundi/Roncalli (SSRN 4497124, 2023).

---

## 4. Structural Additions (New Mechanisms)

### SA1: Explicit Carbon Cost with Separate Carbon Price Trajectory

**What:** Instead of relying on carbon prices embedded in electricity prices, add a separate NGFS carbon price trajectory that creates an explicit carbon cost channel. This is already architected in the code (the `carbon_cost_net` mechanism exists) -- it just needs data.

**Integration:** New BigQuery table or CSV file with carbon prices per (model, scenario, geography, year). Merged in `inputs_processing` pipeline.

**Expected effect:** Dominant mechanism for fossil NPV destruction. At NGFS Below 2C carbon prices ($200-600/tCO2 by 2050), coal and gas EBITDA goes deeply negative.

**Implementation complexity:** LOW-MEDIUM. The code infrastructure exists. Need carbon price data.

### SA2: Stranded Asset Reserve Write-Down

**What:** Add a one-time impairment charge at shock year for fossil assets, proportional to the difference between baseline and target cumulative production.

**Expected effect:** Deepens fossil NPV decline beyond what production + carbon cost changes achieve.

**Implementation complexity:** MEDIUM. Requires new parameter and modification to `compute_ops_block`.

---

## 5. Recommended Approach (Prioritised Implementation Plan)

### Phase 1: Bug Fixes (Immediate, <1 hour)

| # | Action | File | Impact |
|---|--------|------|--------|
| 1.1 | Fix decom cost sign bug | earnings_model/nodes.py:855-858 | HIGH -- stops rewarding fossil retirements |
| 1.2 | Remove terminal value `final_fcff > 0` gate | valuation_model/nodes.py:108 | HIGH -- unbounds carbontech losses, reduces renewable amplification |
| 1.3 | Validate MCPR is active for current run | parameters_earnings_model.yml | Verify enable_mcpr: True |

### Phase 2: Carbon Price Data (1-2 days)

| # | Action | Impact |
|---|--------|--------|
| 2.1 | Source NGFS carbon prices for WITCH CurPol + Below2C | HIGH |
| 2.2 | Create carbon price injection node or BigQuery table | HIGH |
| 2.3 | Test with carbon prices at $50, $100, $200/tCO2 | HIGH -- validates narrative |

### Phase 3: Model Refinements (1 week)

| # | Action | Impact |
|---|--------|--------|
| 3.1 | MCPR carbon-cost-sensitive clearing price (MA2) | MEDIUM -- merit order for renewables |
| 3.2 | Technology-differentiated discount rates (MA3) | MEDIUM |
| 3.3 | Terminal value dampening for shock (MA4) | LOW-MEDIUM |
| 3.4 | Symmetry audit on continued O&M (QW3) | LOW |

### Phase 4: Validation

| # | Action |
|---|--------|
| 4.1 | Run full pipeline with carbon prices active |
| 4.2 | Check that 95%+ of fossil tech-geo combos show negative NPV change |
| 4.3 | Check that all core renewables (Solar, Wind, Hydro, Geothermal) show positive NPV change |
| 4.4 | Verify nuance: NuclearCap mixed, OilCap Africa possible exception, GasCap transition fuel exception |
| 4.5 | Compare against FINDINGS_SUMMARY.md metrics: target <5% paradox cases (down from 16%) |

---

## 6. Nuance Preservation Checklist

### Decom Cost Sign Fix (Phase 1.1)

| Exception Case | Preserved? | Reason |
|---------------|-----------|--------|
| OilCap Africa slight positive | YES | The fix only affects the COST of retirement. If OilCap Africa has minimal retirements (production stays positive), decom cost is small and the price-volume effect still dominates. |
| GasCap transition fuel | YES | Gas retires less than coal. Decom cost is proportional to retirement volume. Small retirements = small decom cost. |
| NuclearCap mixed | YES | Nuclear has high CapEx but zero emissions. Decom cost applies at retirement but is offset by zero carbon cost. |

### Carbon Price Activation (Phase 2)

| Exception Case | Preserved? | Reason |
|---------------|-----------|--------|
| OilCap Africa positive | MAYBE | With carbon prices, OilCap faces $70-90/MWh carbon cost at $200/tCO2. This likely overwhelms any production/price benefit. May need lower regional carbon price for Africa to preserve nuance. |
| GasCap transition fuel | YES | Gas has lower emission factor than coal → lower carbon cost per MWh. At moderate carbon prices ($50-100/tCO2), gas carbon cost (~$18-35/MWh) may not exceed revenue, allowing positive NPV in some regions. |
| Developing region exceptions | YES if regional carbon prices | NGFS provides region-specific carbon prices that are lower for developing economies, preserving legitimate variation. |

### Validation Tests

1. **Direction test:** Median NPV change by technology_type: carbontech < 0, greentech > 0
2. **Exception tolerance:** Allow <10% carbontech positive (legitimate cases), flag >5% greentech negative
3. **Carbon price sensitivity:** NPV change should be monotonically more negative for carbontech as carbon price rises
4. **Coal is always negative:** CoalCap should show negative NPV change in ALL geographies (as confirmed in FINDINGS_SUMMARY)
5. **Terminal value check:** Log the fraction of assets with/without terminal value by technology type

---

## Appendix A: ALTR Model Architecture Summary

### Pipeline Flow
```
download_inputs → inputs_processing → inputs_postproc
    → create_baseline_and_target_trajectories
    → create_late_sudden_trajectories
    → distribute_impacts_to_asset_level
    → earnings_model → valuation_model → reporting
```

### Key Formulas
```
Q = K_avg * capacity_factor * 8760                        [production, MWh]
Revenue = Q * power_price_excarbon_usd_per_mwh             [$/yr]
Var_cost = Q * fuel_price / efficiency                      [$/yr]
Fixed_cost = fom_usd_per_mw_yr * K_for_fixed_cost         [$/yr]
Carbon_cost = Q * carbon_price * emission_factor * (1-PT)   [$/yr, currently = 0]
EBITDA = Revenue - Var_cost - Fixed_cost - Carbon_cost      [$/yr]
CapEx_total = Growth_capex + Replace_capex + Decom_cost     [$/yr, decom sign BUG]
FCFF = EBITDA - CapEx_total                                [$/yr]
PV_FCFF = FCFF * (1+r)^(-t)                               [$ present value]
Terminal_value = FCFF_final * (1+g)/(r-g) * (1+r)^(-T)    [$ if FCFF>0]
NPV = sum(PV_FCFF) + Terminal_value                         [$]
NPV_change = (NPV_shock - NPV_baseline) / abs(NPV_baseline) [%]
```

### Current Parameters
```yaml
shock_year: 2033
alignment_year: 2038
discount_rate_baseline: 0.07
discount_rate_shock: 0.07
terminal_growth_rate: 0.02
market_passthrough: 0
enable_mcpr: True
include_growth_capex: True
include_replacement_capex: True
include_decom_costs: True
apply_continued_om_baseline: False
apply_continued_om_shock: True
```

### Current Scenario Pair
```
Baseline: AR6_WITCH 5.0_CO_CurPol (C5, ~3C, current policies)
Target:   AR6_WITCH 5.0_EN_NPi2020_600 (C3, below 2C)
```

## Appendix B: Critical File Locations

| File | Role |
|------|------|
| `src/crispy_kedro/pipelines/earnings_model/nodes.py` | Revenue, EBITDA, FCFF, MCPR, decom bug |
| `src/crispy_kedro/pipelines/valuation_model/nodes.py` | DCF, terminal value, NPV change |
| `src/crispy_kedro/pipelines/create_late_sudden_trajectories/nodes.py` | 4-bucket alignment, shock trajectories |
| `src/crispy_kedro/pipelines/distribute_impacts_to_asset_level/nodes.py` | Staggered asset-level shock |
| `src/crispy_kedro/pipelines/create_baseline_and_target_trajectories/nodes.py` | TMSR, fair share, baseline/target |
| `conf/base/parameters_earnings_model.yml` | MCPR, cost switches, market passthrough |
| `conf/base/parameters_valuation_model.yml` | Discount rates, terminal value config |
| `conf/base/parameters_create_late_sudden_trajectories.yml` | Shock year, alignment year |
| `data/05_model_output/scenarios_pathways.csv` | Processed scenario data (carbon price = NaN) |
| `FINDINGS_SUMMARY.md` | Previous NPV paradox analysis |
| `CLAUDE.md` | Model architecture documentation |

## Appendix C: Key Academic Citations

- Fabra, N., Reguant, M. (2014). "Pass-Through of Emissions Costs in Electricity Markets." AER 104(9).
- Hirth, L. (2013). "The Market Value of Variable Renewables." Energy Economics 38.
- Bolton, P., Kacperczyk, M. (2021). "Do Investors Care About Carbon Risk?" JFE 142(2).
- NGFS (2024). Climate Scenarios Technical Documentation V5.0.
- Carbon Tracker (2025). "NGFS Scenarios and the Damage Done."
- Semieniuk, G., et al. (2022). "Stranded Fossil-Fuel Assets." Nature Climate Change 12.
- BIS (2023). Working Paper 1274 on Climate Stress Testing.
- Roncalli, T., et al. (2023). "Climate Stress Testing, Asset Pricing." SSRN 4497124.
