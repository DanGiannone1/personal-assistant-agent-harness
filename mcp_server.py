"""CSA Workbench app-state MCP server — the remote doorway to the owner's Cosmos doc.

Cosmos is private-endpoint-only (see docs/deployment.md), so nothing outside the
VNet can reach it directly. This server runs as the `flow-mcp` Container App inside
the VNet-integrated ACA environment (scale-to-zero) and exposes the app-state
operations as MCP tools over streamable HTTP, authenticated by a shared key. That
gives laptops and agents (Claude Code, schedulers, other future agents) tool-level
access to tasks/events/schedules without any network path to Cosmos itself.

Auth: every request must carry the key in `x-api-key` or `Authorization: Bearer`.
Health probe at /health is unauthenticated. Client setup:

    claude mcp add --transport http flow https://<fqdn>/mcp \
        --header "x-api-key: $MCP_API_KEY"
"""

from __future__ import annotations

import hmac
import os
import sys
from pathlib import Path

# Reuse the session-container's appdb (same pattern as app.py) so tool semantics
# match the product exactly.
_SC = Path(__file__).resolve().parent / "session-container"
if str(_SC) not in sys.path:
    sys.path.insert(0, str(_SC))
import appdb  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402

# DNS-rebinding protection only trusts localhost Hosts; behind ACA ingress the
# Host is the app FQDN and auth is the shared key above, so disable it.
mcp = FastMCP(
    "flow-appstate",
    stateless_http=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


# ── Tools ────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_app_state() -> dict:
    """Full CSA Workbench app state: currentRoute, tasks, events, schedules, library, routes."""
    return appdb.load()


@mcp.tool()
def list_tasks(status: str | None = None) -> list[dict]:
    """List tasks, optionally filtered by status (To do / In progress / Blocked / Done)."""
    tasks = appdb.load()["tasks"]
    if status:
        tasks = [t for t in tasks if t["status"].lower() == status.strip().lower()]
    return tasks


@mcp.tool()
def create_task(title: str, status: str = "To do", priority: str = "Medium",
                group: str = "General", due_date: str = "") -> dict:
    """Create a task. status: To do/In progress/Blocked/Done; priority: Low/Medium/High;
    due_date: YYYY-MM-DD or empty."""
    if status not in appdb.TASK_STATUSES:
        raise ValueError(f"status must be one of {appdb.TASK_STATUSES}")
    if priority not in appdb.TASK_PRIORITIES:
        raise ValueError(f"priority must be one of {appdb.TASK_PRIORITIES}")
    created: dict = {}

    def _mut(data):
        task = {
            "id": appdb.new_id("t", data["tasks"]),
            "title": title.strip(), "status": status, "priority": priority,
            "group": (group or "General").strip() or "General", "dueDate": due_date.strip(),
            "subtasks": [], "notes": "", "createdAt": appdb._now_iso(),
        }
        data["tasks"].append(task)
        created.update(task)
    appdb.update(_mut)
    return created


@mcp.tool()
def update_task(task: str, title: str | None = None, status: str | None = None,
                priority: str | None = None, group: str | None = None,
                due_date: str | None = None, notes: str | None = None) -> dict:
    """Update a task; `task` is an id, exact title, or unique title substring.
    Only the provided fields change."""
    if status is not None and status not in appdb.TASK_STATUSES:
        raise ValueError(f"status must be one of {appdb.TASK_STATUSES}")
    if priority is not None and priority not in appdb.TASK_PRIORITIES:
        raise ValueError(f"priority must be one of {appdb.TASK_PRIORITIES}")
    out: dict = {}

    def _mut(data):
        t = appdb.resolve_task(data, task)
        if t is None:
            raise appdb.AbortWrite({"error": f"no unique task matching {task!r}"})
        for field, val in (("title", title), ("status", status), ("priority", priority),
                           ("group", group), ("dueDate", due_date), ("notes", notes)):
            if val is not None:
                t[field] = val.strip() if isinstance(val, str) else val
        out.update(t)
        return out
    return appdb.update(_mut) or out


@mcp.tool()
def delete_task(task: str) -> dict:
    """Delete a task; `task` is an id, exact title, or unique title substring."""
    def _mut(data):
        t = appdb.resolve_task(data, task)
        if t is None:
            raise appdb.AbortWrite({"error": f"no unique task matching {task!r}"})
        data["tasks"] = [x for x in data["tasks"] if x["id"] != t["id"]]
        return {"deleted": t["id"], "title": t["title"]}
    return appdb.update(_mut)


@mcp.tool()
def list_events(date: str | None = None) -> list[dict]:
    """List calendar events, optionally only those on a YYYY-MM-DD date."""
    events = appdb.load()["events"]
    if date:
        events = [e for e in events if e.get("date") == date.strip()]
    return events


@mcp.tool()
def create_event(title: str, date: str, start: str, end: str,
                 type: str = "Meeting") -> dict:
    """Create a calendar event. date: YYYY-MM-DD; start/end: HH:MM."""
    created: dict = {}

    def _mut(data):
        event = {
            "id": appdb.new_id("e", data["events"]),
            "title": title.strip(), "date": date.strip(), "start": start.strip(),
            "end": end.strip(), "type": (type or "Meeting").strip() or "Meeting", "notes": "",
        }
        data["events"].append(event)
        created.update(event)
    appdb.update(_mut)
    return created


@mcp.tool()
def delete_event(event: str) -> dict:
    """Delete an event; `event` is an id, exact title, or unique title substring."""
    def _mut(data):
        e = appdb.resolve_event(data, event)
        if e is None:
            raise appdb.AbortWrite({"error": f"no unique event matching {event!r}"})
        data["events"] = [x for x in data["events"] if x["id"] != e["id"]]
        return {"deleted": e["id"], "title": e["title"]}
    return appdb.update(_mut)


@mcp.tool()
def reseed_library() -> dict:
    """Restore the seeded reference docs to an empty library (repairs a doc that was
    first-seeded by a container without seed_docs/). No-op if the library is non-empty."""
    def _mut(data):
        if data.get("library"):
            raise appdb.AbortWrite({"status": "unchanged", "count": len(data["library"])})
        data["library"] = appdb._seed_library()
        return {"status": "reseeded", "count": len(data["library"])}
    return appdb.update(_mut)


@mcp.tool()
def list_schedules() -> list[dict]:
    """List scheduled reminders (saved prompts run on a cadence and emailed)."""
    return [{**s, "summary": appdb.schedule_summary(s)} for s in appdb.load()["schedules"]]


# ── ASGI app: shared-key auth around the streamable-HTTP MCP app ─────────────

_inner = mcp.streamable_http_app()  # serves MCP at /mcp


async def app(scope, receive, send):
    if scope["type"] != "http":
        return await _inner(scope, receive, send)
    if scope["path"] == "/health":
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/plain")]})
        return await send({"type": "http.response.body", "body": b"ok"})
    expected = os.getenv("MCP_API_KEY", "")
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    auth = headers.get("authorization", "")
    bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    x_key = headers.get("x-api-key", "")
    if not expected or not (hmac.compare_digest(x_key, expected)
                            or hmac.compare_digest(bearer, expected)):
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"text/plain")]})
        return await send({"type": "http.response.body", "body": b"unauthorized"})
    return await _inner(scope, receive, send)
