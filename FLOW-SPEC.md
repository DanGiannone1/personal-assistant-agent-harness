# Flow — Design & Requirements Spec

**Status:** Draft for approval · supersedes the tax-era `MVP-DESIGN.md` / `POC-SUCCESS-CRITERIA.md` / `PITCH-NOTES.md` (those describe the old "Tax Workbench" skin and are now historical).

---

## 1. What this is

**Flow** is the demo application skin for the **agent-harness-accelerator** — a reference implementation showing how to embed an AI assistant *inside* a real web app so it can actually operate the app, not just chat beside it.

The harness is the product. **Flow (a personal productivity app) is disposable dressing** chosen because it is self-evident to any audience and maps cleanly onto the four capabilities we want to prove. The previous skin was a tax tracker; the domain was swapped because tax dragged attention into domain-correctness rabbit holes that are not the point.

### The four capabilities to showcase
1. **Navigation** — the agent moves the user around the app ("take me to today", "open my notes on X").
2. **CRUD** — the agent creates/reads/updates/deletes real records (tasks, calendar events) that persist in app state.
3. **RAG** — the agent does semantic retrieval over a document library and synthesizes grounded answers.
4. **Document ops** — the agent drafts and edits documents in a canvas.

All four are delivered through the **same harness**: GitHub Copilot SDK agent + tools + markdown skills, AG-UI/SSE streaming through an orchestrator proxy, per-user sandbox with a JSON workspace, and a clean responsive two-surface frontend (embedded co-pilot dock + dedicated AI workbench).

---

## 2. Architecture (UNCHANGED — do not rebuild)

```
Frontend (Next.js)        :3000
    ↓ HTTP + SSE
Orchestrator (FastAPI)    :8000   [app.py, session_manager.py]  — never runs the SDK; proxies SSE
    ↓ SSE stream proxy
Session container (FastAPI):8080  [session-container/server.py, agent.py]  — runs the Copilot SDK
    ↓ CopilotClient
Azure OpenAI (gpt-4.1)   + Azure AI Search (RAG only)
```

- **Per-session app state (tasks/events/currentRoute/routes) lives in Azure Cosmos DB** — one document per session, keyed by session id, AAD-only (`DefaultAzureCredential`; no key). The agent's tools mutate it and `/app/state` reads from it, so the verifiable-execution invariant holds against Cosmos.
- **Documents/files live in the per-session workspace folder** (→ ACA Sandbox in production). Uploads and agent-drafted artifacts stay on the filesystem, separate from the structured store.
- Authoritative architecture reference: `.claude/commands/architecture/*`. This reskin changes **entities, screens, theme** — not topology.

### Production runtime & storage (target — not built in this POC)

The per-user sandbox in production is an **Azure Container Apps Sandbox** (`Microsoft.App/SandboxGroups`, public preview) — a per-user **microVM**, hardware-isolated from the host/platform/other sandboxes, started from an OCI image in <1s, **no cost when idle**, with **snapshot-based suspend/resume** that preserves the sandbox's memory + disk state across a session pause. (This is the newer ACA *Sandboxes* primitive, **not** the older ACA *Dynamic Sessions* pool.)

Storage split at that point:
- **Structured CRUD entities** (tasks, events) → a managed database (**Azure Cosmos DB**) as the queryable system of record; `/app/state` reads from it and the agent's tools mutate it (the same verifiable-execution invariant carries over — the agent mutates the exact store the UI renders from).
- **Documents / artifacts** → the sandbox working set (persisted via snapshot suspend/resume), with durable long-term copies in **Blob/ADLS** for anything that must outlive the sandbox.

Status: **Cosmos is now wired** for app state (above). The ACA Sandbox runtime and durable Blob/ADLS document storage remain forward-looking; documents currently live in the local per-session workspace folder.

---

## 3. Surfaces (5 nav destinations)

| # | Nav label | Route | What it shows |
|---|---|---|---|
| 1 | **Home** | `/home` | Today's agenda: what's due today, overdue count, next events, quick stats |
| 2 | **To-Do** | `/todo` | Tasks grouped by bucket, with status pills + priority |
| 3 | **Calendar** | `/calendar` | Agenda-by-day view merging events + tasks with due dates |
| 4 | **Documents** | `/documents` | Document library (seeded + uploaded) and AI-generated drafts, separated |
| 5 | **AI Workbench** | `/assistant` | The dedicated assistant workspace (chat spine + artifact canvas), promoted to first-class nav |

The assistant is **also** always present as a docked co-pilot on the host surfaces (`/home`, `/todo`, `/calendar`, `/documents`). "AI Workbench" is the full-screen version of the same continuous session.

