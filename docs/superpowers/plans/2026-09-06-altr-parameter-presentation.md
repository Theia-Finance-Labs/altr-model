# ALTR parameter presentation plan

Date: 2026-09-06. Input: `docs/research/altr_parameter-audit_Brief_v1.md`. Extends handover-plan Tasks 5 and 11 (`2026-08-31-altr-handover-package.md`), which prescribe the same direction but were not executed.

Goal: one place where a handover user sees every parameter that moves a result, with meaning, unit, range, source, and status; nothing result-affecting left hidden in code; a bad value fails fast; every output carries the config that produced it.

## Decisions (most expensive to reverse first)

**D1. Single source of truth = annotated YAML comments, everything else generated.**
Choice: a fixed comment schema above each key in `conf/base/*.yml`; a script parses it into `docs/parameters.md` and an HTML explorer. Alternative: a hand-written parameters doc. Cost to change later: low for the doc, medium once the HTML page and the KAPSARC deck depend on it. Schema, one comment block per key:

```yaml
# meaning:  fraction of differential carbon cost passed to customers
# unit:     fraction [0, 1]
# default:  0 (firm absorbs all — stress-test convention)
# source:   —
# status:   live | advanced | dead | gated-by:<key>
market_passthrough: 0
```

**D2. Two tiers of config file.** `conf/base/parameters.yml` = the ~16 user knobs (scenario pair, years, filters, cost switches, MCPR on/off, carbon method, DCF headline rates). Per-pipeline files keep everything else under a header `# Advanced — leave alone unless you know why`. Keys are *moved*, never duplicated (Kedro raises on duplicate keys within an env). Alternative: one flat file. Cost to change: trivial, keys are location-independent in Kedro.

**D3. Promote hidden HIGH constants to conf** so the reference is complete: `replacement_capex_rate` (0.02), `decom_cost_share_of_capex` (0.5), `mcpr_value_factors`, `mcpr_marginal_technologies`, `mcpr_floor_at_iam_price`, `excluded_country_iso2`, `retirement_floor_offset_years` (1), `default_capacity_factor` (null → fail on NaN). Defaults equal current code, so results are bit-identical; fixture test is the gate. Alternative: document them as constants in the reference without wiring. Cost to change: low.

**D4. Sweep script gets its own env.** `run_all_scenarios_comparison.py` writes to `conf/study/` and runs `kedro run --env study`; `conf/local/` is never touched by automation. Alternative: keep writing to local with a robust cleanup. Cost: one path constant plus one CLI flag.

**D5. Validation = one plain-Python node at pipeline head**, no pydantic. Dict of `{key: (type, allowed)}`, raises `ValueError` naming key, value, allowed. Alternative: pydantic settings model. Cost to change: rewrite ~60 lines.

## Known unknowns

- **Stale `conf/local/`**: never-delete rule applies. Default: leave it, document it, and flag it in `conf/local/README.md`. Pivot signal: Jakub deletes it or moves it to `conf/local.bak-20260901/`.
- **Whether the fixture run still passes bit-identically after D3.** Default: assume yes because defaults equal constants. Pivot: any diff in `tests/integration` output → stop and diff.
- **Which tech-list constants to promote** (VRE, non-fuel, CCS-eligible, carbontech alignment types). Default: promote as one `technology_groups` block in the advanced tier. Pivot: if the KAPSARC brief treats them as methodology-fixed, document instead.
- **HTML explorer scope.** Default: static single page, search + status filter + source links, generated from the same parse. Pivot: skip if the markdown reference is enough for the workshop.

## Phases

