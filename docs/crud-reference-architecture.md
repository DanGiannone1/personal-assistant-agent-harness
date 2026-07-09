# CRUD Reference Architecture

How records (tasks, events, subtasks) are created, changed, and deleted — and why the same
data can be driven by **two callers** (the assistant and the manual UI) without either lying
about the result.

The rule: **one state model, two callers, one mutation path.** Agent tools and manual REST
endpoints both mutate the *same* owner document through the *same* concurrency-safe primitive.
The UI renders only from that document. Neither caller renders from its own optimism.

This is a reference pattern; the anchors point at this repo, but the contract — a shared
authoritative store, a single read-modify-write primitive, a status-marker outcome model, and
UI that re-reads rather than trusts — is portable.

## One store, rendered as truth

All structured state is a single Cosmos document — `{ currentRoute, tasks[], events[],
routes[], schedules[], library[] }` — keyed by a stable owner id (see
[architecture.md](architecture.md#state-and-storage)). Both callers write it; the pane renders
**only** from `GET /sessions/{id}/app/state`, which reads it back.

This is the [verifiable-execution invariant](architecture.md#anatomy-of-a-turn): a create is
"done" only when the pane, refetched from the store, shows it. A tool that returns
`CREATED task …` but failed to commit cannot fool the UI — the refetch won't contain the
record. **Do not render CRUD results from tool arguments or assistant prose; re-read the
authoritative state.**

## The mutation primitive

Every write goes through [`appdb.update(mutator)`](../session-container/appdb.py)
(`session-container/appdb.py:194`) — read-modify-write with optimistic concurrency:

1. Read the owner doc (with its ETag).
2. Run `mutator(data)`, which edits `data` in place and returns a result string.
3. `replace_item` with `IfNotModified` on the ETag. On an ETag conflict (a concurrent writer
   committed first), **re-read and re-run the mutator** with jittered backoff, up to
   `_MAX_UPDATE_RETRIES` (10, `appdb.py:191`).
4. If contention persists, **raise** — never silently drop the write.

Two invariants make the retry safe and loud:

- **Side-effect-free until commit.** The mutator only edits the in-memory `data`, so re-running
  it after a conflicting read is correct — there is nothing to undo.
- **`AbortWrite` for validation / no-op** (`appdb.py:183`). A mutator raises
  `AbortWrite(result)` to return a message **without writing** — the path for "task not found",
  "no changes specified", "ambiguous reference". This distinguishes *"I chose not to write"*
  from *"the write failed."*

`save()` (`appdb.py:171`) exists but is **last-write-wins and not concurrency-safe** — reserved
for seeding/admin/tests. Concurrent writers (agent tools, the reminder scheduler, manual edits)
**must** use `update()`.

## Caller A — agent tools

The agent's CRUD tools (`create_task`/`update_task`/`delete_task`/`add_subtask`,
`create_event`/`update_event`/`delete_event`, `session-container/agent.py:458` onward) share a
strict shape:

- **Narrow, typed parameters** — one Pydantic param model per tool; no free-form JSON blob.
- **A two-tier validation rule**, codified in `_update`'s docstring (`agent.py:390-398`):
  - *Input-only checks* (empty title, missing date) return a marker **before** `update()` —
    e.g. `TITLE_REQUIRED`, `DATE_REQUIRED`.
  - *Doc-dependent checks* (resolve-by-reference, ambiguity, not-found) raise `AbortWrite`
    **inside** the mutator, so they re-evaluate against the fresh read on each retry.
- **Leading status markers** that classify the outcome (see the contract below):
  `CREATED` / `UPDATED` / `DELETED` / `ADDED` (→ `ok`), `AMBIGUOUS` / `NO_CHANGES` (→ `noop`),
  `*_REQUIRED` / `*_NOT_FOUND` (→ `error`).
- **Strict reference resolution** — `_resolve_task_strict` / `_resolve_event_strict`
  (`agent.py:401-423`) resolve a task/event by id, then exact title, then unique substring, and
  return an explicit `*_NOT_FOUND` or `AMBIGUOUS` error rather than mutating the wrong record.

## Caller B — manual REST endpoints

So the app stands on its own **without the AI**, the UI edits the same document directly through
typed REST endpoints (`app.py:441` onward — `POST/PATCH/DELETE /sessions/{id}/tasks…`). No
session container or agent is involved. They share the store and the primitive but differ in
surface:

- **Typed request bodies** (`TaskCreate`, `TaskUpdate`, …) with field constraints.
- **Enum validation → HTTP 422** — `status`/`priority` are checked against
  `appdb.TASK_STATUSES` / `TASK_PRIORITIES` (`app.py:492-495,514-517`).
- **Missing record → HTTP 404** — the mutator raises `_NotFound`, which `_mutate` maps to a 404
  (`app.py:445-462`); it propagates through `update()` because `update()` only catches
  `AbortWrite`.
- **Same primitive** — every endpoint's mutator runs through `appdb.update`, off-thread.

After a manual mutation the UI calls `refresh()` (`useAgentSession.ts:519`), re-pulling
`/app/state` so a hand edit and an agent edit converge on identical rendering.

## The outcome contract

Both callers surface a **truthful** outcome — but through different channels (agent tools via
`TOOL_CALL_RESULT.outcome`; manual endpoints via HTTP status), and they do **not** map
one-to-one:

| Outcome | Agent tool signal | Manual endpoint signal | UI meaning |
|---|---|---|---|
| `ok` | `CREATED` / `UPDATED` / `DELETED` / `ADDED` | `2xx` + record body | Mutation landed; refetch shows it |
| `noop` | `AMBIGUOUS` / `NO_CHANGES` | *(no manual analogue — a no-field `PATCH` still `200`s)* | Nothing changed; surface why |
| `error` | `*_REQUIRED` / `*_NOT_FOUND` / raised exception | `422` (bad input) / `404` (missing) / `5xx` | Loud failure |

**Mind the asymmetry.** Input validation lands differently on the two callers: a missing title
is `TITLE_REQUIRED` on the agent tool — in `_ERROR_MARKERS` (`agent.py:213`), so it classifies
as **`error`** — while the manual endpoint rejects it with a **`422`**. Same intent, different
signal. And the agent has true no-ops (`AMBIGUOUS` / `NO_CHANGES`) that the manual API has no
equivalent for (it addresses records by explicit id, and a no-op `PATCH` still returns `200`).
For agent tools the outcome is classified from the leading status marker by `_tool_outcome`
(`agent.py:216`, see [harnesses.md](harnesses.md)) — so `NO_CHANGES` shows as a truthful no-op
and `TITLE_REQUIRED` as an honest error, never a fake success.

## Route side effects

Create/update/delete intentionally set the **post-action route** — but only the **agent** tools
do, because an assistant action should land you on its result:

| Action | Agent-tool route effect (`agent.py`) | Manual endpoint |
|---|---|---|
| Create | Open the new record (`/todo/{id}`, `/calendar/{id}`) | No route change — user stays where they clicked |
| Update | Open the changed record | No route change |
| Delete | Return to the list (`/todo`, `/calendar`) | No route change |

The agent sets `currentRoute` in the same mutator that writes the record, so the follow rule
(see [navigation-reference-architecture.md](navigation-reference-architecture.md#the-frontend-follow-contract-event-driven-not-diff-driven))
moves the pane to the result on the post-mutation refetch. Manual edits deliberately leave the
route alone — a form submission shouldn't teleport the user.

## Known gap — validation parity

The two callers **do not yet validate identically.** Manual endpoints reject out-of-enum
`status`/`priority` with a 422 (`app.py:492-495,514-517`); the agent tools accept free-form
strings — `create_task`/`update_task` do `params.status.strip() or "To do"` /
`params.priority.strip() or "Medium"` with **no** membership check (`agent.py:466-467,490-493`).
This is real drift risk: a `status` value the agent will happily create ("Later", "urgent")
would be rejected by the manual API, and vice versa. Documenting it is the first step; the fix
is a single shared validation layer (below).

**Mutation parity is worth tracking as a matrix** — for each entity (task, event, subtask) and
each field, do the agent tool and the manual endpoint enforce the same required/enum/default
rules? Divergences are bugs waiting to surface.

## Migration: one CRUD implementation behind MCP

Tool logic is [duplicated per harness today](architecture.md#limitations-and-known-gaps), and
validation is duplicated again between agent tools and REST endpoints. The
[planned MCP tool substrate](harnesses.md#the-reusable-substrate-direction--not-yet-built)
collapses the *harness* duplication: task/event CRUD lifts into a **Personal Assistant MCP
server** that every harness consumes as a client. The manual REST endpoints, though, live in
the orchestrator — a [pure proxy that never runs the agent SDK](architecture.md#why-the-orchestrator-never-runs-the-sdk),
so they can't consume that MCP server directly; the parity fix on the manual side is a
**shared validation module** that both the tools and the endpoints import. Either path lands the
same goal — one definition of what a valid task is, for every caller.

## CRUD contract checklist

For any new entity or mutation, verify:

- [ ] The write goes through `appdb.update` (never `save`) so it's ETag-safe and loud.
- [ ] The mutator is side-effect-free until commit (safe to re-run on retry).
- [ ] Validation splits correctly: input-only checks before `update`; doc-dependent checks via
      `AbortWrite` inside the mutator.
- [ ] The outcome maps to `ok` / `noop` / `error` via a status marker (agent) or status code
      (REST) — remembering `*_REQUIRED` is an **error**, and the two callers' input-validation
      signals differ.
- [ ] Agent tools set the intended post-action `currentRoute`; manual endpoints leave it alone.
- [ ] The UI re-reads `/app/state` after the mutation — it never renders from tool args.
- [ ] Agent and manual validation agree (or the divergence is tracked in the parity matrix).
