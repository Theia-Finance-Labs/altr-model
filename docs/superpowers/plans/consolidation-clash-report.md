# Consolidation clash report

**Branch** `feat/portable-handover` · **Date** 2026-09-01 · **Reviewer** Bertrand

Every point where this repository's behaviour or keys differed from the handover
lineage (`feat/handover-package` @ `78c1f14` in `crispy-kedro-handover`), and
what was done about each.

## The rule this applies

From the owner ruling of 2026-09-01
(`implementation-notes-handover.md`, "Owner decisions 2026-09-01" + Amendment;
`migration-disposition-ledger.md`, Addendum 2):

* **Your structure is the hard constraint.** Module layout, naming, parameter
  conventions and file organisation are yours. Nothing was moved, split or
  renamed; no module layout was imported from the handover branch; every new
  key lives in one of your six per-pipeline parameter files.
* **Jakub's behaviour wins.** Where the two lineages compute different numbers,
  this branch computes the handover branch's.
* **Clashes surface rather than resolve silently.** That is this document.

Nothing below was decided by preference. Where a clash is recorded but *not*
changed, the reason is stated.

## How to read this

Entries are grouped by the ledger question that governs them. Each gives your
form, the handover form, what was done, and **what to look at** — the specific
thing worth your judgement, not a restatement.

Entries marked **DECIDE** are ones where reasonable people could differ and your
call would change the code. Entries marked **FYI** are mechanical consequences
recorded for completeness.

---

## Q1 — Retirement and replacement masks

All in `src/altr_model/pipelines/calculate_asset_earnings/nodes.py`,
`compute_capacity_flows`. Commit `cf3ad91`.

### Q1-1 · Synthetic assets retired · **DECIDE**

| | |
| --- | --- |
| Your form | `retirement_mask = data["capacity_change"] < 0` — any falling capacity is a retirement, synthetic or real |
| Handover form | `retirement_mask = (capacity_change < 0) & ~is_synthetic` |
| Done | Ported the handover form |

**What to look at.** A synthetic asset is the accounting construct that carries
a company's incremental shock growth. Under your form, when that construct
shrinks it books `retired_max_cap` and — with `include_decom_costs` on, which it
now is — is charged demolition and site-restoration costs for a plant that was
never built. The counter-argument is that synthetic capacity shrinking is still
capacity leaving the system and arguably has *some* cost. If you want that, it
needs a different rate than physical decommissioning, not the same one.

### Q1-2 · Replacement CapEx base · **DECIDE**

| | |
| --- | --- |
| Your form | `replacement_mask = ~is_synthetic & (capacity_change > 0)`; capacity charged = `capacity_change × replacement_capex_rate` |
| Handover form | `replacement_mask = is_real & ~retirement_mask`; capacity charged = `asset_trajectory × 0.02` |
| Done | Ported the handover form, keeping your parameterised rate as the mechanism |

**What to look at.** This is the largest single semantic difference in the
earnings stage, and the two forms mean different things. Yours capitalises a
fraction of *growth*: an asset that never grows never pays maintenance, and a
flat coal plant costs nothing to keep running. The handover form charges routine
capital maintenance on *installed* capacity every year, which is the utility
convention (1–3% of replacement cost annually; EPRI, Lazard LCOE). It is also
what makes continued O&M and replacement CapEx tell a consistent story about a
plant that is being kept alive.

Note the knock-on: because roll-over is no longer a capacity *movement*, the
flow identity `K_t = K_{t-1} − retired + replaced + new_build` can no longer
balance by construction. See Q1-5.

**The switch default flipped too — `include_replacement_capex: False → True`**
(`parameters_calculate_asset_earnings.yml`). On `main` the whole replacement
term is OFF out of the box, so the form above is not merely different from
yours, it is *newly live*: a default run now charges routine capital
maintenance on installed capacity every year where before it charged nothing.
Every absolute `capex_total`, FCFF and NPV moves on that flip alone,
independently of the mask change. If the switch should ship OFF and the form
change be adopted only for runs that ask for it, this is the line to say so on.

### Q1-3 · `replacement_capex_rate` default · FYI

| | |
| --- | --- |
| Your form | `0.05` |
| Handover form | `0.02`, hardcoded |
| Done | Default moved to `0.02`; the key stays yours |

