# Troubleshooting

The failure modes you are most likely to hit, keyed by the error text you will
see. Kedro prints the failing node's name immediately before the traceback —
read that line first; it tells you which of the eight stages you are in.

## Install and environment

### The install resolves forever, or fails on a dependency

**Cause:** wrong Python version. The dependency set pins `>=3.10,<3.11`.

```bash
python --version          # inside the activated venv — must say 3.10.x
```

Recreate the environment with 3.10 explicitly:

```bash
deactivate 2>/dev/null
rm -rf .venv
python3.10 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### `kedro: command not found`

The virtual environment is not active, or the install did not complete. Run
`source .venv/bin/activate`, then `pip install -e .` again. `python -m kedro run
...` works as a fallback.

### `ModuleNotFoundError: No module named 'crispy_kedro'`

`pip install -e .` was run in a different environment than the one you are using
now, or from a directory other than the repository root. Re-run it from the root
with the venv active.

## Input data

### `DatasetError: Failed while loading data from dataset CSVDataset(filepath=data/05_model_input/downloaded_assets.csv)`

The converted model inputs are missing. Three files must exist in
`data/05_model_input/`: `downloaded_assets.csv`, `downloaded_companies.csv`,
`downloaded_scenarios.csv`. Produce them from the delivered files with
`python scripts/prepare_inputs.py` (see [quickstart](quickstart.md) steps 3–4).
If that script itself stops on a missing file under `data/01_raw/`, the
delivered files were never placed there — check for a stray `.zip` you forgot to
unzip.

### `ValueError` naming a missing column, raised by `prepare_inputs.py`

An input file does not carry the deliverables schema — usually an older extract,
or a file re-saved by a spreadsheet application (which silently renames or
reorders columns). The script validates everything before it writes anything, so
`data/05_model_input/` is untouched: fix the source file and re-run.

## Scenario selection

### `AssertionError: Target scenario not found in scenarios pathways`

### `AssertionError: Baseline scenario not found in scenarios pathways`

The name in `conf/base/parameters.yml` does not match any value in the
`scenario` column of `data/05_model_input/downloaded_scenarios.csv`. Names are
matched exactly, spaces and dots included. List what is actually available:

```bash
python -c "import pandas as pd; \
print(sorted(pd.read_csv('data/05_model_input/downloaded_scenarios.csv', \
usecols=['scenario'])['scenario'].unique()))"
```

Two traps: the model prepends `AR6_<provider>_` to the names it builds, so the
value you set must be the full prefixed name as it appears in the file; and the
baseline must exist among rows typed as `baseline`, the target among rows typed
as `target`. The [scenario catalog](scenario_catalog.md) lists known-good pairs.

### `AssertionError: Baseline and target scenarios start at different years`

The two scenarios come from different providers, or from different vintages of
one provider. Pick both members of a pair from the same provider block in the
[scenario catalog](scenario_catalog.md).

### `ValueError: Alignment year must be greater than shock year`

`alignment_year` is earlier than `shock_year` in `conf/base/parameters.yml`.

### `ValueError: With CCS technologies are not present in the scenarios pathways`

### `ValueError: Without CCS technologies are not present in the scenarios pathways`

`ccs_on` does not match the scenario data. Set `ccs_on: True` only for scenario
files that carry ` - w/ CCS` technology variants, `False` for files that carry
` - w/o CCS`, and `Null` to ignore the distinction.

### The run finishes, but the numbers look economically impossible

Not every scenario × technology × geography combination is economically viable,
and the model will happily run the arithmetic on one that is not. Two checks
against the scenario data before blaming the model, both described in the
*Additional notes* section of [ALTR Model User Guide](altr_documentation.pdf):

* **Fixed cost check** — if annual fixed O&M per MW exceeds
  `capacity_factor × 8760 × price`, EBITDA is negative for that row no matter
  what else happens.
* **Variable cost check** — if `fuel_price ÷ efficiency` exceeds the price, every
  unit produced loses money before fixed costs are counted.

## Filtering and coverage

### `ValueError: No assets remaining after filtering`

The filters removed everything. In descending order of likelihood: `company_ids`
lists ids that are not in `downloaded_companies.csv`; `ownership_type` is set to
a level nobody in the file has; the scenario pair's start year lies outside the
asset forecast years; `max_forecast_horizon` is too small for the data.

Start by emptying the filter (`company_ids: []`) and re-running — if that works,
the ids were the problem.

### `ValueError: Ambiguous scenario geography assignment detected`

Two scenario geographies of equal specificity cover the same country, so the
model refuses to pick one arbitrarily. The message lists every offending
`asset_id` and country. Fix it in the scenario data: drop one of the tied
geographies, or narrow one of them. How geography matching works — most specific
wins — is described in the *Additional notes* section of the PDF.

### `AssertionError: Some assets are not assigned to a scenario geography`

An asset's country is not covered by any geography in the scenario file, and the
file has no global geography to fall back to. Either restrict the asset universe
with `company_ids`, or use a scenario file with global coverage.

## Runs and reruns

### Memory pressure or a killed process while loading scenarios

The full scenarios file is the largest input by a wide margin and is read into
memory whole. If the process dies during `Loading data from
downloaded_scenarios`, reduce it rather than the machine:

* Keep only the rows for the providers you actually use — the pair you set in
  `parameters.yml` plus nothing else — and re-run `prepare_inputs.py`.
* Shrink the asset side too: a short `company_ids` list cuts the asset panel and
  every downstream table with it.
* Prove the install works on the committed slice first:
  `kedro run --env fixture --tags altrisk`, which needs no real data at all.

### A re-run picks up stale intermediate data

Outputs are plain CSVs written in place — a re-run overwrites
`data/07_model_output/`, it does not version it. Two consequences:

* Copy the outputs elsewhere before re-running if you want to compare two
  configurations. Nothing in the pipeline does this for you.
* A run that crashed halfway leaves a mix of old and new files on disk. Delete
  `data/07_model_output/` and `data/08_reporting/` before a clean re-run rather
  than reasoning about which files are fresh.

To re-run only part of the pipeline after a late-stage failure, keep the
intermediate files and restart from the failing node:

```bash
kedro run --tags altrisk --from-nodes <node-name>   # resume from a node onward
kedro run --tags altrisk --to-nodes <node-name>     # stop after a node
kedro run --tags altrisk --nodes <node-name>        # a single node
```

The node names are the ones printed as `Running node: ...`;
`kedro registry describe full` lists them all up front (`full` is the registered
pipeline covering the eight stages — `altrisk` is a tag, not a pipeline name, so
it belongs after `--tags`, never after `--pipeline`). This only works when every input
that node needs is a *persisted* dataset — datasets that are not declared in
`conf/base/catalog.yml` live in memory for the length of one run and cannot be
picked up by a later one. If a partial run complains about a missing dataset,
run the full `--tags altrisk` instead.

### The `reporting` stage fails or produces nothing

`reporting` consumes the outputs of the `altrisk` stages. It cannot run on its
own against an empty `data/07_model_output/` — run `kedro run --tags
altrisk,reporting`, or run `altrisk` first and `reporting` after it in the same
working directory.

## Where the logs are

Kedro logs to the console only; there is no log file by default. To keep a
record of a run:

```bash
kedro run --tags altrisk 2>&1 | tee run_$(date +%Y%m%d_%H%M).log
```

The stage-level detail you usually want is already in that stream: the model's
own nodes log row counts and summary statistics at `INFO` as they go
(`Computed FCFF for N asset-year rows`, `Aggregated to N company-level
records`), so a diff of two run logs is often enough to locate where two runs
diverged. If you want logging to a file permanently, add a `conf/logging.yml`
(next to `conf/base/`, not inside it) with a file handler: Kedro picks that path
up automatically, and `KEDRO_LOGGING_CONFIG=<path>` overrides it per run.
