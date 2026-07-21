"""Transport-neutral product tool results and the MVP destination catalog."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping


DESTINATION_IDS = frozenset({
    "engagements", "engagement_overview", "engagement_tasks", "engagement_artifacts",
})
RESULT_STATUSES = frozenset({
    "committed", "resolved", "succeeded", "noop", "needs_confirmation", "ambiguous",
    "invalid", "not_found", "forbidden", "conflict", "failed",
})
_ENGAGEMENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


@dataclass(frozen=True)
class ProductToolResult:
    """Safe structured outcome emitted independently of model-visible text."""

    status: str
    code: str
    operation: str
    message: str = ""
    resource: Mapping[str, Any] | None = None
    destination: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, str):
            raise ValueError("tool result status must be a string")
        if not isinstance(self.code, str):
            raise ValueError("tool result code must be a string")
        if not isinstance(self.operation, str):
            raise ValueError("tool result operation must be a string")
        if self.status not in RESULT_STATUSES:
            raise ValueError(f"unsupported tool result status: {self.status}")
        if not isinstance(self.code, str) or not self.code:
            raise ValueError("tool result code is required")
        if not isinstance(self.operation, str) or not self.operation:
            raise ValueError("tool result operation is required")
        if not isinstance(self.message, str):
            raise ValueError("tool result message must be a string")
        if self.resource is not None and not isinstance(self.resource, Mapping):
            raise ValueError("tool result resource must be an object")
        if self.destination is not None:
            if self.status not in {"committed", "resolved"}:
                raise ValueError("only committed or resolved results may carry a destination")
            validate_destination(self.destination)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "code": self.code,
            "operation": self.operation,
            "message": self.message,
        }
        if self.resource is not None:
            result["resource"] = dict(self.resource)
        if self.destination is not None:
            result["destination"] = dict(self.destination)
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProductToolResult":
        """Reconstruct only the accepted public result shape at transport boundaries."""
        if not isinstance(value, Mapping):
            raise ValueError("tool result must be an object")
        allowed = {"status", "code", "operation", "message", "resource", "destination"}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unsupported tool result fields: {sorted(unknown)}")
        required = {"status", "code", "operation"}
        if missing := required - set(value):
            raise ValueError(f"missing tool result fields: {sorted(missing)}")
        resource = value.get("resource")
        destination = value.get("destination")
        if resource is not None and not isinstance(resource, Mapping):
            raise ValueError("tool result resource must be an object")
        if destination is not None and not isinstance(destination, Mapping):
            raise ValueError("tool result destination must be an object")
        return cls(
            status=value["status"], code=value["code"], operation=value["operation"],
            message=value.get("message", ""), resource=dict(resource) if resource is not None else None,
            destination=dict(destination) if destination is not None else None,
        )


def validate_destination(destination: Mapping[str, Any]) -> None:
    destination_id = destination.get("id")
    path = destination.get("path")
    if destination_id not in DESTINATION_IDS:
        raise ValueError("unknown destination id")
    if not isinstance(path, str):
        raise ValueError("destination path is required")
    engagement_id = destination.get("engagementId")
    scoped = destination_id in {"engagement_overview", "engagement_tasks", "engagement_artifacts"}
    if scoped != isinstance(engagement_id, str):
        raise ValueError("destination engagement shape is invalid")
    if scoped and not _ENGAGEMENT_ID_RE.fullmatch(engagement_id):
        raise ValueError("destination engagement ID is invalid")
    expected = {
        "engagements": "/engagements",
        "engagement_overview": f"/engagements/{engagement_id}",
        "engagement_tasks": f"/engagements/{engagement_id}/tasks",
        "engagement_artifacts": f"/engagements/{engagement_id}/artifacts",
    }[destination_id]
    if path != expected:
        raise ValueError("destination path does not match catalog")
