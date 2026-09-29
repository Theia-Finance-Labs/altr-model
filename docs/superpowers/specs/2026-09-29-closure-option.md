# Year-by-year plant closure (abandonment option) — spec

Status: EXPERIMENTAL, branch `feat/closure-option`. Off by default
(`dcf.closure_option: False`), so the shipped model run is unchanged — owner
ruling 2026-09-29: the partner-facing run keeps its deeply negative values; the
closure option is measured on this branch only.

## Why

Closure exists today only AFTER the horizon (stranded TV = 0; bounded negative
TV = max(run-out, -decom)). Inside the forecast window a plant that loses money
runs on until age or the scenario pathway retires it, so its losses accumulate
into a negative NPV. WITCH 5.0 on the 25 Sep mart: 13,060 negative asset NPVs,
56% of companies negative at BASELINE. `dispatch_floor` only moves the cause
from fuel to fixed O&M (12,996).

## Rule

Deterministic scenarios, so the owner's optimal stopping problem solves exactly
by backward induction, in present-value terms (discounted to the group's base
year, the node's existing convention):

    V[T+1] = terminal value the existing tiers give (unchanged)
    V[t]   = max( exit[t],  pv_fcff[t] + V[t+1] )     where exit is allowed
    exit[t] = -|scrap_usd_per_mw| * capacity[t-1] * discount_factor[t]

The plant closes in the FIRST year the exit arm wins. From that year on its
cash flows are zero, the exit cost is booked as that year's capex/FCFF, and the
terminal value is 0. Closure is permanent (no re-opening).

Consequences: a temporary loss followed by profits runs through; a permanent
loss closes at once; a plant profitable until the carbon price bites closes
mid-life. No fixed "N loss years" heuristic.

## Design decisions (defaults taken; each is a two-way door)

1. **No foresight of the shock.** Baseline: exit allowed in every year.
   Late & sudden: pre-shock years share the baseline outlook, so if the
   matching baseline series closes before `shock_year`, the shock series closes
   in the same year; otherwise exit is allowed only from `shock_year` on.
   Alternative: perfect foresight on both paths. Cost to change: one mask.
2. **Continued O&M stops at closure.** Closure zeroes every cash flow after the
   exit year, including the shock-side continued O&M on first-year capacity.
   Alternative: keep charging it. Cost: a column exception in the zeroing.
3. **Valuation only.** Closed capacity is NOT reallocated to other assets and
   asset output no longer sums to the IAM pathway after closure.
4. **Exit priced on the capacity standing entering the year** (`capacity[t-1]`,
   the first year uses its own) so a plant cannot dodge a decommissioning bill
   the pathway already books in its retirement year (no free exit — cf. ruling
   C2). Scrap price = the horizon `scrap_usd_per_mw` (per-year scrap is not
   carried to this stage). No scrap quote -> no exit arm -> no closure.
5. **Existing TV tiers stay** as V[T+1]; the company floor stays.

## Out of scope

Stochastic prices / option value of waiting; mothballing; reallocation of
closed capacity; partial (unit-level) closure.

## Verification

Unit tests on hand-built frames (exact closed forms): permanent loss, temporary
loss, mid-life closure, no scrap, shock-year masking, baseline pre-shock
closure inherited, retirement-year no-free-exit, flag off = identical output.
Then WITCH 5.0 (25 Sep mart) closure off vs on: negative-NPV count by cause,
companies negative at baseline, portfolio change floored and unfloored.
