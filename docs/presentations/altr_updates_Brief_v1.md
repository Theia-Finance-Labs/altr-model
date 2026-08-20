# ALTR Model Updates — State, Fixes, and Open Decisions

**Brief v1 · 2026-07-08 · model version `7b7546a` · companion to `altr_improvements_Deck_v2` (pptx/pdf/html)**

---

## 1. Where we stood before the changes

The starting point was TRISK's net-profit block transplanted onto asset-level data. Net profit
was revenue minus a per-MWh cost, scaled by a market-data profit margin, discounted with a flat
rate and a Gordon-growth terminal value. Four structural problems:

1. **Earnings, not cash.** No CapEx, no replacement cycles, no decommissioning — the model
   valued an accounting construct that ignored the investment dynamics that dominate
   capital-intensive power economics.
2. **Unreliable margin data.** Net profit margins came from Refinitiv Eikon — gap-filled
   averages that don't survive contact with asset-level granularity.
3. **A valuation layer that couldn't tell brown from green.** One discount rate for everything;
   the only risk differentiation was a flat scenario premium (7% baseline / 8% shock) that
   punished green assets in the shock exactly as hard as coal. Terminal value assumed every
   asset — including a coal plant in a below-2°C world — grows at 2% forever.
4. **Scenario prices that don't clear markets.** AR6 electricity prices are LCOE-derived and
   technology-differentiated. Some technologies were perpetually loss-making *in the baseline*
   — before any shock was applied.

The first ALTR FCFF implementation inherited additional problems of its own: decommissioning
was recorded as **positive** scrap income (retirement paid the company), retiring assets were
double-charged (decommissioning *and* replacement CapEx in the same year), and new-build CapEx
double-counted capital costs already bundled inside IAM O&M series.

## 2. Where the data stood before the changes

- **Direction paradoxes everywhere.** Only ~**52%** of carbontech cases showed the expected
  negative valuation shock — a coin flip. Roughly **1,258** company-technology-geography cells
  had the wrong sign.
- **"Only one scenario worked."** Across the AR6 provider set, only one scenario produced
  expected shock directions for major geographies — the observation that appeared as "why this
  is bad" (slide 11 of the original deck).
- **Baseline negativity.** Perpetually negative baseline NPVs for some technologies made shock
  measurement meaningless for those assets.
- **Silent computation risks.** VRE baseline calculation depended on DataFrame ordering
  (wrong results on unsorted input); the merit-order price decline could be silently negated
  by the price floor.

## 3. What we did — fix by fix, tracked against the original deck

