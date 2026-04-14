# Full Matrix Re-Run with Carbon Cost Method Fix

**Date:** 2026-04-13
**Status:** Approved

## Problem

Two fixes were implemented to improve ALTR model narrative consistency:
1. **Carbon price interpolation** — `carbon_price_usd_per_tco2` added to interpolation in `inputs_processing/nodes.py:644`
2. **Full EF carbon cost method** — `carbon_cost_method: "full_ef"` in `parameters_earnings_model.yml:169`

These were validated on WITCH 5.0 (narrative consistency 81.9% → 88.2%). Now need to validate across all 25 IAM scenario pairs.

## Design

### Config Variants (6 total)

| Config | `carbon_cost_method` | Purpose |
|---|---|---|
| `vanilla` | `differential_ef` | Control — original model, all adjustments OFF |
| `adjusted` | `full_ef` | Full model with all improvements |
| `iso_mcpr` | `differential_ef` | Vanilla + MCPR only |
| `iso_stranding_tv` | `differential_ef` | Vanilla + stranding-aware TV only |
| `iso_dynamic_ef` | `differential_ef` | Vanilla + dynamic marginal EF only |
| `iso_full_ef` | `full_ef` | Vanilla + full_ef carbon cost only |

### Changes Required

1. **`notebooks/run_all_scenarios_comparison.py`**:
   - Add `"carbon_cost_method": "differential_ef"` to `_vanilla_earnings()`
   - Add `"carbon_cost_method": "full_ef"` to `_adjusted_earnings()`
   - Add `iso_full_ef` config variant (vanilla + `carbon_cost_method: "full_ef"`)
   - All `iso_*` configs inherit `"differential_ef"` from vanilla base

2. **No pipeline code changes** — both fixes already in `conf/base/` and source code

### Run Matrix

- 25 providers × 6 configs = **150 runs**
- ~5 min per run = **~12.5 hours**

### Output

- Results in `workspace/comparison_results/{provider}/{config}/`
- Post-run analysis script: `notebooks/analyze_fullef_comparison.py`

### Carbon Price Data Gap

9 providers lack carbon price data (AIM/CGE, GCAM 5.2/5.3, GCAM-PR, IMACLIM, PyPSA-Eur-Sec, TIAM-Grantham, WITCH). For these, carbon cost = $0 under both methods — the full_ef vs differential_ef comparison shows no difference. This correctly reflects the data limitation.

Note: WITCH has 95% carbon price coverage in the AR6 file but the specific scenario pair in the manifest (EN_NoPolicy vs EN_NPi2020_500) may have gaps at certain year/technology combinations.
