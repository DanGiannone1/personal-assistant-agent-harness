"""Strict, catalog-backed navigation for CSA Workbench product tools.

The agent receives stable destination and Engagement IDs only.  This module never
accepts chat text or generates a route from it.
"""

from __future__ import annotations

import re
from typing import Any

import appdb
from workbench_core import ProductToolResult


_STATIC = {
    "engagements": ("/engagements", "Engagements"),
    "workbench": ("/home", "Workbench"),
}
_SCOPED_SUFFIX = {
    "engagement_overview": ("", "Overview"),
    "engagement_tasks": ("/tasks", "Tasks"),
    "engagement_artifacts": ("/documents", "Artifacts"),
}
_ENGAGEMENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def destination_for(actor_id: str, destination_id: str, engagement_id: str | None = None) -> ProductToolResult:
    """Resolve a catalog ID after live membership verification."""
    if destination_id in _STATIC:
        if engagement_id:
            return ProductToolResult("invalid", "navigation.unscoped_destination", "navigate", "This destination does not accept an engagement.")
        path, label = _STATIC[destination_id]
        return ProductToolResult("resolved", "navigation.resolved", "navigate", destination={"id": destination_id, "path": path, "label": label})
    if destination_id not in _SCOPED_SUFFIX:
        return ProductToolResult("invalid", "navigation.unknown_destination", "navigate", "That destination is not available.")
    if not engagement_id:
        return ProductToolResult("invalid", "navigation.engagement_required", "navigate", "An engagement ID is required.")
    if not _ENGAGEMENT_ID_RE.fullmatch(engagement_id):
        return ProductToolResult("invalid", "navigation.invalid_engagement", "navigate", "The engagement ID is invalid.")
    record = appdb.load_engagement(engagement_id)
    # Do not reveal whether a missing ID exists but is inaccessible.
    if record is None or appdb.member_role(record, actor_id) is None:
        return ProductToolResult("not_found", "engagement.not_found", "navigate", "The engagement is unavailable.")
    suffix, label = _SCOPED_SUFFIX[destination_id]
    return ProductToolResult(
        "resolved", "navigation.resolved", "navigate",
        resource={"kind": "engagement", "id": engagement_id},
        destination={"id": destination_id, "path": f"/engagements/{engagement_id}{suffix}", "label": label, "engagementId": engagement_id},
    )


def quick_links(actor_id: str, limit: int = 8) -> list[dict[str, Any]]:
    """Context-only manual convenience links; never used by agent navigation."""
    links = [{"id": key, "path": path, "title": title} for key, (path, title) in _STATIC.items()]
    for engagement in appdb.list_engagements_for(actor_id):
        links.append({"id": "engagement_overview", "path": f"/engagements/{engagement['id']}", "title": engagement["name"], "engagementId": engagement["id"]})
    return links[:limit]


def rank_destinations(
    personal: dict[str, Any], engagements: list[dict[str, Any]], visits: list[dict[str, Any]],
    utterance: str | None = None, today: str | None = None, limit: int = 8,
) -> list[dict[str, Any]]:
    """Compatibility surface for manual quick links only.

    Natural-language resolution is intentionally absent: callers must pass no
    utterance.  Recency can rank known destinations but cannot create a route.
    """
    if utterance:
        return []
    entries = [
        {"path": "/engagements", "title": "Engagements", "kind": "page"},
        {"path": "/home", "title": "Workbench", "kind": "page"},
        *[
            {"path": f"/engagements/{engagement['id']}", "title": engagement["name"], "kind": "engagement-page"}
            for engagement in engagements
        ],
    ]
    recent = {visit.get("path"): index for index, visit in enumerate(visits or [])}
    entries.sort(key=lambda entry: recent.get(entry["path"], len(recent) + 1))
    return entries[:limit]