| Fix (commit) | What changed | Original deck slide it corrects | Effect on data |
|---|---|---|---|
| **NPV direction fixes** (`056d1f6`) | Decom sign → cost; tech discount spreads (brown +100bps / green −50bps, both scenarios 7%); stranding-aware 3-tier terminal value (TV=0 after 3 loss years; 10-yr annuity for declining fossil); terminal FCFF normalized over 3 years; terminal growth split 0% fossil / 2% green | Slide 8 claimed "no difference from TRISK except discount rates, 7%/8%, 2% growth for all" — every element of that sentence is now different | Decom sign alone: carbontech expected-negative 52% → **67%** — the single largest direction lever |
| **Retiring-asset CapEx exclusion** (`31596a0`) | Assets being decommissioned no longer also charged replacement CapEx in the same year | Slide 7's rollover/decommission story (which also had the decom sign backwards) | Removes double-charging that overstated retirement losses |
| **MCPR v2 two-mode pricing** (`49efb56`) | `carbon_explicit` (gas-anchored clearing price + full_ef carbon) and `merit_order_decline` (price falls with VRE share, IMF elasticity); auto-detection by carbon-price coverage | **Absent from the original deck entirely** — the largest omitted update | Addresses the baseline-negativity problem at its source (prices) |
| **VRE baseline + pairing guard** (`5ecdca6`) | Order-independent min-year VRE lookup; runtime warning when carbon_explicit runs without full_ef | Absent | Kills a silent wrong-results path; guards the double-counting decision tree |
| **Merit decline to clearing price** (`7b7546a`) | Decline applied before value factors (floor can't negate it); all techs decline equally; VRE delta no longer mixes baseline/target rows | Absent | Merit-order mechanism now does what the methodology says |

**Where the data stands now (post-fix April batch, 5 providers × 3 configs):** all runs pass
end-to-end (**5/5** providers: COFFEE, GCAM, IMAGE, MESSAGEix-GLOBIOM, WITCH); ~**78.5%** of
carbontech cases show the expected negative shock; ~**85.6%** of greentech cases the expected
positive one. Residual wrong-direction cases remain; gas is the known borderline. These figures
predate a canonical re-analysis — see decision OP1.

**Practice changes that came with the fixes:**

- **Config is the source of truth.** Every stale number in the original deck traced to reading
  Python function signatures instead of `conf/base/*.yml`. All documents now cite config and a
  model version stamp.
- **Overclaims are banned.** "Restores direction in every scenario" is replaced everywhere by
  "large majority, residual cases remain, gas is the open item."
- **MCPR is two-track.** Internal headline config `mcpr_v2_merit`; externally framed as an
  exploratory adjustment pending a methods paper (per review consensus).
- **Honest proxies.** Age-based retirement is described as a proxy for intensity/priority —
  never as economic optimization.

## 4. Decision points to continue development

Already decided (2026-07-06, recorded in the plan of record): tech-level risk premium ·
provider-conditional new-build CapEx · decom as net cost · two-track MCPR · analyze existing
results before re-running · fix deck (done — v2 delivered) · keep age proxy with caveat.

**Open now — your call on each:**

| # | Decision | Options | My recommendation |
|---|---|---|---|
| **OP1** | Acceptance threshold for the direction matrix (the "does it work" gate) | e.g. ≥90% expected-sign per provider×config, gas exempted / ≥85% / no hard gate, trend-only | ≥90% with gas documented as exception; below it, the config fails the gate |
| **OP2** | Canonical paradox bookkeeping — the artifacts disagree (1,258 pre-fix vs 772/775 post-decom vs 1,412 in one commit message vs 803 "best") | Pick one definition (which universe of cells, which configs) and rebuild the count once | Define cell = company×tech×geo per provider×config at HEAD; rebuild from `comparison_results/`; retire all older counts |
| **OP3** | Is gas-positive a paradox or an accepted outcome? | (a) paradox — must trend negative; (b) accepted merit-order winner in some pathways; (c) geography-dependent expectation | (c) — define expected gas direction per scenario family, not globally |
| **OP4** | Sequencing: direction matrix vs CapEx audit | Matrix first (evidence base), audit second / parallel | Matrix first — it's the regression gate every later change needs |
| **OP5** | Tech-specific decom ratios — when? | Now / after matrix / only if matrix flags decom-sensitive cells | After matrix; let the data say whether the flat 50% distorts |
| **OP6** | MCPR methods paper — commission now or wait for AR7/NGFS (expected H2 2026)? | Now (owns the narrative) / wait (risk: scenarios may moot it) / short position note now, full paper after AR7 | Position note now, full paper decision after AR7/NGFS lands |
| **OP7** | Merton PD / credit-risk layer — in scope for this development cycle? | Yes (restores TRISK parity) / defer until valuation layer is validated | Defer until the matrix gate passes twice in a row |
| **OP8** | Deck v2 sign-off — approve for presentation after your read-through? | Approve as-is / revise per feedback / regenerate figures after OP1 matrix | Hold external use until OP1 numbers land; internal use now |

**Immediate next step once you answer OP1–OP4:** build the canonical direction-expectation
matrix from `workspace/comparison_results/` (zero compute — data is on disk) and re-stamp the
results slide with fresh numbers.

---

*Sources: adversarial deck review (11 claims verified against code/config), commits
`056d1f6`–`7b7546a`, April batch logs, plan of record
`docs/superpowers/plans/2026-07-06-altr-reconciliation-and-effectiveness-plan.md`.*
