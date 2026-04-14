# MCPR v2 Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two MCPR modes (carbon_explicit, merit_order_decline) with auto-detection, plus 3 new batch runner configs (iso_d1, mcpr_v2_carbon, mcpr_v2_merit), and validate with 15 focused test runs.

**Architecture:** The existing `apply_mcpr_adjustment()` gains a `mcpr_mode` parameter. Mode `carbon_explicit` forces `full_ef` carbon cost downstream. Mode `merit_order_decline` applies a VRE-penetration-driven clearing price decline factor inside the MCPR function. Auto-detection checks carbon price coverage in scenario data.

**Tech Stack:** Python 3.10, pandas, Kedro, YAML config

**Spec:** `docs/superpowers/specs/2026-04-14-mcpr-v2-redesign.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `conf/base/parameters_earnings_model.yml` | Modify | Add 3 new params |
| `src/crispy_kedro/pipelines/earnings_model/pipeline.py` | Modify | Wire new params to MCPR node |
| `src/crispy_kedro/pipelines/earnings_model/nodes.py` | Modify | Add merit_order_decline branch + auto-detection in `apply_mcpr_adjustment()` |
| `notebooks/run_all_scenarios_comparison.py` | Modify | Add 3 new ConfigVariant definitions |
| No new files created. | | |

---

### Task 1: Add MCPR v2 Parameters to YAML

**Files:**
- Modify: `conf/base/parameters_earnings_model.yml:18-20`

- [ ] **Step 1: Add the three new parameters after line 20**

Open `conf/base/parameters_earnings_model.yml` and add these lines after `mcpr_markup_factor: 1.0` (line 20):

```yaml
mcpr_mode: "auto"                    # "auto" | "carbon_explicit" | "merit_order_decline"
                                     #   auto: selects mode based on carbon price coverage in scenario data
                                     #   carbon_explicit: forces full_ef carbon cost (for IAMs with carbon prices)
                                     #   merit_order_decline: clearing price declines with VRE share (for IAMs without)
mcpr_merit_order_alpha: 0.006        # Merit order price elasticity: -0.6% per 1pp VRE share (IMF WP 2022/220)
mcpr_merit_order_floor: 0.5          # Min clearing price as fraction of original (scarcity rents floor)
```

- [ ] **Step 2: Verify YAML syntax**

Run:
```bash
cd /Users/jakub/Documents/repos/crispy-kedro && python -c "import yaml; yaml.safe_load(open('conf/base/parameters_earnings_model.yml'))"
```

Expected: No output (no errors).

- [ ] **Step 3: Commit**

```bash
git add conf/base/parameters_earnings_model.yml
git commit -m "feat: add MCPR v2 mode parameters to earnings config"
```

---

### Task 2: Wire New Parameters in Pipeline

**Files:**
- Modify: `src/crispy_kedro/pipelines/earnings_model/pipeline.py:54-65`

- [ ] **Step 1: Add three new param inputs to the MCPR node**

In `pipeline.py`, the MCPR node (Node 3, starting at line 53) has an `inputs=dict(...)` block. Add these three entries inside that dict, after the `scenario_vre_share` line (line 64):

```python
                    mcpr_mode="params:mcpr_mode",
                    mcpr_merit_order_alpha="params:mcpr_merit_order_alpha",
                    mcpr_merit_order_floor="params:mcpr_merit_order_floor",
```

The full node should read:

```python
            # Node 3: Apply MCPR adjustment to scenario surfaces
            node(
                func=apply_mcpr_adjustment,
                inputs=dict(
                    scenario_surfaces="_temp_scenario_surfaces",
                    enable_mcpr="params:enable_mcpr",
                    mcpr_method="params:mcpr_method",
                    mcpr_markup_factor="params:mcpr_markup_factor",
                    enable_regional_mcpr_vf="params:enable_regional_mcpr_vf",
                    mcpr_regional_value_factors="params:mcpr_regional_value_factors",
                    assets_data="companies_forecasts",
                    enable_dynamic_capture_ratios="params:enable_dynamic_capture_ratios",
                    scenario_vre_share="_temp_scenario_vre_share",
                    mcpr_mode="params:mcpr_mode",
                    mcpr_merit_order_alpha="params:mcpr_merit_order_alpha",
                    mcpr_merit_order_floor="params:mcpr_merit_order_floor",
                ),
                outputs="_temp_scenario_surfaces_mcpr",
            ),
