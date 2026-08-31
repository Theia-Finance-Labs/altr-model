# Quickstart

From a clean machine to a completed run. Every command below is
copy-pasteable; run them from the repository root unless stated otherwise.

!!! warning "Python 3.10 only"
    The dependency set pins Python `>=3.10,<3.11`. Python 3.11+ will fail at
    install time, and a 3.9 environment will fail at import time. Check with
    `python3.10 --version` before you start.

## 1. Get the code

```bash
git clone <repository-url> altr-model
cd altr-model
```

## 2. Create a virtual environment and install

```bash
python3.10 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -e .
```

Verify the install — this must print a `0.19.x` version and exit cleanly:

```bash
python -c "import crispy_kedro, kedro; print(kedro.__version__)"
```

## 3. Place the input data

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

## 4. Convert the deliverables into model inputs

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

## 5. Choose the run configuration

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
IAM provider. See the [scenario catalog](scenario_catalog.md) for candidate
pairs. The defaults shipped in the file are a valid pair — you can run first and
tune afterwards.

## 6. Run the model

```bash
kedro run --tags altrisk
```

That runs stages 1–7 (46 nodes) and produces the numbers. To also produce the
reporting tables and charts:

```bash
kedro run --tags altrisk,reporting
```

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
successfully` — see [Troubleshooting](troubleshooting.md) for the common causes.
Run duration scales with the number of companies and the forecast horizon; a
first full-universe run is measured in tens of minutes, not seconds.

## 7. Collect the outputs

| Path | What it holds |
| --- | --- |
| `data/07_model_output/company_npv.csv` | **Headline table** — baseline vs shock NPV per company |
| `data/07_model_output/company_technology_npv.csv` | Same comparison, split by technology |
| `data/07_model_output/asset_npv.csv` | Per-asset NPV with its revenue/cost/CapEx components |
| `data/07_model_output/yearly_npv_trajectories.csv` | Year-by-year discounted detail behind the NPVs |
| `data/07_model_output/asset_earnings.csv` | Per-asset, per-year earnings before discounting |
| `data/08_reporting/tables/compliance_ready/` | Export tables (`reporting` tag only) |
| `data/08_reporting/authority_pack/`, `earnings_inner/` | Charts (`reporting` tag only) |

Read them with the [user guide](user_guide.md).

## Smoke test without the real data

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
pip install pytest              # dev dependency, not installed by `pip install -e .`
python -m pytest tests/integration -q
```

## Explore the pipeline graph

```bash
kedro viz run
```

Opens a browser UI showing the stages, their nodes, and the datasets flowing
between them.
