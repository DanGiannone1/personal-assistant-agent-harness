# RAG question answering (target design)

> **Authority:** Target design, not current behavior or approved implementation scope. The
> [current data architecture](../architecture/capabilities/data.md) owns today’s file behavior.
> Stored-data, security, Azure-cost, and rollout choices remain pending explicit owner approval in
> [issue #28](https://github.com/DanGiannone1/csa-workbench/issues/28).

## The simple version

A CSA should be able to ask "what did we agree on data residency for this Engagement?" and get an
answer grounded in the Engagement's own documents, with a citation to the specific source — not a
guess, and not an answer pulled from someone else's Engagement.

This design keeps the two-tier structure a prior implementation used — an ephemeral session workspace for
the document someone is actively working on, and a persistent, indexed corpus for material worth
searching later — but redesigns the indexed tier's authorization from the ground up. See "Not the
target" below for exactly what that replaces.

## What matters most

1. **One authorized logical scope per call.** The caller explicitly selects personal or one
   Engagement scope. The backend—not the model—builds the exact filter.
2. **Search is not authorization.** Every returned document is checked against live ownership or
   membership metadata before any passage reaches the model.
3. **Evidence is current and cited.** The answer uses only passages returned in the current tool
   result, and citations resolve through authenticated application routes.
4. **Retrieved text is untrusted data.** Document content can support an answer but cannot instruct
   the agent, expand scope, invoke tools, or override policy.
5. **No evidence means no answer.** Empty, stale, partial, unauthorized, or failed retrieval is
   reported plainly; model memory never fills the gap.

## Two tiers

| Tier | Scope | How the agent uses it |
|---|---|---|
| Session workspace | One ephemeral assistant session | Listed and read directly; current and quick, gone when the session ends — see [Session and state](../architecture/capabilities/data.md) |
| Indexed corpus | One actor’s personal logical scope, or one Engagement’s logical scope | Retrieved by a typed search tool with citation-grounded results; persistent and retrievable across sessions |

A document is promoted from one tier to the next, never the reverse:

```text
session file -> Engagement artifact (or personal record) -> indexed corpus entry
```

Promotion is an explicit, authorized action at each step — an actor must be authorized to create the
Engagement artifact, and indexing an artifact is a separate, auditable step, not an automatic side
effect of upload. See [document-ai.md](document-ai.md) for the conversion step that makes a document
readable before it is indexed or retrieved.

## Ground rules

- **Per-actor and per-Engagement logical corpora, never a cross-scope query.** One physical index per
  environment may hold chunks from multiple scopes, but every entry carries its owning scope and every
  application query targets exactly one actor or Engagement. There is no user-facing “all documents”
  search and no call may span scopes.
- **Membership-checked retrieval, every query.** A search query is scoped to corpora the querying
  actor currently has authorized access to; the index is never trusted to already reflect current
  membership — access is rechecked at query time, the same as every other typed tool in this
  codebase.
- **Managed identity, never an admin key.** Search access uses the workload's managed identity
  ([Identity and access](../architecture/capabilities/identity-and-access.md) /
  [Infrastructure](../architecture/capabilities/infrastructure.md)), not an admin key or a connection string held
  in application configuration.
- **Citation-grounded answers via typed tools only.** The model calls a typed search/answer tool and
  receives passages with source identifiers; it does not receive a raw index credential or an unscoped
  query feature, and an answer without a returned citation is not presented as grounded fact.
- **Fail loud, never fabricate.** If the corpus is unavailable, misconfigured, or returns nothing
  relevant, the tool result says so structurally; the model is not left to invent an answer to cover a
  missing result.

The recommended first delivery uses the stable Azure AI Search/Foundry IQ `2026-04-01` data-plane
contract with minimal, extractive retrieval. Preview answer synthesis, preview document ACL
ingestion, image serving, and model-generated scope filters are outside the design.

## Good outcome and controls

- The same canary phrase stored under two actors or Engagements is returned only from the explicitly
  authorized scope, including after membership revocation and during index lag.
- Every passage is post-validated against live document metadata; tombstoned or deleted content is
  discarded even if a stale chunk remains in Search.
- Each factual answer claim maps to a returned document/page/chunk reference and an authenticated
  application download route; private Blob/Search URLs never appear.
- Zero passages is a successful empty result, while partial results from the one required source are
  treated as failure rather than silently presented as complete evidence.
- Unit, adapter-parity, authorization, deletion-race, prompt-injection, Azure integration, and browser
  citation tests all pass before dev acceptance; prod enablement is a later explicit decision.

## Typed tool structure

```json
{
  "status": "succeeded",
  "operation": "search_documents",
  "scope": {"kind": "engagement", "id": "eng-42"},
  "result": {
    "passages": [
      {
        "documentId": "doc-7",
        "chunkId": "chunk-12",
        "text": "...",
        "citation": {
          "name": "statement-of-work.pdf",
          "artifactId": "art-7",
          "page": 4,
          "downloadPath": "/engagements/eng-42/artifacts/art-7"
        }
      }
    ]
  }
}
```

| Status | Meaning |
|---|---|
| `succeeded` | Query ran against an authorized corpus; `passages` may be empty |
| `invalid` | Malformed query or scope |
| `not_found` | No authorized corpus exists for the requested scope |
| `failed` | Retrieval infrastructure failed; no passages are fabricated to fill the gap |

Reuses the same structured-outcome pattern as [CRUD](crud.md) and [document-ai.md](document-ai.md)
rather than a bespoke marker-string protocol.

## Answering, not just retrieving

Retrieval alone is not the product experience; the assistant composes an answer from what the tool
returns. That composition step follows the same discipline as every other skill in this codebase:

- The answer may draw only on passages the tool actually returned in this turn, never on the model's
  general knowledge of the topic or an earlier turn's passages that are no longer current.
- Every factual claim in the answer traces to at least one returned `documentId`/`chunkId` and its
  authenticated application citation; the answer never synthesizes a source or exposes a provider URL.
- If the tool result has zero passages, the assistant says plainly that nothing in the corpus answered
  the question — it does not fill the gap with a plausible-sounding guess.
- A skill may issue multiple `search_documents`-style calls before answering, but only within that
  answer-producing turn and against the same selected scope. Each call is independently authorized,
  and earlier-turn passages are not evidence for the current answer.

This mirrors the clear-failure, no-fabrication rules [document-ai.md](document-ai.md) applies to
extraction and summarization, and the [CRUD](crud.md) rule that only a structured, tool-returned
result — never assistant prose — is trusted as fact.

## Not the target: what the prior implementation got wrong

An earlier iteration of this codebase (`session-container/library.py`, since removed — see
[Documents and retrieval](../architecture/capabilities/data.md)) implemented a single, global search
index shared by every user, authenticated with an admin key rather than managed identity, and
returning results with no per-actor or per-Engagement filter — any user's query could return another
user's indexed content. That implementation was removed from this codebase for cause. This
design is not a plan to restore it; every ground rule above exists specifically to close the gap that
made the prior version unsafe: scope the corpus, check membership on every query, and use managed
identity instead of a shared key.

## Current implementation

Nothing in this design exists in the current MVP. There is no indexed corpus of any kind, no search
tool, and no promotion flow from a session file to a durable, retrievable record — Engagement
artifacts today are a byte store with no reading, indexing, or retrieval capability at all. See
[current data architecture](../architecture/capabilities/data.md) for today's file behavior.
