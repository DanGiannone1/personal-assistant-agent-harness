"""Destructively restore the named local CSA Workbench demo fixture.

This is deliberately a *local emulator only* utility.  It refuses an Entra
environment, an Azure/non-loopback Cosmos endpoint, a remote artifact backend,
or any target without an unambiguous reset acknowledgement.  It rebuilds the deterministic demo
actors, their personal spaces/context, Engagements, and local artifact tree.

Usage (from the repository root, with the emulator already running)::

    CONFIRM_DEMO_RESET=YES IDENTITY_MODE=demo DEMO_PASSWORD=... \
      COSMOS_ENDPOINT=http://localhost:8081 COSMOS_DATABASE=csa_workbench_demo \
      COSMOS_CONTAINER=appstate_demo ARTIFACTS_DIR=.mvp-artifacts \
      uv run python scripts/reset_demo_state.py

The database/container names are part of the guard: reset targets must include
``demo`` or ``local`` in both names.  The output is a normalized fixture
fingerprint, not a claim that a browser or agent journey has run.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_VERSION = "mvp-demo-v1"
RESET_OPT_IN = "CONFIRM_DEMO_RESET"
MVP_ARTIFACT_ROOT = ROOT / ".mvp-artifacts"


def load_local_env(path: Path) -> None:
    """Load simple local dotenv assignments without adding a root test dependency."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def configure_import_paths() -> None:
    """Make root and session modules importable when Python executes scripts/ directly."""
    for path in (ROOT, ROOT / "session-container"):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


def _endpoint_host(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("COSMOS_ENDPOINT must be an absolute http(s) URL")
    return parsed.hostname.lower().rstrip(".")


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def reset_guard(env: dict[str, str]) -> dict[str, str]:
    """Validate the entire destructive target before importing storage code."""
    if env.get("IDENTITY_MODE", "").strip().lower() != "demo":
        raise ValueError("reset is allowed only when IDENTITY_MODE=demo")
    if not env.get("DEMO_PASSWORD", "").strip():
        raise ValueError("DEMO_PASSWORD is required for a demo reset")
    if env.get(RESET_OPT_IN, "") != "YES":
        raise ValueError(f"set {RESET_OPT_IN}=YES to acknowledge destructive local demo reset")
    endpoint = env.get("COSMOS_ENDPOINT", "").strip()
    host = _endpoint_host(endpoint)
    if not _is_loopback(host):
        raise ValueError("reset refuses non-loopback or Azure COSMOS_ENDPOINT targets")
    database = env.get("COSMOS_DATABASE", "").strip()
    container = env.get("COSMOS_CONTAINER", "").strip()
    if not database or not container or not all("demo" in value.lower() or "local" in value.lower() for value in (database, container)):
        raise ValueError("COSMOS_DATABASE and COSMOS_CONTAINER must be explicitly named local/demo targets")
    if env.get("ARTIFACTS_ACCOUNT", "").strip():
        raise ValueError("reset refuses ARTIFACTS_ACCOUNT; only the local artifact directory is permitted")
    artifacts_dir = env.get("ARTIFACTS_DIR", "./artifacts").strip()
    artifact_path = Path(artifacts_dir).expanduser().resolve()
    if artifact_path == Path(artifact_path.anchor):
        raise ValueError("ARTIFACTS_DIR must name a local directory, not its filesystem root")
    try:
        artifact_path.relative_to(MVP_ARTIFACT_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("reset only clears the dedicated .mvp-artifacts subtree") from exc
    workspace_path = Path(env.get("WORKSPACE", str(ROOT / "workspace"))).expanduser().resolve()
    if workspace_path != (ROOT / "workspace").resolve():
        raise ValueError("reset only clears the repository-local WORKSPACE path")
    return {
        "endpoint": endpoint,
        "database": database,
        "container": container,
        "artifacts_dir": str(artifact_path),
        "workspace_dir": str(workspace_path),
    }


def _normalize(value):
    """Remove generated/Cosmos fields so an idempotent fixture has one digest."""
    if isinstance(value, dict):
        return {
            key: _normalize(item)
            for key, item in sorted(value.items())
            if key not in {"_etag", "_rid", "_self", "_attachments", "_ts", "createdAt", "uploadedAt", "ts", "savedAt"}
        }
    if isinstance(value, list):
        return [_normalize(item) for item in sorted(value, key=lambda item: json.dumps(item, sort_keys=True))]
    return value


def fixture_summary(appdb) -> dict:
    """Return only stable facts the evidence runners can verify before mutation."""
    users = appdb.list_users()
    engagements = []
    for actor in ("dan", "ava", "sam"):
        engagements.extend(appdb.list_engagements_for(actor))
    unique = {entry["id"]: entry for entry in engagements}
    payload = {
        "fixtureVersion": FIXTURE_VERSION,
        "actors": sorted({user["id"] for user in users}),
        "personalSpaces": [appdb.load_state(actor) for actor in ("dan", "ava", "sam")],
        "engagements": sorted(unique.values(), key=lambda entry: entry["id"]),
    }
    normalized = _normalize(payload)
    digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "fixtureVersion": FIXTURE_VERSION,
        "fixtureHash": digest,
        "counts": {
            "actors": len(users),
            "personalSpaces": 3,
            "engagements": len(unique),
            "artifacts": sum(len(entry.get("library", [])) for entry in unique.values()),
        },
        "actors": normalized["actors"],
        "engagementIds": [entry["id"] for entry in normalized["engagements"]],
    }


def reset() -> dict:
    load_local_env(ROOT / ".env")
    target = reset_guard(dict(os.environ))
    configure_import_paths()
    import appdb  # noqa: PLC0415

    # The target is already guarded above.  Delete all documents from exactly this
    # emulator container, then reseed through the production demo-only path.
    container = appdb._container()
    docs = list(container.query_items(query="SELECT c.id, c.sessionId FROM c", enable_cross_partition_query=True))
    for doc in docs:
        container.delete_item(item=doc["id"], partition_key=doc["sessionId"])

    artifact_root = Path(target["artifacts_dir"])
    if artifact_root.exists():
        shutil.rmtree(artifact_root)
    workspace_root = Path(target["workspace_dir"])
    if workspace_root.exists():
        shutil.rmtree(workspace_root)
    appdb._container_singleton = None
    appdb.ensure_seeded(os.environ["DEMO_PASSWORD"])
    # Seed artifacts use the same code path as the application, without importing
    # the FastAPI lifespan or touching an Azure blob backend (guarded above).
    import app as orchestrator  # noqa: PLC0415
    orchestrator._seed_engagement_artifacts()
    return {"target": target, **fixture_summary(appdb)}


def main() -> None:
    result = reset()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
