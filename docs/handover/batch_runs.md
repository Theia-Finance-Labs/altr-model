# Batch runs and the app

A single configuration is `conf/base/` plus `uv run kedro run` - the
[quickstart](quickstart.md) covers it. This page is for comparing
configurations: running the model several times with different parameters
without editing `conf/base/` between runs, and without one run overwriting
another's outputs. Three tools do it, in ascending order of polish - a
notebook, a CLI script and a Streamlit app - and all three share the same
run-configurations format.

!!! warning "Internal tooling - most of this page is not in the delivered package"
    Of the files documented here, only the `Dockerfile` and
    `notebooks/walkthrough.ipynb` ship in the delivered package. The Streamlit
    app, `run_kedro_batch.py`, `generate_results.ipynb`, the example
    configuration files and `docker-compose.yml` live in the internal
    repository only. If you received this site as part of the package, the
    supported path is the [quickstart](quickstart.md); everything below
    describes tooling the maintainers run for you.

## The run-configurations format

All three tools consume a mapping of `{run_name: {parameter overrides}}`. Each
entry becomes one `kedro run` with those parameters overridden on top of
`conf/base/`, and each run's outputs are copied into their own folder so runs
never overwrite each other.

`notebooks/example_run_configurations.yml` is the reference file: six named
configurations pairing the same baseline/target scenario while varying
granularity, retirement, staggering and continued O&M. Company selection is
deliberately not set per run there - a single selection is applied across the
whole batch (see below).

## The notebook: `generate_results.ipynb`

The interactive form. Two variables control the outputs:

* `runs_configuration` - the `{run_name: {param_overrides}}` dict.
* `companies_selection` - the list of companies entering the run, applied to
  every entry.

Each entry runs, and the headline tables are copied out of
`data/07_model_output/` into a per-run folder. Useful when you want to inspect
intermediate state between runs; for anything unattended, use the script.

## The CLI: `run_kedro_batch.py`

The script form of the same loop - headless batch runs, and the engine behind
the app below:

```bash
uv run python notebooks/run_kedro_batch.py \
    --run-configurations notebooks/example_run_configurations.yml \
    --company-ids notebooks/example_company_selection.csv \
    --output-dir workspace/results_batch \
    --tags altrisk
```

* `--run-configurations` (required) - a YAML or JSON file in the format above.
* `--company-ids` - a CSV (with a `company_id` column), plain text (one id per
  line), or a YAML/JSON list, applied to **every** run in the file. Omit it to
  respect each run's own `company_ids` override (default: all companies).
* `--output-dir` - where the per-run folders land (default
  `workspace/results_batch/`).
* `--tags` - comma-separated Kedro tags (default `altrisk`; use
  `altrisk,reporting` to also copy the figure packs per run).

Each run's folder gets the headline output tables with a `run_id` column
stamped on every row, plus a `run_params.csv` recording exactly which
parameters produced them - the batch-tool version of the
"[record the configuration next to the result](user_guide.md#5-sanity-checks-before-you-trust-a-run)"
rule. A failed run writes `<run_name>_error.txt` and the batch continues; at
the end, `run_manifest.csv` in the output root summarises which runs succeeded,
where their outputs are and how long each took.

`notebooks/example_company_selection.csv` is a 30-company sample chosen to
cover all four alignment × carbon-intensity quadrants (aligned/misaligned ×
high/low carbon). The identifiers in it are licensed data, which is why the
delivered configuration ships with an empty `company_ids` list instead.

!!! note "The batch tools are stricter about scenario pairs than the pipeline"
    The pipeline itself does not reject a baseline/target pair drawn from two
    different IAM providers - it silently intersects their geographies and
    technologies and logs a warning, which quietly degrades results. The batch
    tools check the pair against `--scenarios-csv` up front and **skip** a
    cross-provider run unless `--allow-cross-provider-scenarios` is passed.
    Pick pairs from one provider block of the
    [scenario catalog](scenario_catalog.md).

## The app: Streamlit batch runner

A three-step wizard over the same engine: pick a portfolio (upload a company
selection or use the bundled demo), pick parameters (recommended defaults or a
custom selection), run, and download every output as one zip. It expects the
converted model inputs to already be in `data/05_model_input/` (quickstart
steps 3-4).

Run it natively:

```bash
uv run --group streamlit streamlit run notebooks/streamlit_app.py
```

Or in Docker, which needs nothing installed but Docker itself:

```bash
docker compose up --build
```

Once the logs settle, open <http://localhost:8501>.

The image bakes in the code and dependencies but deliberately not the data:
`docker-compose.yml` mounts the local `data/` and `workspace/` folders at
runtime, so the app reads and writes whatever is on disk, and results survive
the container.
