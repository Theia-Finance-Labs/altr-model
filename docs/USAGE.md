# Using Crispy Kedro

This is a guide for running the climate transition risk model end-to-end.
For contributing to the codebase itself, see the [README](../README.md).

## 1. Kedro quickstart

Crispy Kedro is a [Kedro](https://kedro.org) project. The concepts that
matter for using it:

- **Nodes** are Python functions; **pipelines** wire nodes together.
- The **catalog** (`conf/base/catalog.yml`) declares where each dataset
  lives and how to read/write it. A catalog entry can point at a local CSV
  *or* a live source (a database, a warehouse table) — the pipeline code
  doesn't change either way, only the catalog entry does.
- **Parameters** (`conf/base/parameters*.yml`) are the model's tunable
  inputs, injected into nodes as `params:some_key`.
- Kedro runs are **batch** — you invoke `kedro run`, it executes the graph
  once, end to end, and exits. There's no long-running service.
- **Environments** (`conf/<env>/`) let you override catalog/parameter
  entries per context. `conf/base/` is the shared default; `conf/local/`
  (gitignored) is for your own machine — personal overrides. Kedro merges
  `base` with whichever environment you pass via `--env` (default: `local`,
  silently falling back to `base`-only values where `local` doesn't
  override anything).
- **The model doesn't depend on Kedro to run.** Nodes are plain Python
  functions (`pipelines/*/nodes.py`) that take DataFrames/params in and
  return DataFrames out — Kedro's role is orchestration (wiring, the
  catalog, `kedro run`), not the modeling logic itself. If you ever want to
  drop the framework, the node functions can be called directly from a
  script or notebook with plain pandas DataFrames; nothing in the modeling
  code itself is Kedro-specific.

> 📸 *Screenshot idea: `kedro viz` pipeline graph, annotated with the
> environment/catalog concept.*

## 2. Install