---

## 4. Data model

Replaces the single `filings[]` model. New workspace shape (`session-container/appdb.py`, renamed from `taxdb.py`):

```jsonc
{
  "currentRoute": "/home",
  "tasks": [
    {
      "id": "t-1",
      "title": "Draft Q3 planning doc",
      "status": "In progress",        // To do | In progress | Blocked | Done
      "priority": "High",             // Low | Medium | High
      "group": "Work",                // free-form bucket (Work, Personal, …)
      "dueDate": "2026-06-25",        // YYYY-MM-DD, optional
      "subtasks": [ { "text": "outline", "done": true } ],
      "notes": "…",                   // optional
      "createdAt": "2026-06-20T…"
    }
  ],
  "events": [
    {
      "id": "e-1",
      "title": "Team standup",
      "date": "2026-06-24",
      "start": "10:00",               // 24h, optional
      "end": "10:30",                 // optional
      "type": "Meeting",              // Meeting | Reminder | Focus | …
      "notes": "…"
    }
  ],
  "routes": [ { "path": "/home", "title": "Home", "keywords": ["home","today","overview"] } ]
}
```

**Decision (confirm):** two entities — `tasks` AND `events`. Rationale: a distinct `events` type makes "schedule a 3pm meeting tomorrow" a genuinely different CRUD demo from "add a task," and gives the Calendar real content. Lean alternative: drop `events`, plot task due-dates on the calendar.

Storage/helpers carry over verbatim from `taxdb.py`: atomic `save()` (tmp + `os.replace`), fail-loud `load()`, thread lock, `new_id()`, plus reworked `resolve_destination()` (route + task/event matching) and `is_overdue()`.

---

## 5. Agent tools (`session-container/agent.py`)

Same `define_tool` patterns and outcome classification ("ok"/"noop"/"error") as today.

| Tool | Status | Purpose |
|---|---|---|
| `navigate(destination)` | keep | Deterministic route/entity resolver → resolved / ambiguous / not_found |
| `list_tasks()` | rename (was `list_filings`) | Review all tasks with status/priority/due/overdue |
| `create_task(title, status?, priority?, group?, due_date?)` | rename | Add a task |
| `update_task(task, status?, priority?, group?, due_date?)` | rename | Modify a task |
| `add_subtask(task, text)` | rename (was `add_checklist_item`) | Add a subtask |
| `list_events()` | **new** | Review calendar events |
| `create_event(title, date, start?, end?, type?)` | **new** | Add a calendar event |
| `update_event(event, …)` | **new** | Modify/move an event |
| `list_documents()` | keep | Discover documents |
| `read_workspace_file(path?)` | keep | Read a document |
| `write_file(path, content)` | keep | Draft/edit an artifact |
| `search_documents(query)` | **new (Phase 3, RAG)** | Semantic search over the indexed library → passages + sources |

SYSTEM_PROMPT rewritten for the Flow domain (keep the verbatim-navigate rule, AMBIGUOUS/NOT_FOUND honesty, "only claim what a tool returned," `[Today]`/current-view context injection, scope nudge).

---

## 6. Skills (`session-container/skills/`)

Markdown skills, SDK `{name}/SKILL.md` format.

- **`tasks`** (rename of `filings`) — create/update/review tasks + subtasks; use the `overdue` flag, never judge dates.
- **`calendar`** (**new**) — create/move events; agenda reasoning.
- **`documents`** (keep) — discover → read → answer strictly from what was read; draft as markdown artifacts.
- **`research`** (**new, Phase 3**) — when to call `search_documents`, how to ground an answer in retrieved passages and cite sources.

---

## 7. RAG (Phase 3 — the only net-new infra)

The current app has **no retrieval wired** (verified). Plan:
- Seed a small markdown **document library** (~10–12 realistic docs: meeting notes, a project brief, references) under `session-container/seed_docs/`.
- Index it into a **fresh Azure AI Search index** using the embeddings model the architecture already references (`text-embedding-3-small`).
- Add `search_documents(query)` tool + the `research` skill.

**Honest constraint (fail-loud):** RAG requires Azure AI Search reachable + configured via env vars. The nav/CRUD/document-ops demo runs fully offline; **RAG is the one feature with a hard Azure dependency.** If Search is not configured, `search_documents` must fail loud (clear "search not configured" error), never silently return nothing.

---

## 8. Visual design — Monday.com-style light theme

Single-file recolor in `frontend/src/app/globals.css` (`:root` vars + `@theme inline`; ~15 hardcoded hex spots to audit). Converts the current **dark terracotta glass** theme to a **light, lively** one.

