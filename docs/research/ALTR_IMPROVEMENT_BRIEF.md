# ALTR Framework Improvement Brief
**Based on analysis of 27 papers against the crispy-kedro codebase**
**April 2026 (v2 — includes contagion analysis, NPV paradox assessment, cement project)**

---

## Executive Summary

Four parallel research agents read the methodology sections of 27 papers from the Reading library and compared them against ALTR's current implementation in `crispy-kedro/src/crispy_kedro/pipelines/`. This brief identifies **24 specific improvements** organized by framework component, ranked by impact-to-effort ratio.

ALTR is significantly more advanced than the legacy TRISK model — it already has full EBITDA cost decomposition, technology-specific fuel/O&M/CapEx, MCPR pricing, and staggered asset-level retirement. The improvements below target what ALTR is still missing.

**Key finding:** No paper in the literature implements a true merchant model (merit order dispatch feeding into a structural credit model). Building this would be a genuine academic contribution.

**The NPV paradox is not a single bug but five interacting distortions.** Each independently pushes NPV changes toward zero or counterintuitive directions. Fixing the minimum set of five transforms the model's behavior qualitatively.

---

## Current ALTR Architecture

```
Scenario (AR6/NGFS)
  -> inputs_processing (filter, geography, carbon price injection)
    -> inputs_postproc (retirement dates, refurbishment)
      -> create_baseline_and_target_trajectories (TMSR, company trajectories)
        -> create_late_sudden_trajectories (4-bucket alignment, shock paths)
          -> distribute_impacts_to_asset_level (g-weights by asset age)
            -> earnings_model (revenue, fuel cost, FOM, carbon cost, CapEx -> EBITDA -> FCFF)
              -> valuation_model (DCF, terminal value, NPV, VaR)
                -> reporting
```

### What ALTR Already Has (vs. legacy TRISK)

| Feature | TRISK | ALTR |
|---------|-------|------|
| Profitability | `production * price * margin` | Full EBITDA: Revenue - Fuel/eta - FOM - Carbon - CapEx |
| Fuel costs | None | `fuel_price / efficiency` per asset, zero for renewables |
| Fixed O&M | None | `fom_usd_per_mw_yr * capacity`, continues on stranded capacity |
| CapEx | None | 3-stream: growth + replacement + decommissioning |
| Carbon cost | Price reduction | Differential above marginal generator's EF |
| Pricing | Single exogenous price | MCPR: marginal tech price x value factors |
| Asset retirement | Uniform | Staggered by asset age (logistic g-weights) |
| Alignment classification | Binary (overshoot/no overshoot) | 4-bucket (aligned/misaligned x increasing/decreasing) |
| Merton PD | Yes (basic) | **Not implemented** |

### What ALTR is Missing

1. No Merton PD / credit risk layer (stops at NPV/VaR)
2. No true merchant model (MCPR is static value factors, not dynamic dispatch)
3. No dynamic discount rates (parameters exist but set to 0)
4. No network contagion layer
5. No multi-scenario uncertainty framework
6. Terminal value still dominates (~20x final FCFF)
7. Gas structural positive NPV (open architectural issue)
8. Near-term price windfall from hard baseline->target switch

---

## The NPV Paradox in ALTR

### What it is

16% of technology-geography combinations show HIGHER NPV under the shock scenario than under baseline — meaning fossil companies appear to BENEFIT from climate transition. This is directionally incorrect.

### Root causes and current status

| Root Cause | Description | Status | Impact |
|-----------|-------------|--------|--------|
| RC1 | Carbon prices all NaN from BigQuery | Partially fixed (injection node added) | Low for WITCH (prices already embed carbon) |
| RC2 | Decommissioning cost sign bug (`scrap * retired` was negative) | **Fixed** | HIGH — moved decline rate 52% -> 67% |
| RC3 | Terminal value gate (`if final_fcff > 0` excluded negative TV) | **Fixed** | Medium |
| RC4 | Near-term price windfall (target prices 30-50% higher at shock year) | **Open** | HIGH |
| RC5 | Gas as marginal generator (zero differential carbon cost) | **Open** | Medium |

### Sensitivity results after fixes

| Config | Carbon Decline % | Green Increase % | Carbon Median NPV | Paradox Count |
|---|---|---|---|---|
| Original | 52.3% | 48.7% | -30.8% | 1,258 |
| + Decom fix | 66.9% | 30.8% | -69.0% | 772 |
| ALL CHANGES | 66.7% | 33.3% | -55.7% | 775 |

---

## RC4: The Near-Term Price Windfall — Deep Dive

### The mechanism

The mixed shock surface is constructed with a hard switch at `shock_year`:

```python
mixed_scenario_surfaces = pd.concat([
    scenario_surfaces[(year < shock_year) & (scenario_type == "baseline")],
    scenario_surfaces[(year >= shock_year) & (scenario_type == "target")],
])
```

Before 2033 the company sees baseline prices. At 2033 it instantly sees target prices. The baseline trajectory uses baseline prices for all years.

### The data: target prices are HIGHER near-term

| Geography | Year | Baseline $/MWh | Target $/MWh | Jump |
|-----------|------|----------------|--------------|------|
| USA | 2033 | $49.4 | $64.4 | **+30%** |
| USA | 2050 | $55.0 | $41.5 | -25% |
| CHN | 2033 | $46.0 | $67.5 | **+47%** |
| CHN | 2050 | $52.1 | $39.0 | -25% |
| IND | 2033 | $33.6 | $50.9 | **+51%** |
| IND | 2050 | $38.3 | $33.1 | -14% |

