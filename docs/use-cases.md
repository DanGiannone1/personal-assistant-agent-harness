# Core Use Cases

The concrete things Personal Assistant does, and how to drive each one. Every example is a real
journey you can run against the live app at <http://localhost:3000> (see
[development.md](development.md) to start the stack). Each capability has both a **manual** path (the
app stands on its own) and an **assistant** path (the agent does it for you through tools) — the AI
is an efficiency layer, not a dependency.

A cross-cutting invariant holds throughout: the app pane renders **only** from
`GET /sessions/{id}/app/state`, and the agent's tools mutate that same store — so the assistant can
only claim work a tool actually performed, and you watch the app change as it acts.

---

## 1. Navigation

Move around the app by asking, instead of clicking the rail.

| | |
|---|---|
| **Manual** | Click any item in the left nav (Home, To-Do, Calendar, Documents, Reminders, AI Workbench). |
| **Assistant** | *"take me to my calendar"*, *"open the Q2 budget doc"*, *"go to reminders"* |

Resolution is **deterministic** (no LLM routing) — the `navigate` tool matches your words against the
`routes[]` table plus task/event titles and returns exactly one of:
- **resolved** → the pane moves there;
- **ambiguous** → the agent lists the candidates and asks which one;
- **not-found** → an honest "I couldn't find that" with the closest options (it never navigates to the wrong place).

---

## 2. Task & event CRUD

Create, update, and delete real records that persist in app state and survive a refetch / new tab.

**Tasks** (`/todo`):
> *"Add a high-priority task 'Draft Q3 plan' due Friday in the Work group."*
> *"Mark the Q3 plan task in progress and add a subtask 'gather figures'."*
> *"What's overdue?"* — the agent reads the computed `overdue` flag; it never judges dates itself.
> *"Delete the Q3 plan task."*

**Events** (`/calendar`):
> *"Schedule a 3pm team sync tomorrow."*
> *"Move the design review to Thursday at 10."*

The Calendar view merges events with task **due-dates** into one agenda-by-day, so a task due
Thursday shows alongside Thursday's meetings.

> **Note:** today CRUD is assistant-driven; click-to-add / inline edit (the manual path for tasks,
> events, and reminders) is the next planned increment.

---

## 3. Document drafting

The agent writes and edits markdown documents that open in an artifact canvas.

> *"Draft a project kickoff brief and save it as kickoff.md."*
> *"Add a risks section to the kickoff brief."*

The draft appears under **Documents → Generated this session** and renders live in the canvas (with an
"AI-generated draft · unreviewed" banner). Generated drafts are **session files** — ephemeral — until
you promote one to the Library (§5).

---

## 4. RAG — retrieve over the document Library

Ask questions grounded in your persistent document **Library** (a searchable knowledge base,
pre-loaded with reference docs).

> *"What did we decide about the budget?"*
> *"Search my library for the standard NDA term."*

The `search_documents` tool runs a semantic query against Azure AI Search and the agent answers
**only** from the returned passages, **citing the source filename(s)**. It fails loud rather than
guessing: `NO_RESULTS` (nothing matched), `SEARCH_NOT_CONFIGURED` / `SEARCH_FAILED` (Search
unavailable). See [retrieval.md](retrieval.md) for the index and pipeline.

---

## 5. Save to Library — persistent KB vs ephemeral session files

This is the two-tier document model, and the headline demo. **Session files** (uploads + drafts) are
temporary and read directly; the **Library** is persistent and *retrieved* (RAG). An explicit
**Save to Library** promotes a session file into the knowledge base.

**The flow:**
1. **Upload** a document — Documents → *Uploaded this session* → **Upload** button (manual, no AI).
   A PDF is converted to markdown via Azure Content Understanding.
2. It appears as a **session file** with a **Save to Library** button.
3. Click **Save to Library** (manual) — or say *"save this to my library"* (assistant). The file is
   chunked, indexed in Azure AI Search, and moves into the **Library** group.
4. **It now persists across sessions and is searchable.** Open a brand-new session → the doc is still
   in your Library, and *"search my library for …"* retrieves its content.

**Compare/contrast (both tiers at once):** upload a contract as a *session file* (don't save it), then:
> *"Compare this vendor contract's confidentiality term against my standard NDA in the library."*

The agent **reads the session file directly** and **RAG-searches the Library**, then contrasts them
with grounded citations — exactly the "client's session files vs. the firm's persistent knowledge
base" pattern, in a productivity app.

---

## 6. Scheduled reminders

Save a recurring instruction the app runs on its own and emails you the result.

> *"Email me a daily summary of what's due in the next 3 days at 8am Eastern."*
> *"Every Monday and Friday at 7:30, send me my open tasks."*
> *"What reminders do I have?"* / *"Delete my daily reminder."*

`create_schedule` stores the natural-language prompt with a cadence (`daily`/`weekly` + time +
timezone). On the **Reminders** screen you see each reminder's cadence, next run, last run, and
status. On schedule, the orchestrator runs the saved prompt as a headless agent turn and emails the
output via Azure Communication Services (at-most-once delivery; fails loud on the reminder's status
if it can't run). Locally a 60-second loop drives it; in production an ACA Job on a cron does.

---

## 7. Reporting (proposed)

> **Status: proposed (I13) — not yet built.** Unlike §1–§6, this is a scope proposal, not a runnable
> journey yet. See [spec.md → Reporting (proposed)](spec.md#reporting-proposed).

Ask the agent to compose your own data into a report — a cited markdown artifact you can read, edit,
save, or have emailed on a schedule.

| | |
|---|---|
| **Manual** | *(deferred)* — a dedicated **Reports** screen with saved report history is a later increment. |
| **Assistant** | *"Generate a weekly status report."*, *"Summarize what's overdue."*, *"Give me a digest of this week's tasks and meetings."* |

The `generate_report` tool composes tasks + events (and, optionally, cited **Library** passages) over
a day/week window into a markdown report that opens in the artifact canvas and appears under
**Documents → Generated this session**. Every figure is pulled from the tools — the agent never does
its own arithmetic — and it fails loud (`NO_REPORT_DATA`) rather than inventing content when nothing
falls in the window.

**Persist it:** a report is a session file, so *"save this report to my library"* promotes it into the
persistent Library (§5) — no new machinery.

**Schedule it:** pair Reporting with §6 — *"Email me a weekly status report every Monday at 8am"* — and
the reminder runs the report on a cadence and emails it.

> **Note:** Reporting is assistant-driven in v1 (one `generate_report` tool + a `reporting` skill). The
> manual **Reports** surface, Deep Agents parity, multiple report types, and PDF export are deferred
> increments.

---

## Trying it end to end

A single session that exercises everything:

1. *"Add a high-priority task to review the Q3 budget by Friday."* → To-Do updates.
2. *"Schedule a budget review meeting Thursday at 2pm."* → Calendar updates; appears with the task's Friday due-date.
3. Upload a budget PDF → **Save to Library**.
4. *"Search my library — what's our Q2 budget summary?"* → cited answer from the Library.
5. *"Email me a daily agenda summary at 8am."* → a reminder appears on the Reminders screen.

Each step visibly changes the app, and every claim the assistant makes is backed by a tool that
actually ran — verifiable against `/app/state` and the `logs/trace.jsonl` trace.
