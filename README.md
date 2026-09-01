# ALTR Model

Asset-level transition-risk valuation model: scenario pathways in,
company and asset NPV impacts out.

The full documentation lives in `docs/handover/` and reads either as
plain markdown on GitHub or as a site:

```bash
pip install mkdocs-material
python -m mkdocs serve
```

Start with the [user guide](docs/handover/user_guide.md) once the
quickstart below has produced a run, and keep
[troubleshooting](docs/handover/troubleshooting.md) to hand.

## Quickstart

From a clean machine to a completed run. Every command below is
copy-pasteable; run them from the repository root unless stated otherwise.

> **Python 3.10 only**
> The dependency set pins Python `>=3.10,<3.11`. Python 3.11+ will fail at
> install time, and a 3.9 environment will fail at import time. Check with
> `python3.10 --version` before you start.

### 1. Get the code

```bash
git clone <repository-url> altr-model
cd altr-model
```

### 2. Create a virtual environment and install

```bash
python3.10 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -e .
```

> **The install takes 10–20 minutes, and looks stuck for most of it**
> The dependency set pulls in the Google Cloud client stack, and pip
> backtracks through dozens of `grpcio-status` releases resolving it. It
> prints
>
> ```
> INFO: pip is still looking at multiple versions of grpcio-status to
> determine which version is compatible with other requirements.
> This could take a while.
> ```
>
> and then goes quiet. That is normal — leave it running. In verification the
> first install on a clean machine ran past ten minutes; a later one, with
> pip's cache already populated, finished in 41 seconds. You pay the cost once
> per machine, not once per environment.
>
> `pip` re-resolves from scratch and ignores the `poetry.lock` shipped in the
> repository, so the exact versions you get are whatever is current on PyPI
> within the pins. Install with Poetry instead if you need to match another
> machine's environment exactly — Poetry is the tool that reads the lock file.

Verify the install — this must print a `0.19.x` version and exit cleanly:

```bash
python -c "import crispy_kedro, kedro; print(kedro.__version__)"
```

### 3. Place the input data

The model is fed by three CSV files. Put them, unmodified, in `data/01_raw/`:

| File | Contents |
| --- | --- |
| `assets_forecasts.csv` | Physical assets and their per-year technical forecasts (capacity, technology, country, age) |
| `companies_ownerships.csv` | Which company owns which asset, and at which ownership level |
| `scenarios.csv` | IAM scenario pathways, prices, capacity factors and cost assumptions |

```bash
mkdir -p data/01_raw
cp /path/to/assets_forecasts.csv      data/01_raw/
cp /path/to/companies_ownerships.csv  data/01_raw/
cp /path/to/scenarios.csv             data/01_raw/
```

If `scenarios.csv` was delivered zipped, unzip it first — the pipeline reads the
plain CSV:

```bash
unzip -o /path/to/scenarios.csv.zip -d data/01_raw/
```

#### The fourth file: carbon prices

One more input sits outside `data/`. The catalog entry `ar6_carbon_prices` reads
`6_final_AR6_viable_scenarios.csv` **at the repository root** — an AR6 extract
carrying a carbon price per scenario, geography and year. It is not part of the
three-file drop and `prepare_inputs.py` does not produce it. Without it the run
stops at task 6 of 46 with a `FileNotFoundError`.

```bash
cp /path/to/6_final_AR6_viable_scenarios.csv .    # repository root, not data/
```

Only five columns are read: `scenario_provider`, `scenario`,
`scenario_geography`, `scenario_year`, `carbon_price_usd_per_tco2`.

If your `scenarios.csv` already carries `carbon_price_usd_per_tco2` — WITCH and
REMIND extracts do — the model logs `Carbon prices already populated … skipping
injection` and never uses this file's contents. It must still exist, so a
header-only stand-in is enough:

```bash
echo 'scenario_provider,scenario,scenario_geography,scenario_year,carbon_price_usd_per_tco2' \
  > 6_final_AR6_viable_scenarios.csv
```

Verified: on a scenario file that already carries carbon prices, the stand-in
produces NPVs identical to the real extract. For an IAM that reports no carbon
price, the real file is what supplies them — a stand-in leaves the carbon price
at `0` and the price signal alone carries the transition effect.

### 4. Convert the deliverables into model inputs

The three delivered files use the deliverables schema. One script converts them
into the three files the pipeline consumes:

```bash
python scripts/prepare_inputs.py
```