```

- [ ] **Step 2: Verify pipeline loads**

Run:
```bash
cd /Users/jakub/Documents/repos/crispy-kedro && .venv/bin/python -c "from crispy_kedro.pipelines.earnings_model.pipeline import create_pipeline; p = create_pipeline(); print(f'Pipeline has {len(p.nodes)} nodes')"
```

Expected: `Pipeline has 8 nodes`

- [ ] **Step 3: Commit**

```bash
git add src/crispy_kedro/pipelines/earnings_model/pipeline.py
git commit -m "feat: wire MCPR v2 params in earnings pipeline"
```

---

### Task 3: Add Merit Order Decline + Auto-Detection in nodes.py

**Files:**
- Modify: `src/crispy_kedro/pipelines/earnings_model/nodes.py:423-436` (function signature)
- Modify: `src/crispy_kedro/pipelines/earnings_model/nodes.py:491-495` (early return when disabled)
- Modify: `src/crispy_kedro/pipelines/earnings_model/nodes.py:724-741` (price replacement block)

This is the core implementation. Three changes to `apply_mcpr_adjustment()`.

- [ ] **Step 1: Add new parameters to the function signature**

Add three new params to the `apply_mcpr_adjustment` function signature. The current signature ends at line 435 (`mcpr_floor_at_iam_price: bool = True`). Add after that line:

```python
    mcpr_mode: str = "auto",
    mcpr_merit_order_alpha: float = 0.006,
    mcpr_merit_order_floor: float = 0.5,
```

- [ ] **Step 2: Add auto-detection logic after the `enable_mcpr` check**

After the existing early-return block (lines 491-495), add the auto-detection logic. Insert after `return scenario_surfaces` (line 495):

```python
    # ── MCPR v2: Mode selection ──────────────────────────────────────────
    # Auto-detect mode from carbon price coverage in scenario data.
    if mcpr_mode == "auto":
        target_rows = scenario_surfaces[
            scenario_surfaces.get("scenario_type", pd.Series()) == "target"
        ] if "scenario_type" in scenario_surfaces.columns else scenario_surfaces
        cp_col = "carbon_price_usd_per_tco2"
        if cp_col in target_rows.columns:
            cp_coverage = (target_rows[cp_col].fillna(0) > 0).mean()
        else:
            cp_coverage = 0.0
        resolved_mode = "carbon_explicit" if cp_coverage > 0.5 else "merit_order_decline"
        logger.info(
            "MCPR mode=auto: carbon price coverage=%.1f%% → resolved to '%s'",
            cp_coverage * 100,
            resolved_mode,
        )
    else:
        resolved_mode = mcpr_mode
        logger.info("MCPR mode='%s' (explicitly set)", resolved_mode)
```

- [ ] **Step 3: Add the merit order decline factor to the price replacement block**

Find the price replacement block (around line 728-741). Currently it looks like:

```python
        # Replace the power price with adjusted price.
        has_reference = surfaces["mcpr_reference_price"].notna()
        if mcpr_floor_at_iam_price:
```

Insert the merit order decline factor BEFORE the price replacement, right after `surfaces["mcpr_adjusted_price"] = ...` (line 724-726):

```python
        # ── MCPR v2: Merit order decline (Cevik & Ninomiya 2022) ─────────
        # In merit_order_decline mode, the clearing price falls as VRE share
        # increases, reflecting empirical merit order displacement.
        if resolved_mode == "merit_order_decline" and scenario_vre_share is not None:
            merge_cols = ["scenario_geography", "year"]
            if "vre_share" not in surfaces.columns:
                surfaces = surfaces.merge(
                    scenario_vre_share[merge_cols + ["vre_share"]],
                    on=merge_cols,
                    how="left",
                )
                surfaces["vre_share"] = surfaces["vre_share"].fillna(0.0)

            # Compute VRE share at shock year (baseline for delta)
            shock_year_vre = (
                surfaces.groupby("scenario_geography")["vre_share"]
                .transform("first")
            )
            delta_vre = (surfaces["vre_share"] - shock_year_vre).clip(lower=0.0)

            # Decline factor: (1 - alpha * delta_vre_share_pct)
            # delta_vre is in [0, 1], alpha is per percentage point, so multiply by 100
            decline_factor = (1 - mcpr_merit_order_alpha * delta_vre * 100).clip(
                lower=mcpr_merit_order_floor
            )

            surfaces["mcpr_adjusted_price"] = (
                surfaces["mcpr_adjusted_price"] * decline_factor
            )

            logger.info(
                "Merit order decline applied: alpha=%.4f, floor=%.2f, "
                "VRE delta range [%.1f%%, %.1f%%], price decline range [%.1f%%, %.1f%%]",
                mcpr_merit_order_alpha,
                mcpr_merit_order_floor,
                delta_vre.min() * 100,
                delta_vre.max() * 100,
                (1 - decline_factor.max()) * 100,
                (1 - decline_factor.min()) * 100,
            )

            # Clean up
            surfaces = surfaces.drop(columns=["vre_share"], errors="ignore")
