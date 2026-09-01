# Troubleshooting

The failure modes you are most likely to hit, keyed by the error text you will
see. Kedro prints the failing node's name immediately before the traceback -
read that line first. Node names are namespaced (`<pipeline>.<node>`), so that
one line tells you which of the six stages you are in.

## Install and environment

### The install fails on the Python version

**Cause:** wrong Python version. The dependency set pins `>=3.10,<3.11`.

```bash
uv run python --version          # must say 3.10.x
```

`uv sync` will provision a matching interpreter on its own. If you pinned a
different one, reset it and re-sync:

```bash
rm -rf .venv
uv python pin 3.10
uv sync
```

### `pytest: error: unrecognized arguments: --cov-report --cov src/altr_model`

`pytest-cov` is missing. `pyproject.toml` puts `--cov` in the pytest `addopts`,
so every `pytest` invocation needs the plugin, whatever you are running. It is
part of the default `dev` group, so the fix is normally just to re-sync:

```bash
uv sync
uv run pytest
```

If you are running `pytest` from an environment you built by hand, install
`pytest` and `pytest-cov` into it.

### `kedro: command not found`

You are calling `kedro` outside the project environment. Either prefix commands
with `uv run` (`uv run kedro run ...`) or activate the environment once with
`source .venv/bin/activate`. `uv run python -m kedro run ...` works as a
fallback.

### `ModuleNotFoundError: No module named 'altr_model'`

The environment does not have the project installed - usually a hand-built venv
rather than the one `uv sync` manages. Run `uv sync` from the repository root
and use `uv run`.

### `Kedro is sending anonymous usage data …` on every command

The `kedro-telemetry` plugin, installed as a dependency of Kedro itself. It is a
notice, not an error. Silence it by declining once, in the repository root:

```bash
echo 'consent: false' > .telemetry
```

`KEDRO_DISABLE_TELEMETRY=1` or `DO_NOT_TRACK=1` in the environment does the same
per shell. `.telemetry` is already listed in `.gitignore`.

## Input data

### `DatasetError: Failed while loading data from dataset CSVDataset(filepath=data/05_model_input/assets_forecasts.csv)`

The converted model inputs are missing. Three files must exist in
`data/05_model_input/`: `assets_forecasts.csv`, `companies_ownerships.csv`,
`scenarios.csv`. Produce them from the delivered files with
`uv run python scripts/prepare_inputs.py` (see [quickstart](quickstart.md)
steps 3-4). If that script itself stops on a missing file under `data/01_raw/`,
the delivered files were never placed there - check for a stray `.zip` you
forgot to unzip.

### `ValueError` naming a missing column, raised by `prepare_inputs.py`

An input file does not carry the deliverables schema - usually an older extract,
or a file re-saved by a spreadsheet application (which silently renames or
reorders columns). The script validates everything before it writes anything, so
`data/05_model_input/` is untouched: fix the source file and re-run.

The scenarios check is the strictest of the three: beyond the pathway columns it
requires the whole cost block (`lifetime_years`, `efficiency_decimal`,
`capital_cost_usd_per_mw`, `om_cost_usd_per_mw_per_yr`,
`capacity_additions_mw_per_yr`, `scrap_usd_per_mw`, `carbon_price_usd_per_tco2`,
`fuel_price`). A bare prices-and-pathways extract passes a casual eyeball and
fails here.

### `companies: N% of asset-years sum to >105%` (warning, not an error)

`prepare_inputs.py` totals `ownership_percentage` per `(asset_id, year)` and
warns when the delivered rows over-allocate the asset. Capacity is allocated as
`capacity × ownership_percentage`, so rows that sum above 100% inflate every
downstream number silently.

The usual cause is an extract that flattens every rung of an ownership chain, so
different companies on different rungs each claim the same capacity. Note that
consolidation cannot rescue it: `_consolidate_ownership_stakes` sums **every**
stake a company holds in one asset-year into a single row, and that merge is
sum-preserving. Fix it in the source extract.

## Scenario selection

### `AssertionError: Target scenario '…' not found in scenarios pathways`

### `AssertionError: Baseline scenario '…' not found in scenarios pathways`

The name in `conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml`
does not match any value in the `scenario` column of
`data/05_model_input/scenarios.csv`. Names are matched exactly, spaces and dots
included. List what is actually available:

```bash
uv run python -c "import pandas as pd; \
print(sorted(pd.read_csv('data/05_model_input/scenarios.csv', \
usecols=['scenario'])['scenario'].unique()))"
```

The trap: the model prepends `AR6_<provider>_` to names that lack it, so the
value you set must be the full prefixed name as it appears in the file. The
[scenario catalog](scenario_catalog.md) lists known-good pairs.

### `AssertionError: Baseline and target scenarios start at different years`

The two scenarios come from different providers, or from different vintages of
one provider. Pick both members of a pair from the same provider block in the
[scenario catalog](scenario_catalog.md).

### `ValueError: Alignment year must be greater than shock year`

`alignment_year` is earlier than `shock_year` in
`conf/base/parameters_calculate_company_trajectories.yml`.

### `ValueError: With CCS technologies are not present in the scenarios pathways`

### `ValueError: Without CCS technologies are not present in the scenarios pathways`

`ccs_on` does not match the scenario data. Set `ccs_on: True` only for scenario
files that carry ` - w/ CCS` technology variants, `False` for files that carry
` - w/o CCS`, and `Null` to ignore the distinction.

### The run finishes, but the numbers look economically impossible

