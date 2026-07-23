# Document AI (target design)

> **Authority:** Target design, not current behavior or approved implementation scope. The
> [current data architecture](../architecture/capabilities/data.md) owns today’s file behavior.
> Stored-data, security, Azure-cost, and rollout choices remain pending explicit owner approval in
> [issue #28](https://github.com/DanGiannone1/csa-workbench/issues/28).

## The simple version

An Engagement accumulates real documents: statements of work, architecture diagrams, spreadsheets,
meeting decks. Today the product asks a CSA to keep that material in whatever tool produced it and
paste in what matters. This design describes supported-format document intake — upload a common
office/document format, get back a normalized, readable rendition, and let typed tools extract or
summarize from it — scoped to the Engagement (or actor) that owns it.

Document AI is intake and understanding, not search. It converts and extracts; it does not decide
where a document is stored or who may read it — those decisions stay with the Engagement and
personal-workspace access rules used by [CRUD](crud.md). Retrieval and question answering
over many documents at once is a separate concern — see [rag-qa.md](rag-qa.md).

## What matters most

1. **Scope before content.** A document has exactly one personal or Engagement owner, and every
   upload, read, analysis, save, and delete rechecks that scope’s current authorization.
2. **Original and rendition are different assets.** Preserve the original bytes. Publish normalized
   Markdown only after complete conversion; never substitute an empty or partial rendition.
3. **Lifecycle is explicit.** `pending`, `ready`, `failed`, `deleting`, and deleted states are durable
   metadata, not claims inferred by the assistant.
4. **Tools and skills stay narrow.** Upload, analysis, and creation skills call typed application
   tools. A session draft becomes durable only after the user explicitly names its target scope.
5. **Failure stays visible.** Unsupported, unavailable, or failed analysis never falls back to model
   memory or exposes a provider path, credential, or payload.

The recommended first delivery accepts `.md`, `.txt`, `.pdf`, `.doc`, `.docx`, `.ppt`, `.pptx`,
`.xls`, and `.xlsx` up to the existing 20 MiB durable-file limit. It deliberately excludes macros,
archives, executables, and OCR/image-only promises. Those boundaries are part of the pending approval,
not current product behavior.

## What it adds beyond today

Today, the only durable document capability is manual Engagement-artifact upload/list/download/delete,
byte-for-byte, with no reading or understanding step. Session upload accepts and stores Markdown bytes
only; it does not perform conversion — see
[Documents and retrieval](../architecture/capabilities/data.md). This design adds three things:

1. **Broad-format intake.** Accept common office and document formats (PDF, DOCX, XLSX, PPTX, and
   similar), not only markdown.
2. **Normalization.** Convert an accepted upload into a normalized markdown rendition alongside the
   original, so every downstream tool reads one predictable text structure regardless of source format.
3. **Typed extraction and summarization.** Expose reading a converted document's content, and
   producing a bounded summary of it, as typed tools with structured results — not a bare byte
   download the model can never see, and not free-text "read this file" instructions.

## Ground rules

These follow directly from the [shared foundations](README.md#shared-foundations) every target design
in this directory assumes:

- **Actor- or Engagement-scoped only.** A document belongs to exactly one actor's personal workspace
  or one Engagement, the same two scopes [CRUD](crud.md) already defines. There is no global document
  store and no cross-scope document listing.
- **Membership governs access, not possession of a file reference.** Reading, converting, or
  summarizing a document requires the same membership/ownership check its storage scope already
  requires for any other operation on that Engagement or personal aggregate.
- **Managed identity only.** Any Azure conversion or extraction service this design uses is reached
  with the workload's managed identity ([Identity and access](../architecture/capabilities/identity-and-access.md)),
  never a shared key or connection string embedded in application configuration.
- **Typed tools only.** The model calls a narrow, typed tool (for example, `read_document` or
  `summarize_document`) closed over the actor's authorized scope, and gets back a structured result
  with the extracted text or summary and its source information — never a raw file-system path or an
  instruction to shell out.
- **Engagement-artifact-first storage.** A converted rendition is stored alongside the document it
  came from, in the same scope and under the same role rules — not in a side channel that escapes
  Engagement authorization.

## Structure of the pipeline

```text
upload (actor- or Engagement-scoped, authorized)
  -> format check (accept broad office/document formats)
  -> store original bytes in the owning scope's artifact backend
  -> convert to normalized markdown
  -> store the markdown rendition alongside the original, same scope, same role rules
  -> typed tools (read_document, summarize_document, ...) operate on the rendition
```

A conversion failure leaves the original byte upload intact and reports a typed failure outcome; it
never silently substitutes an empty or partial rendition.

## Good outcome and controls

- A viewer can read or analyze an authorized document; only an editor or owner can upload, promote,
  save, index, or delete within an Engagement.
- The original remains downloadable when normalization fails, and a retry cannot create two logical
  documents or a partial ready state.
- Normalized content and metadata remain in the same owning scope; actor/session/role values are
  transport-bound rather than model arguments.
- Format, empty-file, filename, size, quota, conversion, concurrent-delete, and revoked-membership
  tests exercise both success and failure paths.
- Managed identity and private application routes are the only service and citation boundaries; no
  Blob URL, key, SAS token, or provider credential reaches the model or browser.

## Typed tool result structure

Following the same structured-outcome pattern as [CRUD](crud.md):

```json
{
  "status": "succeeded",
  "operation": "summarize_document",
  "scope": {"kind": "engagement", "id": "eng-42"},
  "resource": {"kind": "artifact", "id": "art-7", "name": "statement-of-work.pdf"},
  "result": {
    "renditionAvailable": true,
    "summary": "..."
  }
}
```

| Status | Meaning |
|---|---|
| `succeeded` | Extraction or summarization completed and is returned in the result |
| `invalid` | Unsupported format, oversized upload, or malformed request |
| `not_found` | No authorized document matches the reference |
| `failed` | Conversion or extraction infrastructure failed; no content is fabricated |

This reuses the same status vocabulary [CRUD](crud.md) and
[Documents and retrieval](../architecture/capabilities/data.md) already use, rather than inventing a
parallel one.

## Heritage, not existing capability

An earlier iteration of this codebase had a working version of the upload-to-markdown conversion step:
a `content_processing.py` module and `ContentProcessor` class converted uploads (including PDF/DOCX
via an Azure document-understanding service) and mirrored bytes to a data-lake store. That module, its
conversion dependencies, and the data-lake mirror step were deliberately removed from this codebase —
`tests/test_release_boundaries.py` currently asserts that `content_processing.py` does not exist and
that `ContentProcessor` does not appear in `session_manager.py` or `pyproject.toml`. This design
borrows the structure of that prior conversion step, not its authorization model: the prior version was
not Engagement/actor-scoped the way [CRUD](crud.md) requires, and reintroducing conversion means
reintroducing it inside that boundary, not restoring the removed module.

## Current implementation

Today's document feature is deliberately narrow:

- Session uploads accept Markdown (`.md`) only — no conversion step exists.
- Engagement artifacts are a manual-only byte store: upload, list, download, delete, with no model
  tool that reads their content and no conversion pipeline.
- There is no broad-format intake, no normalized-markdown rendition, and no extraction/summarization
  tool of any kind.

See [current data architecture](../architecture/capabilities/data.md) for today's file behavior.