**What to look at.** Your parameterisation is kept as the mechanism — the ruling
was explicit that the *number* comes from the handover branch and the *knob*
from you. If 5% was a deliberate calibration rather than a placeholder, say so:
the parameter is the right place for it and only the default would move back.

### Q1-4 · Decommissioning cost sign · **DECIDE**

| | |
| --- | --- |
| Your form | `decom_cost = scrap_usd_per_mw × capex_capacity` |
| Handover form | `decom_cost = abs(scrap_usd_per_mw) × capex_capacity` |
| Done | Ported the handover form |

**What to look at.** `scrap_usd_per_mw` arrives negative (it is `-capex/2`), and
`decom_cost` is summed into `capex_total`, which is subtracted from EBITDA. Your
form therefore *raises* FCFF when an asset retires — retiring a plant pays its
owner. If the intent was to model recoverable scrap value net of demolition,
that is a defensible model, but it belongs as its own signed term, not folded
into a cost line whose sign convention is "outflow".

**The switch default flipped too — `include_decom_costs: False → True`**
(`parameters_calculate_asset_earnings.yml`). As with Q1-2, on `main` the term
is OFF out of the box, so the sign fix above only bites because the switch is
now on by default: a default run charges decommissioning on every retiring
asset where before it charged nothing. Same call to make, on the same line.

**Both flips together.** `include_replacement_capex` and `include_decom_costs`
both move `False → True` against `main`; `include_growth_capex` stays `False`.
These are the two default changes in this report that move every absolute
number in a run nobody has reconfigured, so they are called out here rather
than left to the parameter diff.

### Q1-5 · `validate_capacity_flow_identity` is now unreachable-and-wrong · FYI

The function divides `roll_over_cap` by `replacement_capex_rate` to recover a
capacity movement. Under Q1-2 roll-over is a fraction of installed capacity, so
that division recovers the trajectory, not a movement, and the identity cannot
balance. It was already dead — its only call site in `compute_flow_based_capex`
is commented out, and the handover branch carries the same TODO — so it was left
alone rather than deleted or repaired.

**What to look at.** It is dead code that now reads as wrong rather than merely
approximate. Deleting it is a one-line change and would remove a trap; that is
your call, not ours.

---

## Q2 — The NPV-direction feature set (`056d1f6`)

Commit `95d5b7c`.

### Q2-1 · Price ramp · **DECIDE**

| | |
| --- | --- |
| Your form | `combine_company_trajectory_cases` hard-switches the late & sudden financial surfaces to the target scenario at `shock_year` |
| Handover form | Linear blend baseline → target across `[shock_year, alignment_year]` |
| Done | Ported as a `price_ramp` parameter (default `True`) in `parameters_calculate_company_trajectories.yml`; the hard switch is `price_ramp: False` and is still tested |

**What to look at.** Two things.

First, *where* it lives. The handover branch ramps inside the earnings stage's
panel assembly. Your structure joins the surfaces one stage earlier, in
`combine_company_trajectory_cases`, so that is where it went — same arithmetic,
your seam.

Second, and this is the one to check: **a ramped pathway keeps carrying the
BASELINE `scenario` name and `scenario_type`.** Its surface is a mixture of the
two scenarios, so labelling it "target" would be false, and there is no third
label. This reproduces the handover branch exactly, but it means
`asset_earnings.scenario_type` reads `baseline` for every row while
`trajectory_type` still distinguishes the two worlds. Anyone grouping by
`scenario_type` will get a surprise. It is also load-bearing: `scenario_type`
selects the discount rate, so with the ramp on, both worlds take
`discount_rate_baseline`. That is harmless today only because the two rates ship
equal (`0.07`). **If you ever set them apart, the ramp will silently neutralise
the difference.** Worth a decision now rather than a bug later.

### Q2-2 · `alignment_year` default · FYI

`2035` → `2038`, the transition window the handover branch runs. Not cosmetic:
it sets the ramp's duration, so it interacts with Q2-1.

### Q2-3 · Terminal value · **DECIDE**

