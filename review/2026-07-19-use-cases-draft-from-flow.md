> **Provenance:** scenario catalog drafted 2026-07-17/19 in the flow clone against the pre-pivot docs; statuses are stale relative to this repo (Engagements, auth, parity are shipped here). Re-baseline before adopting into docs/use-cases.md.

# Core Use Cases

The canonical scenario set for the product. It serves two purposes at once:

1. **A real tool for CSA Engagement work.** Every scenario below is something a cloud solution
   architect actually does: prepare for customer calls, capture what happened in them, track
   actions and risks across Engagements, work with documents, and report status.
2. **A live reference architecture.** Each scenario demonstrates a reusable pattern — the same
   pattern an enterprise team (for example, a customer building its own agent) applies to its own domain. The
   capability layer is domain-agnostic; our CSA nouns are the first plugged-in domain, not the
   skeleton. See the [teach-through map](#teach-through-map).

This list is the acceptance bar: the build, the demo script, and client teaching material should
all test against these same scenarios.

## How to read a scenario

Each scenario carries a **capability signature** using six letters:

| Letter | Capability | Reference |
|---|---|---|
| **C** | Context — what the turn already knows (user, Engagement, screen, selection, memory) | [context-reference-architecture.md](context-reference-architecture.md) |
| **N** | Navigation — moving the user to a destination | [navigation-reference-architecture.md](navigation-reference-architecture.md) |
| **Q** | Record query — reading live records to act on them | [crud-reference-architecture.md](crud-reference-architecture.md) |
| **W** | Record write — create/update/delete; risky or bulk changes behind preview-and-confirm | [crud-reference-architecture.md](crud-reference-architecture.md) |
| **D** | Doc AI — the workspace: read, compare, extract, generate documents | [retrieval.md](retrieval.md) |
| **R** | Retrieval — content search over the indexed Library, with citations | [retrieval.md](retrieval.md) |

And a **status**: **Today** (runs in the live app — see [development.md](development.md) to start
it), **Partial** (the core runs; Engagement scoping or a richer step is pending), or **Target**
(designed, not yet built). Statuses reflect the default (Copilot) harness;
[harnesses.md](harnesses.md) tracks the Deep Agents parity gap.

A cross-cutting invariant holds throughout: the app pane renders **only** from
`GET /sessions/{id}/app/state`, the store the tools actually mutate — so the assistant can only
claim work a tool performed, and you watch the app change as it acts.

---

## Orient and capture

### 1. Orient — "what needs my attention?" `C+Q+N` — Partial

> *"take me to my calendar"* · *"what's overdue?"* · *"open the Fabrikam Engagement"*

Navigation resolves deterministically today (no LLM routing): **resolved** moves the pane,
**ambiguous** lists candidates, **not-found** answers honestly and stays put. "What's overdue"
reads the computed `overdue` flag — the agent never judges dates itself. Target adds personalized
quick links and salience ("2 overdue actions") ranked from working context.

### 2. Quick capture — log it from anywhere `C+W` — Partial

> *"Customer asked for a private-endpoint cost estimate — log it as a high-priority action, due
> Friday."*

No navigation, no form. Context supplies the Engagement scope; the backend validates and commits;
the app opens the new record. Task/event CRUD runs today against personal scope and is
assistant-driven (manual click-to-add / inline edit is a planned increment); Engagement scoping
and post-commit navigation are the target.

### 3. Capture from a call — transcript in, records out `D→W` — Target

> *"Here's the transcript from today's call — summarize it, pull out the action items, decisions,
> and any new risks, and log them against this Engagement."*

The highest-value CSA scenario: every customer call produces this chore. Expected behavior: the
transcript is converted and read in the workspace; extracted items land in **one batched preview**
("6 actions, 2 risks, 1 milestone update — save?"); one confirmation commits through the same
write path chat uses. *Teaches: doc-to-records; many front doors, one write path.*

---

## Work the records

### 4. Ask the records `C+Q` — Partial

> *"Show open high-priority actions due this month."* · *"Which tasks mention state filings?"*

Today the agent fetches the records and reasons over them in context. Target: filterable
conditions map to a real query; fuzzy ones ("mention state filings") fall back to
fetch-and-reason — the tiered query — and counts come back before bulk actions so previews can
say "this affects 14 records."

### 5. Gap-fill — bulk write from a computed difference `Q→W` — Target

> *"Create a follow-up action for every Engagement that hasn't had a status update this month."*

Query Engagements, subtract the ones with recent updates, bulk-create behind one preview ("this
creates 5 actions"), commit, report. No grid filter can express "missing" — this is the shape
that justifies query-then-act. *Teaches: cross-domain query → bulk write (client equivalent in
the [teach-through map](#teach-through-map)).*

---

## Work the documents

### 6. Draft a document `D` — Today

> *"Draft a project kickoff brief and save it as kickoff.md."* · *"Add a risks section."*

The draft appears under **Documents → Generated this session** and renders in the artifact canvas
with an "AI-generated draft · unreviewed" banner. Drafts are ephemeral session files until
promoted to the Library.

### 7. Ask the corpus `R` — Today

> *"What did we decide about the budget?"* · *"Where did we land on the Cosmos security posture?"*

`search_documents` runs a semantic query against the Library index; the agent answers **only**
from returned passages and **cites the source filename(s)**. It fails loud rather than guessing:
`NO_RESULTS`, `SEARCH_NOT_CONFIGURED`, `SEARCH_FAILED`. Target: citations resolve to openable
references, not just filenames.

### 8. Session file vs. Library — the two-tier model `D+R` — Today

**Session files** (uploads + drafts) are temporary and read directly; the **Library** is
persistent and retrieved. An explicit **Save to Library** (button or *"save this to my library"*)
chunks and indexes the file; it then survives new sessions and is searchable. The compare demo
exercises both tiers at once:

> *"Compare this vendor contract's confidentiality term against my standard NDA in the library."*

The agent reads the session file directly, retrieves from the Library, and contrasts them with
citations. *Teaches: workspace (free, disposable) vs. system of record (indexed, persistent) —
the store/workbench split.*

### 9. Compare and cover `Q/R→D` — Target

> *"Compare the customer's RFP against our HLD — which requirements aren't covered?"*
> *"How does this SOW differ from the one we did for them last year?"*

Find both documents (metadata query or content search — possibly in another Engagement), pull
copies into the workspace, produce a structured comparison. *Teaches: cross-scope reads are
normal, not an edge case.*

---

## Records ↔ corpus crossovers

### 10. Corpus-to-records `R×Q→W` — Target

> *"The June transcript mentions two risks we never logged — add them."*
> *"Does the risk register cover everything raised in last week's steering meeting?"*

Retrieval finds the content; a record query fetches the register; the agent diffs the two and
proposes writes behind a preview. Only works if citations and record IDs live in **one reference
system** — the scenario that proves (or breaks) it. *Teaches: retrieval joined to records — the
pattern the client's design has not yet solved.*

### 11. Rollup — records to document `Q→D` — Target

> *"Draft my weekly status across all Engagements."*

Query everything active, generate the summary in the user's saved format (persona and
conventions from context), offer the download. The scheduled variant is scenario 13.

---

## Composites

### 12. Prep me — the flagship `C→Q+R→D→N` — Target

> *"Prep me for tomorrow's Fabrikam call."*

Context picks the Engagement; query pulls open actions, risks, and milestones; retrieval pulls
what the last two transcripts said; doc AI generates a one-page brief; the app opens it. The
demo that shows composition nobody explicitly designed.

### 13. Proactive — the app works while you don't `schedule→Q→D` — Partial

> *"Every Friday at 7:30, email me my open actions by Engagement."*

`create_schedule` stores the natural-language prompt with cadence, time, and timezone; the
**Reminders** screen shows cadence, next/last run, and status. On schedule, the orchestrator runs
the prompt as a headless agent turn and emails the result (at-most-once; fails loud on the
reminder's status). Locally a 60-second loop drives it; in production an ACA Job on a cron does.
Runs today for simple prompts; the rollup-quality output is target.

### 14. Close-out — one narrated preview, several writes `W+D` — Target

> *"Log today's meeting: mark the POC milestone done, add the identity risk we found, and draft
> the recap email."*

Multiple writes across record types plus a generated document, gated by **one composite preview**
that narrates the whole plan — not a separate confirmation per step.

---

## Pipeline shapes and the rules they force

Every scenario above is an instance of one loop — **find → ground → preview → act → show** — and
the catalog forces five design rules:

1. **One write path, one preview.** Chat, transcripts, spreadsheets, and query results are
   different front doors to the same validated, previewed, confirmed write (3, 5, 10, 14).
2. **One reference system.** Query results, citations, extractions, UI selections, and
   destinations must all yield IDs every other capability accepts (10, 12).
3. **Three finders, two showers.** Find by field (Q), by meaning (R), or by place (N); show as a
   chat answer/artifact or as a view. Any new feature should name its finders and showers.
4. **Composite previews.** Multi-write scenarios need one narrated approval, not a gauntlet (14).
5. **Read breadth exceeds write scope.** Cross-Engagement reads are everyday (9); writes stay
   scoped and gated.

Navigation's real positions: a **scope-setter** ("switch to Website Launch" sets context for
later turns), a **deliverable** ("show me the overdue tasks" can answer with the filtered view),
and a **terminal step** (after commit, land on the record). If a design requires
"navigate, then act," context is underpowered.

## Teach-through map

How each of our scenarios teaches a pattern the client applies to their own domain:

| Our scenario | Client equivalent | Pattern taught |
|---|---|---|
| 3 — Capture from a call | PDF → workplan tasks / info requests | Doc-to-records; one write path, batched preview |
| 5 — Gap-fill | Trial-balance requests for missing entities | Cross-domain query → bulk write |
| 8 — Two-tier documents | Chat files vs. DM store | Workspace vs. system of record |
| 9 — Compare and cover | Engagement letters year-over-year | Workspace compare; cross-scope read |
| 10 — Corpus-to-records | (unsolved in their design) | Retrieval joined to records |
| 11/13 — Rollup + proactive | Status reporting | Records-to-doc; proactive agent |
| 12 — Prep me | Steering-meeting prep | Full-stack composition |
| 2 — Quick capture | "Update this task" from any screen | Context replaces navigation |
| 14 — Close-out | Multi-domain save | Composite preview |

## Run it today

A single session that exercises everything currently live:

1. *"Add a high-priority task to review the Q3 budget by Friday."* → To-Do updates.
2. *"Schedule a budget review meeting Thursday at 2pm."* → Calendar shows the meeting beside the
   task's Friday due-date.
3. Upload a budget PDF → **Save to Library** (converted to markdown via Content Understanding,
   then chunked and indexed).
4. *"Search my library — what's our Q2 budget summary?"* → cited answer from the Library.
5. *"Email me a daily agenda summary at 8am."* → a reminder appears on the Reminders screen.

Each step visibly changes the app, and every claim is backed by a tool that actually ran —
verifiable against `/app/state` and `logs/trace.jsonl`.
