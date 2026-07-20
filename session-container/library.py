"""Persistent document Library — the searchable knowledge base (RAG corpus).

Two-tier document model:
  - **Session files**: ephemeral, per-session workspace, read *directly* by the agent
    (they're few and current — no retrieval needed).
  - **Library**: persistent, indexed in Azure AI Search → *retrieved* (RAG) across all
    sessions. A session file becomes Library knowledge via `save_to_library`.

This module owns the Search-index side of the Library: chunking, indexing, search,
fetch, delete. The owner's Library *list* (for the UI) lives in the Cosmos owner doc
(`appdb.library[]`); promotion writes both. Auth is the Azure AI Search admin key
(same as the seed indexer). Single-user POC: the index IS the one owner's library — add
an `owner` field + filter to scope per-user when multi-user lands.

Fails loud: every non-success path returns a leading status marker; never fabricates.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

INDEX_NAME = "csa-workbench-documents-index"
SEMANTIC_CONFIG = "csa-workbench-semantic"
API_VERSION = "2024-07-01"
MAX_CONTENT_BYTES = 2_000_000   # cap a promotable doc (matches the viewer's 2MB read cap)
MAX_CHUNKS = 800                # keep a doc under the single-query top:1000 ceiling


def _config() -> tuple[str, str]:
    endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
    key = os.getenv("AZURE_SEARCH_KEY")
    if not endpoint or not key:
        raise RuntimeError(
            "SEARCH_NOT_CONFIGURED: Azure AI Search is not configured "
            "(missing AZURE_SEARCH_ENDPOINT / AZURE_SEARCH_KEY)."
        )
    return endpoint.rstrip("/"), key


def _client() -> httpx.Client:
    endpoint, key = _config()
    return httpx.Client(
        base_url=endpoint,
        headers={"api-key": key, "Content-Type": "application/json"},
        timeout=30,
    )


def _slug(filename: str) -> str:
    """Search doc keys allow only letters/digits/_/-/=; make a safe id prefix."""
    return re.sub(r"[^A-Za-z0-9_\-=]", "_", filename)


def _odata(value: str) -> str:
    """Escape a string literal for an OData filter — single quotes are doubled. Prevents a
    filename like o'brien.md from breaking (or injecting into) the `filename eq '...'` filter."""
    return value.replace("'", "''")


def title_from_filename(filename: str) -> str:
    return re.sub(r"\.(md|markdown|txt|pdf|docx?)$", "", filename, flags=re.I).replace("-", " ").replace("_", " ")


def chunk_markdown(text: str) -> list[str]:
    """Split a markdown doc into chunks at level-1/2 headings (heading + body to the next).
    Falls back to a single chunk for heading-less content. Drops whitespace-only chunks."""
    parts = re.split(r"(?m)^(#{1,2}\s.*)$", text)
    chunks: list[str] = []
    preamble = parts[0].strip()
    if preamble:
        chunks.append(preamble)
    for i in range(1, len(parts), 2):
        heading = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        chunk = (heading + "\n" + body).strip() if body else heading
        if chunk:
            chunks.append(chunk)
    return [c for c in chunks if c.strip()]


def _index_definition() -> dict:
    fields = [
        {"name": "id", "type": "Edm.String", "key": True, "filterable": True, "searchable": False},
        {"name": "filename", "type": "Edm.String", "filterable": True, "facetable": True, "searchable": True},
        {"name": "title", "type": "Edm.String", "searchable": True, "filterable": True},
        {"name": "chunk", "type": "Edm.String", "searchable": True, "analyzer": "en.microsoft"},
    ]
    return {
        "name": INDEX_NAME,
        "fields": fields,
        "semantic": {
            "configurations": [{
                "name": SEMANTIC_CONFIG,
                "prioritizedFields": {
                    "titleField": {"fieldName": "title"},
                    "prioritizedContentFields": [{"fieldName": "chunk"}],
                    "prioritizedKeywordsFields": [{"fieldName": "filename"}],
                },
            }]
        },
    }


def ensure_index() -> None:
    """Create-or-update the index (idempotent). Azure AI Search returns 201 on create and
    204 when updating an existing index. Fails loud on a real error."""
    with _client() as c:
        resp = c.put(f"/indexes/{INDEX_NAME}", params={"api-version": API_VERSION}, json=_index_definition())
        if resp.status_code not in (200, 201, 204):
            raise RuntimeError(f"INDEX_ENSURE_FAILED: {resp.status_code} {resp.text[:300]}")


def _doc_id(filename: str, idx: int) -> str:
    """Chunk id = slug + short filename hash + index. The hash keeps distinct filenames that
    slug to the same prefix (e.g. 'a/b.md' and 'a_b.md') from colliding on the same keys."""
    h = hashlib.sha1(filename.encode("utf-8")).hexdigest()[:8]
    return f"{_slug(filename)}-{h}--{idx}"


def _chunk_ids(filename: str) -> list[str]:
    """All current chunk ids for a filename, via an exact (escaped) filename filter — works
    regardless of the id scheme that wrote them. Fails loud on a Search error rather than
    silently returning [] (which would make delete look successful while removing nothing)."""
    with _client() as c:
        resp = c.post(
            f"/indexes/{INDEX_NAME}/docs/search",
            params={"api-version": API_VERSION},
            json={"search": "*", "filter": f"filename eq '{_odata(filename)}'", "select": "id", "top": 1000},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"SEARCH_FAILED: {resp.status_code} {resp.text[:200]}")
    return [r["id"] for r in resp.json().get("value", [])]


