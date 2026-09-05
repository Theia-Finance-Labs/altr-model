# Benchmarks (internal)

Full-universe measurement harness used for the 2026-09 decision suite
(`docs/superpowers/plans/measurement-batch-results.md`). Internal only: not on
the export allowlist, and it needs the deliverables data staged under
`data/05_model_input/`.

- `bench_run.py <label> '<json extra params>'` — one `kedro run --env full --tags altrisk`
  through the `KedroSession` API (so nested `dcf` overrides work; respecify the
  whole block), outputs cleared first, disk guard at 2.5 GB.
- `bench_metrics.py extract <label>` — snapshot company/technology NPVs, the Q2
  coverage table and the NaN-window census under `data/09_benchmarks/<label>/`.
- `bench_metrics.py compare <label> <ref>` — headline, levels, sign flips, top
  technology moves (`ref` may be `golden`).
- `rerun_after_reexport.sh` — the arms to re-measure when a corrected extract
  lands (fuel price ex-carbon; pathway unit label). ~1 hour.
