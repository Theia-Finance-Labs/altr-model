# Configuration

## Where to edit

- `base/parameters.yml` — user-facing parameters. Edit this for a normal run. Every key carries a comment block (meaning / unit / default / source / status); `docs/parameters.md` and the interactive selector `docs/parameters.html` are generated from it (`scripts/gen_param_docs.py`), and the README's parameter overview lists all 59 keys in the selector's order.
- `base/parameters_<pipeline>.yml` — advanced knobs per pipeline. Leave alone unless you know why.
- `base/catalog.yml` — dataset locations. `ar6_carbon_prices` points at a repo-root CSV that must be present.

## How environments merge

`src/crispy_kedro/settings.py` sets `base_env: base` and `default_run_env: local`. Kedro 0.19's OmegaConfigLoader deep-merges all `parameters*.yml` of one env into one dict (filenames do not matter; a leaf key present in two files of the same env raises an error, disjoint leaves of one block may be split across files), then merges the run env over base **destructively per top-level key** (a nested block is replaced whole).

- One-off override: `kedro run --params="shock_year=2030"`.
- Study sweeps: `notebooks/run_all_scenarios_comparison.py` writes to `study/` and runs `kedro run --env study`.
- `local/` is for personal, uncommitted settings and credentials only. It is gitignored. Anything you put there silently overrides base on every run; see `local/README.md`.
- `prod/catalog.yml` is not a working environment: its dataset names do not match the pipeline inputs and `assets_forecasts` collides with a node output.

## Instructions

1. Set `baseline_scenario` / `target_scenario` in `base/parameters.yml` to a pair present in `downloaded_scenarios` (see `docs/handover/scenario_catalog.md` for pairs already run).
2. Optionally set `company_ids`, `shock_year`, `alignment_year`.
3. `kedro run --tags=altrisk` (add `,reporting` for plots).