def index_document(filename: str, title: str, text: str) -> int:
    """Chunk `text` and (re)index it under `filename`, replacing any prior chunks for that
    filename (idempotent). Returns the chunk count. Fails loud on oversized input."""
    if len(text.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise RuntimeError(f"LIBRARY_TOO_LARGE: document exceeds {MAX_CONTENT_BYTES // 1_000_000}MB.")
    ensure_index()
    chunks = chunk_markdown(text)
    if not chunks:
        raise RuntimeError("EMPTY_DOCUMENT: nothing to index (no text content).")
    if len(chunks) > MAX_CHUNKS:
        raise RuntimeError(f"LIBRARY_TOO_LARGE: document produced {len(chunks)} chunks (max {MAX_CHUNKS}).")
    new_ids = {_doc_id(filename, i) for i in range(len(chunks))}
    actions: list[dict] = []
    # Remove stale chunks from a prior version of this file (exact match, any prior id scheme).
    for old_id in _chunk_ids(filename):
        if old_id not in new_ids:
            actions.append({"@search.action": "delete", "id": old_id})
    for idx, chunk in enumerate(chunks):
        actions.append({
            "@search.action": "mergeOrUpload",
            "id": _doc_id(filename, idx),
            "filename": filename,
            "title": title,
            "chunk": chunk,
        })
    with _client() as c:
        resp = c.post(f"/indexes/{INDEX_NAME}/docs/index", params={"api-version": API_VERSION}, json={"value": actions})
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"INDEX_UPLOAD_FAILED: {resp.status_code} {resp.text[:300]}")
    failures = [r for r in resp.json().get("value", []) if not r.get("status")]
    if failures:
        raise RuntimeError(f"INDEX_UPLOAD_PARTIAL: {failures[:3]}")
    return len(chunks)


def delete_document(filename: str) -> int:
    """Remove all of a filename's chunks from the index. Returns the number deleted."""
    ids = _chunk_ids(filename)
    if not ids:
        return 0
    actions = [{"@search.action": "delete", "id": i} for i in ids]
    with _client() as c:
        resp = c.post(f"/indexes/{INDEX_NAME}/docs/index", params={"api-version": API_VERSION}, json={"value": actions})
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"INDEX_DELETE_FAILED: {resp.status_code} {resp.text[:300]}")
    return len(ids)


def get_document_text(filename: str) -> str | None:
    """Reconstruct a Library doc's text from its indexed chunks for the viewer. Best-effort
    rejoin (inter-chunk whitespace is normalized) — NOT the byte-exact original. Returns
    None if the filename has no chunks."""
    with _client() as c:
        resp = c.post(
            f"/indexes/{INDEX_NAME}/docs/search",
            params={"api-version": API_VERSION},
            json={"search": "*", "filter": f"filename eq '{_odata(filename)}'", "select": "id,chunk", "top": 1000},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"SEARCH_FAILED: {resp.status_code} {resp.text[:200]}")
    rows = resp.json().get("value", [])
    if not rows:
        return None
    rows.sort(key=lambda r: int(r["id"].rsplit("--", 1)[-1]))
    return "\n\n".join(r.get("chunk", "") for r in rows).strip()


def ensure_seeded_indexed(seed_dir: str | Path) -> int:
    """Index any seed reference doc that isn't already in the index, so the seeded library[]
    list and the searchable index can't diverge on a fresh deploy (a list pointing at nothing).
    Idempotent; returns the count newly indexed. Best-effort — the caller logs failures."""
    seed_path = Path(seed_dir)
    if not seed_path.is_dir():
        return 0
    n = 0
    for p in sorted(seed_path.glob("*.md")):
        if get_document_text(p.name) is None:  # not yet indexed
            index_document(p.name, title_from_filename(p.name), p.read_text(encoding="utf-8"))
            n += 1
    return n


def search(query: str, top: int = 4) -> str:
    """Semantic (BM25 + reranker) search over the Library. Returns a formatted PASSAGES
    block with source filenames, or a leading status marker on every non-success path."""
    try:
        endpoint, key = _config()
    except RuntimeError as exc:
        return str(exc)
    body = {
        "search": query,
        "top": top,
        "select": "filename,title,chunk",
        "queryType": "semantic",
        "semanticConfiguration": SEMANTIC_CONFIG,
    }
    try:
        resp = httpx.post(
            endpoint + f"/indexes/{INDEX_NAME}/docs/search",
            params={"api-version": API_VERSION},
            headers={"api-key": key, "Content-Type": "application/json"},
            json=body, timeout=20,
        )
    except httpx.HTTPError as exc:
        return f"SEARCH_FAILED: could not reach Azure AI Search ({exc})."
    if resp.status_code != 200:
        return f"SEARCH_FAILED: Azure AI Search returned {resp.status_code}: {resp.text[:200]}"
    results = resp.json().get("value", [])
    if not results:
        return f"NO_RESULTS: nothing in the Library matched '{query}'."
    lines = [f"PASSAGES for '{query}' ({len(results)} from the Library):"]
    for r in results:
        snippet = " ".join((r.get("chunk") or "").split())
        lines.append(f"- source: {r.get('filename')}\n  {snippet}")
    return "\n".join(lines)