```

- [ ] **Step 4: Verify the module loads**

Run:
```bash
cd /Users/jakub/Documents/repos/crispy-kedro && .venv/bin/python -c "from crispy_kedro.pipelines.earnings_model.nodes import apply_mcpr_adjustment; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Verify pipeline loads end-to-end**

Run:
```bash
cd /Users/jakub/Documents/repos/crispy-kedro && .venv/bin/python -c "from crispy_kedro.pipelines.earnings_model.pipeline import create_pipeline; p = create_pipeline(); print(f'Pipeline has {len(p.nodes)} nodes')"
```

Expected: `Pipeline has 8 nodes`

- [ ] **Step 6: Commit**

```bash
git add src/crispy_kedro/pipelines/earnings_model/nodes.py
git commit -m "feat: add MCPR v2 merit_order_decline mode and auto-detection"
```

---

### Task 4: Add New ConfigVariants to Batch Runner

**Files:**
- Modify: `notebooks/run_all_scenarios_comparison.py:134-187`

- [ ] **Step 1: Add iso_d1 config**

After the `iso_full_ef` config definition (line 187), add:

```python
# 7. iso_d1 — vanilla + D1 discount rate spread only
# Tests the hypothesis that the discount spread is the dominant driver
# of the +19.5pp interaction term in the full adjusted config.
_iso_d1_val = _vanilla_valuation()
_iso_d1_val["dcf"]["brown_discount_spread"] = 0.01   # +100bps for carbontech
_iso_d1_val["dcf"]["green_discount_spread"] = 0.005  # -50bps for greentech
CONFIG_VARIANTS["iso_d1"] = ConfigVariant(
    name="iso_d1",
    earnings_params=_vanilla_earnings(),
    valuation_params=_iso_d1_val,
)
```

- [ ] **Step 2: Add mcpr_v2_carbon config**

```python
# 8. mcpr_v2_carbon — MCPR carbon_explicit mode (forces full_ef)
# For IAMs with carbon price data: MCPR sets clearing price,
# full_ef carbon costs create the asymmetric fossil penalty.
_mcpr_v2c_earn = _vanilla_earnings()
_mcpr_v2c_earn["enable_mcpr"] = True
_mcpr_v2c_earn["carbon_cost_method"] = "full_ef"
CONFIG_VARIANTS["mcpr_v2_carbon"] = ConfigVariant(
    name="mcpr_v2_carbon",
    earnings_params=_mcpr_v2c_earn,
    valuation_params=_vanilla_valuation(),
)
```

- [ ] **Step 3: Add mcpr_v2_merit config**

```python
# 9. mcpr_v2_merit — MCPR merit_order_decline mode
# For IAMs without carbon prices: clearing price declines with VRE share.
_mcpr_v2m_earn = _vanilla_earnings()
_mcpr_v2m_earn["enable_mcpr"] = True
_mcpr_v2m_earn["enable_dynamic_capture_ratios"] = True
CONFIG_VARIANTS["mcpr_v2_merit"] = ConfigVariant(
    name="mcpr_v2_merit",
    earnings_params=_mcpr_v2m_earn,
    valuation_params=_vanilla_valuation(),
)
```

Note: The `mcpr_v2_merit` config sets `enable_mcpr: True` and `enable_dynamic_capture_ratios: True`. The `mcpr_mode` parameter is read from the YAML config (`parameters_earnings_model.yml`), which defaults to `"auto"`. For the merit_order_decline test specifically, we need to override this. The batch runner writes param overrides to `conf/local/`, so we need to add `mcpr_mode` to the earnings params dict.

Update the `_mcpr_v2m_earn` dict:

```python
_mcpr_v2m_earn = _vanilla_earnings()
_mcpr_v2m_earn["enable_mcpr"] = True
_mcpr_v2m_earn["enable_dynamic_capture_ratios"] = True
_mcpr_v2m_earn["mcpr_mode"] = "merit_order_decline"
```

And update `_mcpr_v2c_earn` similarly:

```python
_mcpr_v2c_earn = _vanilla_earnings()
_mcpr_v2c_earn["enable_mcpr"] = True
_mcpr_v2c_earn["carbon_cost_method"] = "full_ef"
_mcpr_v2c_earn["mcpr_mode"] = "carbon_explicit"
```

- [ ] **Step 4: Verify the batch runner loads**

Run:
```bash
cd /Users/jakub/Documents/repos/crispy-kedro && python -c "from notebooks.run_all_scenarios_comparison import CONFIG_VARIANTS; print(f'{len(CONFIG_VARIANTS)} configs: {sorted(CONFIG_VARIANTS.keys())}')"
```

Expected: `9 configs: ['adjusted', 'iso_d1', 'iso_dynamic_ef', 'iso_full_ef', 'iso_mcpr', 'iso_stranding_tv', 'mcpr_v2_carbon', 'mcpr_v2_merit', 'vanilla']`

