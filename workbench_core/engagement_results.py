"""Translation of Engagement service outcomes into product tool results."""

from __future__ import annotations

from .engagements import Outcome
from .tool_protocol import ProductToolResult


_EMPTY_MESSAGE_STATUSES = frozenset({"succeeded", "resolved", "committed"})


def engagement_product_result(outcome: Outcome) -> ProductToolResult:
    """Return the one typed tool-result representation of an Engagement outcome.

    The service-owned status and operation remain authoritative.  Unknown outcome
    statuses are an adapter fault, so fail closed rather than emitting a generic
    successful-looking result.
    """
    if outcome.status in _EMPTY_MESSAGE_STATUSES:
        message = ""
    elif outcome.status == "invalid":
        details = "; ".join(outcome.errors.values())
        message = f"INVALID: {details}" if details else "INVALID: engagement input is invalid."
    elif outcome.status == "not_found":
        message = "ENGAGEMENT_NOT_FOUND: no visible engagement matches that reference."
    elif outcome.status == "forbidden":
        message = "FORBIDDEN: your engagement role does not allow that action."
    elif outcome.status == "noop":
        message = "NO_CHANGES: the engagement already has that state."
    elif outcome.status == "ambiguous":
        message = "AMBIGUOUS: multiple visible engagements match that reference."
    elif outcome.status == "conflict":
        message = "CONFLICT: the engagement changed; refresh and try again."
    elif outcome.status == "failed":
        message = "FAILED: engagement operation failed."
    else:
        raise ValueError(f"unsupported engagement outcome status: {outcome.status}")

    resource = None
    if outcome.record and outcome.record.get("id"):
        resource = {"kind": "engagement", "id": outcome.record["id"]}
    return ProductToolResult(
        outcome.status,
        outcome.code or f"engagement.{outcome.status}",
        outcome.operation,
        message,
        resource=resource,
    )
