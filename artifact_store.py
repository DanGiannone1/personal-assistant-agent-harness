"""Durable per-engagement artifact bytes — local directory or Azure Blob.

Metadata (name, size, uploader) lives on the engagement doc's `library[]`; this
module only moves bytes, keyed by (engagement_id, artifact_id). Backend selection:
`ARTIFACTS_ACCOUNT` set → Azure Blob via DefaultAzureCredential (managed identity
in prod), container `ARTIFACTS_CONTAINER` (default "engagement-artifacts"); otherwise a local
directory (`ARTIFACTS_DIR`, default ./artifacts) for dev and tests. No shared
keys, no SAS — access goes through the orchestrator, which enforces membership.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
DEFAULT_CONTAINER = "engagement-artifacts"

_blob_service = None  # cached BlobServiceClient (created once, thread-safe SDK)


def _check_ids(engagement_id: str, artifact_id: str) -> None:
    """Both ids are system-minted (eng-…/art-…); refuse anything path-shaped."""
    for value in (engagement_id, artifact_id):
        if not _ID_RE.match(value):
            raise ValueError(f"invalid artifact key segment: {value!r}")


def _account() -> str | None:
    return os.getenv("ARTIFACTS_ACCOUNT") or None


def assert_durable_configuration(identity_mode: str) -> None:
    """Reject an Entra release that would silently use ephemeral local bytes."""
    if identity_mode == "entra" and not _account():
        raise ValueError("ARTIFACTS_ACCOUNT is required when IDENTITY_MODE=entra")


def describe() -> str:
    account = _account()
    if account:
        return f"azure-blob:{account}/{os.getenv('ARTIFACTS_CONTAINER', DEFAULT_CONTAINER)}"
    return f"local-dir:{os.getenv('ARTIFACTS_DIR', './artifacts')}"


# ── Local directory backend ──────────────────────────────────────────────────

def _local_path(engagement_id: str, artifact_id: str) -> Path:
    root = Path(os.getenv("ARTIFACTS_DIR", "./artifacts"))
    return root / engagement_id / artifact_id


# ── Azure Blob backend ───────────────────────────────────────────────────────

def _container_client():
    global _blob_service
    from azure.core.exceptions import ResourceExistsError
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    account = _account()
    if _blob_service is None:
        _blob_service = BlobServiceClient(
            account_url=f"https://{account}.blob.core.windows.net",
            credential=DefaultAzureCredential(),
        )
    client = _blob_service.get_container_client(os.getenv("ARTIFACTS_CONTAINER", DEFAULT_CONTAINER))
    try:
        client.create_container()
    except ResourceExistsError:
        pass
    except Exception as exc:  # container may pre-exist without create rights
        logger.debug("create_container skipped: %s", exc)
    return client


def _blob_name(engagement_id: str, artifact_id: str) -> str:
    return f"{engagement_id}/{artifact_id}"


# ── Public interface ─────────────────────────────────────────────────────────

def put(engagement_id: str, artifact_id: str, data: bytes, content_type: str) -> None:
    _check_ids(engagement_id, artifact_id)
    if _account():
        from azure.storage.blob import ContentSettings
        _container_client().upload_blob(
            _blob_name(engagement_id, artifact_id), data, overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )
        return
    path = _local_path(engagement_id, artifact_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def get(engagement_id: str, artifact_id: str) -> bytes | None:
    _check_ids(engagement_id, artifact_id)
    if _account():
        from azure.core.exceptions import ResourceNotFoundError
        try:
            return _container_client().download_blob(
                _blob_name(engagement_id, artifact_id)).readall()
        except ResourceNotFoundError:
            return None
    path = _local_path(engagement_id, artifact_id)
    return path.read_bytes() if path.exists() else None


def delete(engagement_id: str, artifact_id: str) -> bool:
    _check_ids(engagement_id, artifact_id)
    if _account():
        from azure.core.exceptions import ResourceNotFoundError
        try:
            _container_client().delete_blob(_blob_name(engagement_id, artifact_id))
            return True
        except ResourceNotFoundError:
            return False
    path = _local_path(engagement_id, artifact_id)
    if path.exists():
        path.unlink()
        return True
    return False