Requires Python 3.10 (3.11+ is not supported due to dependency constraints).
We use [uv](https://docs.astral.sh/uv/) for both installing Python and
managing the project's virtual environment — no `pyenv` needed, `uv sync`
downloads and pins the right Python version automatically from
`requires-python` in `pyproject.toml`.

### macOS / Linux

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh

git clone <repo-url>
cd crispy-kedro

uv sync
source .venv/bin/activate
```

### Windows (PowerShell)

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

git clone <repo-url>
cd crispy-kedro

uv sync
.venv\Scripts\activate
```

## 3. Getting the data

This is the part that matters most for most readers of this doc.

The model needs exactly three CSV files, placed in `data/05_model_input/`:

| File | Schema |
|---|---|
| `scenarios.csv` | see [below](#scenarioscsv) |
| `assets_forecasts.csv` | see [below](#assets_forecastscsv) |
| `ownership_tree.csv` | see [below](#ownership_treecsv) |

### Where the data comes from

> ⚠️ **TODO (fill in):** describe the actual delivery channel — e.g. shared
> drive link, secure transfer, internal portal — and who to contact for
> access or a refresh.

### Schemas

#### `assets_forecasts.csv`

Physical power-generation assets (plants) and their technical
characteristics — capacity, technology, location, age — one row per asset
per forecast year.

| Column | Type | Meaning |
|---|---|---|
| `asset_id` | string | Unique identifier for the physical asset. |
| `year` | int | Year this row's forecast values apply to. |
| `sector` | string | Economic sector the asset belongs to. |
| `technology` | string | Technology the asset uses within its sector. |
| `capacity_unit` | string | Unit that `capacity` is expressed in. |
| `capacity` | float | Production capacity of the asset in that year. |
| `asset_age` | float | Age of the asset, in years, as of that row's year. |
| `country_iso2` | string | ISO 3166-1 alpha-2 code of the asset's country. |
| `country_name` | string | Human-readable name of the asset's country. |
| `asset_name` | string | Human-readable name of the asset. |
| `latitude` | float | Asset location, latitude. |
| `longitude` | float | Asset location, longitude. |
| `age_is_inferred` | bool | Whether `asset_age` was inferred rather than sourced directly. |
| `capacity_factor` | float | Fraction of nameplate capacity the asset is expected to run at. |
| `emission_factor` | float | Emissions per unit of output for this asset/technology. |

#### `ownership_tree.csv`

Which companies own which assets, and to what degree — one row per
asset-company ownership link per year.

| Column | Type | Meaning |
|---|---|---|
| `asset_id` | string | Unique identifier for the physical asset. |
| `company_id` | string | Unique identifier for the owning company. |
| `year` | int | Year this ownership link applies to. |
| `ownership_type` | string | Basis of the ownership relationship (e.g. equity vs. operational control). |
| `ownership_percentage` | float | Share of the asset owned by the company, as a fraction. |
| `sector` | string | Economic sector the asset belongs to. |
| `technology` | string | Technology the asset uses within its sector. |
| `asset_name` | string | Human-readable name of the asset. |
| `company_name` | string | Human-readable name of the owning company. |

#### `scenarios.csv`

Climate transition scenario pathways — projected prices, capacity,
efficiency, and cost assumptions per scenario/technology/geography/year.
These are the reference trajectories that assets and companies are
measured against.

| Column | Type | Meaning |
|---|---|---|
| `scenario` | string | Identifier of the climate scenario/pathway model run. |
| `scenario_type` | string | Whether this scenario is used as the baseline or the target pathway. |
| `scenario_geography` | string | Geography the scenario pathway applies to. |
| `sector` | string | Economic sector the pathway applies to. |
| `technology` | string | Technology the pathway applies to within its sector. |
| `year` | int | Year this row's pathway values apply to. |
| `scenario_price` | float | Output price projected under this scenario. |
| `fuel_price` | float | Fuel input price projected under this scenario. |
| `scenario_pathway` | float | Projected production/capacity pathway value for this row. |
| `scenario_capacity_factor` | float | Fraction of nameplate capacity assumed under this scenario. |
| `country_iso2_list` | string (comma-list) | ISO 3166-1 alpha-2 codes of countries covered by `scenario_geography`. |
| `lifetime_years` | float | Assumed operating lifetime of the technology, in years. |
| `efficiency_decimal` | float | Conversion efficiency of the technology, as a fraction. |
| `om_cost_usd_per_mw_per_yr` | float | Operations & maintenance cost per MW per year. |
| `capital_cost_usd_per_mw` | float | Capital expenditure per MW of capacity. |
| `carbon_price_usd_per_tco2` | float | Carbon price assumed under this scenario, per tonne of CO2. |

## 4. Running the model

### Tags

Use `--tags` to run the model stages as a group, or `--pipeline` with one of
the explicit namespace names in the pipeline reference below to run a single
stage:

- `altrisk`: the actual model — inputs through valuation (NPV). This is
  the minimum to get results.
- `reporting`: produces plots from `altrisk` outputs (`asset_earnings`,
  `company_trajectories`, `yearly_npv_trajectories`) — no compliance
  tables, no separate validation step, just plots. Depends on `altrisk`
  having already run.

```bash
# results only
kedro run --tags=altrisk

# results + plots
kedro run --tags=altrisk,reporting
```

VS Code users: `.vscode/launch.json` has matching debug configs ("Kedro
Run AltRisk (Debug)", "Kedro Run AltRisk with reporting (Debug)").

### Notebook (batch runs)

`notebooks/generate_results.ipynb` runs multiple parameterized configs in
one go — useful for comparing scenarios or granularities without editing
`conf/base/` between runs.

- `runs_configuration`: a dict of `{run_name: {param_overrides}}`. Each
  entry becomes one `kedro run` with those parameters overridden on top of
  `conf/base/`.
- `workspace_dir` (`workspace/results_<version>/`): each run's outputs and
  plots are copied here under `workspace_dir/<run_name>/`, so multiple runs
  don't overwrite each other in `data/`.
- Company vs. asset granularity is controlled by two parameters, set per
  run in `runs_configuration` — see
  [`reduce_granularity_from_asset_to_company_level`](#5-pipeline-reference)
  and its effect on outputs in [section 6](#6-model-outputs).
- The notebook only runs the `altrisk` tag and saves the `07_model_output`
  CSVs per run — it doesn't run `reporting` or copy any plots. If you want
  plots for a specific run, run it separately via the CLI
  (`--tags=altrisk,reporting`, see below) with that run's parameters.

> 📸 *Screenshot idea: the `runs_configuration` cell with 2-3 example runs.*

### Batch runs without a notebook

`notebooks/run_kedro_batch.py` is the script form of the same pattern —
useful for headless/CI-style batch runs, or as the engine behind the
Streamlit app below:

```bash
python notebooks/run_kedro_batch.py \
    --run-configurations notebooks/example_run_configurations.yml \
    --company-ids notebooks/example_company_selection.csv \
    --workspace-dir workspace/results_batch \
    --tags altrisk
```

- `--run-configurations`: a YAML/JSON file shaped like the notebook's
  `runs_configuration` dict. `notebooks/example_run_configurations.yml`
  reproduces the six configs (including the ones left commented out) from
  `generate_results.ipynb`.
- `--company-ids`: a CSV (`company_id` column), plain text (one id per
  line), or YAML/JSON list, applied to every run in the file.
  `notebooks/example_company_selection.csv` is a sample of 30 large
  companies picked to cover all four alignment × carbon-intensity
  quadrants (`aligned`/`misaligned` × `high_carbon`/`low_carbon`) — see the
  file's own columns for how each was classified.
- Baseline/target scenario pairs are validated to come from the same IAM
  provider before a run starts (see `notebooks/scenario_utils.py`) — the
  pipeline itself only warns and silently intersects geographies/
  technologies on a mismatch, which otherwise fails quietly rather than
  loudly. Pass `--allow-cross-provider-scenarios` to bypass this.
- Same output-copying behavior as the notebook, plus a `run_manifest.csv`
  per batch summarizing which runs succeeded.

`notebooks/streamlit_app.py` wraps the same script in a form-based UI —
build configurations interactively (with the scenario dropdown already
constrained to same-provider pairs), upload or paste a company selection,
download the resulting config YAML, and run the batch with live progress
and per-run download buttons:

```bash
uv sync --group streamlit
uv run streamlit run notebooks/streamlit_app.py
```

## 5. Pipeline reference

Each project pipeline is namespaced, with its own inputs, outputs, and
parameters file under `conf/base/`. Datasets are catalog entry names (see
`conf/base/catalog.yml`); parameters are keys from the pipeline's
`parameters_<pipeline>.yml`, injected as `params:<key>`.

The six namespaces expose grain-specific tables; scenario pathways and wide
allocation frames remain internal datasets and do not cross pipeline boundaries.

### `prepare_scenario_asset_and_company_inputs`

- **Inputs:** `assets`, `ownership_tree`, `scenarios`
- **Outputs:** `asset_forecast_panel`, `company_projection_inputs`

| Parameter | Type | Meaning and impact |
|---|---|---|
| `baseline_scenario` | string | Scenario id used as the no-transition reference pathway that baseline trajectories follow. |
| `target_scenario` | string | Scenario id used as the transition pathway that shock trajectories move toward. |
| `company_ids` | list of strings (optional) | Restricts the run to these companies; empty/unset processes all companies in the input data. Directly controls run size and runtime. |
| `ownership_type` | string | Which ownership relationship to use when allocating assets to companies (e.g. `"direct"`). Changes which assets get attributed to which company. |
| `ccs_on` | bool or null | Whether to use the with-CCS or without-CCS scenario variant for Coal/Gas/Biomass technologies (`null` = no distinction). Changes which technology rows are matched from `scenarios.csv`. |
| `max_forecast_horizon` | int | Number of years of forecast kept per asset/company. Larger = longer trajectories but more low-confidence out-years. |
| `theta_capex_recovery` | float | CapEx-recovery weighting applied when scaling electricity price forecasts. Higher values increase modeled price recovery of capital costs. |
| `reduce_granularity_from_asset_to_company_level` | bool | **Major impact.** `True` aggregates inputs to one synthetic row per company-technology before the rest of the pipeline runs; `False` keeps real per-asset granularity. Changes the row count, identifiers, and structure of every downstream output — see [section 6](#6-model-outputs). |

### `calculate_company_trajectories`

- **Inputs:** `company_projection_inputs`
- **Outputs:** `company_pathways_pre_allocation`

Kedro Viz shows alignment classification followed by four separate methodology
nodes: aligned/misaligned × increasing/decreasing technology. A final node
combines those four case outputs and activates baseline assumptions before the
shock year and target assumptions from the shock year onward.

| Parameter | Type | Meaning and impact |
|---|---|---|
| `shock_year` | int | Year the late-sudden transition starts; assumptions switch from baseline to target in this year. |
| `alignment_year` | int | Year by which requested trajectories reach the target pathway. |

### `allocate_company_trajectories_to_assets`

- **Inputs:** `asset_forecast_panel`, `company_pathways_pre_allocation`
- **Outputs:** `asset_trajectories`, `company_trajectories`

`asset_trajectories` is long at asset/year/type grain and contains
`baseline` and `latesudden`. `company_trajectories` is long at
company/geography/sector/technology/year/type grain and contains `baseline`,
`target`, `late_sudden_requested`, and `late_sudden_realized`; the realized
series is the sum of post-allocation asset capacity.

The graph shows the technology-direction split, separate decreasing and
increasing allocation nodes, their explicit recombination, the long asset-table
construction, and company-level reconciliation as distinct steps.

| Parameter | Type | Meaning and impact |
|---|---|---|
| `shock_year` | int | Shared transition start year used when allocating company impacts to assets. |
| `alignment_year` | int | Shared target-alignment year used by retirement and allocation logic. |
| `apply_retirement_baseline` | bool | Whether asset retirement dates are enforced in the baseline (no-shock) trajectory. |
| `apply_retirement_shock` | bool | Whether asset retirement dates are enforced in the late-sudden (shock) trajectory. |
| `apply_decreasing_staggered_shock` | bool | Whether the shock is staggered across a quantile curve for technologies with decreasing output, vs. applied uniformly. |
| `staggered_shock.g_k` | float | Curve-shape parameter for the staggered shock (steepness of the quantile allocation curve). |
| `staggered_shock.n_quantiles` | int | Number of quantile buckets the staggered shock is split across. |

### `calculate_asset_earnings`

- **Inputs:** `asset_trajectories`
- **Outputs:** `asset_earnings`

`asset_earnings` retains `late_sudden_phase`, alignment metadata, and the asset
trajectory value needed by reporting, so reporting does not bypass the earnings
stage to reload `asset_trajectories`.

| Parameter | Type | Meaning and impact |
|---|---|---|
| `market_passthrough` | float (0-1) | Fraction of carbon price passed through to market prices. `0` = no passthrough, `1` = full passthrough; changes projected revenue under the shock scenario. |
| `include_growth_capex` | bool | Whether to include CapEx for new-build capacity growth in the cost stack. |
| `include_replacement_capex` | bool | Whether to include CapEx for replacing retired eligible assets. |
| `include_decom_costs` | bool | Whether to include decommissioning costs for retired assets. |
| `apply_continued_om_baseline` | bool | Whether fixed O&M keeps being charged (at first-year capacity) after retirement, in the baseline trajectory. |
| `apply_continued_om_shock` | bool | Same, for the shock trajectory. |

### `calculate_asset_and_company_npv`

- **Inputs:** `asset_earnings`
- **Outputs:** `asset_npv`, `company_npv`, `company_technology_npv`,
  `yearly_npv_trajectories`

| Parameter | Type | Meaning and impact |
|---|---|---|
| `dcf.discount_rate_baseline` | float | Real discount rate applied to baseline cash flows in the DCF. Higher = lower NPV. |
| `dcf.discount_rate_shock` | float | Real discount rate applied to shock (late-sudden) cash flows; typically set higher than baseline to reflect transition risk. |
| `dcf.terminal_value.method` | string (`"none"` \| `"perpetuity"`) | Whether a terminal value is added beyond the forecast horizon. |
| `dcf.terminal_value.g_real_default` | float | Real terminal growth rate used when `method` is `"perpetuity"`. |

### `plot_transition_risk_results`

- **Inputs:** `asset_earnings`, `company_trajectories`, `yearly_npv_trajectories`
- **Outputs:** `asset_financial_trajectories_plots_dir` (plots for the
  other two nodes are written directly to disk, not catalog outputs — see
  [section 6](#plots))

| Parameter | Type | Meaning and impact |
|---|---|---|
| `plot_staggered_shock_use_log_scale` | bool | Plots the staggered-shock chart's y-axis on a log scale. |
| `plot_staggered_shock_show_shock_absorption` | bool | Overlays a shock-absorption band on the staggered-shock chart. |
| `reporting.plots.dpi` | int | Resolution (dots per inch) plots are saved at. |

## 6. Model outputs

### Tables

All model result tables live in **`data/07_model_output/`** (NPVs,
earnings, trajectories) — produced by the `altrisk` pipeline. There is no
separate compliance/curated table layer today.

### Granularity changes the shape of every output

`reduce_granularity_from_asset_to_company_level` (see
[section 5](#5-pipeline-reference)) is the single parameter most likely to
surprise you: it doesn't just change row counts, it changes what an "asset"
*is* in the output.

Example, comparing two runs of the same company/scenario under
`workspace/results_V21/`:

- **Asset granularity** (`reduce_granularity_from_asset_to_company_level: False`):
  `asset_npv.csv`'s `asset_id` is the real physical asset id (e.g.
  `INTERNAL_A_L100000103087_int_ast_power_gem_stage2_GasCap`), `is_synthetic`
  is `False`, and `company_npv.csv`'s `asset_count` reflects the true number
  of physical assets owned by the company (e.g. `74` for Iberdrola SA).
- **Company granularity** (`reduce_granularity_from_asset_to_company_level: True`):
  physical assets are aggregated into one synthetic row per
  company/sector/technology/geography before the model runs.
  `asset_npv.csv`'s `asset_id` becomes a generated id like
  `NEW_CN_2023551807935057693_Power_HydroCap_EU`, `is_synthetic` is `True`,
  and `company_npv.csv`'s `asset_count` drops to the number of
  technology/geography buckets rather than physical assets (e.g. `11` for
  the same company).

NPV totals also differ between the two runs (not just their granularity) —
aggregating before running the model is not equivalent to aggregating the
model's asset-level output afterwards, because retirement, staggered-shock,
and continued-O&M logic all operate differently on synthetic
technology-level "assets" than on real ones. Don't mix outputs from
different granularity settings when comparing runs, and check
`run_params.csv` (written per run under `workspace/results_<version>/`) to
confirm which setting produced a given output.

### Plots

Plots are **not** catalog datasets — they're written directly to disk
inside reporting nodes via matplotlib (so they won't show up in `kedro
viz`'s data flow, and some folders are wiped and rewritten on every
`reporting` run):

| Folder (under `data/08_reporting/`) | Produced by |
|---|---|
| `companies_trajectories_plots/` | `plot_late_sudden_trajectories` |
| `companies_staggered_shock_plots/` | `plot_staggered_shock` |
| `asset_financial_trajectories/` | `plot_asset_financial_trajectories` |

> 📸 *Screenshot idea: one example plot from each folder above.*

## 7. (Optional) Troubleshooting / kedro-viz

```bash
kedro viz
```

Opens a web UI showing the pipeline graph, node inputs/outputs, and data
lineage — useful for seeing which tag(s) touch which datasets.

> 📸 *Screenshot idea: kedro-viz graph with the `altrisk` and `reporting`
> tag filters highlighted.*

### Common issues

- **`kedro run` fails immediately on a missing dataset** — usually means
  one of the three input CSVs isn't in `data/05_model_input/`, or is
  misnamed. Re-check [section 3](#3-getting-the-data).
- **`--tags=reporting` alone does nothing / errors** — reporting consumes
  `altrisk` outputs (`asset_earnings`, `company_trajectories`,
  `yearly_npv_trajectories`); run `--tags=altrisk,reporting` (or run
  `altrisk` first).
