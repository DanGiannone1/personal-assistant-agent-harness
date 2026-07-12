# Roadmap — from demo accelerator to a competitive agentic workspace

Personal Assistant today is a demo: a harness-swappable agent embedded inside a small
productivity app, built to prove four capabilities ([spec.md](spec.md)). This roadmap is the
path from that demo to a product that competes with general AI assistants (claude.ai,
ChatGPT) on their own turf — while pressing the structural advantages a chat-first product
cannot match.

**The thesis.** A general assistant is a place you *bring* your work; this app is where the
work *lives*. The assistant here operates a real system of record — tasks, calendar,
documents, reminders — under the [verifiable-execution
invariant](architecture.md#anatomy-of-a-turn): the UI renders only from state the tools
actually mutated, so a claim can never outrun reality. To compete genuinely we must match the
assistant fundamentals users now expect (memory, artifacts, connectors, background work,
research) *and* keep that trust property as the differentiator, not lose it as we grow.

## Where we stand (honest inventory)

| Capability | Status | Anchor |
|---|---|---|
| Navigation — deterministic resolver, three outcomes | ✅ shipped | [navigation-reference-architecture.md](navigation-reference-architecture.md) |
| CRUD — agent tools + manual REST over one ETag-safe path | ✅ shipped | [crud-reference-architecture.md](crud-reference-architecture.md) |
| RAG — indexed Library, cited passages | ✅ shipped | [retrieval.md](retrieval.md) |
| Document ops — upload/CU conversion, drafting, canvas | ✅ shipped | [retrieval.md](retrieval.md) |
| Reminders — scheduled prompts, emailed results | ✅ shipped | [architecture.md](architecture.md#scheduled-reminders) |
| Two interchangeable harnesses behind one seam | ✅ shipped (parity gap: Deep Agents lacks Schedules/Library tools) | [harnesses.md](harnesses.md) |
| Skills — SKILL.md, progressive disclosure | ✅ shipped | [spec.md](spec.md#skills) |
| Honest tool outcomes — `ok`/`noop`/`error` + candidates | ✅ shipped | [architecture.md](architecture.md#sse-and-ag-ui-event-flow) |
| Context layer — persona, memory, context bundles | ❌ not built | this doc |
| Reporting — NL query over the user's own records | ❌ not built | this doc |
| Connectors — consent-gated external accounts | ❌ not built | this doc |
| HITL approvals on agent actions | ❌ not built (manual UI has confirm-to-delete only) | this doc |
| Evals | ❌ not built | this doc |
| Multi-user | ❌ single-owner POC | [architecture.md](architecture.md#auth-and-trust-model) |

## The competitive bar

What a top general assistant brings, and where each lands for us:

| Pillar | They have | Our position |
|---|---|---|
| Memory & personalization | Persistent, cross-conversation memory | **Gap.** Close it with a *legible* context layer (below) — memory the user can read, edit, and see applied per turn, scoped to the workspace |
| Artifacts | Rich interactive documents | Partial — markdown/CSV canvas; needs interactive HTML artifacts and in-place editing |
| Extensibility | Skills + MCP connectors | Skills shipped; tool substrate should itself become MCP ([harnesses.md](harnesses.md#the-reusable-substrate-direction--not-yet-built)) |
| Background work | Scheduled/autonomous tasks | Reminders *summarize and email*; the step-change is background runs that **act** on records under standing approvals |
| Research | Multi-source web research with citations | Library-only RAG today; web research is a later phase |
| Trust | Prose claims; the user verifies | **Our wedge.** Verifiable execution, deterministic navigation, honest outcome classification — structural, not promptable |

## The context layer (the missing lever)

Capability without context is generic: a skill that fires without knowing who the user is,
what they're working toward, or what state their workspace is in gives answers no better
than a public chatbot's. The design splits context into **types** — each with its own
storage and grounding model — that compose into a **per-turn bundle**.

| Context type | Holds | Storage & grounding rule | Delivery |
|---|---|---|---|
| User persona | Role, tone, output preferences, language | Stored; legible and user-editable; never inferred silently | Injected into the system prompt at turn start |
| Workspace memory | Durable decisions, conventions, goals ("we agreed to…") | Stored **only with explicit user confirmation**; user can view/edit/delete | Injected, scoped (global vs per-group) |
| Live grounding | Tasks, events, schedules, current view | **Never stored** — queried live from the owner doc; derived flags (overdue) computed, not persisted | Tools (today), MCP (planned) |
| Documents | Session files + Library | Content stays in its store; the app keeps **pointers and an index, never copies** | Direct read (session) / cited retrieval (Library) |
| Connected signals | The user's external mail/calendar/files | Consent-gated, read live as the user, **ephemeral** — nothing persisted | Thin connector tools |
| Reference knowledge | Curated, slow-changing knowledge base | Indexed for retrieval; versioned; the one place large-scale RAG earns its role | Heavy retrieval behind a tool |

Two principles run through every row, and both are already this repo's ethos:

- **Stored ≠ grounded.** Fast-changing state is queried at use, never copied into memory —
  copied state drifts, and a stale answer delivered confidently is worse than none.
- **Legibility.** Everything stored about the user is a visible, editable artifact — plus a
  per-turn **context inspector** showing exactly what was injected and why. Personalization
  the user can audit is the trust-preserving answer to "why did it say that?".

[personalized-navigation-via-user-context.md](personalized-navigation-via-user-context.md)
is the first concrete application: context *ranks*, never *gates*.

## Phases

### Phase 1 — Context: make it personal

The largest capability gap against general assistants, and the foundation everything later
composes with.

- **Persona record** in the owner doc (role, tone, output prefs, language) with a Settings
  surface — stored, legible, adjustable. Pre-fetched into the system prompt each turn
  (extending the existing `[Today: …] [Current view: …]` preamble in
  `useAgentSession.ts`).
- **Workspace memory** — the agent may propose a durable memory ("save that deliverables
  are due Fridays?"); it is written only on user confirmation, and listed/editable in the UI.
- **Context inspector** — a per-turn view of the composed bundle (persona + memory + live
  snapshot) with the reason each piece applied.
- **Close the Deep Agents parity gap** (Schedules/Library tools) so both harnesses run the
  full capability set.

### Phase 2 — Substrate & reach: make it capable

- **MCP tool substrate** — lift the `appdb` tools (navigate/CRUD/schedules/library) into one
  MCP server both harnesses consume; ends per-harness duplication and the
  validation-parity drift documented in
  [crud-reference-architecture.md](crud-reference-architecture.md).
- **Reporting** — deterministic NL-query over the user's own records ("what did I finish
  this month, by group?") rendering table/chart artifacts. Completes the capability matrix.
- **Connectors** — one consent-gated, ephemeral external-account integration (calendar or
  mail) proving the pattern: run-as-user, read-at-use, nothing persisted.
- **Artifact upgrades** — interactive HTML artifacts; edit-in-place on drafts.

### Phase 3 — Autonomy & trust: make it dependable

Autonomy expands only as fast as the trust machinery that supervises it.

- **HITL approvals** — approve/edit/reject interrupts on destructive or bulk agent actions,
  then *standing approvals* ("always allow marking tasks done") with an audit trail.
- **Background agents that act** — schedules graduate from "summarize and email" to
  agents that mutate records under standing approvals, with every run traced.
- **Evals** — a skill-eval harness: navigation resolution cases, overdue logic, RAG
  citation checks, CRUD outcome contracts. Gate on it.
- **Library indexing tiers** — metadata-only / lead+ToC / full-content as an explicit
  choice at save time, making the cost/recall tradeoff visible.
- **Observability** — per-tool outcome metrics on the existing trace spine; dashboards.

### Phase 4 — Product foundations: make it real

- **Multi-user** — swap the single owner key for the signed-in user's id
  (`COSMOS_OWNER_ID` → Entra `oid`, the seam noted in `appdb.py`), per-user Library
  namespaces, real authz on every endpoint.
- **Web research** — multi-source retrieval beyond the Library, cited, with the same
  fail-loud grounding bar as `search_documents`.
- **Performance** — prompt caching, token-efficiency passes, model routing across tiers.

## Sequencing rationale

Context (P1) precedes autonomy (P3): background agents are only trustworthy when persona
and memory make their behavior predictable and the inspector makes it auditable. The MCP
substrate (P2) precedes connectors and multi-user: one canonical tool layer is the thing
you secure and permission, not N harness dialects. Evals land before autonomy expands —
an agent allowed to act unattended must be an agent whose regressions are caught by a
gate, not by users.

## Non-negotiables carried forward

Every phase inherits the invariants that make this app worth choosing over a chat window:

- The pane renders **only** from `/app/state`; tools mutate that exact store.
- Resolution is deterministic; ambiguity and not-found are surfaced outcomes, never guesses.
- No silent fallbacks: errors classify as errors, in the trace the user can open.
- Stored context is user-visible and user-editable; live state is never copied into memory.
