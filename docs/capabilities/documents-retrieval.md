# Documents and Retrieval

> **Authority:** Canonical subordinate design for Engagement artifacts and the boundaries around
> session files, the legacy Library, conversion, and retrieval
>
> **Deployed application revision:** `ce251fbbe03c6b99bc38e676a8be88e9f199f777`
>
> **Parent:** [Authoritative Product and System Design](../design.md)
>
> **Issue:** [#18](https://github.com/DanGiannone1/csa-workbench/issues/18)

## What the release provides

CSA Workbench has one supported durable document capability in this release: **Engagement
artifacts**. An authorized member uses the Engagement Documents tab to upload, list, download, or
delete a file. The application remains useful without document conversion or Azure AI Search.

An Engagement artifact is shared product state:

- its bytes are stored in Azure Blob Storage in the Entra deployment;
- its metadata is stored on the Engagement aggregate in Cosmos DB;
- current Engagement membership controls discovery and download; and
- role controls mutation: owners and editors can upload or delete, while viewers can list and
  download.

Nothing placed in chat or in the assistant workspace becomes an Engagement artifact automatically.
There is no Save-to-Engagement or promotion command in the deployed application revision.

## The manual artifact path

The web UI calls the authenticated artifact API directly. It does not ask the model to infer or
perform these actions.

1. **List** — `GET /engagements/{engagementId}/artifacts` returns metadata from the authorized
   Engagement record.
2. **Upload** — `POST /engagements/{engagementId}/artifacts` accepts one non-empty file up to 20 MiB.
   The server strips path components, restricts the stored display name, creates an artifact ID,
   writes bytes first, then adds metadata and activity to Cosmos.
3. **Download** — `GET /engagements/{engagementId}/artifacts/{artifactId}` reads the authorized Blob
   object and returns it as an attachment through the application API. The product exposes no
   public Blob URL or SAS path.
4. **Delete** — `DELETE /engagements/{engagementId}/artifacts/{artifactId}` removes metadata and
   activity through the Engagement mutation path, then deletes the bytes.

All four operations re-read current membership. Upload and delete require at least `editor`; list
and download require at least `viewer`. A non-member receives the same not-found response as an
unknown Engagement. Role checks occur again inside retried Engagement mutations so a stale browser
or concurrent role change cannot authorize a write.

The upload path removes newly written bytes if the subsequent metadata mutation fails. Delete is
not a cross-store transaction: metadata is removed before Blob deletion, so a Blob deletion failure
can leave unlisted bytes for operational cleanup. The current metadata contains artifact ID, name,
size, client-supplied content type, uploader, and upload time. It does **not** store a content hash,
revision history, provenance chain, conversion state, or indexing state.

Implementation: [artifact store](../../artifact_store.py), [artifact API](../../app.py), and
[Engagement Documents UI](../../frontend/src/components/workbench/EngagementScreens.tsx).

## Storage and deployment boundary

In the Entra release profile, startup requires `ARTIFACTS_ACCOUNT`. `artifact_store.py` uses
`DefaultAzureCredential` and stores each object under
`{engagementId}/{artifactId}` in the configured private container. The deployment provisions:

- a private Blob container named `engagement-artifacts`;
- disabled public network access, shared-key access, and public Blob access;
- a Blob private endpoint and private DNS; and
- `Storage Blob Data Contributor` for the API managed identity only.

The runtime has no Blob artifact role because the active model tool inventory has no Engagement
artifact read or write tool. Local demo and test runs instead use `ARTIFACTS_DIR`; that filesystem
adapter is not a durability claim for deployed use.

Deployment sources: [platform infrastructure](../../infra/platform.bicep) and
[application configuration](../../infra/apps.bicep).

## Other document surfaces are session-scoped or legacy

The repository still contains earlier document-workbench code. It is not the shared artifact
contract and is not automatically connected to an Engagement.

### Session uploads and generated files

Agent session ownership is process-local. Uploaded and generated files live in that session's
runtime workspace, and the browser keeps the session ID and completed chat messages in
`sessionStorage`. A refresh may reconnect while the same processes and workspace remain, but an
orchestrator or runtime replacement can lose the session, transcript, and files.

Markdown uploads are written directly to the runtime workspace. Other allowlisted formats require
the optional conversion path; when conversion is not configured the upload returns a visible 503.
When configured, the converter attempts to place the original and converted Markdown in ADLS and
forwards the Markdown into the runtime workspace. Those ADLS objects have no supported conversation
metadata or rehydration path, and their writes are best-effort, so they do not make a conversation
upload durable. ADLS and Content Understanding are not configured in the deployed MVP, so this
conversion path is off there.

The UI can list session files and open UTF-8 content up to 2 MiB. Generated `.md`, `.txt`, and
`.csv` files can be edited in place. The artifact canvas shows only files classified as generated;
its **Save** button overwrites that workspace file. It does not save to Blob or to an Engagement.
The upload manifest is also workspace-local; if its write fails, an uploaded file can be classified
as generated.

The two harness modules still define workspace read/write and Library tools, but neither active
harness exposes them to the model. The release inventory is limited to navigation and supported
Engagement record operations. Therefore the model cannot directly read a session upload, generate
a workspace file, search documents, save to the Library, or manage an Engagement artifact in the
deployed application revision.

Implementation: [session manager](../../session_manager.py), [runtime file API](../../session-container/server.py),
[Deep Agents adapter](../../session-container/agent_deepagents.py), [Copilot adapter](../../session-container/agent.py),
and [artifact canvas](../../frontend/src/components/ArtifactCanvas.tsx).

### Legacy Personal Library and Search

The host UI still renders a Personal Library and **Save to Library** controls. This is a legacy,
optional compatibility path, not a supported release capability:

- an actor's Library list metadata is stored in that actor's Cosmos state;
- saving a UTF-8 session file writes chunks to Azure AI Search, then records its filename and title
  in Cosmos;
- opening a Library item reconstructs normalized text from Search chunks rather than reading an
  authoritative original; and
- deleting removes the actor's metadata and then chunks selected by filename.

The Search schema and queries contain no actor, identity realm, Engagement, or document-scope field
or authorization filter. Chunk IDs and replacement/deletion are based on filename, and the adapter
uses an admin key. Consequently separately scoped users with the same filename can overwrite,
retrieve, or delete the same indexed content. Actor-scoped Cosmos metadata does not correct that
shared-index boundary.

Azure AI Search is absent from the deployed MVP and its endpoint/key are not supplied to the
release containers. With Search unconfigured, legacy save/open operations fail visibly and the
legacy search function returns `SEARCH_NOT_CONFIGURED`; core Engagement work and the manual artifact
path continue. Search must remain off for this release. This document does not define a future
search-authorization or citation design.

Implementation: [legacy Library adapter](../../session-container/library.py),
[orchestrator Library routes](../../app.py), and [development configuration](../development.md).

## Explicit non-capabilities

The release does not promise:

- durable conversations, durable chat uploads, or durable generated drafts;
- automatic sharing from an Engagement route, context tag, filename, or model statement;
- Save-to-Engagement, draft promotion, copy provenance, approval, review, or compensation workflow;
- model direct-read of Engagement artifacts or session uploads;
- document-grounded answers, structured citations, citation-open behavior, or page/section locators;
- authorized personal or Engagement retrieval, cross-document comparison, or semantic Search; or
- canvas persistence beyond the current runtime workspace.

Artifact download is a byte transfer, not model grounding. Artifact metadata in an Engagement does
not mean the model read the file.

## Evidence and remaining gaps

Checked-in tests and executable probes cover distinct parts of the boundary:

- focused contract tests verify that Entra startup refuses the local artifact backend and that the
  final infrastructure excludes Search and ADLS while providing the private Blob topology;
- the local Engagement browser script defines probes for upload, list, member download, viewer
  read-only UI, and owner delete;
- local smoke scripts define probes for byte round-trip, metadata/activity, path-shaped-ID
  rejection, size limits, empty uploads, canonical ID handling, and deletion; and
- the authoritative design records a live Blob-backed API round-trip at the final Azure topology,
  including upload, download/hash equality, list, and delete.

There is no checked-in transcript for that live Blob round-trip, so its request/response details and
hash evidence cannot be independently replayed from this repository. There is also no tracked local
browser or smoke result for the artifact lifecycle, so those scripts are available oracles and their
runtime behavior remains **UNVERIFIED** in a fresh clone. They do not prove the deployed private Blob
path. The current test material also does not prove atomic cross-store delete, stored hashes,
content inspection, malware scanning, or safe rendering of arbitrary uploaded formats; none is a
release promise.

Evidence sources: [release-boundary tests](../../tests/test_release_boundaries.py),
[infrastructure contract tests](../../tests/test_infra_entra_contract.py),
[Engagement browser journey](../../scripts/engagements_e2e.mjs),
[domain smoke](../../scripts/engagement_domain_smoke.py), and
[API probe](../../scripts/api_probe.py).
