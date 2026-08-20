# ALTR Reconciliation & Effectiveness Plan — 2026-07-06

Source: adversarial review of `ALTR improvements strategy.pptx` (2026-06-09, 13 slides)
against model HEAD `7b7546a` (2026-04-14, branch `feat/altr-npv-fixes`).

Verdict: every confirmed divergence is **deck-lags-model**. Root cause: deck numbers were
read from Python function signatures (8% shock, flat 2% growth, 0.5 passthrough) instead of
`conf/base/*.yml`, which is what runs.

## Findings summary

| # | Slide | Deck claim | Model actual | Verdict | Sev |
|---|-------|-----------|--------------|---------|-----|
| C1 | 2 | passthrough default 0 | 0 in config | MATCH | — |
| C2 | 6 | EBITDA = rev − fuel − FOM − carbon | exact | MATCH | — |
| C3 | 2/6 | one carbon formula, ×capacity | two modes (`full_ef` default / `differential_ef`) + `mcpr_mode`; ×volume Q | DIVERGES | MED |
| C4 | 7 | buildout CapEx operative | `include_growth_capex: False` (IAM O&M bundles capital) | PARTIAL | MED |
| C5 | 7 | decom = **positive** cash (scrap); rollover at end-of-life | decom = **cost** (outflow, abs(capex/2)); rollover = flat 2%/yr maintenance on non-retiring real assets | DIVERGES | HIGH |
| C6 | 8 | 7% baseline / **8% shock** | 7% / 7% in config; 8% is dead signature default | STALE | MED |
| C7 | 8 | terminal growth 2% all | brown 0% / green 2%; 2% fallback unreached | DIVERGES | MED |
| C8 | 8 | "no difference from TRISK except discount rates" | + tech spreads (+100/−50bps), stranding-aware 3-tier TV, 3-yr terminal normalization, tech growth split | DIVERGES | HIGH |
| C9 | 9 | "no forced stranding" | `stranding_aware_tv: True` forces TV=0 for stranded | PARTIAL (inline) | MED |
| C10 | 5 | paper ~7% + hedge | unverified (low stakes, already hedged) | UNVERIFIED | LOW |
| C11 | 11 | "only one scenario had expected directions" | pre-MCPR-v2 state; post-fix ~78.5%/85.6% expected-direction, 5/5 providers PASS | STALE | HIGH |
| OM | — | (absent) | entire MCPR v2 category: `49efb56`, `5ecdca6`, `7b7546a` | OMITTED | HIGH |

Code-hygiene side findings (inert but confusing): signature defaults diverge from config —
`market_passthrough=0.5` (nodes.py:1383), `discount_rate_shock=0.08` (valuation nodes.py:16),
`carbon_cost_method='differential_ef'` (nodes.py:1388).

## Decision points (Jakub) — DECIDED 2026-07-06

Decisions: **D1 = B** (technology-level spreads, keep current). **D2 = C** (provider-conditional —
audit which IAM O&M series bundle capital costs, enable growth CapEx per provider; keep False
until audit lands). **D3 = B** (net cost, keep current; deck wording must flip). **D5 = (a)**
(analyze existing `comparison_results/` first). D4/D6 default to recommendations
(`mcpr_v2_merit` headline; fix deck).

- **D1 — Risk-premium channel.** A: scenario-level (7/8%). B: technology-level spreads
  (current: brown +100bps, green −50bps, both scenarios 7%). C: both.
  *Recommendation: B; run A and C as sensitivity rows.*
- **D2 — Buildout growth CapEx.** A: on. B: off (current; IAM O&M double-count).
  C: provider-conditional (audit which IAM O&M series include capital).
  *Recommendation: B now; C as follow-up if new-build economics needed.*
- **D3 — Decommissioning sign/magnitude.** A: positive scrap (deck). B: net cost, 50% CapEx/MW
  (current). C: B with tech-specific ratios.
  *Recommendation: B; C later. Deck text must be corrected regardless.*
- **D4 — Headline config.** Bless `mcpr_mode: auto`; choose headline config among
  `mcpr_v2_merit` / `mcpr_v2_carbon` / `iso_d1` for reported results.
  *Recommendation: `mcpr_v2_merit` (reflects all three April fixes).*
- **D5 — Effectiveness criterion + scope.** Define acceptance: e.g. ≥90% expected-sign cells
  per provider×config; paradox count < 803 (vault benchmark); gas = documented exception.
  Scope: (a) analyze existing `workspace/comparison_results/` (zero compute) →
  (b) re-run 5-provider batch only if D1–D3 change defaults → (c) 11-provider sweep for paper.
  *Recommendation: (a) now; (b) conditional; (c) later.*
- **D6 — Reconciliation direction.** Fix deck to match model (all findings), change model only
  where D1–D3 overridden. *Recommendation: fix deck.*

## Addendum — presentation notes (2026-07-06)

Notes from the recent ALTR deep-dive presentation, cross-checked against HEAD:

