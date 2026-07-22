# Session-state boundary

> **Authority:** Focused current-boundary note; [design](../design.md) remains higher authority.

## In plain language

An agent session is a temporary working conversation, not a product record. It remains usable only
while the owning API process and runtime state stay alive. If either is replaced, the frontend
creates a new session and reloads the actor's durable product state — Engagements and personal
Tasks/Calendar/Reminders are unaffected because they live in Cosmos, not in the session.

## State boundary

| State | Owner | Lifetime |
|---|---|---|
| Actor profile, Engagement records, personal-workspace aggregate, artifact metadata, activity | Cosmos DB | Durable across sessions and compute replacement |
| Engagement artifact bytes | Local artifact directory or Blob Storage | Durable across sessions and compute replacement |
| Session ID and actor binding | API and runtime process maps | Lost when the relevant process is replaced |
| Harness conversation | Live `AgentSession`; Deep Agents uses `InMemorySaver` | Lost with the runtime session or process |
| Chat upload, generated file, upload manifest | Per-session runtime workspace directory | Ephemeral filesystem state |
| Completed chat shown after a same-tab reload | Browser `sessionStorage` | Browser-tab state, not server truth |
| Structured and raw trace JSONL | Local process filesystem when tracing is enabled | Optional and ephemeral; no user-retrievable receipt |
| Per-session turn lock | Runtime process memory (`asyncio.Lock`) | Process-local only |

Cosmos updates to Engagement and personal-workspace documents use optimistic ETag replacement with
bounded retry. That protects durable aggregate writes from lost updates; it does not make a chat,
stream, or session durable.

## Session lifecycle

`POST /sessions` requires the configured user authentication. The API generates an opaque ID and
asks the runtime to create that session bound to the authenticated actor. Only after runtime creation
succeeds does the API record the same owner in its process-local map and return `201`. The
workspace is created immediately; the harness initializes lazily on the first turn.

Every session-scoped route re-probes the runtime and compares the authenticated actor with the API's
owner map. An unknown session, an owner mismatch, or a session whose API binding was lost all return
`404`, so another actor cannot use a guessed ID to learn that a session exists. The runtime separately
checks its write-once actor binding for chat and file calls; a mismatched forwarded actor receives the
same `404` without changing or deleting the original session.

`DELETE /sessions/{id}` checks ownership, removes the API's in-memory binding, and makes a
best-effort runtime delete; runtime cleanup failure is logged but does not change the API's `204`
response. The UI's **New session** action aborts its active stream, best-effort deletes the old
session, creates a new one, then reloads the actor's durable personal and Engagement state — it does
not delete Engagements, personal records, or committed artifacts.

## Turns, streaming, and concurrency

The runtime keeps one `asyncio.Lock` per session, acquires it before the SSE generator starts, and
immediately returns `409 Session is busy` if another turn already owns it; different sessions proceed
independently. The API proxies typed AG-UI events and validates their order — a stream must begin
with `RUN_STARTED` and end with exactly one valid `RUN_FINISHED` or `RUN_ERROR`. The runtime applies a
per-turn timeout (300 seconds by default); a timeout or unhandled failure destroys the live harness,
emits `RUN_ERROR`, and releases the session lock.

**Stop is a client-side stream abort.** The UI ignores later buffered events and makes input usable
again. There is no public cancel endpoint or durable cancelled state; a tool mutation that committed
before disconnect remains committed, and the next authoritative state read is the only trusted signal.

This coordination is valid only with one live API process and one live runtime process — the current
deployment enforces `0-1` replicas for frontend, API, and runtime. There is no distributed lease,
shared session registry, or cross-replica turn coordinator; increasing replicas would break these
ownership and locking assumptions and is outside the MVP.

## Local isolation

`dev.py` scopes launcher-owned workspace/logs to `.local-runs/<id>` and local durable artifact bytes
to `.mvp-artifacts/<id>` when `CSA_LOCAL_RUN_ID` is set, so a developer can run an isolated stack
alongside another one. It does not stop independently started processes. See
[development](../development.md) for the exact isolation variables.

## Failure and recovery

| Condition | Current behavior |
|---|---|
| API process replaced or scaled to zero | Owner map is gone; the old session ID fails ownership and the UI creates a new session |
| Runtime process/workspace replaced or scaled to zero | Runtime session, actor map, harness memory, uploads, and local traces are gone; the UI creates a new session |
| Old workspace exists without a runtime actor binding | Runtime returns `404` and fails closed rather than rebinding the workspace |
| Cosmos unavailable | Durable reads/writes fail; the session never becomes an alternative state store |
| Stream timeout or malformed upstream lifecycle | UI receives `RUN_ERROR`; there is no durable receipt or resumable cursor |

## Related authority

- [Design](../design.md)
- [Agent harness](agent-harness.md)
- [Identity and access](identity-access.md)
- [Development](../development.md)
- [Testing and evals](testing-evals.md)
