# Crispy Kedro - Climate Risk Financial Analysis Pipeline

[![Powered by Kedro](https://img.shields.io/badge/powered_by-kedro-ffc900?logo=kedro)](https://kedro.org)

A climate risk financial analysis pipeline that performs transition risk analysis by modeling the financial impact of climate scenarios on companies and their assets in the energy sector.

## Installation

### 1. Create a Virtual Environment with Python 3.10

The project requires Python 3.10 (3.11+ is not supported due to dependency constraints).

```bash
# Using pyenv (recommended)
pyenv install 3.10.15
pyenv local 3.10.15

# Or using venv with Python 3.10
python3.10 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 2. Install Dependencies with Poetry

```bash
# Install Poetry if you don't have it
curl -sSL https://install.python-poetry.org | python3 -

# Install project dependencies
poetry install

# Activate the Poetry shell
poetry shell
```

## Running the Pipeline

### Step 1: Download Input Data

If you have GCP credentials for BigQuery:

```bash
kedro run --tags=download_inputs
```

If you **don't have GCP credentials**, manually place these files in the `data/05_model_input/` folder:
- `downloaded_assets.csv`
- `downloaded_scenarios.csv`
- `downloaded_companies.csv`

### Step 2: Run the Model

#### Option A: Using Kedro CLI

Run the model with basic configuration from `conf/base/`:

```bash
# Get results only
kedro run --tags=altrisk

# Get results with plots and reporting
kedro run --tags=altrisk,reporting
```

The basic configuration includes company selection and other parameters defined in the `conf/base/` folder.

#### Option B: Using VS Code Debug Configurations

Use the pre-configured debug settings in `.vscode/launch.json`:

1. **Kedro Run AltRisk with reporting (Debug)**: Runs with `--tags=altrisk,reporting` (results + plots)
2. **Kedro Run AltRisk (Debug)**: Runs with `--tags=altrisk` (results only)
3. **Kedro Download Trisk data (Debug)**: Runs with `--tags=download_inputs` (data download)

#### Option C: Using Jupyter Notebook for Batch Processing

Use `notebooks/generate_results.ipynb` to:
- Generate batches of results with parameter overriding
- Run with or without plots
- Currently configured to run over all companies (not just the selection in `conf/base/`)

For scenario-pair sweeps, `notebooks/run_all_scenarios_comparison.py` is the
script form: it reads a scenario manifest, writes each variant's overrides to a
dedicated `conf/study/` environment (never `conf/local/`), shells out to
`kedro run --env study`, and collects results under
`workspace/comparison_results/`. `--dry-run` prints the plan without running.

## Code Structure

The main pipeline code is located in `src/crispy_kedro/pipelines/`. Each pipeline is in its own folder:

- `download_inputs/`: Downloads data from BigQuery
- `inputs_processing/`: Filters and processes input data
- `inputs_postproc/`: Final data preparation
- `create_baseline_and_target_trajectories/`: Creates production trajectories
- `create_late_sudden_trajectories/`: Models delayed policy scenarios
- `distribute_impacts_to_asset_level/`: Applies staggered shock methodology
- `earnings_model/`: Calculates asset-level earnings
- `valuation_model/`: Converts earnings to NPV using DCF
- `reporting/`: Generates outputs and visualizations

Each pipeline folder contains:
- `nodes.py`: The actual data processing functions
- `pipeline.py`: Pipeline definition and node connections

Four further folders under `pipelines/` - `layer1/`, `layer2/`,
`outputs_processing/` and `report_outputs/` - are legacy code with no
`pipeline.py`, so Kedro's auto-discovery never registers them and nothing in a
run executes them.

For more information on Kedro pipelines and project structure, see the [Kedro documentation](https://docs.kedro.org).

## Configuration

**Edit `conf/base/parameters.yml`.** It holds every parameter a normal run changes (scenario pair, company filter, shock and alignment years, MCPR and carbon-cost switches, capex switches, the DCF block), each with a comment block giving meaning, unit, default, source and status. Per-pipeline files `conf/base/parameters_<pipeline>.yml` hold advanced knobs; leave them unless you know why. `docs/parameters.md` is generated from these comment blocks. Every run validates the resolved parameters before the first node (`src/crispy_kedro/hooks.py`); a typo in an enum or an out-of-range number stops the run with the key, the value and the allowed set.

How Kedro resolves the configuration here:

- `src/crispy_kedro/settings.py` sets `default_run_env: "local"`, so a bare `kedro run` loads `conf/base/` and then `conf/local/` on top.
- Within one environment, all `parameters*.yml` files are deep-merged into one dict; filenames do not matter; a leaf key that appears in two files raises an error, while two files may contribute disjoint leaves to the same block.
- Across environments the merge is **destructive per top-level key**: a key in any `conf/local/*.yml` replaces the same key from base, and a nested block such as `dcf` is replaced whole, siblings included.
- Move a key between files, never copy it; keep each block (`dcf`, `staggered_shock`) in one file so a local override has one place to copy from.
- `conf/local/` is gitignored. Nothing automated writes there any more; the batch runner uses its own `conf/study/` env. If you find parameter files in `conf/local/`, they are silently overriding base.

Prefer command-line overrides for one-off runs:

```bash
kedro run --tags=altrisk --params="shock_year=2030,carbon_cost_method=full_ef"
```

`notebooks/generate_results.ipynb` passes `extra_params` to `KedroSession`; the scenario sweep `notebooks/run_all_scenarios_comparison.py` writes `conf/study/` and runs `kedro run --env study`.

## Parameter overview

All 59 parameters, in the order of the interactive selector
([`docs/parameters.html`](docs/parameters.html) - searchable, with unit,
default, source and status per key; [`docs/parameters.md`](docs/parameters.md)
is the same table in markdown). All three are generated from the comment blocks
in `conf/base/*.yml` by `scripts/gen_param_docs.py` - edit the YAML comments,
then regenerate.

### User tier - `conf/base/parameters.yml`

- `baseline_scenario` - IAM scenario used as the no-transition reference pathway
- `target_scenario` - IAM scenario the late-sudden shock converges to
- `company_ids` - restrict the run to these company ids (empty list = all companies)
- `ownership_type` - which ownership links attach assets to companies (`direct` / `indirect`)
- `ccs_on` - which CCS variant of coal/gas/biomass/oil scenarios to use
- `max_forecast_horizon` - years of asset-level GEM forecast kept before scenario pathways take over
- `shock_year` - first year of the late-sudden transition shock
- `alignment_year` - year company production reaches the target pathway; also floors retirement at +1
- `enable_mcpr` - market-clearing-price (MCPR) adjustment on/off; master switch for every `mcpr_*` key
- `mcpr_mode` - how MCPR treats carbon: `carbon_explicit` or `merit_order_decline` *(gated by `enable_mcpr`)*
- `carbon_cost_method` - `full_ef` vs `differential_ef` emission-factor treatment in the carbon cost
- `market_passthrough` - share of carbon cost passed through to customers
- `price_ramp` - blend baseline→target prices over the transition window instead of a hard switch
- `include_growth_capex` - charge capex for capacity additions
- `include_replacement_capex` - charge routine replacement capex on operating capacity
- `include_decom_costs` - charge decommissioning cost on retired capacity
- `dcf.discount_rate_baseline` - real discount rate, baseline pathways
- `dcf.discount_rate_shock` - real discount rate, shock pathways (ships equal to baseline)
- `dcf.brown_discount_spread` - extra discount spread on carbontech assets, both legs
- `dcf.green_discount_spread` - discount reduction on non-carbontech assets (greenium)
- `dcf.terminal_value.method` - terminal value after the last modelled year: `perpetuity` or `none`
- `dcf.terminal_value.g_real_default` - fallback real terminal growth *(dead: brown/green rates are always set)*
- `dcf.terminal_value.g_real_brown` - real terminal growth, carbontech
- `dcf.terminal_value.g_real_green` - real terminal growth, greentech
- `dcf.terminal_value.normalization_window` - years averaged into the terminal FCFF
- `dcf.stranding_aware_tv` - three-tier terminal value: stranded zero / carbontech annuity / perpetuity
- `dcf.stranding_consecutive_years` - consecutive loss years that mark an asset stranded *(gated by `stranding_aware_tv`)*
- `dcf.brown_remaining_life_years` - annuity horizon for still-profitable carbontech *(gated by `stranding_aware_tv`)*

### Advanced - `parameters_distribute_impacts_to_asset_level.yml`

- `apply_retirement_baseline` - zero baseline activity once an asset passes its technology lifetime
- `apply_retirement_shock` - the same retirement rule on the shock trajectories
- `apply_decreasing_staggered_shock` - allocate the cut in staggered age waves instead of proportional scaling
- `staggered_shock.g_k` - steepness of the logistic weight ordering assets for the cut *(gated)*
- `staggered_shock.n_quantiles` - number of age waves the cut is spread over *(gated)*
- `retirement_floor_offset_years` - no asset retires before `alignment_year` + this offset

### Advanced - `parameters_earnings_model.yml`

- `mcpr_method` - how the clearing price is derived (`marginal_technology`) *(gated by `enable_mcpr`)*
- `mcpr_markup_factor` - multiplier on the marginal cost to form the clearing price *(gated)*
- `mcpr_merit_order_alpha` - merit-order price elasticity per pp of VRE share *(paper-track only)*
- `mcpr_merit_order_floor` - floor on the merit-order clearing price *(paper-track only)*
- `enable_dynamic_capture_ratios` - VRE value factors from VRE capacity share instead of static defaults *(gated)*
- `enable_regional_mcpr_vf` - geography-specific VRE value factors *(gated)*
- `mcpr_regional_value_factors` - the regional VRE value-factor table, three penetration tiers *(gated by `enable_regional_mcpr_vf`)*
- `apply_continued_om_baseline` - keep charging fixed O&M on capacity frozen at retirement, baseline leg
- `apply_continued_om_shock` - the same on the shock leg - the stranding lever
- `dynamic_marginal_ef` - marginal EF declines with VRE share *(inert under the shipped `full_ef` configuration)*
- `replacement_capex_rate` - yearly replacement capex as a share of operating capacity *(gated by `include_replacement_capex`)*
- `decom_cost_share_of_capex` - decommissioning cost per retired MW as a share of capex *(gated by `include_decom_costs`)*
- `default_capacity_factor` - capacity factor used when the scenario reports none
- `mcpr_marginal_technologies` - technologies eligible to set the clearing price *(gated)*
- `mcpr_floor_at_iam_price` - MCPR may only lift prices toward the clearing price, never lower them *(gated)*
- `mcpr_value_factors` - uniform per-technology value factors on the clearing price *(gated)*

### Advanced - `parameters_inputs_postproc.yml`

- `reduce_granularity_from_asset_to_company_level` - collapse the asset panel to one synthetic row per company × technology

### Advanced - `parameters_inputs_processing.yml`

- `excluded_country_iso2` - assets in these countries are dropped before modelling (the historical NGFS hard-fix, now a parameter)

### Reporting - `parameters_reporting.yml`

- `plot_staggered_shock_use_log_scale` - log-scale y axis on the staggered-shock plots
- `reporting.basis` - label for the monetary basis (`real` / `nominal`; label only, no conversion)
- `reporting.base_year` - price base year shown in subtitles (label only)
- `reporting.top_n_assets_per_company` - assets per company shown in asset-level plots
- `reporting.plots` - PNG/PDF output switches, dpi and figure size
- `reporting.materiality_threshold_usd` - QC threshold below which NPV deltas are immaterial
- `reporting.small_numbers_rounding` - QC threshold for flagging tiny residuals

## Outputs

Results are saved in the `data/` directory:
- `data/07_model_output/`: Model results (NPV, earnings, etc.)
- `data/08_reporting/`: Charts and reports (when using `reporting` tag)

## Visualization

Explore the pipeline structure interactively:

```bash
kedro viz
```

This opens a web interface showing the pipeline flow, data lineage, and dependencies.

## License

This project is licensed under the terms specified in the LICENSE file.
