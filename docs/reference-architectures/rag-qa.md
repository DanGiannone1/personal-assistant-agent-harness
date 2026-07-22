# RAG question answering (target design)

> **Authority:** Target design. Not a description of current behavior — [../design.md](../design.md)
> owns the current boundary. See "Where the current MVP stands" below for the honest gap to what is
> implemented today.

## The simple version

A CSA should be able to ask "what did we agree on data residency for this Engagement?" and get an
answer grounded in the Engagement's own documents, with a citation to the specific source — not a
guess, and not an answer pulled from someone else's Engagement.

This design keeps the two-tier shape a prior implementation used — an ephemeral session workspace for
the document someone is actively working on, and a persistent, indexed corpus for material worth
searching later — but redesigns the indexed tier's authorization from the ground up. See "Not the
target" below for exactly what that replaces.

## Two tiers

| Tier | Scope | How the agent uses it |
|---|---|---|
| Session workspace | One ephemeral assistant session | Listed and read directly; current and quick, gone when the session ends — see [Session and state](../capabilities/session-state.md) |
| Indexed corpus | One actor's personal corpus, or one Engagement's corpus | Retrieved by a typed search tool with citation-grounded results; persistent and retrievable across sessions |

A document is promoted from one tier to the next, never the reverse:

```text
session file -> Engagement artifact (or personal record) -> indexed corpus entry
```

Promotion is an explicit, authorized action at each step — an actor must be authorized to create the
Engagement artifact, and indexing an artifact is a separate, auditable step, not an automatic side
effect of upload. See [document-ai.md](document-ai.md) for the conversion step that makes a document
readable before it is indexed or retrieved.

## Ground rules

- **Per-actor and per-Engagement corpora, never global.** Every indexed entry carries the owning actor
  ID or Engagement ID it was indexed under. There is no cross-Engagement or cross-actor corpus, and no
  "all documents" index.
- **Membership-checked retrieval, every query.** A search query is scoped to corpora the querying
  actor currently has authorized access to; the index is never trusted to already reflect current
  membership — access is rechecked at query time, the same as every other typed tool in this
  codebase.
- **Managed identity, never an admin key.** Search access uses the workload's managed identity
  ([Identity and access](../capabilities/identity-access.md) /
  [Infrastructure](../capabilities/infrastructure.md)), not an admin key or a connection string held
  in application configuration.
- **Citation-grounded answers via typed tools only.** The model calls a typed search/answer tool and
  receives passages with source identifiers; it does not receive a raw index credential or an unscoped
  query surface, and an answer without a returned citation is not presented as grounded fact.
- **Fail loud, never fabricate.** If the corpus is unavailable, misconfigured, or returns nothing
  relevant, the tool result says so structurally; the model is not left to invent an answer to cover a
  missing result.

## Typed tool shape

```json
{
  "status": "succeeded",
  "operation": "search_documents",
  "scope": {"kind": "engagement", "id": "eng-42"},
  "result": {
    "passages": [
      {"sourceId": "art-7", "sourceName": "statement-of-work.pdf", "text": "..."}
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
- Every factual claim in the answer traces to at least one returned `sourceId`; the answer surfaces
  that source rather than a synthesized citation.
- If the tool result has zero passages, the assistant says plainly that nothing in the corpus answered
  the question — it does not fill the gap with a plausible-sounding guess.
- A skill may chain multiple `search_documents`-style calls across turns (for example, to check
  several artifacts before answering), but each call is independently scoped and authorized; no call
  inherits a broader scope from an earlier one in the same conversation.

This mirrors the fail-loud, no-fabrication contract [document-ai.md](document-ai.md) applies to
extraction and summarization, and the [CRUD](crud.md) rule that only a structured, tool-returned
result — never assistant prose — is trusted as fact.

## Not the target: what the prior implementation got wrong

An earlier iteration of this codebase (`session-container/library.py`, since removed — see
[Documents and retrieval](../capabilities/documents-retrieval.md)) implemented a single, global search
index shared by every user, authenticated with an admin key rather than managed identity, and
returning results with no per-actor or per-Engagement filter — any user's query could surface any
other user's indexed content. That implementation was removed from this codebase for cause. This
design is not a plan to restore it; every ground rule above exists specifically to close the gap that
made the prior version unsafe: scope the corpus, check membership on every query, and use managed
identity instead of a shared key.

## Where the current MVP stands

Nothing in this design exists in the current MVP. There is no indexed corpus of any kind, no search
tool, and no promotion flow from a session file to a durable, retrievable record — Engagement
artifacts today are a byte store with no reading, indexing, or retrieval capability at all. See
[../capabilities/documents-retrieval.md](../capabilities/documents-retrieval.md) for the authoritative
current-state contract and its evidence status.