It reads `data/01_raw/` and writes `data/05_model_input/`:

```
data/05_model_input/downloaded_assets.csv
data/05_model_input/downloaded_companies.csv
data/05_model_input/downloaded_scenarios.csv
```

Both directories can be overridden: `python scripts/prepare_inputs.py --source
data/01_raw --dest data/05_model_input`. The script validates every input before
it writes anything, so a schema problem stops it with a named missing column
rather than leaving a half-converted `data/05_model_input/`.

### 5. Choose the run configuration

Open `conf/base/parameters.yml`. It is the single user-facing configuration file
— scenario pair, shock timing, company filter, MCPR settings and cost switches,
each annotated in place. The three you will almost always touch:

```yaml
baseline_scenario: "AR6_REMIND-MAgPIE 2.1-4.2_EN_NPi2020_3000"
target_scenario: "AR6_REMIND-MAgPIE 2.1-4.2_EN_NPi2020_500"
shock_year: 2033
```

Both scenario names must appear in the `scenario` column of
`data/05_model_input/downloaded_scenarios.csv`, and both must come from the same
IAM provider. See the [scenario catalog](docs/handover/scenario_catalog.md) for candidate
pairs. The defaults shipped in the file are a valid pair — you can run first and
tune afterwards.

### 6. Run the model

```bash
kedro run --tags altrisk
```

That runs stages 1–7 (46 nodes) and produces the numbers. To also produce the
reporting tables and charts:

```bash
kedro run --tags altrisk,reporting
```

Budget for it: `reporting` (stage 8, 9 more nodes) renders a figure per company
per view and dominates the wall clock. On the five-company fixture slice
`altrisk` alone finished in 9.8 s while `altrisk,reporting` took 7m26s and wrote
901 files. Run `altrisk` on its own while you are still tuning parameters.

Expected console landmarks, in order:

```
INFO     Kedro project altr-model
INFO     Loading data from downloaded_scenarios (CSVDataset)...
INFO     Running node: check_input_parameters([params:shock_year;params:alignment_year]) -> None
INFO     Completed node: check_input_parameters
INFO     Completed 1 out of 46 tasks
...
INFO     Saving data to company_npv (CSVDataset)...
INFO     Completed 46 out of 46 tasks
INFO     Pipeline execution completed successfully in 123.4 sec.
```

The run has failed if you do not see `Pipeline execution completed
successfully` — see [Troubleshooting](docs/handover/troubleshooting.md) for the common causes.
Run duration scales with the number of companies and the forecast horizon; a
first full-universe run is measured in tens of minutes, not seconds.

### 7. Collect the outputs

| Path | What it holds |
| --- | --- |
| `data/07_model_output/company_npv.csv` | **Headline table** — baseline vs shock NPV per company |
| `data/07_model_output/company_technology_npv.csv` | Same comparison, split by technology |
| `data/07_model_output/asset_npv.csv` | Per-asset NPV with its revenue/cost/CapEx components |
| `data/07_model_output/yearly_npv_trajectories.csv` | Year-by-year discounted detail behind the NPVs |
| `data/07_model_output/asset_earnings.csv` | Per-asset, per-year earnings before discounting |
| `data/08_reporting/tables/compliance_ready/` | Export tables (`reporting` tag only) |
| `data/08_reporting/authority_pack/`, `earnings_inner/` | Charts (`reporting` tag only) |

Read them with the [user guide](docs/handover/user_guide.md).

### Smoke test without the real data

The repository ships a tiny committed input slice and a `fixture` environment
that points at it, with every output redirected to `data/fixture_run/`. It runs
the whole model in minutes and touches nothing in `data/07_model_output/`:

```bash
kedro run --env fixture --tags altrisk
```

Use it to check the install before the real data arrives, and after any change
to the code or configuration. The same run, wrapped in assertions on the output
columns and NPV values, is the project's regression test:

```bash
pip install pytest pytest-cov   # dev dependencies, not installed by `pip install -e .`
python -m pytest tests/integration -q
```

Both packages are needed: `pyproject.toml` puts `--cov` in the pytest `addopts`,
so `pytest` without `pytest-cov` exits on `unrecognized arguments: --cov-report`.
Expect `4 passed` in about 20 seconds.

### Explore the pipeline graph

```bash
kedro viz run
```

Opens a browser UI showing the stages, their nodes, and the datasets flowing
between them.