All technologies receive these same prices (WITCH doesn't differentiate by technology). After MCPR adjustment, there's only ~10-15% differentiation via value factors.

### Why target prices are higher near-term (this is correct economics)

In a stringent transition scenario:
- **Near-term (2030s):** Carbon prices are imposed, expensive abatement is needed, fossil plants must retrofit or pay. The marginal cost of electricity rises because the system is still fossil-dependent but paying carbon costs.
- **Long-term (2040s-2050s):** Cheap renewables dominate, the marginal generator shifts from gas to solar/wind, the market clearing price falls below current-policy baseline.

The IAM is modeling this correctly in aggregate. The problem is not the data.

### The architectural problem: hard switch + discounting

The hard switch creates a discontinuous price jump at shock_year. Combined with the late-sudden production trajectory, here's what happens to a coal company:

```
Year:       2030  2031  2032  | 2033   2034   2035   ...  2045   2050
                              | <- shock_year
Price:      $49   $49   $49   | $64    $63    $61    ...  $45    $42
            <- baseline ->     | <- target (initially HIGHER) ->

Production: 70    70    70    | 65     55     45    ...  10     0
            <- baseline ->     | <- declining under shock ->
```

Revenue under each trajectory:

| Year | Baseline Revenue | Shock Revenue | Delta |
|------|-----------------|---------------|-------|
| 2033 | 70 x $49 = $3,430M | 65 x $64 = $4,160M | **+$730M** |
| 2034 | 70 x $50 = $3,500M | 55 x $63 = $3,465M | -$35M |
| 2035 | 70 x $51 = $3,570M | 45 x $61 = $2,745M | -$825M |
| ... | | | |
| 2050 | 70 x $55 = $3,850M | 0 x $42 = $0 | -$3,850M |

The near-term revenue windfall at 2033-2034 partially offsets the long-term production decline. With 7% discounting, near-term cash flows have much higher present value weight. The windfall in years 1-2 disproportionately inflates the shock NPV.

### This affects ALL technologies

- **Coal/Gas:** Lose production but gain price near-term -> NPV less negative than it should be, sometimes positive
- **Solar/Wind:** Gain production AND gain price near-term -> NPV more positive than it should be (double tailwind)

The net effect: NPV_shock - NPV_baseline is pushed upward for everyone. For fossils, this can flip the sign (the paradox). For renewables, it exaggerates the benefit.

### Three possible fixes

**Fix A — Ramp the prices (simplest, most defensible):**

Instead of a hard switch, linearly blend baseline and target prices over the transition window:

```python
# In assemble_asset_panel, replace the hard concat with:
if year < shock_year:
    price = baseline_price
elif year < alignment_year:
    blend = (year - shock_year) / (alignment_year - shock_year)
    price = baseline_price * (1 - blend) + target_price * blend
else:
    price = target_price
```

This makes the price transition gradual — matching the production transition. The near-term windfall is smoothed because the company doesn't immediately receive full target prices.

Conceptually clean: if the company transitions gradually (late & sudden ramp from shock_year to alignment_year), it should face gradually transitioning prices too.

**Fix B — MCPR smoothing (moderate):**

Compute the MCPR reference price as the baseline marginal price pre-shock and the target marginal price post-shock, then ramp between them. The MCPR already partially dampens the windfall via value factors, but doesn't smooth the underlying price signal.

**Fix C — Price decomposition (most rigorous, hardest):**

Decompose the target price:
```
target_price = carbon_free_price + carbon_cost_on_marginal_generator
```

Apply the carbon-free price as the market clearing price (which is typically LOWER than baseline once renewables enter) and the carbon cost explicitly via the differential carbon cost mechanism. This avoids double-counting AND eliminates the windfall because the carbon-free component of the target price is typically lower than baseline.

This is effectively what the ALTR NPV research doc recommends for AIM/CGE scenarios. For WITCH, the decomposition requires estimating how much carbon the IAM already embedded in its price.

**Assessment:**

| Fix | Complexity | NPV Paradox Impact | Side Effects |
|-----|-----------|-------------------|--------------|
| A: Price ramp | Simple (~10 lines in `assemble_asset_panel`) | **High** — eliminates discontinuous windfall | Changes economic narrative (gradual vs. abrupt) |
| B: MCPR smoothing | Moderate (modify `apply_mcpr_adjustment`) | **Medium** — dampens but doesn't eliminate | MCPR already partially does this |
| C: Price decomposition | High (IAM-specific carbon content estimation) | **Highest** — fixes root cause | Requires per-IAM calibration |

---

## RC5: Gas Structural Positive — Deep Dive

### The mechanism

Gas is typically the marginal generator. The MCPR sets the market clearing price based on the highest-priced marginal technology (Gas, Coal, Oil, Biomass). Gas receives a value factor of 1.0.

The differential carbon cost formula:
```
excess_ef = max(emission_factor - marginal_emission_factor, 0)
carbon_cost = Q * carbon_price * excess_ef * (1 - passthrough)
```

Since gas IS the marginal generator (or very close), `excess_ef ≈ 0`. Gas pays virtually zero differential carbon cost. Meanwhile, gas production declines slowly (it's the "bridge fuel" in most scenarios), and the near-term price windfall applies fully.

### Why this matters

Gas companies show positive NPV under transition because:
1. Zero or near-zero differential carbon cost
2. Full near-term price windfall (same as coal)
3. Slower production decline than coal (bridge fuel role)
4. Moderate fixed O&M relative to revenue

### Possible fixes

1. **Use full emission factor, not differential:** `carbon_cost = Q * cp * EF * (1 - passthrough)` — treats carbon cost as an absolute OPEX, not relative to the marginal generator. This is simpler but inconsistent with the MCPR logic (which assumes the market price already reflects marginal carbon cost).

2. **Model gas displacement by renewables:** As VRE capacity grows, gas utilization drops and its capture price falls (fewer hours as the marginal generator). Dynamic MCPR value factors that worsen for gas as VRE penetration rises would capture this.

3. **Separate carbon cost for marginal vs. infra-marginal:** The marginal generator sets the market price (including its carbon cost). Infra-marginal generators earn a surplus equal to the difference between the market price and their own marginal cost. Gas as the marginal generator earns zero surplus from carbon. But if renewables push gas OUT of the marginal position, gas must pay full carbon cost as an infra-marginal generator that can no longer set the price. This is the merit order effect — and implementing it properly leads to M6 (full merit order dispatch).

---

## Unified Priority List for ALTR (All 24 Improvements)

### Tier 1: Critical — Directly Addresses NPV Paradox

| # | Improvement | NPV Paradox? | Complexity | Source |
|---|-----------|-------------|------------|--------|
| **RC4** | **Smooth price transition** (ramp baseline->target over shock window) | **YES** — eliminates near-term windfall | Simple | Architectural fix |
| **RC5** | **Gas carbon cost fix** (full EF or dynamic MCPR value factors) | **YES** — gas stops showing positive NPV | Moderate | Architectural fix |
| **D2** | **Stranding-aware terminal value** — cap TV for declining techs, or `TV = max(normalized_fcff, 0) * multiplier` | **YES** — prevents 20x amplification of stressed FCFF | Simple | Gourdel (2024) |
| **D1** | **Activate brown/green discount spreads** (params exist, set to 0) | **YES** — compresses carbontech NPV, expands greentech | Simple | Bolton & Kacperczyk; all papers |
| **M2** | **Dynamic MCPR** — value factors respond to VRE penetration per scenario year | **YES** — as renewables grow, capture price drops further | Moderate | Cormack (2020) |

### Tier 2: High Impact — Extends ALTR Capabilities

| # | Improvement | NPV Paradox? | Complexity | Source |
|---|-----------|-------------|------------|--------|
| **S1** | **Company-level heterogeneity** (alpha parameters replacing uniform TMSR) | Partial | Moderate | CERM (Garnier, Eq. 41-42) |
| **M1** | **Merton PD layer** — convert NPV to probability of default. **When building this, resurface Gourdel (2024):** (a) carbon premium in lending rates creates feedback loop between PD and interest rate; (b) interest cost enters through firm-specific discount factor `rho = (1-delta)/(1 + kappa(1-tau))`, creating a valuation feedback loop (not a direct FCFF subtraction); (c) endogenous interest rate `kappa = r + mu + (LGD*EDF)/(1-EDF)` where EDF depends on firm value which depends on kappa (solve simultaneously, Gourdel Eq. 9-10, Section 4.5). See also: Reinders for base Merton (static parameters, closed-form NPV→PD), Cormack for time-dependent drift + dynamic leverage via debt covenants, Le Guenedal for jump-diffusion with Bayesian scenario updating (applied to bond pricing, adaptable to NPV). | No (new output) | Medium | Reinders (2020), **Gourdel (2024)**, Cormack (2020), Le Guenedal (2022) |
| **N1** | **Veraart contagion module** (Layer 3 post-processor) | No (systemic amplification) | Moderate | Veraart; Pang & Shrimali |
| **P1** | **Country-asset-specific scenarios** (cement sector extension with SFI data) | Partial | Moderate | Project 1 design |
| **C4** | **Wright's Law learning curves** for technology cost trajectories | Partial | Moderate | Way et al. (2022) |
| **S2** | **Experience-curve-based prices** replacing linear interpolation | Partial | Moderate | Way et al. (2022) |
| **C3** | **Sector-specific carbon cost pass-through rates** (cement 65%, auto 30%) | **YES** | Simple | Barclays (2021) |

### Tier 3: Medium Impact

| # | Improvement | NPV Paradox? | Complexity | Source |
|---|-----------|-------------|------------|--------|
| **D3** | **Dynamic leverage under stress** (needs Merton first) | YES (if Merton added) | Low-Medium | Cormack (2020) — debt covenant `debt(t) <= d_ratio^UB × EBITDA(t)` produces dynamic leverage. ~~Reinders (2020)~~ assumes static Merton parameters. |
| **M4** | **Rating-dependent volatility** (needs Merton first) | YES (if Merton added) | Low-Medium | Cormack (2020) |
| **M3** | **Total asset value loss (xi → 1) = certain default** (needs Merton first). Note: Merton equity cannot go negative (call option floor at zero); the relevant case is total asset destruction where distance-to-default → -∞. | YES (if Merton added) | Simple | Reinders (2020), Section 4 |
| **G1** | **Gourdel carbon premium feedback loop** (needs Merton first) — endogenous interest rate where PD ↔ borrowing cost are solved simultaneously. Interest cost enters through firm-specific discount factor `rho = (1-delta)/(1 + kappa(1-tau))`, not as direct FCFF subtraction. Climate-conditional lending rates. | YES (if Merton added) | Medium-High | Gourdel (2024) |
| **D4** | **Debt covenant constraints** (cap borrowing by EBITDA ratio) | No | Moderate | Cormack (2020) |
| **D5** | **Separate ST/LT debt** with industry-specific default point | No | Low | Yang et al. (KMV) |
| **D6** | **Probability-weighted multi-scenario NPV** | No | Medium | Le Guenedal (2022) |
| **N2** | **Entropy-reconstructed exposure matrix** for contagion module | No | Moderate | Pang & Shrimali |
| **P2** | **Cement TMSR adaptation** for demand-driven sectors | Partial | Medium | Calipel et al. |
| **P3** | **SFI vs Asset Impact data comparison** | No | Low | Project 1 design |

### Tier 4: Frontier (Research-Grade)

| # | Improvement | NPV Paradox? | Complexity | Source |
|---|-----------|-------------|------------|--------|
| **M6** | **Merit order dispatch model** (novel academic contribution) | **YES** | Very High | No paper does this |
| **M5** | **Monte Carlo Climate VaR** — probabilistic loss distribution via MC draws over valuation parameters (Level 1: discount rate, terminal growth, spread; Level 2: + carbon price, pass-through; Level 3: full Desnos/Roncalli with I-O and copula). See `docs/research/CLIMATE_VAR_MONTE_CARLO_PROPOSAL.md` for full methodology, literature review (Desnos/Amundi, MSCI CVaR, Moody's, Le Guenedal Bayesian weighting), and implementation plan. | Partial | Level 1: Low-Med; Level 2: Med; Level 3: High | Desnos et al. (2023), MSCI, Le Guenedal (2022) |
| **S3** | **Multiple shock channels per sector** | Partial | High | Calipel et al. |
| **N3** | **Cross-holdings extension** (Elsinger) | No | High | Elsinger (2009) |

---

## Minimum Viable Set to Fix the NPV Paradox

If you can only do 5 changes:

1. **RC4** — Ramp prices from baseline to target over the shock window (eliminates windfall)
2. **D2** — Stranding-aware terminal value (prevents 20x amplification of stressed FCFF)
3. **D1** — Activate brown/green discount spreads (already parameterized, just set to non-zero)
4. **RC5** — Fix gas carbon cost (either full EF or dynamic MCPR value factors)
5. **M2** — Dynamic MCPR value factors by VRE penetration (solar capture price drops as solar grows)

These five target five distinct root causes of the paradox. RC4 fixes the price discontinuity. D2 fixes terminal value domination. D1 fixes uniform discounting. RC5 fixes gas free-riding. M2 fixes static VRE pricing. Together they address every mechanism that pushes the NPV signal toward zero or positive for carbontech.

---

## Implementation Roadmap

### Phase 1: NPV Paradox Fixes (1-2 weeks)

| ID | Change | Files Affected | Lines of Code |
|----|--------|---------------|---------------|
| RC4 | Price ramp (Fix A) | `earnings_model/nodes.py` (assemble_asset_panel, ~line 639) | ~15 lines |
| D1 | Set brown_discount_spread to +0.01, green to -0.005 | `conf/base/parameters_valuation_model.yml` | 2 lines |
| D2 | Cap terminal value: `TV *= max(min(normalized_fcff/baseline_fcff, 1.5), 0)` | `valuation_model/nodes.py` (~line 148) | ~10 lines |
| RC5 | Dynamic MCPR value factors for gas declining with VRE share | `earnings_model/nodes.py` (apply_mcpr_adjustment, ~line 476) | ~30 lines |

### Phase 2: New Capabilities (2-4 weeks each)

| ID | Change | Files Affected |
|----|--------|---------------|
| M1 | Merton PD layer (new pipeline) | New `credit_risk_model/` pipeline |
| S1 | Company-level alpha parameters | `create_late_sudden_trajectories/nodes.py` |
| P1 | Country-asset-specific scenarios | `inputs_processing/nodes.py` |
| C4 | Wright's Law cost curves | `earnings_model/nodes.py` (new cost projection module) |

### Phase 3: Frontier (1-2 months each)

| ID | Change | Files Affected |
|----|--------|---------------|
| N1 | Veraart contagion module | New `contagion_model/` pipeline |
| M6 | Merit order dispatch | New `merit_order/` pipeline replacing MCPR |
| M5 | Monte Carlo framework | Architecture change across valuation pipeline |

---

## Top 5 Priority Papers to Deep-Read

1. **Cormack et al. (2020)** — `RELEVANT.transition_risk.cormack_energy_transition_financial_risks.pdf`
   *Why:* Only paper with LCOE-based pricing and time-dependent Merton drift. Closest to a merchant model. Blueprint for dynamic MCPR and Merton layer.

2. **Reinders et al. (2020)** — `RELEVANT.climate_stress_test.reinders_finance_approach_cst.pdf`
   *Why:* Most portable Merton extension. Clean closed-form equations for translating NPV shocks to PD. Shows leverage amplification (15-37% underestimation from sector averages).

3. **Way et al. (2022)** — `RELEVANT.transition_risk.way_etal_technology_forecasts_energy_transition.pdf`
   *Why:* Empirically calibrated cost learning curves (Wright's Law). Replaces assumption of static technology costs.

4. **Gourdel (2024)** — `RELEVANT.credit_risk.gourdel_credit_climate_sentiments.pdf`
   *Why:* Stranding-aware terminal value and interest-rate feedback equilibrium.

5. **Veraart (2020)** — `financial_contagion.veraart_distress_default_contagion.pdf`
   *Why:* Parsimonious contagion model with 5 interpretable parameters. Related contagion work by Pang & Shrimali (SSRN 4905653, 2024) uses Barucca's framework (which subsumes Veraart) within the CGFI/TRISK research ecosystem, applied to developing Asian economies.

---

## Network Contagion: Three Models Compared

### Papers reviewed

| Feature | Barucca et al. | Elsinger | Veraart |
|---------|---------------|----------|---------|
| Mechanism | General framework (unifies clearing + ex-ante) | Clearing with cross-holdings + seniority | Distress + default contagion |
| Pre-default losses | Yes (ex-ante EN) | No | Yes (Beta CDF parameterization) |
| Cross-holdings | No | Yes | No |
| Key equation | `E = Phi(E)` fixed point | Nested: `V=f(p), p=g(V)` | `E = Phi(E)` with 5-param valuation |
| Python code | `github.com/marcobardoscia/neva` | Algorithm provided | Straightforward iteration |
| Data needs | Exposure matrix, volatility | + cross-holdings + seniority | Exposure matrix + 5 parameters |

### Recommended: Veraart

- Fewest data requirements (no cross-holdings needed)
- 5 parameters with clear economic meaning: capital cushion (k), recovery rates (R, beta), distress shape (a, b)
- Subsumes Eisenberg-Noe and Rogers-Veraart as special cases
- Handles distress contagion (mark-to-market) — empirically the dominant channel (~2/3 of crisis losses)
- Applied within the CGFI/TRISK research ecosystem by Pang & Shrimali (SSRN 4905653, 2024) using Barucca's network valuation framework on developing Asian economies with NGFS scenarios

### Integration architecture

```
ALTR Pipelines (existing)
  -> Company-level NPV shocks + FCFF trajectories
  -> Exposure mapping: x_i = SUM_j(exposure_ij * loss_fraction_j)
  -> Veraart fixed-point: E* = Phi(E)
  -> System-wide losses, cascade defaults, amplification ratio
```

---

## Cement Sector Extension (Project 1)

### Country-asset-specific scenario construction

```
Current:  Company C (UK HQ) -> UK scenario -> uniform TMSR
Proposed: Company C -> UK(30%), France(25%), India(25%), Thailand(20%) assets
          -> country-specific scenarios per asset
          -> weighted company-level shock
```

### Key questions

1. **TMSR for cement:** Cement demand is construction-driven, not tech-substitution-driven. Calipel et al. identified 4 distinct risk drivers: carbon price, green cement innovation, demand reduction, CCS maturity. TMSR only captures one.
2. **Pass-through:** Cement can partially pass costs (regional markets, high transport costs). Barclays estimates 65% for cement vs 30% for automotive. Needs sector calibration.
3. **Data comparison:** SFI vs Asset Impact — coverage, quality, and results divergence.

---

## Merton Model Limitations for Climate Risk

From Monasterolo's framework and confirmed by paper analysis:

| Merton Assumption | Why It Fails for Climate | ALTR Impact | Fix |
|-------------------|------------------------|-------------|-----|
| Static debt threshold | Constant default barrier ignores refinancing risk under stress | Not applicable (ALTR has no Merton yet) | When adding M1: use dynamic leverage R/(1-xi) |
| Normal distribution (thin tails) | Climate shocks are fat-tailed, non-linear, with tipping points | Not applicable yet | When adding M1: consider jump-diffusion (Le Guenedal) |
| Scenario-independent volatility | Stressed firms should have higher asset volatility | Not applicable yet | When adding M1: rating-dependent sigma (Cormack) |
| Backward-looking calibration | Historical data doesn't capture forward-looking transition risk | Partially addressed (forward-looking scenarios) | Continue using scenario-based approach |
| Single-period | No maturity structure, no dynamic capital decisions | Not applicable yet | When adding M1: multi-period Merton (Cormack) |

These limitations apply if/when ALTR adds a Merton layer (improvement M1). The key insight: when building M1, don't implement vanilla Merton — incorporate the extensions from the literature from the start.

---

## Key Academic Insights

> **Building a merit order dispatch model that feeds technology-specific capture prices into a Merton structural credit model with scenario-dependent drift would be a genuine academic contribution.** No paper in the reviewed literature does this end-to-end. The closest is Cormack (LCOE-weighted blended price), but even that doesn't compute capture prices or model supply-demand clearing. This is the gap where ALTR can lead rather than follow.

> **The NPV paradox is five interacting distortions** — near-term price windfall (RC4), gas free-riding on marginal position (RC5), terminal value domination (D2), uniform discounting (D1), and static VRE pricing (M2). Each independently mutes the transition signal. Together they make ALTR appear insensitive to scenarios. The minimum viable fix set targets all five.

---

## References (Paper Locations)

All papers referenced are in `~/Desktop/Reading/` organized by topic folder. See `~/Desktop/Reading/MASTER_INDEX.md` for the full inventory and `~/Desktop/Reading/CLAUDE.md` for the organization workflow.

Key files:
- `climate_stress_test/RELEVANT.climate_stress_test.reinders_finance_approach_cst.pdf`
- `transition_risk/RELEVANT.transition_risk.cormack_energy_transition_financial_risks.pdf`
- `transition_risk/RELEVANT.transition_risk.way_etal_technology_forecasts_energy_transition.pdf`
- `credit_risk/RELEVANT.credit_risk.gourdel_credit_climate_sentiments.pdf`
- `climate_stress_test/RELEVANT.climate_stress_test.garnier_cerm_climate_extended_risk_model.pdf`
- `climate_stress_test/RELEVANT.climate_stress_test.le_guenedal_2022_thesis.pdf`
- `climate_stress_test/RELEVANT.climate_stress_test.farmer_kleinnijenhuis_stress_testing_macrocosm.pdf`
- `climate_stress_test/RELEVANT.climate_stress_test.acharya_engle_nyfed_climate_stress_testing_2023.pdf`
- `financial_contagion/RELEVANT.financial_contagion.barucca_network_valuation.pdf`
- `financial_contagion/RELEVANT.financial_contagion.elsinger_networks_cross_holdings.pdf`
- `financial_contagion/financial_contagion.veraart_distress_default_contagion.pdf`
- `transition_risk/RELEVANT.transition_risk.khan_science_based_transition_risk_2024.pdf`
- `transition_risk/RELEVANT.transition_risk.calipel_sectoral_transition_risk_drivers.pdf`
- `transition_risk/RELEVANT.transition_risk.barclays_corporate_transition_forecast_2021.pdf`
- `climate_stress_test/RELEVANT.climate_stress_test.tang_cervenka_asset_level_power_sector.pdf`

---

## April 2026 Update: New Research Mapped to ALTR Framework

**Based on research conducted 2026-04-10/11 covering 2024-2026 literature. Full briefs in:**
- `/Users/jakub/Documents/repos/transport/climate_stress_testing_frontiers_literature.md`
- `/Users/jakub/Documents/repos/transport/agriculture_transition_risk_literature_review.md`
- Obsidian vault: `sources/jung_2025_crisk-jfe.md`, `sources/kerkhofs_2025_asset-level-tail-risk-physical.md`, `sources/fialkowski_2025_production-network-contagion.md`, `sources/howard_sterner_2025_damage-function-meta.md`, `sources/bressan_2024_asset-level-physical-risk.md`, `sources/reissl_2025_dsk-agent-based.md`

---

### New Capability: Physical Risk Module (P4) — High Priority

**Kerkhofs, Bernhofen, Borsuk, Baer, Ranger, Schoutens & Shrimali (2025)**, *Environmental Research: Climate*. **Same research group as TRISK** (Baer is co-author).

This paper provides a ready-made physical risk complement to ALTR's transition risk pipeline:

- Uses the **same DCF framework** as ALTR (paper cites Bressan et al. 2024 as the DDM predecessor; same research group as Tang & Cervenka)
- Three financial transmission channels: direct capital damages (83.2%), production disruption (16.8%), insurance premiums (tail risk only)
- **Copula-based spatial correlations** (Gaussian, t-Copula, R-vine) for portfolio-level tail risk
- Applied to India power sector (424 assets, 126 firms) — same asset class as ALTR

**Key quantitative findings:**
- Complete independence underestimates tail risks by up to 20% vs. copula models
- Complete dependence overestimates by 207%
- Insurance affects tail risk but not average impacts (23-96% higher tail risk without insurance)
- Correlation structure can triple the 95th percentile and quadruple the 99th percentile PD change (both Merton and empirical models show this pattern; Kerkhofs Section 3.3, p. 12)
- Average portfolio impact: -0.70% (baseline flood scenario)

**Integration architecture:**
```
ALTR existing pipelines (transition risk)
  -> Kerkhofs physical risk module (NEW)
     -> Hazard simulation (GIRI flood maps, copula-calibrated)
     -> Asset-level damage + disruption + insurance (DCF impact)
     -> Portfolio-level VaR via Monte Carlo with copula correlations
  -> Combined transition + physical risk NPV
```

**Supporting evidence:**
- Bressan et al. (2024, Nature Communications): **investor losses underestimated up to 70% without asset-level data, 82% without tail acute risk modelling**. This validates ALTR's bottom-up approach AND argues for adding physical risk.
- Commercial data now available: S&P Climanomics (7.1M locations), Jupiter (22.3B), MSCI (4M+), but GARP benchmark shows significant vendor divergence.

| # | Improvement | Complexity | Source |
|---|-----------|------------|--------|
| **P4** | **Kerkhofs physical risk module** — DCF-based, copula-correlated, three transmission channels | High (new pipeline) | Kerkhofs et al. (2025) |
| **P5** | **Bressan asset-level validation** — compare ALTR aggregate vs. asset-level physical risk estimates | Medium | Bressan et al. (2024) Nature Comms |

---

### Update to M1: Merton PD Layer — New References

**CRISK (Jung, Engle & Berner, JFE 2025):** First peer-reviewed market-based climate systemic risk measure in a top-3 finance journal. Three variants: CRISK (climate stress capital shortfall), mCRISK (isolates climate from market), S&CRISK (compound climate+market). Moves from scenario-dependent periodic exercises to continuous market-implied monitoring.

**BIS WP 1274 (2025):** Extends Vasicek model with physical risk component. Key finding: "absence of generally accepted industry models of credit risk adjusted for physical risk factors." Asset devaluation >30% for ~5% of firms; PDs below investment-grade for ~16%.

**Implication for M1:** When building ALTR's Merton layer, consider offering both:
1. Classic Merton (Reinders, Gourdel) — scenario-dependent, periodic
2. CRISK-style market-implied — continuous monitoring, compound scenarios

Updated M1 reference list:
- Reinders (2020) — base Merton with deterministic carbon cost shocks
- Cormack (2020) — time-dependent drift, rating-dependent volatility
- Le Guenedal (2022) — jump-diffusion with Bayesian scenario updating
- **Gourdel (2024)** — carbon premium feedback loop, stranding-aware TV
- **Jung, Engle & Berner (2025) — CRISK** (market-based alternative)
- **BIS WP 1274 (2025)** — Vasicek physical risk extension
- **Kerkhofs et al. (2025)** — Merton PD from physical risk shocks (empirical vs structural comparison)

---

### Update to N1: Contagion Module — New Evidence

**Fialkowski, Diem, Borsos & Thurner (Feb 2025)**, arXiv:2502.17044. First model integrating production network dynamics with interbank contagion. ~1M firm supply chain links + bank-firm loans + interbank network.

**Key finding: when production network contagion is included, interbank contagion increases by 70%. Financial systemic risk up 28%.**

This strengthens the case for N1 (Veraart contagion module) but also suggests a **supply chain layer** between ALTR's firm-level outputs and the contagion module:

```
ALTR (firm-level NPV shocks)
  -> Supply chain propagation (Fialkowski/Tabachova)
     -> Veraart financial contagion (existing N1 plan)
        -> System-wide losses
```

**Tabachova et al. (2024, J. Financial Stability, DOI: 10.1016/j.jfs.2024.101336):** Supply chain network contagion amplifies expected banking losses by 4.3x, VaR by 4.5x, and expected shortfall by 3.2x. A small fraction of firms carry substantial systemic risk, affecting up to 16% of banking system equity. Applied to Hungarian economy with ~410,000 firms. **[Note: a previously cited claim about "0.5% of bank equity targeted support reducing losses from 6% to 1%" was not found in any version of this paper and has been removed.]**

| # | Improvement | Complexity | Source |
|---|-----------|------------|--------|
| **N4** | **Supply chain propagation layer** between ALTR and contagion module | High | Fialkowski et al. (2025) |
| **N5** | **Targeted intervention simulation** — test liquidity support efficiency | Medium | Tabachova et al. (2024) |

---

### Update to Scenario Design (S-series) — NGFS Under Pressure

**NGFS Short-Term Scenarios (May 2025):** First 3-5 year scenarios. Four narratives: "Highway to Paris", "Sudden Wake-Up Call", "Disasters and Policy Stagnation", "Diverging Realities". Three models (GEM-E3, EIRIN, CLIMACRED). 50 sectors, 46 countries with sectoral PD + valuations.

**Critical finding:** All four scenarios produce 2030 GDP outcomes within <2.5% range — narrower than IMF's average one-year forecast error of 2.7% (Cliffe, Green Central Banking 2025).

**NTTL Scenarios (Exeter/USS):** Four alternatives ("Meltdown", "Boom & Bust", "Green Phoenix", "Roaring 20s") with geopolitics and tipping points. **GDP range 6x wider than NGFS** (-7.56% to +1.54% vs. -1.27% to +0.32%).

**NGFS Phase V damage function retracted (Dec 2025):** Kotz et al. (2024) retracted from Nature. Removing Uzbekistan reduced 2100 damage estimates by ~two-thirds. Updated methodology expected Phase VI (end 2026).

**Implication for ALTR:**
1. ALTR should be able to ingest NGFS short-term scenarios (3-5 year horizon) in addition to long-term AR6 scenarios
2. Consider supporting NTTL-style bespoke scenarios for wider stress range
3. Sensitivity analysis around scenario choice is now essential (the foundational inputs are contested)

| # | Improvement | Complexity | Source |
|---|-----------|------------|--------|
| **S4** | **NGFS short-term scenario ingestion** — 3-5 year horizon, 50 sectors, 46 countries | Medium | NGFS (2025) |
| **S5** | **NTTL scenario support** — wider GDP range, geopolitical narratives | Medium | Exeter/USS |
| **S6** | **Multi-scenario sensitivity framework** — run ALTR across scenario families, report range | Medium | OMFIF (2025), Cliffe (2025) |

---

### Update to Damage Functions — The Vacuum

The Kotz retraction creates a methodological vacuum directly affecting any physical risk extension of ALTR:

| Function | Approach | GDP loss at 3C | Status |
|----------|----------|---------------|--------|
| Kalkuhl & Wenz (2020) | Level effects only | Modest | Former NGFS Phase IV. Conservative. |
| Kotz et al. (2024) | Lagged level (8-10yr) | 2-4x Kalkuhl | **Retracted Dec 2025** |
| Burke, Hsiang & Miguel (2015) | Growth effects (permanent) | Much larger | Influential but contested |
| Bilal & Kanzig (2024, NBER) | Global temperature, empirical | 12% per 1C | Working paper. 6x larger than prior. SCC $1,367/t |
| Howard & Sterner (2025, ERE) | Meta-analysis with AICc | 7.1-12.6% | Peer-reviewed July 2025. Best available meta-analysis. |

**Recommendation:** If ALTR adds physical risk (P4), use Howard & Sterner (2025) as the central damage function estimate with Bilal-Kanzig as an upper bound. Explicitly present the range rather than a point estimate. The core unresolved question — level vs. growth vs. lagged effects — should be a configurable parameter.

---

### New: Regulatory Compliance Context

**EBA/GL/2025/04 (November 2025):** Final guidelines making climate stress testing mandatory. Two pillars: Climate Stress Test (CST) for capital/liquidity + Climate Resilience Analysis (CRA) for business model viability. Effective January 2026 for large institutions, January 2027 for small/non-complex. Joint ESAs guidelines (January 2026) extend to insurers and pensions.

**ECB 2025 climate overlay results:**
- Transition risk: +74 bps CET1 depletion; physical risk (floods): +77 bps
- Combined: 487 bps total vs. 419 bps baseline — climate adds ~0.7 pp
- High energy-intensive sectors: 91% median PD increase

**ISDA Phase 4 (January 2026):** Translates NGFS short-term scenarios into trading book market risk shocks.

**Implication for ALTR:** ALTR outputs should be mappable to EBA requirements. Specifically:
- NPV/VaR outputs feed into CST (capital adequacy)
- Scenario-based projections feed into CRA (business model viability)
- If M1 (Merton PD) is implemented, PD outputs directly serve regulatory requirements
- Physical risk module (P4) addresses the EBA requirement to cover both risk types

---

### New: Sector Extension Evidence (Agriculture, Cement)

**Agricultural transition risk research (April 2026):** Four transition risk channels identified for agriculture: demand substitution, input substitution, cost profile changes, land transition risk. FAIRR Climate Risk Tool projects $23.7B EBIT decline for top 40 livestock companies by 2030 under 2C scenario. 20 of 40 largest livestock companies would operate at a loss.

**Relevance to ALTR:**
- Agricultural TMSR adaptation needed (demand-driven, not tech-substitution-driven — same challenge as cement P2)
- FAIRR dataset (40 largest livestock companies) provides validation benchmark
- Four modelling concepts proposed: O&G (demand destruction), EV (adaptive capacity), Carbon Tax (margin compression), Land Cost (input constraint)
- Danish agricultural carbon tax (2030, EUR 16-40/tCO2e) provides first live calibration

| # | Improvement | Complexity | Source |
|---|-----------|------------|--------|
| **P6** | **Agricultural sector extension** — adapt TMSR for demand-driven sectors, calibrate with FAIRR | High | FAIRR (2023), OECD-FAO (2024) |
| **P7** | **Geopolitical scenario overlay** — critical minerals, CBAM, chokepoint disruptions | High | IEA (2025), IMF GFSR (2025) |

---

### Updated Unified Priority List (v3 — April 2026)

**Tier 1: Critical — NPV Paradox Fixes** (unchanged)
- RC4: Smooth price transition
- RC5: Gas carbon cost fix
- D2: Stranding-aware terminal value
- D1: Activate brown/green discount spreads
- M2: Dynamic MCPR value factors

**Tier 2: High Impact** (updated)
- S1: Company-level heterogeneity
- M1: Merton PD layer (**now with CRISK, BIS WP 1274, Kerkhofs references**)
- **M1b: Empirical PD model** (NEW — Kerkhofs/Alagoskoufis, ~30 lines, no volatility calibration needed. Uses leverage + profitability changes ALTR already computes. More robust than Merton for non-listed firms. Dual output: Merton for listed, empirical for rest.)
- **M5a: Monte Carlo + copula portfolio VaR** (PROMOTED from Tier 4 — Kerkhofs proves correlations change tail risk by 20-207%. Gaussian copula as starting point, t-copula upgrade later. Produces distribution instead of point estimate.)
- N1: Veraart contagion module
- P1: Country-asset-specific scenarios (cement)
- C4: Wright's Law learning curves
- **P4: Kerkhofs physical risk module** (NEW — same research group as TRISK, parked for now)
- **S4: NGFS short-term scenario ingestion** (NEW — 3-5 year horizon)
- **M2b: Supply-price elasticity** (NEW — Kerkhofs Section 2.2.2, theoretically grounded alternative to static MCPR value factors. Computes price change from capacity exit via supply-demand elasticity. Replaces/augments M2.)

**Tier 3: Medium Impact** (updated)
- D3-D6: Leverage, covenants, multi-scenario
- M3-M4: Rating-dependent volatility, negative firm value
- G1: Gourdel carbon premium feedback
- N2: Entropy-reconstructed exposure matrix
- P2-P3: Cement TMSR adaptation, SFI comparison
- **K1: PRISK ratio measure** (NEW — Kerkhofs Section 2.3.1, trivial 2-line addition. Ratio V_shock/V_baseline alongside NPV_change. Better behaved near zero, cleaner portfolio aggregation.)
- **K2: Insurance cost feedback channel** (NEW — Kerkhofs Section 2.2.3, novel for transition risk. Rising insurance premiums for fossil assets as transition progresses. No other transition paper implements this.)
- **P5: Bressan asset-level validation** (NEW)
- **N4: Supply chain propagation layer** (NEW — Fialkowski)
- **S5-S6: NTTL scenarios, multi-scenario sensitivity** (NEW)

**Tier 4: Frontier** (updated)
- M6: Merit order dispatch
- M5: Monte Carlo Climate VaR
- S3: Multiple shock channels per sector
- N3: Cross-holdings extension
- **P6: Agricultural sector extension** (NEW)
- **P7: Geopolitical scenario overlay** (NEW)
- **N5: Targeted intervention simulation** (NEW — Tabachova)

---

### Updated Implementation Roadmap (v3)

**Phase 1: NPV Paradox Fixes** (1-2 weeks) — unchanged

**Phase 2: New Capabilities** (2-4 weeks each)
- M1: Merton PD layer (now informed by CRISK + BIS WP 1274)
- S1: Company-level alpha parameters
- P1: Country-asset-specific scenarios
- C4: Wright's Law cost curves
- **S4: NGFS short-term scenario ingestion** (NEW — enables 3-5 year stress tests)

**Phase 3: Physical Risk + Contagion** (1-2 months each)
- **P4: Kerkhofs physical risk module** (DCF + copula-based tail risk)
- N1: Veraart contagion module
- **N4: Supply chain propagation** (Fialkowski/Tabachova)
- M6: Merit order dispatch

**Phase 4: Sector Extension + Frontier** (2-3 months)
- P2/P6: Cement + agriculture TMSR adaptation
- M5: Monte Carlo Climate VaR
- **S5-S6: NTTL scenarios + multi-scenario sensitivity**
- **P7: Geopolitical scenario overlay**

---

### Updated Top 5 Priority Papers to Deep-Read

1. **Cormack et al. (2020)** — unchanged, closest to merchant model blueprint
2. **Reinders et al. (2020)** — unchanged, most portable Merton extension
3. **Kerkhofs et al. (2025)** — *Environmental Research: Climate*. **NEW.** Physical risk complement to ALTR. Same research group. DCF + copula + three transmission channels. Reading folder: `Kerkhofs_2025_Environ._Res.__Climate_4_025014.pdf`
4. **Jung, Engle & Berner (2025)** — *JFE*. **NEW.** CRISK: market-based climate systemic risk. When building M1, this provides the alternative to scenario-dependent Merton.
5. **Fialkowski et al. (2025)** — arXiv:2502.17044. **NEW.** Supply chain + interbank contagion integration. 70% amplification. When building N1/N4.

(Way et al. and Gourdel remain important but are now #6 and #7)

---

### Key Academic Insight (Updated)

> **The Kerkhofs paper is the most strategically important new reference for ALTR.** It comes from the same research group (Baer, Ranger, Shrimali = TRISK/CGFI/Oxford), uses the same DCF framework (Tang & Cervenka), and addresses the most commonly requested missing capability (physical risk). Integrating it would give ALTR the distinction of being the only open-source model covering both transition AND physical risk at asset level — the gap identified in the EBA 2025 guidelines.

> **CRISK changes the conversation about what a climate risk measure can be.** Instead of periodic scenario-dependent exercises, CRISK provides continuous market-implied monitoring. If ALTR builds M1 as a Merton layer, it should offer both modes: (1) scenario-based for regulatory compliance (EBA), (2) CRISK-style for real-time supervisory monitoring.

> **The NGFS credibility crisis (Kotz retraction + narrow GDP range) strengthens ALTR's value proposition.** ALTR is bottom-up and asset-level, making it less dependent on aggregate damage functions than top-down models. But ALTR should explicitly offer multi-scenario sensitivity (S6) to address the scenario design concerns raised by NTTL, Carbon Tracker, and Finance Watch.