- **OP9 RESOLVED (2026-07-25) — supersedes D4's headline choice below:** canonical
  single-vintage rebuild (30/30 runs, 5 providers × {vanilla, mcpr_v2_carbon, mcpr_v2_merit,
  mcpr_v2_carbon_full, mcpr_v2_merit_full, adjusted}) shows merit_order_decline is NOT rescued
  by the valuation suite: 43.9% carbon direction vs 42.9% isolated (MCPR v1's interaction was
  +19.5pp); MESSAGEix 19.5%; Middle East 1.0%. Per pre-set rule: merit → paper track;
  carbon_explicit is the only production v2 mode. Headline = **both, labeled**:
  `mcpr_v2_carbon_full` as production config (72.6% direction, green 90.8%, baselines intact,
  only family improving Middle East), `adjusted` as direction-optimized sensitivity (86.5%,
  −77.7% median shock, green baseline cost 79.4%). Follow-up: `mcpr_mode: auto` must fall
  back to carbon_explicit/no-decline, never merit. Note: the 2026-07-24 cross-run anomalies
  were two concurrent batches racing on conf/local; single-vintage rerun is clean.
  Evidence: workspace/batch_run_canonical_rebuild.log + comparison_results (2026-07-25).
- **D4 RESOLVED — two-track (2026-07-06, superseded on headline by OP9 above):** internal headline = `mcpr_v2_merit` for
  direction-testing; anything external/published frames MCPR as exploratory sensitivity
  pending the paper + engineering review. Reassess when AR7/NGFS prices land (H2 2026).
  (Background: meeting consensus = "explore as paper, not implement blindly"; MCPR v2 is
  implemented in 49efb56/5ecdca6/7b7546a and batch-validated 5/5.)
- **NEW D7 — age-as-proxy:** keep age-based retirement sequencing; improve proxy with
  Climate Trace / AR6 efficiency-intensity data (backlog task); deck slide 9 must caveat
  "age proxies carbon intensity and retirement priority — no economic-rationale claim."
- **AR7/NGFS trigger:** new scenarios (expected H2 2026 — i.e. imminent) may provide
  market-clearing prices directly, superseding MCPR. Reassess D4 when published.
- **Corroborations:** scrap-sign fix already in code (C5 → deck-only fix confirmed);
  brown 0% / green 2% terminal growth (C7); Bolton spreads in both scenarios (D1);
  "removed CapEx for some runs" = include_growth_capex False (D2); carbon double-counting
  "decision tree" already exists as `mcpr_mode: auto` + carbon_explicit warning (deck's
  new MCPR slide should state this).
- Naming: ALTR is an intentional rebrand (IP narrative) away from TRISK — deck slide 0/2
  labels can state this as fact.

## Phases

### Phase 0 — Decisions
Jakub answers D1–D6. Blocks Phase 2 and 3 content; Phase 1(a) can start immediately.

### Phase 1 — Effectiveness re-test ("test their effectiveness")
1. Build direction-expectation matrix from existing `workspace/comparison_results/`
   (5 providers × {iso_d1, mcpr_v2_carbon, mcpr_v2_merit}): % expected-sign by
   technology × geography × provider; paradox counts vs 1258 (pre) / 1412 (056d1f6) / 803 (vault).
2. Gas borderline analysis (known open item).
3. If D1–D3 flip any default: re-run batch at HEAD (~31 min/config), regenerate matrix.
4. Gate: matrix reviewed; acceptance criterion from D5 evaluated → PASS/FAIL per config.

### Phase 2 — Model changes (only per decisions)
- Align dead signature defaults with config (passthrough 0, shock 0.07, carbon method) — no
  behavior change, removes the divergence root cause.
- D2=C task: audit IAM O&M cost definitions per provider (REMIND/WITCH/POLES documented as
  bundling annualized capital; verify COFFEE, GCAM, IMAGE, MESSAGEix). Deliverable: per-provider
  table → `include_growth_capex` becomes a per-provider override in batch configs. Keep global
  default False until audit lands.
- D1/D3 confirmed as current defaults — no changes.
- Regression: rerun one provider (WITCH) before/after; NPV outputs must be identical when
  only signature defaults changed.

### Phase 3 — Deck corrections (slide-by-slide)
- S2/S6: carbon cost = ×volume Q; add two-mode (`full_ef` default / `differential_ef`) + `mcpr_mode auto`.
- S7: decom is a COST (abs(capex/2) outflow), not scrap revenue; rollover = 2%/yr maintenance
  (EPRI/Lazard), retiring assets excluded (31596a0); buildout CapEx off by default + why.
- S8: 7%/7% + tech spreads +100/−50bps; growth brown 0% / green 2%; replace "no difference
  except discount rates" with the four valuation deltas (spreads, stranding TV, normalization,
  growth split).
- S9: qualify "no forced stranding" (valuation-level stranding TV active); add age-as-proxy
  caveat per D7 (age proxies intensity/retirement priority, not economic rationale).
- S11: replace "only one scenario" with current direction stats + residual-paradox honesty.
- NEW slide(s): MCPR v2 price adjustment (two modes, auto-detection, merit-order fix, VRE
  baseline fix) — the largest omitted update.
- S5: keep the hedged 7% paper claim (C10) unless verification says otherwise.

### Phase 4 — Verification gate
- Fresh direction matrix attached to deck results slide.
- `/review` pass on deck text (anti-AI guard, overclaim check — no "every scenario" language).
- Checklist: each finding C3–C11 + OM has a corresponding deck edit or explicit waiver.

## Verification status caveats
- C3/C4 verdicts from subagent verification, spot-checked inline (config lines confirmed).
- C6/C7/C8 independently confirmed inline from primary sources.
- C5/C11 verified inline (code read + batch log).
- C9 partially verified; C10 unverified — both low risk. Adversarial refutation pass did not
  run (spend limit); severities are reviewer-assigned, not debate-hardened.
