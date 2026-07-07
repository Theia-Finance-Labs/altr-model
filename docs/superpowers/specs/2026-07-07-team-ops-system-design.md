# Team-Ops System Design — `theia-ops`

**Date:** 2026-07-07
**Status:** Approved by Jakub (brainstorming session, all 4 sections)
**Home:** This spec starts in crispy-kedro and moves to the `theia-ops` repo once created.

## 1. Purpose

The Theia-Finance-Labs team (6 people: Jakub, Bertrand, Antonio, Max, Soenke, Jakob) repeatedly drops ticket hygiene on GitHub Projects, keeps documentation scattered across Google Docs, local files, and two tangled Dropbox roots, and works in silos coordinated only through Jakub's bilaterals. Evidence: newest crispy-kedro issue activity 2025-09-09, zero milestones, four unowned org boards.

`theia-ops` is an internal product that makes the system maintain itself: every recorded meeting automatically becomes board updates, a team-readable digest, and archived documentation. Humans decide; the pipeline does the bookkeeping.

Starting scope: transaction cost minimizer (crispy-kedro). Designed from day one to expand to all ~30 org repos/projects.

## 2. Decision log (choices made during design)

| Decision | Choice | Alternative rejected |
|---|---|---|
| Ticket tool | Free GitHub (Issues + Projects v2) | Linear ($16/u/mo) — rejected on cost challenge; GitHub covers ~80%, digest ritual covers the notification gap |
| Approach | Full custom product from day one | Staged validate-then-productize — Jakub chose deliberately after contradiction flag |
| Runtime | GitHub Actions (repository_dispatch) | Zapier event source; fully-local pipeline |
| Trigger | Scheduled dispatcher on Jakub's Mac using authenticated Granola MCP | Rationale: Granola records on the Mac anyway, so no added laptop dependency; kills Zapier dependency and payload unknown |
| AI operator | Jakub only for now; team-ready by design | Team-wide Claude Code adoption in v1 |
| Meeting record | One running Google Doc, newest on top | Per-meeting docs; Dropbox markdown; Doc-as-primary-source |
| Repo home | Theia-Finance-Labs org, private | Public; Jakub's personal account |
| Board | One org-wide "Theia Team Board" with Project field | Per-repo boards |
| Sprints | 2-week iterations aligned to odd-Monday check-ins | Weekly |
| Docs rule | Versions with code → repo `docs/`; else → Dropbox tree | Notion (rejected earlier: one-way read-only GitHub sync) |

## 3. Architecture

```
Granola (Jakub records all meetings on his Mac)
   │  note lands in a meeting-type folder
   ▼
Dispatcher (launchd job on Jakub's Mac, scheduled evenings)
   │  headless Claude + Granola MCP: fetch new notes since last run
   │  POST each note → GitHub repository_dispatch (payload: note + folder + note-id)
   ▼
GitHub Actions pipeline (Python package + Claude API)
   ├─→ GitHub Issues + Projects v2 board   (create/update/comment; never close)
   ├─→ Running Google Doc via Docs API     (prepend digest, newest on top)
   └─→ Dropbox project folder              (archive digest markdown in 04_meetings/)
```

Auth: Anthropic API key, Google service account (Doc shared to it), Dropbox app token — all GitHub Actions secrets. Granola auth exists only on the Mac (MCP OAuth), never headless in CI.

Cost: ≈ $15–35/month (Granola Business seat $14 + Anthropic API usage; Actions/Docs/Dropbox free tier).

## 4. Meeting system

Granola folders route extraction; templates (stored in `templates/granola/`, pasted into Granola once) force the note structure the extractor depends on.

| Folder | Cadence | Extraction focus |
|---|---|---|
| `Sprint Planning` | Mondays 1h | Sprint goal, per-person planned tickets, new issues, decisions |
| `Bilaterals` | 5 × 30min/week (Bertrand, Antonio, Max, Soenke, Jakob — each with Jakub) | Per-ticket progress + blockers for that colleague, new actions, decisions |
| `Sprint Check-in` | Odd Mondays 30–45min | Per-person Done/Next/Blocked, sprint health, scope changes |
| `Org Meeting` | Mondays 45min | Only the "project-relevant items" template section; empty → no-op |
| `Research Brainstorm` | Future monthly | Ideas → candidate issues labeled `research`, no auto-assignment |

Team speaking conventions (teachable in one meeting):
- Signposting: "Decision: …", "Action: NAME to X by DATE"; one owner per action.
- Bilateral template contains an "off the record" section; its content is dropped at extraction time and never leaves the API call.

## 5. Extraction

One Claude API call per note, meeting-type-specific prompt, strict JSON schema:

```json
{
  "meeting_type": "bilateral",
  "date": "2026-07-13",
  "attendees": ["Jakub", "Max"],
  "decisions": ["Use merit-order decline on clearing price"],
  "actions": [{"title": "…", "owner": "max", "due": "2026-07-17", "related_issue": 19}],
  "updates": [{"issue_ref": 15, "status_change": "In Progress", "note": "…"}],
  "blockers": ["…"],
  "new_topics": ["…"]
}
```

`pipeline/config/team.yaml` maps spoken names → GitHub handles and registers projects (slug, repo(s), Dropbox path, board Project-field value).

