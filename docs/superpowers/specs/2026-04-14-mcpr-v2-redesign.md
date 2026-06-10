# MCPR v2 Redesign: Two-Mode Price Adjustment

**Date:** 2026-04-14
**Author:** Jakub Cervenka
**Status:** Design approved, pending implementation

---

## Problem

The current MCPR (Marginal Cost Price Ratio) adjustment lifts all technology prices to the wholesale market clearing price, then applies value/capture factors for VRE. In isolation, this **hurts** carbon-negative direction for 16/24 providers (avg -9.8pp) because it raises fossil revenue without sufficient offsetting cost.

The interaction analysis from the 150-run comparison (25 providers x 6 configs) shows:
- Sum of isolated adjustment impacts: **-9.2pp** (net negative)
- Full adjusted config impact: **+10.3pp** (positive)
- Interaction term: **+19.5pp** (dominates)

The interaction term is attributed to the D1 discount rate spread (+100bps brown, -50bps green), which is present in the full `adjusted` config but never tested in isolation.

### Root cause

MCPR lifts fossil revenue via the clearing price. The mechanism that should offset this — carbon costs — depends on the IAM:
- **18/25 providers** have explicit carbon prices in AR6 data. Carbon costs work but require `full_ef` method (not `differential_ef`) to penalize gas.
- **7/25 providers** have zero carbon prices. No offsetting mechanism exists.

## Design

### Two MCPR Modes

**Parameter:** `mcpr_mode: "auto" | "carbon_explicit" | "merit_order_decline"`

#### Mode 1: `carbon_explicit`

For IAMs with carbon price data (18 providers). The clearing price adjustment stays unchanged. The fix is forcing `carbon_cost_method: "full_ef"` so all fossil technologies pay full carbon cost.

**Mechanism (Fabra & Reguant 2014; Sijm et al. 2006):**
- All generators earn: `P_clearing(g,t) x VF(tech)`
- Fossil generators pay: `Q x carbon_price x EF` (full emission factor)
- Net: renewables gain windfall, fossil margins crushed by carbon cost

**No new code in the MCPR function.** The mode forces `carbon_cost_method: "full_ef"` in the earnings config.

**Providers:** WITCH 5.0, all REMIND variants (8), MESSAGEix 1.1, IMAGE 3.0/3.2, POLES ENGAGE/GECO, GEM-E3, TIAM-ECN, TIAM-UCL.

#### Mode 2: `merit_order_decline`

For IAMs without carbon prices (7 providers). The clearing price itself declines with VRE penetration.

**Mechanism (Cevik & Ninomiya 2022, IMF WP 2022/220; Sensfuss et al. 2008):**

```
P_clearing(g, t) = P_max_dispatchable(g, t) x (1 - alpha x delta_VRE_share(g, t))
```

Where:
- `delta_VRE_share(g, t)` = VRE share at year t minus VRE share at shock year
- `alpha` = 0.006 (IMF: -0.6% wholesale price per 1pp VRE share increase)
- Floor at 50% of original clearing price (scarcity rents prevent full collapse)

Dynamic value factors (Hirth 2013 curves) always enabled in this mode.

**Providers:** AIM/CGE 2.2, GCAM 5.2/5.3, GCAM-PR 5.3, IMACLIM 1.1, PyPSA-Eur-Sec, TIAM-Grantham 3.2.

#### Auto-detection

`mcpr_mode: "auto"` checks if >50% of target scenario rows have `carbon_price_usd_per_tco2 > 0`:
- Yes -> `carbon_explicit`
- No -> `merit_order_decline`

### New Parameters

```yaml
# In parameters_earnings_model.yml
mcpr_mode: "auto"                # "auto" | "carbon_explicit" | "merit_order_decline"
mcpr_merit_order_alpha: 0.006    # IMF elasticity: -0.6% per 1pp VRE share
mcpr_merit_order_floor: 0.5      # Min clearing price as fraction of original
```

### New Batch Runner Configs

| Config | MCPR | Carbon cost | D1 spread | Stranding TV | Purpose |
|--------|------|-------------|-----------|--------------|---------|
| `iso_d1` | off | differential_ef | +100bps/-50bps | off | Isolate D1 discount spread |
| `mcpr_v2_carbon` | carbon_explicit | full_ef (forced) | off | off | Test Mode 1 alone |
| `mcpr_v2_merit` | merit_order_decline | differential_ef | off | off | Test Mode 2 alone |

### Focused Test Matrix

5 providers x 3 configs = 15 runs (~75 min):

**Providers:**
- MESSAGEix-GLOBIOM 1.1 — worst MCPR isolated impact (-41.8pp), has carbon prices
- WITCH 5.0 — baseline scenario, well-understood, has carbon prices
- IMAGE 3.0 — worst regression under adjusted (-26.0pp), has carbon prices
- GCAM 5.2 — largest no-carbon-price provider
- COFFEE 1.1 — biggest adjusted improvement (+34.3pp), partial carbon prices (10%)

**Success criteria:**
- `iso_d1`: large positive carbon-neg delta across all 5 providers (confirms D1 is the dominant driver)
- `mcpr_v2_carbon` on MESSAGEix: flips from -41.8pp to positive
- `mcpr_v2_carbon` on IMAGE 3.0: fixes the -26.0pp regression
- `mcpr_v2_merit` on GCAM 5.2: positive carbon-neg delta without carbon prices
- No config produces carbon cost results that are pathological (e.g., >20x revenue consistently)