| | |
| --- | --- |
| Your form | One Gordon-growth perpetuity, applied where `final_fcff > 0` and `r > g`; a single `terminal_growth_rate`; terminal FCFF = the final year alone |
| Handover form | Three tiers (stranded → TV 0; profitable declining carbontech → finite annuity; else perpetuity), technology-specific growth rates, and terminal FCFF normalized over a window |
| Done | Ported all of it, behind `dcf.stranding_aware_tv` (default `True`) |

**What to look at.** The anchor condition changed from `final_fcff > 0` to
`final_fcff != 0`, and that is independent of the stranding switch. Your
comment on it was explicit — the positive test "is what keeps a loss-making
asset from being handed a negative perpetuity". Under the ported rule a
loss-making asset that does *not* meet the stranding test now takes a negative
perpetuity.

The argument for it: an asset losing money at the horizon is worth less than
nothing to its owner, and flooring it at zero flatters the shock world
specifically, since that is where the losses are. The argument against it is
yours and still stands if the stranding tiers are ever switched off — with
`stranding_aware_tv: False` there is no abandonment option to bound the loss,
and a permanently loss-making asset gets an unbounded negative perpetuity. **If
you disagree with the ported rule, this is the single line to discuss**
(`has_terminal_fcff = final_fcff != 0`).

### Q2-4 · Technology-differentiated discount rates · FYI

New: `dcf.brown_discount_spread` (+100 bps) and `dcf.green_discount_spread`
(−50 bps), applied on top of the scenario base rate by `alignment_type`. Your
tree had a uniform rate. Setting both to `0` restores it exactly.

### Q2-5 · Dynamic marginal EF and `carbon_cost_method` · FYI

Ported as parameters and a live code path, but **inert**. Both act on
`marginal_emission_factor`, which the market-clearing-price adjustment produced;
that adjustment stays retired (see MCPR-1), so the column is absent, the
marginal EF is 0, `"full_ef"` and `"differential_ef"` coincide, and the dynamic
scaling multiplies zero. Every technology pays its full emission factor, exactly
as before.

**What to look at.** This is the one place we carried code that does nothing
today. The alternative was to drop it and lose the differential path if MCPR
ever returns. If you would rather not carry inert branches, deleting
`_vre_capacity_share` and the two keys is self-contained and loses nothing that
is currently running.

### Q2-6 · Non-finite `npv_change` · FYI

A zero baseline NPV produced `±inf`; it is now `NaN` in all three aggregation
nodes. `inf` is not "infinitely worse", and it poisons every downstream mean.

### Q2-7 · `ar6_carbon_prices` NOT adopted · **DECIDE**

| | |
| --- | --- |
| Your form | Carbon prices arrive only in `scenarios.csv` (`carbon_price_usd_per_tco2`) |
| Handover form | Plus an `ar6_carbon_prices` catalog entry reading a repo-root side-file, injected per scenario/geography/year |
| Done | **Kept your form.** The handover behaviour was not ported |

**What to look at.** This is the one place the ruling's "Jakub's behaviour wins"
was *not* applied, so it needs your agreement rather than just your awareness.
The reasons: the injection node early-returns whenever the scenario table
already carries carbon prices, which every shipped IAM extract does, so it never
fires; adopting it would add a fourth required input file that neither
`scripts/prepare_inputs.py` produces nor the package ships (a known defect on
the handover branch — its own notes B12/B13 flag a verbatim external run dying
with `FileNotFoundError`); and equivalence was reached without it, which is the
evidence that it is inert rather than the assumption. Documented in
`docs/handover/quickstart.md` under "Carbon prices: there is no fourth file".

---

## Q3 — Emission-factor forward fill

Commit `b423be2`.

### Q3-1 · Fill grain · FYI

| | |
| --- | --- |
| Your form | No forward fill; missing EF reaches `compute_ops_block`'s `fillna(0.0)` |
| Handover form | `groupby(["asset_id", "technology"]).ffill()` in the earnings validation |
| Done | Ported into `validate_asset_trajectories`, but grouped on `ASSET_SERIES_KEYS` |

**What to look at.** The handover branch fills on `(asset_id, technology)`. In
your tree a physical asset legitimately appears once per owner and once per
trajectory, and your own module comment says every time-series operation must
use the complete canonical grain — so the fill uses `ASSET_SERIES_KEYS`. The two
agree wherever EF is constant across owners and trajectories, which it is in all
observed data; the narrower key would let one owner's value carry into
another's row. **This is a case where your convention is the stricter one and we
followed it, not the handover branch.**