Not every scenario × technology × geography combination is economically viable,
and the model will happily run the arithmetic on one that is not. Two checks
against the scenario data before blaming the model, both described in
[Methodology notes](methodology_notes.md#economic-viability-of-a-scenario-pair):

* **Fixed cost check** - if annual fixed O&M per MW exceeds
  `capacity_factor × 8760 × price`, EBITDA is negative for that row no matter
  what else happens.
* **Variable cost check** - if `fuel_price ÷ efficiency` exceeds the price, every
  unit produced loses money before fixed costs are counted.

## Filtering and coverage

### `ValueError: No assets remaining after filtering`

The filters removed everything. In descending order of likelihood: `company_ids`
lists ids that are not in `companies_ownerships.csv`; the scenario pair's start
year lies outside the asset forecast years; `max_forecast_horizon` is too small
for the data; the `ccs_on` setting sent every asset to a technology variant the
scenario file does not carry.

Start by emptying the filter (`company_ids: []`) and re-running - if that works,
the ids were the problem. Note that there is **no ownership-tier filter**:
companies are not selected by ownership level, so a tier setting cannot be what
emptied the panel.

### `ValueError: ownership_percentage looks like a 0-1 fraction (max=…)`

The ownership extract uses the 0-1 fraction convention; the model expects the
0-100 percent scale, and dividing a fraction by 100 would shrink allocated
capacity roughly a hundredfold. Rescale the extract upstream rather than
patching the node.

### `ValueError: Ambiguous scenario geography assignment detected`

Two scenario geographies of equal specificity cover the same country, so the
model refuses to pick one arbitrarily. The message lists every offending
`asset_id` and country. Fix it in the scenario data: drop one of the tied
geographies, or narrow one of them. How geography matching works - most specific
wins - is described in
[Methodology notes](methodology_notes.md#how-assets-are-matched-to-a-scenario-geography).

### `AssertionError: Some assets are not assigned to a scenario geography`

An asset's country is not covered by any geography in the scenario file, and the
file has no global geography to fall back to. Either restrict the asset universe
with `company_ids`, or use a scenario file with global coverage.

## Runs and reruns

### Memory pressure or a killed process while loading scenarios

The scenarios file is the largest input by a wide margin and is read into memory
whole. If the process dies during `Loading data from scenarios`, reduce it
rather than the machine:

* Keep only the rows for the providers you actually use - the pair you set in
  the parameters file plus nothing else - and re-run `prepare_inputs.py`.
* Shrink the asset side too: a short `company_ids` list cuts the asset panel and
  every downstream table with it.
* Prove the install works on the committed slice first:
  `uv run kedro run --env fixture --tags altrisk`, which needs no real data at
  all.

### A re-run picks up stale intermediate data

Outputs are plain CSVs written in place - a re-run overwrites
`data/07_model_output/`, it does not version it. Two consequences:

* Copy the outputs elsewhere before re-running if you want to compare two
  configurations. Nothing in the pipeline does this for you.
* A run that crashed halfway leaves a mix of old and new files on disk. Delete
  `data/07_model_output/` and `data/08_reporting/` before a clean re-run rather
  than reasoning about which files are fresh.

To re-run only part of the pipeline after a late-stage failure, keep the
intermediate files and restart from the failing node:

```bash
uv run kedro run --tags altrisk --from-nodes <node-name>   # resume from a node onward
uv run kedro run --tags altrisk --to-nodes <node-name>     # stop after a node
uv run kedro run --tags altrisk --nodes <node-name>        # a single node
```

The node names are the namespaced ones printed as `Running node: ...`;
`uv run kedro registry describe __default__` lists them all up front. There is
no pipeline called `full` - `altrisk` is a **tag**, not a pipeline name, so it
belongs after `--tags`, never after `--pipeline`; the six pipeline names
`kedro registry list` prints are what `--pipeline` accepts.

Partial runs only work when every input a node needs is a *persisted* dataset.
The hand-offs between stages 1, 2 and 3 (`asset_forecast_panel`,
`company_projection_inputs`, `company_pathways_pre_allocation`) are
`MemoryDataset`s declared nowhere in `conf/base/catalog.yml`, so they live for
the length of one run only and cannot be picked up by a later one. If a partial
run complains about a missing dataset, run the full `--tags altrisk` instead.

### The reporting stage fails or produces nothing

`plot_transition_risk_results` consumes the outputs of the `altrisk` stages. It
cannot run on its own against an empty `data/07_model_output/` - run a bare
`uv run kedro run` (all six stages), or run `--tags altrisk` first and
`--tags reporting` after it in the same working directory.

Note also that it writes to hardcoded `data/08_reporting/` paths rather than
through the catalog, so `--env fixture` does **not** redirect its output. That
is why the fixture regression run excludes it.

## Where the logs are

Kedro logs to the console only; there is no log file by default. To keep a
record of a run:

```bash
uv run kedro run --tags altrisk 2>&1 | tee run_$(date +%Y%m%d_%H%M).log
```

The stage-level detail you usually want is already in that stream: the model's
own nodes log row counts and summary statistics at `INFO` as they go
(`Computed FCFF for N asset-year rows`, `Aggregated to N company-level
records`), so a diff of two run logs is often enough to locate where two runs
diverged. If you want logging to a file permanently, add a `conf/logging.yml`
(next to `conf/base/`, not inside it) with a file handler: Kedro picks that path
up automatically, and `KEDRO_LOGGING_CONFIG=<path>` overrides it per run.
