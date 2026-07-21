"""Strict, catalog-backed navigation for CSA Workbench product tools.

The agent receives stable destination and Engagement IDs only.  This module never
accepts chat text or generates a route from it.
"""

from __future__ import annotations

import re
import appdb
from workbench_core import ProductToolResult


_STATIC = {
    "engagements": ("/engagements", "Engagements"),
}
_SCOPED_SUFFIX = {
    "engagement_overview": ("", "Overview"),
    "engagement_tasks": ("/tasks", "Tasks"),
    "engagement_artifacts": ("/artifacts", "Artifacts"),
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