Inert on the committed fixture slice, whose EF series already spans the horizon —
the regression pins did not move. It bites on inputs whose EF series is shorter
than the trajectory, which is the production case the handover branch hit.

---

## Q4 — Frozen capacity at retirement

Commit `ebc3536`.

### Q4-1 · Dataset restored · FYI

`frozen_capacity_at_retirement` was retired here and is restored, produced by
`allocate_company_trajectories_to_assets` and consumed by
`calculate_asset_earnings`. It is numerically inert: nothing in the earnings
maths reads it (fixed costs use first-year capacity), and the regression pins
did not move.

### Q4-2 · Produced in the allocation stage, not its own · FYI

The handover branch has it in the impact-distribution stage. Here it is a node
in the allocation pipeline, filtering the wide allocation panel — `retirement_year`
is already carried on every row, so it is a filter, not a join, and no new
pipeline or intermediate dataset was created.

**Correction (2026-09-01 review).** This entry originally said the carried
`retirement_year` was sufficient to filter on. It is not: allocation clips
retirement to `max(retirement_year, alignment_year + 1)`
(`_allocation_nodes.py`), so for any asset dated to retire on or before the
alignment year the raw column names a year the asset is still running. The
node anchored on the raw value and therefore froze the wrong capacity for
exactly those assets. Fixed — the node now takes `alignment_year` and applies
the same clip. The pins did not move, because the dataset is numerically inert
(Q4-1); this is a latent defect that would have surfaced the moment anything
started reading the column.

### Q4-3 · Merge keys · FYI

The handover branch merges on five keys (no `sector`); this merges on your
six-key `ASSET_KEYS + ["year"]` with `validate="many_to_one"`. Same rows, one
more guard.

### Q4-4 · Three of your tests were changed · **DECIDE**

The ruling explicitly supersedes the test that defended the removal, so:

* `tests/test_run.py` — `frozen_capacity_at_retirement` removed from
  `REMOVED_DATASETS`;
* `tests/test_run.py` — `test_pipeline_public_contracts_are_narrow_and_canonical`
  now expects two allocation outputs and two earnings data inputs instead of one
  each;
