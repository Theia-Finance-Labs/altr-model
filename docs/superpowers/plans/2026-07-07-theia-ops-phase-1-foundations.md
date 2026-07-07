# theia-ops Phase 1 — Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the `theia-ops` repo, the org-wide Theia Team Board, the five Granola meeting templates, the operating manual, and agent context files — everything the Phase 2 pipeline will plug into.

**Architecture:** Pure foundations — no pipeline code yet. A private org repo holds conventions-as-files; a GitHub Projects v2 board with Project/Sprint fields becomes the single team board; Granola templates force the note structure Phase 2's extractor depends on. Spec: `docs/superpowers/specs/2026-07-07-team-ops-system-design.md` (crispy-kedro, commits 190bee7 + 6a2d862).

**Tech Stack:** `gh` CLI (repo, Projects v2), Markdown, Granola templates.

## Global Constraints

- Repo: `Theia-Finance-Labs/theia-ops`, **private**.
- Workers run on **Opus** (`model: opus`); the Phase gate reviewer runs on **Fable** — exactly one reviewer, Santa-method adversarial style.
- **Never delete files** (Jakub's global rule) — supersede into archive locations instead.
- AGENTS.md files ≤150 lines.
- Pipeline permissions (future phases) are additive-only; nothing in Phase 1 grants delete/close automation.
- Team roles (spec §1b): Soenke = PM successor (handover-readiness), Bertrand = first commenter on technical development.
- All `gh` commands target org `Theia-Finance-Labs`; verify with `gh auth status` before starting.

---

### Task 1: Create the `theia-ops` repo with skeleton and AGENTS.md

**Files:**
- Create: `theia-ops/README.md`, `theia-ops/AGENTS.md`, `theia-ops/docs/.gitkeep`, `theia-ops/templates/granola/.gitkeep`, `theia-ops/templates/github/.gitkeep`, `theia-ops/pipeline/.gitkeep`, `theia-ops/dispatcher/.gitkeep`, `theia-ops/tests/.gitkeep`
- Copy: crispy-kedro `docs/superpowers/specs/2026-07-07-team-ops-system-design.md` → `theia-ops/docs/spec-2026-07-07-team-ops-system-design.md` (copy, do not remove the original)

**Interfaces:**
- Produces: repo `Theia-Finance-Labs/theia-ops` on default branch `main`; directory layout per spec §7 that every later task writes into.

- [ ] **Step 1: Create the private repo and clone it**

```bash
gh repo create Theia-Finance-Labs/theia-ops --private \
  --description "Team operations product: meeting→board pipeline, templates, operating manual" \
  --clone
cd theia-ops
```
Expected: repo URL printed; local clone exists.

- [ ] **Step 2: Create skeleton and README**

```bash
mkdir -p docs/setup templates/granola templates/github pipeline dispatcher tests .github/workflows
touch docs/.gitkeep templates/granola/.gitkeep templates/github/.gitkeep pipeline/.gitkeep dispatcher/.gitkeep tests/.gitkeep
```

`README.md`:
```markdown
# theia-ops

Internal team-operations product for Theia Finance Labs.
Every recorded meeting becomes board updates, a team digest, and archived docs.

- Spec: `docs/spec-2026-07-07-team-ops-system-design.md`
- How the team works: `docs/operating-manual.md`
- Setup & handover runbook: `docs/setup/`

Operated by Jakub (v1); designed for handover to Soenke.
```

- [ ] **Step 3: Write `AGENTS.md`**

```markdown
# AGENTS.md — theia-ops

## What this repo is
Internal product turning Granola meeting notes into GitHub board updates,
a running Google Doc digest, and Dropbox-archived documentation.
Spec: docs/spec-2026-07-07-team-ops-system-design.md (read it first).

## Layout
- pipeline/    Python package (Phase 2): ingest → extract → reconcile → apply → publish
- dispatcher/  Mac-side trigger (Phase 3): launchd + headless Claude with Granola MCP
- templates/granola/  Meeting templates — the extractor's input contract
- templates/github/   Issue templates + AGENTS.md template for org repos
- docs/        Operating manual, Dropbox structure, setup/handover runbook
- tests/       Golden fixtures: synthetic transcripts → expected JSON

## Hard rules
- Pipeline writes are additive-only: create/update/comment. NEVER close issues.
- Raw transcripts never committed, never printed to CI logs.
- Idempotency marker in every created issue: <!-- granola:<note-id> -->
- Names→handles→roles live in pipeline/config/team.yaml — no hardcoded people.
- Technical issues get label `technical` + review request to Bertrand.
- Nothing may assume Jakub-specific paths beyond dispatcher/ (Soenke handover).

## Verification
- pytest tests/ (Phase 2+); every PR runs CI; --dry-run before live runs.
```

- [ ] **Step 4: Copy the spec in, commit, push**

```bash
cp /Users/jakub/Documents/repos/crispy-kedro/docs/superpowers/specs/2026-07-07-team-ops-system-design.md \
   docs/spec-2026-07-07-team-ops-system-design.md
git add -A
git commit -m "chore: repo skeleton, AGENTS.md, spec import"
git push -u origin main
```
Expected: push succeeds; `gh repo view Theia-Finance-Labs/theia-ops` shows the files.

---

### Task 2: Create the Theia Team Board (Projects v2)

**Files:** none (GitHub configuration); document IDs in `docs/setup/board.md`.

**Interfaces:**
- Produces: project number + field IDs recorded in `docs/setup/board.md` — Phase 2's `apply_github.py` and Phase 3 secrets reference these exact IDs.

- [ ] **Step 1: Create the project**

```bash
gh project create --owner Theia-Finance-Labs --title "Theia Team Board" --format json
```
Expected: JSON with `"number": <N>` — record `<N>`.

- [ ] **Step 2: Add the Project single-select field**

```bash
gh project field-create <N> --owner Theia-Finance-Labs \
  --name "Project" --data-type SINGLE_SELECT \
  --single-select-options "TCM,MCPR,Scenario-Tools,Org"
```
Expected: field JSON returned.

- [ ] **Step 3: Manual UI steps (CLI cannot do these) — document as performed**

In the board UI (`https://github.com/orgs/Theia-Finance-Labs/projects/<N>`):
1. Settings → Status field → add options **Blocked** and **In Review** (keeping Todo, In Progress, Done).
2. Add field → **Iteration** named `Sprint`, 2-week duration, starting next odd Monday (2026-07-13).
3. Workflows → enable **Auto-add to project** for repo `crispy-kedro` (filter: `is:issue is:open`), **Item closed → Done**, **Pull request merged → Done**.

- [ ] **Step 4: Record board metadata**

`docs/setup/board.md` in theia-ops:
```markdown
# Theia Team Board
- Project number: <N>
- URL: https://github.com/orgs/Theia-Finance-Labs/projects/<N>
- Fields: Status (Todo/In Progress/Blocked/In Review/Done), Priority (native), Sprint (2-week iteration), Project (TCM/MCPR/Scenario-Tools/Org)
- Field IDs (gh project field-list <N> --owner Theia-Finance-Labs --format json): <paste>
- Built-in workflows enabled: auto-add (crispy-kedro), closed→Done, merged→Done
```

```bash
gh project field-list <N> --owner Theia-Finance-Labs --format json   # paste IDs into board.md
git add docs/setup/board.md && git commit -m "docs: record Theia Team Board configuration" && git push
```
Expected: board.md committed with real IDs, no `<N>`/`<paste>` placeholders left.

---

### Task 3: Write the five Granola meeting templates

**Files:**
- Create: `templates/granola/sprint-planning.md`, `templates/granola/bilateral.md`, `templates/granola/sprint-checkin.md`, `templates/granola/org-meeting.md`, `templates/granola/research-brainstorm.md`

**Interfaces:**
- Produces: section headings that Phase 2 extraction prompts key on verbatim — do not rename headings later without updating `pipeline/prompts/`.

- [ ] **Step 1: Write `sprint-planning.md`**

```markdown
# Sprint Planning — {date}
## Sprint goal
## Carry-over from last sprint
## Plan per person
(Jakub / Bertrand / Max / Antonio / Kevin / Jakob / Soenke — issue refs + planned work)
## New issues to create
(one line each: title — owner — due — project)
## Decisions
(say "Decision: …" out loud)
## Parked
```

- [ ] **Step 2: Write `bilateral.md`**

```markdown
# Bilateral {name} × Jakub — {date}
## Ticket updates
(per issue: #ref — status — progress note — blockers)
## New actions
(say "Action: NAME to X by DATE" — one owner each)
## Decisions
## Off the record
(anything here is NEVER extracted or stored outside Granola)
```

- [ ] **Step 3: Write `sprint-checkin.md`**

```markdown
# Sprint Check-in — {date}
## Per person: Done / Next / Blocked
## Sprint health
(on track / at risk / off track + why)
## Scope changes
## Decisions
```

- [ ] **Step 4: Write `org-meeting.md` and `research-brainstorm.md`**

`org-meeting.md`:
```markdown
# Org Meeting — {date}
## General notes
(not extracted)
## Project-relevant items
(ONLY this section is extracted; leave empty if nothing project-related)
## Decisions
## Actions
```

`research-brainstorm.md`:
```markdown
# Research Brainstorm — {date}
## Ideas discussed
## Candidate issues
(title — rough scope — champion; labeled `research`, unassigned)
## References
(papers, links)
## Decisions
```

- [ ] **Step 5: Verify headings and commit**

```bash
grep -c '^## ' templates/granola/*.md
```
Expected: sprint-planning 6, bilateral 4, sprint-checkin 4, org-meeting 4, research-brainstorm 4.

```bash
git add templates/granola && git commit -m "feat: Granola meeting templates (extraction input contract)" && git push
```

- [ ] **Step 6: Manual — paste templates into Granola + create folders**

In Granola: create folders `Sprint Planning`, `Bilaterals`, `Sprint Check-in`, `Org Meeting`, `Research Brainstorm`; create one template per folder from these files. (Jakub's Business seat.)

---

### Task 4: Write the operating manual

**Files:**
- Create: `docs/operating-manual.md`

**Interfaces:**
- Produces: the document Soenke inherits; the conventions Phase 2 prompts encode; onboarding material for Week-3 (Phase 4).

- [ ] **Step 1: Write `docs/operating-manual.md`**

```markdown
# Operating Manual — Theia Finance Labs

## Meetings (all recorded by Jakub via Granola)
| Meeting | When | Template folder |
|---|---|---|
| Sprint Planning | Mondays 1h | Sprint Planning |
| Bilaterals ×5 (Bertrand, Antonio, Max, Soenke, Jakob) | weekly 30min | Bilaterals |
| Sprint Check-in | odd Mondays 30-45min | Sprint Check-in |
| Org Meeting | Mondays 45min | Org Meeting |
| Research Brainstorm | monthly (from Phase 4+) | Research Brainstorm |

## Speaking conventions (make the AI extraction reliable)
- "Decision: …" for any decision.
- "Action: NAME to X by DATE" — exactly one owner per action.
- Bilateral personal topics go under "Off the record" — never extracted.

## Tickets
- Everything actionable is a GitHub issue in its project repo, on the Theia Team Board.
- Fields: Status, Priority, Sprint (2-week), Project.
- Labels: `from-meeting` (pipeline-created), `technical` (auto-requests Bertrand's review), `research`.
- The pipeline never closes issues — closures are proposed in the Monday digest, a human clicks.
- Milestones = deliverables; set at Sprint Planning.

## The Monday digest ritual
Sprint Planning opens by reading the digest (GitHub Discussion + top of the Team Meeting Log Doc):
what moved, stale >14 days, proposed closures, unowned actions. The digest IS our notification system.

## Where documents live
- Versions with code → that repo's `docs/`.
- Everything else → Dropbox `Projects/<project>/` tree (see docs/dropbox-structure.md, Phase 5).
- Meeting record for humans → the running "Team Meeting Log" Google Doc.

## Roles
Jakub: PM + research manager (v1 operator) · Soenke: finance/admin, PM successor ·
Bertrand: technical owner, first commenter on technical work · Max: data engineer ·
Antonio: methodology + own tools · Kevin: methodology/academic lead · Jakob: CEO, scenario tools.
```

- [ ] **Step 2: Commit**

```bash
git add docs/operating-manual.md && git commit -m "docs: operating manual v1" && git push
```

---

### Task 5: AGENTS.md template for org repos + crispy-kedro instance

**Files:**
- Create: `templates/github/AGENTS-template.md` (in theia-ops)
- Create: `AGENTS.md` (in crispy-kedro, committed to its current branch)

**Interfaces:**
- Produces: per-repo agent context; crispy-kedro's instance is the model for Phase 5 org rollout.

- [ ] **Step 1: Write `templates/github/AGENTS-template.md`**

```markdown
# AGENTS.md — {repo}

## Purpose
{1-2 sentences: what this repo does, for which project}

## Team context
Board: Theia Team Board (org project). Issues carry Status/Priority/Sprint/Project fields.
Conventions: theia-ops/docs/operating-manual.md. Technical review: Bertrand first.

## Layout
{top-level dirs, one line each}

## Commands
{build / test / run — exact commands}

## Rules
{repo-specific constraints; keep total file ≤150 lines}
```

- [ ] **Step 2: Write crispy-kedro `AGENTS.md` from the template**

```markdown
# AGENTS.md — crispy-kedro

## Purpose
Kedro pipeline for CRISPY climate risk / transaction cost minimizer (TCM) modelling.

## Team context
Board: Theia Team Board (org project). Issues carry Status/Priority/Sprint/Project fields.
Conventions: theia-ops/docs/operating-manual.md. Technical review: Bertrand first.

## Layout
- src/        Kedro pipelines and nodes
- conf/       Kedro configuration (base/local)
- docs/       research notes, superpowers specs+plans, source docs
- notebooks/  exploratory analysis
- tests/      pytest suite
- MCPR/, pkg/, workspace/  model-specific workstreams

## Commands
- poetry install
- poetry run kedro run
- poetry run pytest tests/

## Rules
- Methodology docs live in docs/; never delete files — archive instead.
- ALTR/MCPR changes need Bertrand's review before merge.
```

- [ ] **Step 3: Commit both**

```bash
# in theia-ops
git add templates/github/AGENTS-template.md && git commit -m "feat: AGENTS.md template for org repos" && git push
# in crispy-kedro
cd /Users/jakub/Documents/repos/crispy-kedro
git add AGENTS.md && git commit -m "docs: add AGENTS.md agent context" -- AGENTS.md
```
Expected: both commits clean; crispy-kedro commit touches only AGENTS.md.

---

### Task 6: Triage crispy-kedro's stale issues onto the board

**Files:** none (GitHub state); produces `docs/setup/triage-2026-07.md` in theia-ops.

**Interfaces:**
- Consumes: board number `<N>` from Task 2's `docs/setup/board.md`.
- Produces: all open crispy-kedro issues on the board with Project=TCM; a triage sheet for Jakub's Sprint-Planning decisions.

- [ ] **Step 1: Add all open issues to the board**

```bash
for i in 13 14 15 16 17 19; do
  gh project item-add <N> --owner Theia-Finance-Labs \
    --url https://github.com/Theia-Finance-Labs/crispy-kedro/issues/$i
done
```
Expected: 6 items added (verify the open list first with `gh issue list --repo Theia-Finance-Labs/crispy-kedro --state open`).

- [ ] **Step 2: Set Project=TCM on each added item**

```bash
gh project item-list <N> --owner Theia-Finance-Labs --format json > /tmp/items.json
# For each item id in items.json (jq '.items[].id'):
gh project item-edit --id <ITEM_ID> --project-id <PROJECT_ID> \
  --field-id <PROJECT_FIELD_ID> --single-select-option-id <TCM_OPTION_ID>
```
IDs come from Task 2's board.md. Expected: item-list shows Project=TCM on all six.

- [ ] **Step 3: Write the triage sheet (decisions belong to Jakub, not the agent)**

`docs/setup/triage-2026-07.md`:
```markdown
# Stale-issue triage — for Sprint Planning
| # | Title (short) | Last update | Proposed | Decide |
|---|---|---|---|---|
| 13 | fuel price in profit equation | 2025-08-28 | keep, backlog | |
| 14 | decom_usd_per_mw node | 2025-08-28 | keep, backlog | |
| 15 | Flow identity violations | 2025-08-29 | keep, assign Bertrand | |
| 16 | unachieved compensation metric | 2025-08-29 | keep, backlog | |
| 17 | negative FCFF exploration | 2025-08-29 | discuss: close or re-scope | |
| 19 | capex + earnings/revenue baseline | 2025-09-09 | keep, current sprint | |
Milestones: propose at Sprint Planning (none exist today).
```

```bash
git add docs/setup/triage-2026-07.md && git commit -m "docs: stale-issue triage sheet for sprint planning" && git push
```

---

### Task 7: Phase 1 Santa gate — one Fable reviewer

**Files:** produces `docs/setup/gate-phase-1.md` in theia-ops.

**Interfaces:**
- Consumes: everything Tasks 1–6 produced.
- Produces: PASS verdict required before the Phase 2 plan is written.

- [ ] **Step 1: Dispatch exactly one Fable reviewer (ecc:santa-method, single-reviewer variant)**

Reviewer brief (adversarial): *"Verify Phase 1 against spec §7 layout, §4 meeting system, §10.1, and Global Constraints. Try to FAIL it: missing dirs, template headings that diverge from spec §4, board fields/automations not actually configured (check live via gh), AGENTS.md >150 lines, placeholders left in board.md/triage sheet, any deleted files, crispy-kedro commit touching more than AGENTS.md. Output: PASS or FAIL with itemized findings."*

- [ ] **Step 2: Fix findings, re-run reviewer until PASS, record verdict**

`docs/setup/gate-phase-1.md`: date, reviewer model (Fable), findings, resolutions, final PASS.

```bash
git add docs/setup/gate-phase-1.md && git commit -m "docs: phase 1 santa gate verdict" && git push
```
Expected: PASS recorded. **Only then** write the Phase 2 plan (pipeline core: extract/reconcile/apply, golden fixtures, TDD).

---

## Self-review (done)

- **Spec coverage:** Phase 1 items of §10.1 all mapped (repo→T1, board→T2, folders+templates→T3, manual→T4, AGENTS.md→T5, triage→T6); gate→T7. Later-phase spec sections intentionally deferred to their own plans.
- **Placeholders:** `<N>`/`<ITEM_ID>` are runtime-discovered GitHub IDs recorded in board.md by design, not plan gaps. No TBDs.
- **Consistency:** template headings in T3 match manual T4 and spec §4; label names (`from-meeting`, `technical`, `research`) consistent across T4/T5/T6.
