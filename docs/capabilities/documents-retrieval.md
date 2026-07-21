# Artifact and session-file boundary

> **Authority:** Focused current-boundary note; [design](../design.md) remains higher authority.

## What exists

**Engagement artifacts** are the one supported durable document capability. An authorized member
uses the Engagement's Artifacts tab to upload, list, download, or delete a file:

- metadata (ID, name, size, content type, uploader, upload time) is stored in the Engagement's
  Cosmos document under `library[]`;
- bytes are stored by the configured artifact backend — a local isolated directory
  (`.mvp-artifacts/<run-id>` in local development) or Azure Blob Storage when `ARTIFACTS_ACCOUNT` is
  configured, required for an Entra release; and
- access follows the same Engagement role rules as everything else: any member may list/download,
  and only an editor or owner may upload/delete (see [CRUD](crud.md#roles)).

Upload accepts one non-empty file up to 20 MiB; the server strips path components and sanitizes and
caps the stored display name at 120 characters. Bytes are written first, then metadata; a metadata
failure deletes the just-written bytes, and delete removes metadata before bytes — best-effort
ordering, not an atomic cross-store transaction. The artifact API is manual-only: it is not in the
assistant's tool inventory today (see [Agent harness](agent-harness.md)).

**Assistant session files** are different. They live in the ephemeral session workspace and are not
Engagement artifacts. Session uploads accept Markdown (`.md`) only, enforced by
`workbench_core.upload_policy`. Generated and uploaded files are ephemeral and do not survive a
runtime/API replacement; see [Session and state](session-state.md).

## What deliberately does not exist

There is no supported Library, Search, or generic retrieval surface in this MVP:

- no global document library, saved-search, or cross-Engagement document index;
- no automatic promotion of a session upload into a durable Engagement artifact, and no
  Save-to-Engagement action;
- no document conversion pipeline, semantic chunking, or citation-grounded retrieval; and
- no model tool that directly reads an Engagement artifact or a session upload — artifact download is
  a byte transfer through the authenticated API, not model grounding.

Generic enterprise search and broader document/retrieval capability are future non-goals, not current
MVP capabilities. Modules that previously implemented a legacy Personal Library backed by Azure AI
Search (`session-container/library.py`) have been removed from this codebase; any reference to
Library/Search elsewhere in the repository is history or an explicit exclusion, not a live feature.

## Evidence status

Focused release-boundary tests verify that an Entra-mode startup refuses the local artifact backend
(`ARTIFACTS_ACCOUNT` required) and that upload-filename policy accepts only `.md` for session uploads
(`tests/test_release_boundaries.py`). A local browser journey passed 41/41 checks at the current
revision. **UNVERIFIED:** a live Blob-backed artifact round trip against a deployed Azure instance —
local development exercises only the local-directory backend.

## Related authority

- [Design](../design.md)
- [CRUD](crud.md)
- [Session and state](session-state.md)
- [Identity and access](identity-access.md)