- [ ] **Step 5: Verify the write_param_overrides function handles mcpr_mode**

Check that the batch runner's param override writer can handle the new `mcpr_mode` key. The runner writes earnings params to `conf/local/parameters_earnings_model.yml`. Since `mcpr_mode` is a top-level key in that file, it should be written correctly by the existing override logic. Verify by doing a dry run:

```bash
cd /Users/jakub/Documents/repos/crispy-kedro && python notebooks/run_all_scenarios_comparison.py --configs mcpr_v2_merit --providers "GCAM 5.2" --dry-run
```

Expected: Shows 1 planned run: `GCAM 5.2 [mcpr_v2_merit]`

- [ ] **Step 6: Commit**

```bash
git add notebooks/run_all_scenarios_comparison.py
git commit -m "feat: add iso_d1, mcpr_v2_carbon, mcpr_v2_merit batch configs"
```

---

### Task 5: Run Focused Test Matrix (15 runs)

**Files:**
- No code changes. This is a validation task.

- [ ] **Step 1: Run iso_d1 for all 5 providers**

```bash
cd /Users/jakub/Documents/repos/crispy-kedro && python notebooks/run_all_scenarios_comparison.py \
  --providers "MESSAGEix-GLOBIOM_1.1" "WITCH 5.0" "IMAGE 3.0" "GCAM 5.2" "COFFEE 1.1" \
  --configs iso_d1 \
  2>&1 | tee workspace/batch_run_iso_d1.log
```

Expected: 5 runs, all PASS. ~25 min.

- [ ] **Step 2: Run mcpr_v2_carbon for all 5 providers**

```bash
cd /Users/jakub/Documents/repos/crispy-kedro && python notebooks/run_all_scenarios_comparison.py \
  --providers "MESSAGEix-GLOBIOM_1.1" "WITCH 5.0" "IMAGE 3.0" "GCAM 5.2" "COFFEE 1.1" \
  --configs mcpr_v2_carbon \
  2>&1 | tee workspace/batch_run_mcpr_v2_carbon.log
```

Expected: 5 runs, all PASS. ~25 min.

- [ ] **Step 3: Run mcpr_v2_merit for all 5 providers**

```bash
cd /Users/jakub/Documents/repos/crispy-kedro && python notebooks/run_all_scenarios_comparison.py \
  --providers "MESSAGEix-GLOBIOM_1.1" "WITCH 5.0" "IMAGE 3.0" "GCAM 5.2" "COFFEE 1.1" \
  --configs mcpr_v2_merit \
  2>&1 | tee workspace/batch_run_mcpr_v2_merit.log
```

Expected: 5 runs, all PASS. ~25 min.

- [ ] **Step 4: Analyze results — compute carbon-neg % and compare**

Write and run an analysis script:

```bash
cd /Users/jakub/Documents/repos/crispy-kedro && python -c "
import pandas as pd
from pathlib import Path

results_dir = Path('workspace/comparison_results')
configs = ['vanilla', 'iso_d1', 'mcpr_v2_carbon', 'mcpr_v2_merit']
providers = [
    'MESSAGEix-GLOBIOM_1.1', 'WITCH_5.0', 'IMAGE_3.0', 'GCAM_5.2', 'COFFEE_1.1',
]
carbon_techs = ['CoalCap', 'GasCap', 'OilCap']

rows = []
for prov in providers:
    for cfg in configs:
        path = results_dir / prov / cfg / 'company_technology_npv.csv'
        if not path.exists():
            continue
        df = pd.read_csv(path)
        carbon = df[df['technology'].str.startswith(tuple(carbon_techs))]
        if len(carbon) == 0:
            continue
        neg_pct = (carbon['npv_change'] < 0).mean() * 100
        rows.append({'provider': prov, 'config': cfg, 'carbon_neg_pct': round(neg_pct, 1)})

result = pd.DataFrame(rows)
pivot = result.pivot(index='provider', columns='config', values='carbon_neg_pct')
pivot = pivot.reindex(columns=[c for c in configs if c in pivot.columns])
print(pivot.to_string())
"
```

Expected: A table showing carbon-neg % for each provider × config.

**Success criteria from spec:**
- `iso_d1`: large positive delta vs vanilla across all 5
- `mcpr_v2_carbon` on MESSAGEix: positive delta (vs vanilla iso_mcpr's -41.8pp)
- `mcpr_v2_merit` on GCAM 5.2: positive delta vs vanilla

- [ ] **Step 5: Commit analysis results**

```bash
git add workspace/batch_run_iso_d1.log workspace/batch_run_mcpr_v2_carbon.log workspace/batch_run_mcpr_v2_merit.log
git commit -m "test: MCPR v2 focused test matrix results (15 runs)"
```