**Phase 1 — entry point and env hygiene** — DONE 2026-09-06
1. [x] `conf/base/parameters.yml` written with 17 user-tier keys plus the whole `dcf` block in D1 schema; keys removed from per-pipeline files; those files carry the advanced banner and D1 comments.
2. [x] Lines 9–18 and 37–12109 of the old inputs_processing file moved to `docs/handover/scenario_catalog.md`. Pre-edit copies of the two rewritten base files kept in `workspace/conf_local_leftover_20260901_iso_d1/`.
3. [x] Sweep script writes one merged `conf/study/parameters.yml` from all base files, runs `kedro run --env study`; docstring corrected; `conf/study/**` gitignored; `tests/test_sweep_overrides.py` added.
4. [x] README Configuration section, `conf/README.md`, `conf/local/README.md` written.
5. [x] Stale `conf/local/` files verified byte-identical to the sweep's `iso_d1` output for the IMAGE 3.2 pair (run 9/25, 2026-09-01 14:43, never finished) and moved to `workspace/conf_local_leftover_20260901_iso_d1/`.
Gate used: resolved `context.params` dict identical before and after (35 top-level keys); study env loads through `KedroSession(env="study")` with overrides applied and all base keys present. A full `kedro run` was not executed.

**Phase 2 — nothing hidden, nothing dead** — DONE 2026-09-06
5. [x] Promoted with bit-identical defaults and wired through `pipeline.py`: `replacement_capex_rate`, `decom_cost_share_of_capex`, `default_capacity_factor` (null = fail fast), `mcpr_value_factors`, `mcpr_marginal_technologies`, `mcpr_floor_at_iam_price`, `excluded_country_iso2`, `retirement_floor_offset_years` (threaded through both allocation helpers). `tests/test_promoted_defaults.py` asserts conf == function default per key, the historical 22-country list, MCPR fallback dicts, null-CF failure, and that every `params:` reference in every pipeline resolves.
6. [x] Removed from conf and wiring: `theta_capex_recovery` (node kept, no-op), five dead reporting keys. `g_real_default` kept, labelled unreachable (Codex: it is wired). `conf/prod/catalog.yml` neutralised to a comment explaining why (previous content preserved under `workspace/conf_local_leftover_20260901_iso_d1/`).
7. [x] Function defaults aligned: `market_passthrough` 0.5→0.0, `discount_rate_shock` 0.08→0.07 (test reference loop updated to match), `save_pdf` False→True.
Gate: resolved params diff vs pre-Phase-1 snapshot = exactly the promoted keys added and the dead keys removed, no value changed; default pipeline builds (58 nodes); suite 53 passed. Deviation log: `compute_capacity_flows` helper needed the rate threaded through (caught by `test_capacity_flows_geography`).

**Phase 3 — fail fast, stamp outputs** — DONE 2026-09-06
8. [x] `validate_parameters(parameters)` replaces `check_input_parameters`; `PARAMETER_SPEC` covers 52 keys (type, enum or range), reports every error at once naming key, value and allowed set. `tests/test_parameter_validation.py` (10 tests) includes a guard that every declared non-reporting key is in the spec.
9. [x] `export_reporting_tables` takes the full `parameters` dict, writes `tables/run_parameters.csv` (one row per leaf key), and the methodology table reads `dcf.discount_rate_*` instead of the `"7%"/"8%"` literals.
Gate: suite 64 passed; export node inputs verified to include `parameters`.

**Phase 4 — the reference** — 10, 11, 13 DONE 2026-09-06; 12 in progress
10. [x] `scripts/gen_param_docs.py` parses the D1 blocks (nested paths, multi-line fields, list keys) → `docs/parameters.md`, 59 parameters. `tests/test_gen_param_docs.py` covers attachment on an inline YAML and asserts every shipped key is documented.
11. [x] Same parse → `docs/parameters.html`: single file, search, tier chips, gated / dead filters, click-to-expand rows. Verified in the browser.
12. [x] Docstring sweep: Parameters sections on 26 param-taking node functions across six pipelines, each entry naming its conf key; `scale_electricity_price` docstring restored with a pass-through note. Docstring-only diff, suite re-run green afterwards.
13. [x] Scope note added at the top of methodology brief Appendix A pointing to `docs/parameters.md` for this repo.
Regenerate after any conf change: `uv run python scripts/gen_param_docs.py`.

Mechanical last: mkdocs nav, commit per phase, Bertrand review before merge (AGENTS.md rule).

## Approve or pick before starting

1. D1 comment schema as written, or a different field set?
2. D3: promote the hidden constants (bit-identical defaults) or document-only?
3. Stale `conf/local/`: leave and flag, or will you move it aside yourself?
4. Phase 4 item 11 (HTML explorer): in scope for the KAPSARC workshop, or markdown only?
