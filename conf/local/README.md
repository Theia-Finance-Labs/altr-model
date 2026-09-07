# conf/local — personal overrides only

This directory is gitignored and is the DEFAULT run environment
(`settings.py: default_run_env: local`). Any `parameters*.yml` or
`catalog.yml` here replaces the same top-level keys from `conf/base/` on
every `kedro run`, silently.

Use it for credentials and machine-specific paths. Do not use it for
experiments; use `kedro run --params=...` or the `conf/study/` env that the
batch runner manages.

On 2026-09-06 four leftover sweep files (variant `iso_d1`, IMAGE 3.2 pair,
written 2026-09-01) were moved from here to
`workspace/conf_local_leftover_20260901_iso_d1/`. They had been overriding
base for five days.