| Token | Value | Use |
|---|---|---|
| canvas `--app-bg` | `#f6f7fb` | app background |
| `--surface-1` | `#ffffff` | cards, panels |
| `--surface-2` | `#f0f1f5` | hover/secondary |
| `--border-subtle` | `#e6e9ef` | borders/dividers |
| `--text-primary` | `#323338` | main text |
| `--text-secondary` | `#676879` | secondary |
| `--text-muted` | `#9699a6` | labels/hints |
| `--brand-primary` | `#0073ea` | primary action (blue) |
| `--brand-accent` | `#6c6cff` | AI/agent accent (purple) |
| status: Done | `#00c875` | green pill |
| status: In progress | `#fdab3d` | orange pill |
| status: Blocked / overdue | `#e2445c` | red pill |
| status: To do | `#c4c4c4` | gray pill |

- Remove the dark ambient orbs (or replace with very faint light-color blobs).
- User message bubble → blue/purple gradient; assistant bubble → light gray card.
- Goal: reads as a credible, familiar productivity app (Monday/Linear family), not a neon redesign.

---

## 9. Frontend work

- `WorkbenchNav.tsx` → 5 items (Home · To-Do · Calendar · Documents · AI Workbench).
- `WorkbenchApp.tsx` `RouteContent` → Home / To-Do / Calendar (agenda) / Documents renderers.
- `lib/types.ts` → `AppState { currentRoute, tasks[], events[], routes[] }` + `Task`, `Event` interfaces (replace `TWFiling`).
- Reducer route-setting tool set updated to the new mutating tools (`create_task`, `update_task`, `add_subtask`, `create_event`, `update_event`, `navigate`).
- Keep the responsive behavior (dock collapse < ~1100px, workspace nav-rail hide) and the "[Today] / [Current view]" prompt-context injection.

---

## 10. Sequencing (one commit per phase)

0. **Push clean baseline** to the recreated empty GitHub repo (backup before changes).
1. **Backend reskin** — `appdb.py` model, tools, skills, routes, system prompt. (no UI yet)
2. **Frontend reskin + Monday recolor** — screens + theme + types + nav.
3. **RAG** — seed library, AI Search index, `search_documents`, `research` skill.
4. **Playwright validation** — walk every journey with screenshots (per CLAUDE.md), fix issues.

---

## 11. Success criteria

Validated **only** via Playwright against the real frontend, as a real user, with screenshots at each step (per CLAUDE.md). Each journey must work end-to-end:

1. **Navigation** — "take me to my calendar" / "open the project brief" routes the app correctly in one `navigate` call; ambiguous → candidate chips; unknown → fail-loud refuse, no wrong nav.
2. **Task CRUD** — "add a high-priority task 'X' due Friday in Work" creates a visible row with correct fields; "mark it in progress" updates it; state survives a refetch (lives in workspace state, not just chat).
3. **Event CRUD** — "schedule a 3pm meeting tomorrow" creates a calendar event visible on the agenda; "move it to Thursday" updates it.
4. **Document ops** — "draft a project kickoff doc and save it" produces a markdown artifact in the canvas + Documents; "tighten the intro" edits it.
5. **RAG** — "what did I decide about X in my notes?" returns a grounded answer with sources from the indexed library (when Search configured).
6. **Verifiable execution** — the right pane renders **only** from `/app/state`; the agent claims an action only after the tool returned success; tool failures surface (fail loud).
7. **Feel** — runs on `python dev.py` locally end-to-end; light Monday theme reads clean; assistant step-trace looks polished; New Session reseeds clean state.

---

## 12. Non-goals / guardrails

- No real auth, no database, no multi-user — per-session sandbox only.
- **Public repo hygiene:** never commit real personal data or any client/vendor branding. Seed data is synthetic-but-realistic. Demo on real data only via gitignored local content. (See memory: pre-push-scrub.)
- No new architectural abstractions — reskin within the existing harness (Simplify First).
- Tax domain fully removed.

---

## 13. Open decisions (confirm before/while building)

1. **Two entities (`tasks` + `events`) vs. one** — spec assumes two. ✅ recommended.
2. **RAG timing** — spec sequences it as Phase 3 (after the shell works). ✅ recommended.
3. **Full light theme** vs. dark-with-accents — spec assumes full light. ✅ recommended.
4. **Delete** — full "CRUD" implies it, but the tool list has no `delete_task`/`delete_event`. Add delete (recommended — cheap, completes the story) or scope CRUD to create/read/update?
5. **RAG verification reachability** — proving §14.G end-to-end needs live Azure AI Search. Is it reachable in dev, or is RAG marked **unverified** until the resource is wired?

