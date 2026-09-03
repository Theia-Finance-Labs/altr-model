# Ownership attribution in ALTR — brief for presentation materials

Source material for decks and methodology slides. Drafted 2026-09-04 from the
ALTR consolidation work; PACTA citations verified against the primary
methodology documents.

## The one-slide version

A power plant can be claimed by more than one company at once - the operating
subsidiary directly, the parent through equity look-through, JV partners each
through their share. Any attribution rule must answer two different questions,
and no single rule answers both:

1. **Economic exposure** - what share of this asset's cash flows does *this
   company* have a claim on?
2. **Physical accounting** - do the attributed shares, summed over all
   companies, add up to the real fleet?

ALTR makes this a parameter (`ownership_aggregation`) instead of pretending one
answer is correct: `sum` totals every stake a company holds (economic
exposure); `tier_filter` keeps one relationship type so each megawatt is
counted once (physical accounting). Measured on the current data, `sum`
attributes 2.68x the fleet's ownership-weighted capacity across 7,752
claimants; `tier_filter` covers the same 21,821 assets once through 4,899
operating owners.

## What PACTA does - and why it supports the parameter design

- **PACTA's consolidation is the `sum` logic, formalized.** The Equity
  Ownership approach attributes production up the ownership tree *weighted by
  equity stake, explicitly including minority stakes*, level by level to the
  ultimate parent. "If Company A owns x% of Asset 1, it gets attributed x% of
  its production." (PACTA for Banks §1.7.2; PACTA for Investors §1.2.3.)
- **Double-counting across the tree is accepted by design.** Shares sum to
  100% only at the direct-asset level; the same megawatt then legitimately
  appears in the subsidiary and, stake-weighted, in every parent above it.
  PACTA never de-duplicates the company universe - it avoids double-counting
  only at the financial layer, where each security maps to exactly one company
  node. ALTR has no such layer, so the caveat lands on us: **under `sum`,
  every cross-company aggregate is claim-weighted, not physical, and must be
  labelled so.**
- **Even PACTA has two rules.** Credit Ownership (for debt) attributes each
  instrument to exactly one node, unweighted - the rule follows the analytical
  purpose, inside one methodology. That is the strongest argument that a
  parameter, not a single "correct" mode, is the right design.
- **TRISK's public documentation is silent on ownership** - it inherits
  whatever consolidation its input data carries.

## The NPV consequence, in one paragraph

Ownership enters the model as a linear scalar on capacity, and every major
cost line is linear in it, while the stranding classification is sign-based -
so a company's `npv_change` ratio is invariant to the *size* of its stakes and
moves only through *composition* (which assets and which companies enter).
Absolute NPV levels scale with the full attribution factor. Practical rule for
every chart: risk signals may be compared across modes with care; absolute
levels may never be, and every published number names the mode it used.

## Sources

- PACTA for Banks Methodology Document (2DII, 2020), §1.7.2, §1.11 -
  transitionmonitor.com/wp-content/uploads/2020/09/PACTA-for-Banks-Methodology-Document.pdf
- PACTA for Investors Methodology Document v1.0 (2023), §1.2.3, Accounting
  Principals (p.15) -
  transitionmonitor.com/wp-content/uploads/2023/02/PACTA-for-Investors-Methodology-document_Final.1.pdf
- Share Ownership Weighting, pacta.data.preparation (RMI) -
  rmi-pacta.github.io/pacta.data.preparation/articles/share_ownership_methodology.html
- TRISK working paper (SSRN 4254114); trisk.analysis inputs vignette
  (theia-finance-labs.github.io).

*Companion detail: the "Ownership attribution and aggregation" section of the
ALTR methodology notes (altr-model repo, docs/handover/methodology_notes.md),
which carries the full mode table, allocation-machinery interaction, and
limitations.*