Idempotency: every created issue carries `<!-- granola:<note-id> -->`; the pipeline searches for the marker before writing. Re-running any note produces zero duplicates.

## 6. Outputs

### GitHub
- One org Projects v2 board: **Theia Team Board**. Fields: Status (Todo/In Progress/Blocked/In Review/Done), native Priority, Sprint (2-week iteration), Project (single-select). Saved views: current-sprint Kanban, per-person, per-project roadmap.
- Built-in automations on: auto-add from registered repos, auto-Done on close/merge.
- Pipeline permissions — additive only: creates issues (assigned, labeled `from-meeting`), updates fields/statuses, comments meeting notes onto issues. **Never closes issues**; closures are proposed in the digest.
- Weekly Monday digest (before sprint planning), posted as GitHub Discussion + Doc entry: what moved, stale >14 days, proposed closures, unowned actions, dispatcher heartbeat. The digest is the notification system — sprint planning opens by reading it.

### Google Doc
- One running "Team Meeting Log" Doc; pipeline prepends per-meeting digests (date, type, decisions, actions with issue links, blockers). Comments are human-only territory in v1.

### Dropbox
- Standard tree per project; pipeline writes only `04_meetings/YYYY/`:

```
Projects/<project-slug>/
  00_admin/  01_docs/  02_data/  03_analysis/  04_meetings/  99_archive/
```

- Two existing roots ("2° Investing Dropbox", "Dropbox (2° Investing)") get an audit → mapping doc (old path → new path) → staged migration. Nothing is ever deleted; superseded material goes to `99_archive/`. Canonical-root choice is the first migration decision (flagged, not guessed).
- Placement rule: versions with code → repo `docs/`; everything else → Dropbox tree.

## 7. Repo layout

```
theia-ops/
  AGENTS.md
  pipeline/
    ingest.py  extract.py  reconcile.py  apply_github.py
    publish_gdoc.py  publish_dropbox.py
    prompts/   schemas/   config/team.yaml
  dispatcher/            # launchd plist + script (Mac-side trigger)
  .github/workflows/     # dispatch-run, CI, weekly digest cron
  templates/
    granola/             # 5 meeting templates
    github/              # issue templates + AGENTS.md template for org repos
  docs/
    operating-manual.md  # meetings, ticket conventions, docs placement rule
    dropbox-structure.md # target tree + migration map
    setup/               # secrets, service accounts, colleague onboarding
  tests/                 # golden fixtures: synthetic transcripts → expected JSON
```

## 8. Error handling

- Failed pipeline run → auto-filed issue in `theia-ops` with logs + note ID. Nothing fails silently.
- Extraction schema-validated; one retry; then "needs manual processing" issue with note link.
- Unmapped owner names → digest "unowned actions" section, never dropped.
- Dispatcher heartbeat in weekly digest: meetings happened but nothing processed → flagged.
- Raw notes/transcripts never committed or printed to Actions logs; only extracted structure.

## 9. Testing

- Golden-fixture tests in CI: 3–5 synthetic transcripts per meeting type → expected JSON (pytest).
- `--dry-run` mode prints intended mutations without writing.
- Idempotency regression test: same note twice → zero duplicates.
- Staging: test Doc + dry-run against production board before first live run.

## 10. Rollout

1. **Week 1 — Foundations:** repo, board, Granola folders + templates, operating manual v1, AGENTS.md in crispy-kedro, triage of 6 stale issues into a real sprint.
2. **Week 1–2 — Pipeline core:** extract → reconcile → GitHub writer; golden tests; dry-run.
3. **Week 2 — Wiring:** dispatcher, Doc + Dropbox writers, secrets; first live meeting end-to-end.
4. **Week 3 — Team onboarding:** present at Monday planning; teach speaking conventions; digest ritual starts.
5. **Week 4+ — Dropbox migration + org expansion** (AGENTS.md + board conventions to other repos).

## 11. Success criteria

- Meeting actions land as tickets without manual entry (target: >80% capture measured over 4 weeks).
- Stale-issue count trends down; board reflects reality at each Monday planning.
- Colleagues read/comment the digest (Doc engagement).
- Zero silent pipeline failures.

## 12. Known unknowns & risks

| Unknown | Default | Pivot signal |
|---|---|---|
| Granola MCP note-fetch reliability in headless local runs | Dispatcher uses `claude -p` with authenticated MCP | Auth breaks headless → dispatcher becomes a manual once-a-day command |
| Extraction quality on real (not synthetic) meetings | Templates + signposting make notes extraction-friendly | <80% capture after 2 weeks → tighten templates before touching prompts |
| Team adherence to speaking conventions | One-meeting training + digest visibility | Convention decay → add per-meeting "extraction quality" note to digest |
| Docs API prepend formatting complexity | Structured digest blocks via batchUpdate | Formatting fights back → digest becomes link-index to Dropbox markdown |
| Dropbox canonical root | Decided in migration doc with team | — |

## 13. Out of scope (v1)

- Parsing Google Doc comments back into the pipeline.
- Auto-closing issues; auto-assigning to coding agents (Claude Code GitHub app is a natural later step).
- Non-meeting ingestion (email, Slack).
- Migrating historical meeting notes.