---

## 14. Verification & Evidence (definition of done)

**Standard of proof.** Per CLAUDE.md, the only valid test is Playwright driving the real frontend as a human, with screenshots examined — not "it compiles," not API-only checks. Every claim must show three things together: (1) the user can **see** it (rendered-UI screenshot), (2) it is **real** — the right pane renders only from `/app/state`, so a `/app/state` dump must contain the record (the *same-fact* check vs. the chat claim), and (3) it **survives** a refetch/refresh.

**Evidence package** (committed to `review/<date>/`): a traceability matrix `FINDINGS.md` mapping every item below → its evidence file → pass/fail; numbered per-journey screenshots (each examined, not assumed); `/app/state` JSON dumps before/after mutations; the Playwright scripts; and a one-command runner (`npm test`) so a reviewer reproduces it.

### A. Baseline / it runs
- [ ] **Stack boots clean** — `python dev.py` brings up 3000/8000/8080. *See:* all three return 200; no tracebacks.
- [ ] **Fresh session seeds** — new session creates `.flowdb.json` with seed tasks/events. *See:* Home screenshot with seed data.
- [ ] **New Session resets** — reseeds clean state. *See:* before/after screenshots; state dump returns to seed.

### B. Surfaces render (all 5)
- [ ] **Home `/home`** — agenda, overdue count, next events. *See:* screenshot matching seed state.
- [ ] **To-Do `/todo`** — tasks grouped, status pills + priority. *See:* screenshot; pill colors match status.
- [ ] **Calendar `/calendar`** — agenda-by-day, events + due tasks merged. *See:* screenshot with a seeded event and a due task on correct days.
- [ ] **Documents `/documents`** — seeded library + generated drafts in separate groups. *See:* screenshot; no `.flowdb.json` leaking as a doc.
- [ ] **AI Workbench `/assistant`** — chat spine + artifact canvas, same session as the dock. *See:* screenshot.

### C. Navigation (capability 1)
- [ ] **Agent navigation** — "take me to my calendar" routes there. *See:* screenshot + tool-trace showing **one** `navigate` call.
- [ ] **Entity navigation** — "open the project brief" / "show task X" lands on the item. *See:* screenshot.
- [ ] **Re-navigation in one session** — navigate away and back repeatedly (old bug). *See:* screenshots of 2+ round trips.
- [ ] **Client quick-nav** — sidebar clicks instant, no agent turn. *See:* screenshot + no SSE/agent call fired.

### D. Task CRUD (capability 2)
- [ ] **Create** — "add a high-priority task 'X' due Friday in Work". *See:* rendered row **+ `/app/state` dump** with correct fields.
- [ ] **Update status** — "mark it in progress". *See:* pill turns orange + state dump.
- [ ] **Update fields** — reassign group/priority/due. *See:* screenshot + state dump.
- [ ] **Subtask** — "add a subtask 'outline'". *See:* subtask appears + state dump.
- [ ] **Delete** — (pending §13.4 decision) row removed + state dump.

### E. Event CRUD (capability 2)
- [ ] **Create event** — "schedule a 3pm meeting tomorrow". *See:* event on agenda for correct day/time + state dump.
- [ ] **Move event** — "move it to Thursday". *See:* moved on agenda + state dump.

### F. Document ops (capability 3)
- [ ] **Draft** — "draft a project kickoff doc and save it". *See:* artifact in canvas **and** Documents; file in workspace.
- [ ] **Edit** — "tighten the intro". *See:* before/after content; change visible in canvas.
- [ ] **Read/summarize uploaded** — upload a file → "summarize this". *See:* grounded summary referencing real content.

### G. RAG (capability 4)
- [ ] **Grounded answer** — "what did I decide about X in my notes?". *See:* answer **with sources** + tool-trace showing `search_documents`.
- [ ] **Fail-loud when Search unconfigured** — *See:* clear "search not configured" error, **never** a silent/made-up answer.
- [ ] **Honesty marker** — if live Azure Search can't be exercised, this row is marked **UNVERIFIED**, not faked.

### H. Verifiable execution (anti-hallucination)
- [ ] **Pane renders only from `/app/state`** — never optimistically from tool args. *See:* claim and state dump agree.
- [ ] **No claim without success** — *See:* a forced failure where the agent does **not** claim success.
- [ ] **Persistence** — refresh after a mutation. *See:* before/after-refresh screenshots; record persists.

