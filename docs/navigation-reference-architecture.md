# Navigation Reference Architecture

How the assistant moves the app from one screen to another — and why navigation is a
**trust boundary**, not a place to let the model improvise.

The rule: **the model expresses intent; application code owns resolution.** The agent calls
one tool with the user's words; a deterministic resolver in the app turns those words into a
concrete route (or a short list to disambiguate). The model never chooses a URL.

This is a reference pattern. The anchors below point at this repo's implementation, but the
contract — one intent call, a deterministic resolver, three explicit outcomes, an
event-driven follow rule — is portable to any assistant that drives a UI.

## One intent call, not a navigation agent

The agent has a single navigation tool, [`navigate(destination)`](../session-container/agent.py)
(`session-container/agent.py:425`). It passes the user's phrasing through — ideally verbatim
("my calendar", "the crypto task", "documents") — and gets back a **grounded** answer in one
call. There is no loop where the model guesses a path, sees a 404, and guesses again.

The contrast this design rejects: a multi-call "navigation agent" that reasons its way to a
URL. That is slower, non-deterministic, and unfalsifiable — the model can assert it navigated
somewhere that does not exist. Here, routing is **application logic exposed as a tool**, so the
same input always resolves the same way and every outcome is explainable from code.

## The resolver contract

All parsing lives in [`resolve_destination(data, destination)`](../session-container/appdb.py)
(`session-container/appdb.py:294`). It is deterministic — **no LLM** — and returns exactly one
of three shapes:

| Outcome | Shape | Meaning | Effect on `currentRoute` |
|---|---|---|---|
| `resolved` | `{status, path, title}` | Intent matched exactly one destination | **Set** to `path` |
| `ambiguous` | `{status, candidates[]}` | Intent matched several — the user must pick | **Unchanged** (no-op) |
| `not_found` | `{status, candidates[]}` | Nothing matched | **Unchanged** (no-op) |

Only `resolved` mutates state. The tool applies this by writing `currentRoute` on `resolved`
and raising [`AbortWrite`](../session-container/appdb.py) for the other two
(`session-container/agent.py:427-436`) — so an ambiguous or unknown destination **leaves the
app exactly where it was** and returns candidates instead of moving the user somewhere wrong.

Ambiguous and not-found are **first-class outcomes, not failures to hide.** Both leave the app
where it was and return candidate destinations that become clickable chips in the trace. They
differ in *signal*: an **ambiguous** result is a neutral no-op ("which one did you mean?"); a
**not-found** result surfaces as an *error* ("nothing matched") — but still offers fallback
destinations rather than a dead end. Either way the user gets a choice, never a wrong move or a
silent failure. (The candidate sources differ too: not-found returns `_all_destinations(data)[:8]`,
capped at 8, `appdb.py:371`; ambiguous returns the matched destinations, uncapped,
`appdb.py:369-370`. The trace then caps the chips it renders to 6, `agent.py:251`.)

## How resolution matches (deterministic layers)

`resolve_destination` tries increasingly loose matches and stops at the first that yields a
single hit (`appdb.py:307-371`):

1. **Exact static route** — path or title equals the query (`/calendar`, "Calendar").
2. **Exact task/event title** — a single record whose title equals the query resolves to its
   detail route (`/todo/{id}`, `/calendar/{id}`).
3. **Substring + keyword match across routes, tasks, and events** — a route matches on a ≥3-char
   *raw* substring of its title or a keyword, **or** on a whole-word keyword hit (the
   word-boundary rule stops a 1–2 char query from matching inside a word). Tasks/events join by
   ≥3-char substring on title. Keyword-only hits are then filtered by the stopword-residual
   guard below.

One or more matches after dedup → `resolved` (exactly one) or `ambiguous` (more than one); zero
→ `not_found`.

### The stopword residual guard (fail-loud matching)

The subtlest — and most important — piece is the guard at `appdb.py:350-355`. A **keyword-only**
match (one resting on a keyword hit, not a title substring) is trusted **only if, after removing
the matched keyword and a set of filler stopwords** (`my`, `the`, `page`, `view`, `open`,
`show`, …), **no content words remain.** This lets "my calendar" and "the documents page"
resolve, while forcing `"crypto mining dashboard"` to fail loud (`not_found`) instead of
silently resolving to Home via the stray "dashboard" keyword.

This is the navigation analogue of *no silent fallbacks*: a partial keyword hit that leaves
unexplained words is treated as **not understood**, not as a lucky guess.

## Outcome → trace signal

