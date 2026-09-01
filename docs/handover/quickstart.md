# Quickstart

From a clean machine to a completed run. Every command below is
copy-pasteable; run them from the repository root unless stated otherwise.

!!! warning "Python 3.10 only"
    The dependency set pins Python `>=3.10,<3.11`. Python 3.11+ will fail at
    install time, and a 3.9 environment will fail at import time. `uv` will
    provision 3.10 for you; if you manage interpreters yourself, check with
    `python3.10 --version` before you start.

## 1. Get the code

```bash
git clone https://github.com/Theia-Finance-Labs/altr-model.git
cd altr-model
```

!!! note "One repository"
    An earlier delivery plan split the work across a second repository,
    `altr-model-refactored`. The 2026-09-01 owner ruling settled on a single
    repo - `Theia-Finance-Labs/altr-model`, the clone URL above and the one the
    methodology PDF already gives - and that second repository is retired. If
    you were pointed at `altr-model-refactored`, use this URL instead.

## 2. Install with uv

The project is managed with [uv](https://docs.astral.sh/uv/). One command
creates the virtual environment, resolves against the committed `uv.lock` and
installs the project plus its dev tools:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # if uv is not installed yet
uv sync
```

On Windows, install uv from PowerShell instead; `uv sync` is the same
everywhere:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

`uv sync` installs the `dev` group by default, so `pytest`, `pytest-cov` and
`ruff` are already there. Two optional groups are *not* installed and are not
needed to run the model:

| Group | Install with | What it is for |
| --- | --- | --- |
| `docs` | `uv sync --group docs` | Building this documentation site locally. |
| `streamlit` | `uv sync --group streamlit` | The batch-run app under `notebooks/` (internal builds only - a delivered copy carries neither the app nor this group, so the row is there for completeness, not as an instruction). |

`pyproject.toml` declares one further optional group, used only by the
maintainers' internal input tooling. It is not installed by default and you
never need it; in a delivered copy the module it serves is not present either,
which is why nothing in this documentation describes it.

Verify the install - this must print a `0.19.x` version and exit cleanly:

```bash
uv run python -c "import altr_model, kedro; print(kedro.__version__)"
```

Every command below is prefixed with `uv run`, which resolves against the
project environment without you activating it. If you would rather activate it
once, `source .venv/bin/activate` (Windows: `.venv\Scripts\activate`) and drop
the prefix.

## 3. Place the input data

The model is fed by three CSV files. Put them, unmodified, in `data/01_raw/`:

| File | Contents |
| --- | --- |
| `assets_forecasts.csv` | Physical assets and their per-year technical forecasts (capacity, technology, country, age) |
| `companies_ownerships.csv` | Which company owns which asset, and the ownership percentage of each stake |
| `scenarios.csv` | IAM scenario pathways, prices, capacity factors and cost assumptions |

Column-level dictionaries for all three files, including the units traps
(`ownership_percentage` is on the 0-100 scale, not a fraction):
[input data reference](input_data.md).

```bash
mkdir -p data/01_raw
cp /path/to/assets_forecasts.csv      data/01_raw/
cp /path/to/companies_ownerships.csv  data/01_raw/
cp /path/to/scenarios.csv             data/01_raw/
```

If `scenarios.csv` was delivered zipped, unzip it first - the pipeline reads the
plain CSV:

```bash
unzip -o /path/to/scenarios.csv.zip -d data/01_raw/
```

!!! note "There is no download pipeline"
    Ingestion is not part of the Kedro graph. The three files are produced by
    the maintainers with internal tooling that is not part of this package;
    you receive them through another channel and place them as above. Nothing
    in `kedro run` fetches data, so a run can never surprise you by reaching
    for a network source.

### Carbon prices: there is no fourth file

Carbon prices reach the model through the `carbon_price_usd_per_tco2` column of
`scenarios.csv`, which `scripts/prepare_inputs.py` requires. There are three
input files, not four.

An earlier lineage also carried an `ar6_carbon_prices` catalog entry, reading a
root-level side-file and injecting a carbon price per scenario, geography and
year. It is deliberately **not** adopted here. That injection begins by checking
whether the scenario table already carries carbon prices and returns untouched
when it does — which is the case for every IAM extract this package ships, so it
never fired. Adopting it would have added a required fourth input file that
neither `prepare_inputs.py` produces nor the package ships, in exchange for no
change in behaviour.

If you bring an IAM extract whose `carbon_price_usd_per_tco2` column is empty,
the carbon cost will be zero everywhere rather than silently wrong; fill the
column in your scenarios input rather than reaching for a side-file.

One artefact of that lineage is still committed: `tests/fixtures/data/`
contains an `ar6_carbon_prices.csv`. It is **inert** - no catalog entry, no
node and no test reads it as an input - and it is kept rather than deleted so
the file the retired entry pointed at stays inspectable. Do not take its
presence as a fourth input file.

## 4. Convert the deliverables into model inputs

The three delivered files use the deliverables schema. One script validates them
and writes the files the pipeline consumes:

```bash
uv run python scripts/prepare_inputs.py
```

It reads `data/01_raw/` and writes `data/05_model_input/`:

```
data/05_model_input/assets_forecasts.csv
data/05_model_input/companies_ownerships.csv
data/05_model_input/scenarios.csv
```

Both directories can be overridden: `uv run python scripts/prepare_inputs.py
--source data/01_raw --dest data/05_model_input`. The script validates every
input before it writes anything, so a schema problem stops it with a named
missing column rather than leaving a half-converted `data/05_model_input/`.

## 5. Choose the run configuration

There is **no `conf/base/parameters.yml`**. Kedro merges every
`conf/base/parameters*.yml` into one flat namespace, and ALTR splits that
namespace across six per-pipeline files. The one you normally touch is
`conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml` - scenario
pair, company filter, CCS switch, forecast horizon and granularity, each
annotated in place. Shock timing sits next to the pipeline that consumes it, and
the cost switches next to theirs:

| File | What it holds |
| --- | --- |
| `parameters_prepare_scenario_asset_and_company_inputs.yml` | `baseline_scenario`, `target_scenario`, `company_ids`, `ownership_type`, `ownership_aggregation`, `ccs_on`, `max_forecast_horizon`, `reduce_granularity_from_asset_to_company_level` |
| `parameters_calculate_company_trajectories.yml` | `shock_year`, `alignment_year`, `price_ramp` |
| `parameters_calculate_asset_earnings.yml` | `market_passthrough`, the cost switches and the carbon-cost method |
| `parameters_allocate_company_trajectories_to_assets.yml` | retirement and staggering knobs |
| `parameters_calculate_asset_and_company_npv.yml` | the `dcf` block |
| `parameters_plot_transition_risk_results.yml` | plotting toggles |

The three keys you will almost always touch:

```yaml
# conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml
baseline_scenario: "AR6_AIM/CGE 2.2_EN_NPi2020_1200f"
target_scenario: "AR6_AIM/CGE 2.2_EN_NPi2020_900f"

# conf/base/parameters_calculate_company_trajectories.yml
shock_year: 2033
```

Both scenario names must appear in the `scenario` column of
`data/05_model_input/scenarios.csv`, and both must come from the same IAM
provider. See the [scenario catalog](scenario_catalog.md) for candidate pairs.
The defaults shipped in the files are a valid pair - you can run first and tune
afterwards. Full per-key annotations: [parameters reference](parameters.md).

## 6. Run the model

```bash
uv run kedro run --tags altrisk
```

That runs stages 1-5 (29 nodes) and produces the numbers. To also produce the
figures:

```bash
uv run kedro run
```

A bare `uv run kedro run` runs the default pipeline, which is all six stages.
The plotting stage renders a figure per company per view and dominates the wall
clock, so run `--tags altrisk` on its own while you are still tuning parameters.

Expected console landmarks, in order:

```
INFO     Kedro project altr-model
INFO     Loading data from scenarios (CSVDataset)...
INFO     Running node: prepare_scenario_asset_and_company_inputs.prepare_scenarios: ...
INFO     Completed 1 out of 29 tasks
...
INFO     Saving data to company_npv (CSVDataset)...
INFO     Completed 28 out of 29 tasks
INFO     Pipeline execution completed successfully.
```

Node names are namespaced with their pipeline (`<pipeline>.<node>`), which is
how you tell which stage a failure is in. The run has failed if you do not see
`Pipeline execution completed successfully` - see
[Troubleshooting](troubleshooting.md) for the common causes. Run duration scales
with the number of companies and the forecast horizon; a first full-universe run
is measured in tens of minutes, not seconds.

## 7. Collect the outputs

| Path | What it holds |
| --- | --- |
| `data/07_model_output/company_npv.csv` | **Headline table** - baseline vs shock NPV per company |
| `data/07_model_output/company_technology_npv.csv` | Same comparison, split by technology and geography |
| `data/07_model_output/asset_npv.csv` | Per-asset NPV with its revenue/cost/CapEx components |
| `data/07_model_output/yearly_npv_trajectories.csv` | Year-by-year discounted detail behind the NPVs |
| `data/07_model_output/asset_earnings.csv` | Per-asset, per-year earnings before discounting |
| `data/07_model_output/asset_trajectories.csv` | Per-asset capacity path per trajectory type |
| `data/07_model_output/company_trajectories.csv` | Company baseline / target / requested / realised paths |
| `data/07_model_output/frozen_capacity_at_retirement.csv` | For each retiring asset, the capacity it last stood at, carried from its retirement year onward - a lookup surface, not a cost driver |
| `data/08_reporting/` | Figure packs (`reporting` tag only) |

Read them with the [user guide](user_guide.md).

## Smoke test without the real data

The repository ships a tiny committed input slice and a `fixture` environment
that points at it, with every persisted output redirected to
`data/fixture_run/`. It runs the five model stages in minutes and touches
nothing in `data/07_model_output/`:

```bash
uv run kedro run --env fixture --tags altrisk
```

The slice lives in `tests/fixtures/data/` (`assets_forecasts.csv`,
`companies_ownerships.csv`, `scenarios.csv`) and
`conf/fixture/parameters_prepare_scenario_asset_and_company_inputs.yml`
overrides the scenario pair to one the slice actually contains. Use it to check
the install before the real data arrives, and after any change to the code or
configuration.

`notebooks/walkthrough.ipynb` is the guided version of the same run: it
executes the fixture slice top to bottom and reads each output table with
commentary, so by the end you know which file answers which question.

!!! note "The fixture environment covers the model stages, not the plots"
    `plot_transition_risk_results` writes to hardcoded `data/08_reporting/`
    paths that configuration cannot redirect, so it is excluded from the fixture
    run rather than allowed to escape the quarantine.

The same run, wrapped in assertions on the output columns and NPV values, is the
project's regression test:

```bash
uv run pytest
```

`pytest` and `pytest-cov` come with the default `dev` group, so `uv sync` has
already installed them - `pyproject.toml` puts `--cov` in the pytest `addopts`,
and without the plugin `pytest` exits on `unrecognized arguments: --cov-report`.

## Explore the pipeline graph

```bash
uv run kedro viz run
```

Opens a browser UI showing the stages, their nodes, and the datasets flowing
between them.

## Running several configurations

Comparing parameter sets - different scenario pairs, granularities, cost
switches - without editing `conf/base/` between runs is what the batch tooling
is for: [batch runs and the app](batch_runs.md). Note that most of it is
maintainer tooling left out of sanitized delivery copies; the page says
exactly which pieces a copy carries.