### I. Fail-loud / negative paths
- [ ] **Unknown destination** — honest refuse + candidate chips, no wrong nav. *See:* screenshot.
- [ ] **Ambiguous nav** — disambiguation, one `navigate` call. *See:* screenshot.
- [ ] **Corrupt/missing state** — clear error, no silent fallback. *See:* induced-error screenshot.
- [ ] **Cancel mid-stream** — stop halts cleanly, no partial-state corruption. *See:* screenshot + state intact.

### J. Visual / theme (Monday light)
- [ ] **Light theme applied** — white canvas, dark text, colored pills; dark orbs gone. *See:* screenshots of all 5 surfaces.
- [ ] **Status colors correct** — Done green / In progress orange / Blocked red / To-do gray. *See:* To-Do screenshot.
- [ ] **No leftover terracotta/dark** — *See:* grep for old hexes returns none + visual scan.
- [ ] **Responsive** — dock collapses < ~1100px; workspace nav-rail hides. *See:* narrow-viewport screenshots.

### K. Architecture integrity
- [ ] **Orchestrator never runs the SDK** — still a pure SSE proxy. *See:* code unchanged + a streamed run through it.
- [ ] **AG-UI events intact** — TOOL_CALL_START/END, TEXT_MESSAGE_CONTENT, RUN_FINISHED. *See:* event log from a real turn.
- [ ] **Tax fully removed** — *See:* grep for `filing`/`tax`/`taxdb` returns none in shipped code.

### L. Reproducibility & honesty
- [ ] **One-command rerun** — `npm test` runs all journeys headlessly. *See:* runner output + committed `review/<date>/` screenshots.
- [ ] **Traceability matrix** — `review/<date>/FINDINGS.md` maps every item → evidence file → pass/fail.
- [ ] **Limitations section** — explicit list of anything unverified/out-of-scope (RAG infra, delete decision, etc.).

### M. Adversarial / critique subagent reviewers (Phase 4)

**Ground rules (every reviewer):**
- [ ] Each finding cites a **concrete artifact** (screenshot, `/app/state` dump, file:line, event log) — no vibes.
- [ ] Each finding is tagged **blocking / major / minor** with **repro steps**.
- [ ] Findings are **adversarially verified before counting** — a separate pass tries to refute each; unconfirmed findings drop.
- [ ] Reviews judge **capabilities / UX / integration**, *not* productivity-domain trivia.
- [ ] **No overstated verdicts** ("beats X") — per-criterion pass/fail + findings list only.
- [ ] Plain language; a jargon-dense review is itself a finding.

**Reviewer panel (distinct lenses, parallel):**
- [ ] **Skeptical end-user (UX)** — does it get me to my goal fast and pleasantly? *See:* findings on confusing flows, dead ends, perceived latency, ugly/empty states, with screenshots.
- [ ] **Hallucination / trust auditor** — tries to make the agent claim work it didn't do; checks pane-vs-`/app/state` every action; off-script asks. *See:* attempts + outcomes; any claim/state divergence is **blocking**.
- [ ] **Break-it tester** — out-of-order responses, cancel mid-stream, re-navigation, ambiguous/empty/garbage input, rapid repeats, injection-y prompts. *See:* each attack + fail-loud vs. corruption.
- [ ] **Integration / architecture reviewer** — Copilot SDK + AG-UI used cleanly; orchestrator still a pure proxy; event protocol intact; fail-loud; matches `.claude/commands/architecture/*`. *See:* code citations + a real turn's event log.
- [ ] **Visual / design critic** — Monday.com fidelity, consistency, responsive, polish vs. neon. *See:* annotated screenshots of all 5 surfaces + narrow viewport.
- [ ] **Capabilities reviewer (the real bar)** — beyond scripted prompts: composes tools for novel asks ("what's overdue and move it to next week", "summarize my notes then make a task"). *See:* unscripted-ask battery + transcripts.
- [ ] **Demo-readiness reviewer** — would a customer leaving a slow LangGraph stack be impressed? Where would a live demo embarrass us? *See:* ranked demo-risk list.

**Synthesis & convergence gate:**
- [ ] **Synthesizer** dedups across reviewers, ranks by severity, drops refuted findings → one merged `FINDINGS.md`.
- [ ] **Fix loop** — every blocking/major fixed and **re-verified** with a fresh screenshot/state dump (not just "addressed").
- [ ] **Exit criterion** — iterate review→fix until a round yields **zero new blocking/major** (loop-until-dry), capped to converge. *See:* per-round counts trending to zero.
- [ ] **Honest residual** — surviving minors / won't-fix listed explicitly in the limitations section.

> Execution note: §14.M runs as a **structured Workflow** (parallel reviewers → adversarial verify → synthesize → fix loop) with structured findings, not an ad-hoc swarm. It is a **billable multi-agent fan-out** launched only on explicit go for the review phase.