* `tests/integration/test_fixture_catalog_complete.py` — the expected base
  catalog gains the dataset (and the test's name no longer says "ten").

Each assertion was **edited with a comment citing the ruling**, never deleted,
so the original intent stays visible in the diff and in the file.

**What to look at.** The narrow-contract test was deliberate design — "the
earnings stage takes exactly one input" is a real invariant and it is now
weaker. If you would rather keep it absolutely, the alternative is to fold
frozen capacity into `asset_trajectories` as extra columns instead of a second
dataset. That was not done because it would change your canonical table's
schema, which seemed the larger violation of the two.

---

## MCPR

### MCPR-1 · Stays retired · FYI

Nothing MCPR crossed, per the ruling. Recorded here because it is the reason
Q2-5 is inert.

**Evidence it cannot explain any residual delta**: on the handover branch's own
fixture, `enable_mcpr: False` produces byte-identical outputs, because
`mcpr_floor_at_iam_price` clamps the adjusted price back to the IAM price
everywhere on this data (handover notes D82, B6). MCPR's absence is therefore
not available as an explanation for anything, and none of the entries above
lean on it.

---

## Ownership

### OWN-1 · Ownership tier selection · **RESOLVED-AS-PARAMETER**

| | |
| --- | --- |
| Your form | `filter_companies(companies_ownerships, company_ids)` — consolidates across every tier, summing all stakes a company holds in an asset-year. No `ownership_type` parameter |
| Handover form | Selects a tier (`ownership_type`, default `"direct"`) **first**, then consolidates within it |
| Done | **Both, under `ownership_aggregation`.** The owner ruled on 2026-09-01 that this is a parameter, not a winner: `"tier_filter"` (DEFAULT — the handover form, tier then consolidate) and `"sum"` (your form, every holding totalled). One key in `parameters_prepare_scenario_asset_and_company_inputs.yml`, one branch inside your `filter_companies`; `_consolidate_ownership_stakes` still untouched |

**Which mode to use.** Run `"tier_filter"` for anything that has to match the
validated baseline — it is what last year's published results and the pinned
fixture NPVs were produced under — and `"sum"` when the numbers have to line up
with a TRISK run, which reads a company's holding as direct + equity.

**Ruling lineage.** Owner decision of 2026-09-01, the same ruling this report
applies (`implementation-notes-handover.md`, "Owner decisions 2026-09-01" +
Amendment; `migration-disposition-ledger.md`, Addendum 2). The entry below is
kept as the record of *why* the default is the tier filter — the argument no
longer decides which code ships, only which mode a run should pick.

**What to look at.** This was the largest behavioural difference between the two
lineages and the change that closed the equivalence gate, so it deserves the
most scrutiny.

The substance: a company's stake in an asset is recorded at several tiers — a
direct holding, and the equity stakes that roll up through subsidiaries. These
are alternative *views* of the same capacity, not additive components of it.
Summing them allocates the same plant to the same company more than once. On the
fixture slice, one company holds a plant at 50.00% direct **and** 0.45% equity;
consolidating across tiers gave it 50.45%, and the asset universe went from 721
owner-asset rows to 1,591 — a 2.2× inflation of every absolute output.

Why your form looks reasonable in isolation: `_consolidate_ownership_stakes`
exists to stop duplicate `(company_id, asset_id, year)` keys reaching the
per-asset pivot, and summing does remove them. It fixes the symptom. But the
duplicates were the *tiers*, and the handover notes on the same port record the
ordering explicitly — filter first, consolidate within the selected tier —
precisely because your lineage's ownership table has no tier column while ours
does.

`_consolidate_ownership_stakes` itself is unchanged and still sums whatever it
is given. That is deliberate: its contract is "sum these", and the ordering is
what makes that safe.

The consolidation regression test documented the no-tier behaviour in prose
("the parameter of the same name is gone too"). It is rewritten around the
restored ordering, with new cases for both company schemas (`ownership_type`
naming the rungs, `ownership_level` numbering them) and for an input carrying
neither, which warns and keeps every row.

**Correction (2026-09-01 review).** "Both schemas covered" was true of the
happy path only. Under the named `ownership_type` schema a configured tier the
data does not carry — and the documented value `"indirect"` was exactly that,
since the shipped input holds `direct` and `equity` — matched nothing and
returned an EMPTY panel, taking every company out of the run silently;
arbitrary values were accepted the same way. The test that should have caught
it asserted the empty result as if it were the feature (it was even named
"…selects the other rung"). Both schemas now validate and raise a `ValueError`
naming the configured value and what is available, the parameter comment names
`direct`/`equity` rather than `direct`/`indirect`, and the test asserts the
equity rows come back and that an absent tier raises.

**If you think summing tiers is right**, it is now a setting rather than an
argument: `ownership_aggregation: "sum"`. The 2.2× is the reason the default is
not that — a run must state which reading it used, and two runs on different
readings cannot be compared on absolute numbers.

The consolidation regression test carries both modes: the tier-first cases
above, plus `"sum"` totalling one company's 50.00% direct and 0.45% equity
stakes to 50.45%, an equity-only holder that `"tier_filter"` drops and `"sum"`
keeps, and a `ValueError` naming both options on anything else.

### OWN-2 · The recipient's data has no tier column · **RULED-A-DATA-DEFECT**

| | |
| --- | --- |
| Found | The deliverables `companies_ownerships.csv` (2026-08-25 drop) has **8 columns and no tier column at all** — `asset_id`, `company_id`, `year`, `ownership_percentage`, `sector`, `technology`, `asset_name`, `company_name`. Neither `ownership_type` nor `ownership_level` |
| Why it matters | Every argument in OWN-1 above — the default, the 2.2× on absolute outputs, the whole `ownership_aggregation` design — assumes a tier column exists. On the recipient's actual file `_select_ownership_tier` takes its third branch and keeps every row, so `"tier_filter"` silently degrades into `"sum"` on the full ownership chain. The internal `downloaded_companies.csv` (BigQuery marts) DOES carry `ownership_type`, which is why this was invisible internally |
| Ruling | Owner, 2026-09-01: a tier-less export is a **DATA-EXPORT DEFECT**, not a run-time mode. `scripts/prepare_inputs.py::build_companies` now refuses such a file outright (`require_ownership_tier`), naming the column, the consequence and the remedy |
| Action | **Owner + Bertrand: re-export the deliverables including `ownership_type` from the marts.** Until that lands, the 2026-08-25 drop cannot be converted into model inputs |

**Measured on the 2026-08-25 drop** (1,048,249 rows, 152,972 asset-years),
totalling `ownership_percentage` per `(asset_id, year)` with no tier selected:

| Statistic | Value |
| --- | --- |
| Asset-years summing above 105% | **92.0%** |
| Median asset-year sum | **227.5%** |
| Maximum asset-year sum | 903.3% |
| Asset-years within 99–101% | 4.3% |

A median of 227% is the ownership chain restating the same capacity roughly
twice over. `allocate_assets_to_companies` multiplies capacity by
`ownership_percentage / 100` with no renormalisation, so every absolute output
of such a run — NPV, earnings, allocated capacity — is inflated by about that
factor. It is not a rounding-scale problem that a warning covers.

**Why it fails rather than warns.** `check_ownership_allocation` already warned
about exactly this number, and the warning is not enough: it fires on stderr
mid-conversion, the script writes `data/05_model_input/` anyway, and the run
that follows produces plausible-looking numbers. The tier column is part of the
input contract, so its absence belongs with the other missing-column failures.

**The export build is unaffected.** `build_export.py --data-source` only
*stages* the three raw files into `data/01_raw/`; it never calls
`prepare_inputs.py`. The guard therefore fires at the recipient's quickstart
step 4, not during export assembly, and the export gate still passes on the
tier-less drop. Quickstart step 3 says so explicitly.

---

## Naming and column clashes (no behaviour change)

### NAME-1 · Power price column · FYI

Yours is `power_price_excarbon_usd_per_mwh`; the handover branch's is
`power_price_usd_per_mwh`. Same value, same role. **Yours is kept everywhere** —
it is also the better name, since it says which convention the price follows.

### NAME-2 · Earnings output columns · FYI

Your `asset_earnings` carries `asset_age` and `late_sudden_phase`, which the
handover branch's does not. Kept; they are additions, not conflicts, and the
plotting stage uses them.

### NAME-3 · Grouping keys throughout · FYI

Wherever the handover branch groups on a narrower key set than your
`ASSET_SERIES_KEYS` / `ASSET_KEYS` (the EF fill, the capacity-flow shift, the
continued-O&M first-year capacity, the frozen-capacity merge), **your key set was
used**. It is a superset in every case, so the results agree on all observed
data while being correct on multi-owner and multi-geography assets, which the
narrower keys are not.

### NAME-4 · Unresolved `scenario_type` · **DECIDE**

| | |
| --- | --- |
| Your form | `compute_yearly_npv_trajectories` **raises** listing the offending asset ids |
| Handover form | Logs an error naming the affected (geography, sector, technology) combinations and **drops** the rows |
| Done | **Kept your form.** Not changed |

**What to look at.** This is a divergence we did not resolve in the handover
branch's favour, so flagging it plainly. The handover branch drops because it hit
the condition in production (its own TODO says roughly 200 rows per run, cause
unfixed upstream); yours refuses to produce a valuation it cannot explain. Your
form is the better engineering and it does not fire on this data, so changing it
would have traded a real guard for a defect the ruling never asked us to import.
But it means a production run that would have completed on the handover branch
will stop here. **Your call whether that is what you want on full data.**

---

## Fixture and gate changes

### GATE-1 · The slice was re-cut · FYI

`tests/fixtures/data/{assets_forecasts,companies_ownerships}.csv` were rebuilt on
the five companies the handover branch's committed slice holds, so that the two
branches' outputs are comparable company for company. Same scenario pair
(`AR6_WITCH 5.0_EN_NoPolicy` / `AR6_WITCH 5.0_EN_NPi2020_500`) — that already
matched. The builder now defaults to the companies already in the committed
slice, read off the CSV rather than written into the source (they are licensed
identifiers, and the sanitizer was right to object when they were hardcoded).

### GATE-2 · Regression pins re-derived · FYI

`tests/integration/test_fixture_run.py` pins were re-derived from a run of this
tree at each step, never copied from the handover branch. They moved three
times: at the re-cut (different companies), at Q1 (different CapEx), and at Q2
(different terminal values). They did **not** move at Q3 or Q4, which is the
evidence those two are inert on this slice.

### GATE-3 · Equivalence result · FYI

Aligned slice, both trees' fixture pipelines, `--tags altrisk`:

| Level | Column | Max relative deviation |
| --- | --- | --- |
| Company (5 rows) | `baseline_npv` | 5.7e-16 |
| Company | `latesudden_npv` | 2.1e-16 |
| Company | `npv_change` | 1.4e-15 |
| Company | `asset_count` | 0 (exact) |
| Asset (721 rows, keys identical) | worst of 16 columns | 7.6e-14 |

Row counts match exactly at both levels and no key exists on one side only.
Every deviation is at float64 accumulation noise; **no residual difference
requires an explanation, and none is attributed to MCPR.**

### GATE-4 · Lint delta · FYI

`ruff check src` goes 105 → 109. The four are all the mechanical consequence of
the parameters the ruling adds, in rule categories that already had hits:

* `PLR0913` +3 — `compute_yearly_npv_trajectories`, `compute_ops_block`,
  `combine_company_trajectory_cases` and `prepare_asset_forecast_panel` each
  gained ported parameters;
* `PLR0912` +1 — the terminal-value ladder branches.

**No new rule category, and zero net-new `# noqa`.** A `# noqa: PLR0913` was
briefly added to `compute_yearly_npv_trajectories` and then removed: the honest
count is better than a suppressed one. `src/` now carries no `noqa` at all. The
remaining `tests/` delta is `PLR2004` magic values in the new characterization
tests, consistent with the 37 already there.

---

## Summary for review

| Decide first | Why it matters |
| --- | --- |
| ~~**OWN-1** ownership tier~~ — settled: `ownership_aggregation`, default `"tier_filter"` | was 2.2× on every absolute output; now a documented mode switch |
| **OWN-2** re-export the deliverables with `ownership_type` — ruled, but an OPEN ACTION for owner + Bertrand | the delivered file has no tier column, so the default mode degrades to summing the whole chain: median asset-year ownership 227%. `prepare_inputs.py` now refuses the drop |
| **Q2-1** price ramp labels rows `baseline` | silently neutralises any future split between the two discount rates |
| **Q2-3** negative perpetuity | reverses an explicit design choice of yours |
| **Q1-2 / Q1-4** the two switch defaults flip `False → True` vs `main` (`include_replacement_capex`, `include_decom_costs`) | both terms are newly LIVE in a default run, so every absolute number moves before either form change is even considered |
| **Q1-2** replacement CapEx base | changes what "maintenance" means in the model |
| **NAME-4** raise vs drop | your guard kept; may stop a full-data run |
| **Q2-7** carbon-price side-file | the one place the ruling was not applied |
| **Q1-4** decom sign | retiring an asset used to pay its owner |
| **Q4-4** narrowed contract test | a deliberate invariant is now weaker |

## Reviewer notes for the maintainer (post-review, non-blocking)

Left by the final dual review; none blocks merge, all worth knowing:

1. **Names are no longer group keys.** company_name/asset_name are carried as
   `first` aggregations over the load-bearing keys (2134579) — a blank name can
   neither delete a stake nor split a company. If a future change re-keys on
   names, both failure modes return.
2. **Exported uv.lock keeps streamlit's transitive-only packages** (altair,
   pydeck, blinker) — inert, `uv lock --check` passes, but visible to a reader.
3. **Terminal-value normalization still averages filled zeros across data
   gaps** in the last window years (deliberate X2 scoping: the stranding
   CLASSIFICATION ignores gaps; the normalization mean does not).
4. **The prepare_inputs tier guard covers the documented ingress only** — a
   tier-less CSV dropped directly into data/05_model_input/ bypasses it and
   over-allocates with only a log line. Deliberate (hand-made-frame
   compatibility); noted here so nobody assumes the hole is fully closed.
5. **ownership_level holding strings** coerces to NaN and raises with a
   message that points at the values, not the schema mismatch — loud but
   imprecise; not believed to be a shape in circulation.