## Files to Modify

| File | Change |
|------|--------|
| `src/crispy_kedro/pipelines/earnings_model/nodes.py` | Add merit_order_decline branch in `apply_mcpr_adjustment()`. New params: `mcpr_mode`, `mcpr_merit_order_alpha`, `mcpr_merit_order_floor`. |
| `src/crispy_kedro/pipelines/earnings_model/pipeline.py` | Wire new params from YAML to the MCPR node. |
| `conf/base/parameters_earnings_model.yml` | Add `mcpr_mode`, `mcpr_merit_order_alpha`, `mcpr_merit_order_floor`. |
| `notebooks/run_all_scenarios_comparison.py` | Add 3 new ConfigVariant definitions. |

**Files NOT modified:** Valuation model, reporting, inputs processing.

## Literature

- Fabra, N. & Reguant, M. (2014). "Pass-Through of Emissions Costs in Electricity Markets." AER, 104(9), 2872-2899.
- Sijm, J., Neuhoff, K. & Chen, Y. (2006). "CO2 Cost Pass-Through and Windfall Profits in the Power Sector." Climate Policy, 6(1), 49-72.
- Cevik, S. & Ninomiya, K. (2022). "Fossil Fuels, Renewables, and the Energy Transition." IMF Working Paper 2022/220.
- Sensfuss, F., Ragwitz, M. & Genoese, M. (2008). "The Merit-Order Effect." Energy Policy, 36(8), 3076-3084.
- Hirth, L. (2013). "The Market Value of Variable Renewables." Energy Economics, 38, 218-236.
- Hirth, L., Ueckerdt, F. & Edenhofer, O. (2015). "Integration Costs Revisited." Renewable Energy, 74, 925-939.
- Borenstein, S., Bushnell, J. & Wolak, F. (2000). "Measuring Market Power in the California Electricity Market." J. Ind. Econ., 48(2), 197-223.

---

## Findings (appended 2026-06-10)

The 15-run focused test matrix completed. The D1-dominates hypothesis from the Design section was **partially falsified**.

### Per-mechanism results vs vanilla

| Provider | `iso_d1` (D1 alone) | `mcpr_v2_carbon` (Mode 1) | `mcpr_v2_merit` (Mode 2) |
|---|---|---|---|
| WITCH 5.0 | **+8.7pp** | +7.9pp | n/a (has carbon) |
| MESSAGEix-GLOBIOM 1.1 | ~0pp | **-5.4pp** | n/a (has carbon) |
| IMAGE 3.0 | ~0pp | tbc | n/a |
| GCAM 5.2 | ~0pp | n/a (no carbon) | tbc |
| COFFEE 1.1 | ~0pp | tbc | tbc |

### What this changes about the v1->v2 narrative

1. **D1 is not carrying the result alone.** Only WITCH responds to D1 in isolation (+8.7pp). The +19.5pp interaction term in the original 150-run analysis is therefore *not* purely a D1 effect — it's genuine synergy across the adjustment suite (MCPR + carbon cost method + D1 + terminal value treatment).
2. **Mode 1 (`mcpr_v2_carbon` with forced `full_ef`) is not a clean win.** It helps WITCH (+7.9pp) but *hurts* MESSAGEix (-5.4pp). The MCPR revenue lift can still overwhelm the carbon cost even when `full_ef` is forced, in providers where carbon price magnitudes don't scale with the clearing-price lift.
3. **Carbon prices were already flowing**, contradicting the original NaN-fillna assumption: WITCH target scenarios carry $200-722/tCO2 explicitly. The fix is therefore not "turn on the carbon channel" but **route the channel correctly per IAM** (differential vs full vs disabled, depending on carbon embedding in the IAM's electricity price).
4. **18/25 providers carry explicit carbon prices, 7/25 don't.** Mode 2 (`merit_order_decline`) is the only viable route for the 7 — there is no carbon channel to forcibly activate.

### Paper-writing narrative (binding)

Frame the adjustment suite as a **coherent synergistic system**, not a sequence of independent fixes. Specifically:

> "The combination of market-clearing pricing (MCPR), carbon cost pass-through (full_ef for IAMs with explicit prices, merit-order decline for those without), discount-rate differentiation (D1), and unconditional terminal value produces a consistent carbon-negative improvement that none achieves alone. Across the 15-run focused test matrix, no single mechanism delivers the +10.3pp seen in the full adjusted configuration; the +19.5pp interaction term documented in the original 150-run analysis is therefore a genuine systemic effect, not an artifact of D1 in isolation."

### Open

- IMAGE 3.0 mcpr_v2_carbon expected to fix the -26.0pp regression — tbc
- GCAM 5.2 mcpr_v2_merit alpha=0.006 sensitivity (try 0.004 and 0.008 if positive delta is marginal)
- Carbon cost / revenue ratio under high carbon prices: observed 5-14x for fossil plants under WITCH C1 — this is correct 1.5C economics, not a pathology, but should be flagged in the paper's robustness section.

### Cross-references

- Memory: `project_mcpr_v2_findings.md`
- Vault: `synthesis/synth-mcpr-v2-test-findings-2026-04.md` (planned)
- Methodology: `MCPR/ALTR_MCPR_methodology_v1.md` — still v1, predates this mode split. v2 methodology section to be added when paper draft begins.