The three resolver outcomes surface to the UI through the custom `TOOL_CALL_RESULT` event
(see [architecture.md](architecture.md#sse-and-ag-ui-event-flow),
[harnesses.md](harnesses.md)):

| Tool result marker | `TOOL_CALL_RESULT.outcome` | UI |
|---|---|---|
| `NAVIGATED to …` | `ok` | Pane follows the route |
| `AMBIGUOUS: … matches multiple …` | `noop` | Candidate chips, pane stays |
| `NOT_FOUND: no destination matched …` | `error` | Fallback-destination chips, pane stays |

The outcome is classified from the tool's **leading status marker** by `_tool_outcome`
(`agent.py:216`): `AMBIGUOUS` is in `_NOOP_MARKERS`, while a marker ending in `NOT_FOUND` maps to
`error`. **Both leave the pane put** — the follow rule keys on `outcome === "ok"`, so *neither* a
noop nor an error moves the user. The difference is the signal the trace shows (neutral "which
one?" vs. a red "not found") — and either way it is honest: an unresolved navigation is never
rendered as a false success.

## The frontend follow contract (event-driven, not diff-driven)

The pane follows server navigation as **behavior**, codified in
[`useAgentSession.ts`](../frontend/src/hooks/useAgentSession.ts). The rules:

1. **Follow only on a successful route-setting tool.** The client follows `currentRoute` only
   when a tool in `ROUTE_SETTING_TOOLS` (`useAgentSession.ts:10`) completes with outcome `ok`
   (`useAgentSession.ts:427`). It does **not** diff `currentRoute` and follow on any change — an
   old change-heuristic dropped re-navigation to the current route; the event-driven rule
   handles it.
2. **Manual navigation wins.** If the user clicks the sidebar mid-turn, `userNavSinceToolRef`
   (`useAgentSession.ts:322,438`) suppresses the route-*follow* on the trailing refetch — the
   refetch still runs to pull fresh state, but a deliberate click is not yanked back — unless a
   *later* agent nav supersedes it that same turn.
3. **Last-issued refetch wins.** Every tool completion (`TOOL_CALL_END`, `useAgentSession.ts:438`)
   triggers a `/app/state` refetch; a monotonic sequence (`appStateSeqRef`,
   `useAgentSession.ts:325,348-354`) drops any out-of-order snapshot so a stale read can't
   clobber the pane.
4. **Cancellation is respected.** After Stop, `cancelledRef` (`useAgentSession.ts:327,408`)
   ignores buffered events from the cancelled turn, so they can't re-navigate.

The pane renders the route from `/app/state` — the store the tool mutated — **never from the
tool's arguments or the assistant's prose.** This is the navigation face of the
[verifiable-execution invariant](architecture.md#anatomy-of-a-turn): the app can't claim to
be somewhere it isn't.

## Anti-patterns

- **Don't let the model compute route paths.** It emits intent; the resolver owns paths. A
  model-chosen URL is unfalsifiable and drifts from the real route table.
- **Don't render the pane from tool arguments or assistant text.** Follow server state only.
- **Don't treat ambiguous/not-found as an error to swallow or a success to fake.** They are
  outcomes with candidates — surface them (as a neutral noop and a red error respectively).
- **Don't add bidirectional substring matching** to "be helpful." It over-matches; the
  word-boundary + stopword-residual rules exist to fail loud instead.

## Migration: one resolver behind MCP

Today each harness wires its own `navigate` tool, but both call the same
`resolve_destination`. The [planned MCP tool substrate](harnesses.md#the-reusable-substrate-direction--not-yet-built)
lifts the resolver into a **Personal Assistant MCP server** so every harness (Copilot, Deep
Agents, future) consumes one canonical navigation implementation — identical outcomes, one
place to evolve the route table and stopword policy.

## Navigation contract checklist

For any new destination type or resolver change, verify:

- [ ] Exact match (path/title) is tried before fuzzy matching.
- [ ] A single hit → `resolved`; multiple → `ambiguous`; none → `not_found`.
- [ ] Only `resolved` mutates `currentRoute`; the other two are no-ops with candidates.
- [ ] Keyword-only matches pass the stopword-residual guard (no unexplained content words).
- [ ] Candidate handling is precise: not-found caps at 8, ambiguous is uncapped, trace chips cap
      at 6 — none are relevance-ranked (fixed route→task→event order).
- [ ] The tool emits a status marker that classifies to `ok`/`noop`/`error` correctly
      (`NAVIGATED`→ok, `AMBIGUOUS`→noop, `*_NOT_FOUND`→error).
- [ ] The pane follows only on a successful route-setting tool; manual nav is not overridden.
