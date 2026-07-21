"""The small shared Engagement application service.

Persistence and user lookup are deliberately supplied by the caller so this module
can be imported by both the orchestrator and the session runtime without bringing
their framework or Cosmos dependencies into the domain rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Protocol


ROLE_RANK = {"viewer": 0, "editor": 1, "owner": 2}
ROLES = tuple(ROLE_RANK)
STATUSES = ("green", "yellow", "red")


@dataclass(frozen=True)
class Outcome:
    """A transport-neutral, typed result for an Engagement operation."""

    status: str
    operation: str
    record: dict[str, Any] | None = None
    target_user_id: str | None = None
    changed_fields: tuple[str, ...] = ()
    errors: dict[str, str] = field(default_factory=dict)
    code: str | None = None


@dataclass(frozen=True)
class _Mutation:
    outcome: Outcome
    commit: bool


class EngagementRepository(Protocol):
    def create(self, actor_id: str, values: dict[str, Any]) -> dict[str, Any]: ...
    def load(self, engagement_id: str) -> dict[str, Any] | None: ...
    def list_for(self, actor_id: str) -> list[dict[str, Any]]: ...
    def update(self, engagement_id: str, mutator: Callable[[dict[str, Any]], _Mutation]) -> Outcome: ...
    def log_activity(self, engagement: dict[str, Any], actor_id: str, action: str, detail: str) -> None: ...


class EngagementService:
    """Authorization, validation, and resulting-state rules for Engagement basics."""

    def __init__(self, repository: EngagementRepository, user_lookup: Callable[[str], dict[str, Any] | None]):
        self._repository = repository
        self._user_lookup = user_lookup

    def list(self, actor_id: str) -> Outcome:
        return Outcome("succeeded", "list", record={"engagements": self._repository.list_for(actor_id)})

    def get(self, actor_id: str, engagement_id: str) -> Outcome:
        record = self._visible(actor_id, engagement_id)
        if record is None:
            return Outcome("not_found", "get", code="engagement.not_found")
        return Outcome("succeeded", "get", record=record)

    def resolve(self, actor_id: str, reference: str) -> Outcome:
        """Resolve only within the actor's permitted Engagements."""
        ref = (reference or "").strip()
        if not ref:
            return Outcome("invalid", "resolve", errors={"engagement": "required"})
        records = self._repository.list_for(actor_id)
        exact_id = next((item for item in records if item.get("id") == ref), None)
        if exact_id:
            return Outcome("resolved", "resolve", record=exact_id)
        exact_name = [item for item in records if (item.get("name") or "").lower() == ref.lower()]
        if len(exact_name) == 1:
            return Outcome("resolved", "resolve", record=exact_name[0])
        if len(exact_name) > 1:
            return Outcome("ambiguous", "resolve", code="engagement.ambiguous")
        partial = [item for item in records if ref.lower() in (item.get("name") or "").lower()]
        if len(partial) == 1:
            return Outcome("resolved", "resolve", record=partial[0])
        return Outcome("not_found" if not partial else "ambiguous", "resolve", code="engagement.not_found")

    def create(self, actor_id: str, values: dict[str, Any]) -> Outcome:
        normalized, errors = self._normalize(values, creating=True)
        if not errors:
            errors.update(self._validate_state({"status": "green", "statusNote": "", **normalized}))
        if errors:
            return Outcome("invalid", "create", errors=errors)
        if normalized.get("status", "green") == "green":
            normalized["statusNote"] = ""
        existing = next(
            (record for record in self._repository.list_for(actor_id)
             if record.get("createdBy") == actor_id
             and self._role(record, actor_id) == "owner"
             and (record.get("name") or "").strip().lower() == normalized["name"].lower()),
            None,
        )
        if existing is not None:
            return Outcome("noop", "create", record=existing)
        record = self._repository.create(actor_id, normalized)
        return Outcome("committed", "create", record=record, changed_fields=tuple(normalized))

    def update(self, actor_id: str, engagement_id: str, values: dict[str, Any]) -> Outcome:
        initial = self._visible(actor_id, engagement_id)
        if initial is None:
            return Outcome("not_found", "update", code="engagement.not_found")
        required = "owner" if "name" in values else "editor"

        def mutate(record: dict[str, Any]) -> _Mutation:
            denied = self._authorize(record, actor_id, required, "update")
            if denied:
                return _Mutation(denied, False)
            normalized, errors = self._normalize(values)
            if errors:
                return _Mutation(Outcome("invalid", "update", errors=errors), False)
            if not normalized:
                return _Mutation(Outcome("noop", "update", record=record), False)
            candidate = dict(record)
            candidate.update(normalized)
            if candidate.get("status") == "green":
                candidate["statusNote"] = ""
            state_errors = self._validate_state(candidate)
            if state_errors:
                return _Mutation(Outcome("invalid", "update", errors=state_errors), False)
            changed = tuple(key for key, value in candidate.items() if record.get(key) != value and key in set(normalized) | {"statusNote"})
            if not changed:
                return _Mutation(Outcome("noop", "update", record=record), False)
            for key in changed:
                record[key] = candidate[key]
            self._repository.log_activity(record, actor_id, "engagement.updated", ", ".join(changed))
            return _Mutation(Outcome("committed", "update", record=record, changed_fields=changed), True)

        return self._repository.update(engagement_id, mutate)

    def share(self, actor_id: str, engagement_id: str, user_ref: str, role: str) -> Outcome:
        initial = self._visible(actor_id, engagement_id)
        if initial is None:
            return Outcome("not_found", "share", code="engagement.not_found")
        def mutate(record: dict[str, Any]) -> _Mutation:
            denied = self._authorize(record, actor_id, "owner", "share")
            if denied:
                return _Mutation(denied, False)
            normalized_role = (role or "").strip().lower() or "viewer"
            if normalized_role not in ROLES:
                return _Mutation(Outcome("invalid", "share", errors={"role": "must be owner, editor, or viewer"}), False)
            target = self._user_lookup((user_ref or "").strip())
            if target is None or not target.get("id"):
                return _Mutation(Outcome("invalid", "share", errors={"userId": "unknown user"}), False)
            target_id = target["id"]
            existing = next((member for member in record.get("members", []) if member.get("userId") == target_id), None)
            if existing and existing.get("role") == normalized_role:
                return _Mutation(Outcome("noop", "share", record=record, target_user_id=target_id), False)
            if existing and existing.get("role") == "owner" and normalized_role != "owner":
                owners = [member for member in record.get("members", []) if member.get("role") == "owner"]
                if len(owners) == 1:
                    return _Mutation(Outcome("invalid", "share", errors={"members": "an engagement must keep at least one owner"}), False)
            if existing:
                existing["role"] = normalized_role
            else:
                record.setdefault("members", []).append({"userId": target_id, "role": normalized_role})
            self._repository.log_activity(record, actor_id, "member.added", f"{target_id} as {normalized_role}")
            return _Mutation(Outcome("committed", "share", record=record, target_user_id=target_id,
                                     changed_fields=("members",)), True)

        return self._repository.update(engagement_id, mutate)

    def remove_member(self, actor_id: str, engagement_id: str, member_id: str) -> Outcome:
        initial = self._visible(actor_id, engagement_id)
        if initial is None:
            return Outcome("not_found", "remove_member", code="engagement.not_found")

        def mutate(record: dict[str, Any]) -> _Mutation:
            denied = self._authorize(record, actor_id, "owner", "remove_member")
            if denied:
                return _Mutation(denied, False)
            target = next((member for member in record.get("members", []) if member.get("userId") == member_id), None)
            if target is None:
                return _Mutation(Outcome("not_found", "remove_member", code="member.not_found"), False)
            owners = [member for member in record.get("members", []) if member.get("role") == "owner"]
            if target.get("role") == "owner" and len(owners) == 1:
                return _Mutation(Outcome("invalid", "remove_member", errors={"members": "an engagement must keep at least one owner"}), False)
            record["members"] = [member for member in record["members"] if member.get("userId") != member_id]
            self._repository.log_activity(record, actor_id, "member.removed", member_id)
            return _Mutation(Outcome("committed", "remove_member", record=record, changed_fields=("members",)), True)

        return self._repository.update(engagement_id, mutate)

    def _visible(self, actor_id: str, engagement_id: str) -> dict[str, Any] | None:
        record = self._repository.load(engagement_id)
        return record if record and self._role(record, actor_id) else None

    def _authorize(self, record: dict[str, Any], actor_id: str, minimum: str, operation: str) -> Outcome | None:
        role = self._role(record, actor_id)
        if role is None:
            return Outcome("not_found", operation, code="engagement.not_found")
        if ROLE_RANK[role] < ROLE_RANK[minimum]:
            return Outcome("forbidden", operation, errors={"role": f"requires {minimum} access"})
        return None

    @staticmethod
    def _role(record: dict[str, Any], actor_id: str) -> str | None:
        member = next((item for item in record.get("members", []) if item.get("userId") == actor_id), None)
        return member.get("role") if member else None

    def _normalize(self, values: dict[str, Any], creating: bool = False) -> tuple[dict[str, Any], dict[str, str]]:
        allowed = {"name", "description", "customer", "status", "statusNote", "startDate", "targetDate"}
        errors: dict[str, str] = {}
        normalized: dict[str, Any] = {}
        for key, value in values.items():
            key = "statusNote" if key == "statusWhy" else key
            if key not in allowed:
                errors[key] = "unknown field"
                continue
            if value is None and not creating:
                continue
            if not isinstance(value, str):
                errors[key] = "must be a string"
                continue
            normalized[key] = value.strip()
        if creating and not normalized.get("name"):
            errors["name"] = "required"
        if "name" in normalized and not normalized["name"]:
            errors["name"] = "required"
        for field, limit in (("name", 120), ("description", 500), ("customer", 120), ("statusNote", 300)):
            if field in normalized and len(normalized[field]) > limit:
                errors[field] = f"must be at most {limit} characters"
        if "status" in normalized:
            normalized["status"] = normalized["status"].lower()
            if creating and not normalized["status"]:
                normalized["status"] = "green"
            elif normalized["status"] not in STATUSES:
                errors["status"] = "must be green, yellow, or red"
        for field in ("startDate", "targetDate"):
            if normalized.get(field):
                if len(normalized[field]) != 10:
                    errors[field] = "must be an ISO calendar date"
                    continue
                try:
                    parsed = date.fromisoformat(normalized[field])
                except ValueError:
                    errors[field] = "must be an ISO calendar date"
                    continue
                if parsed.isoformat() != normalized[field]:
                    errors[field] = "must be an ISO calendar date"
        return normalized, errors

    @staticmethod
    def _validate_state(record: dict[str, Any]) -> dict[str, str]:
        status = (record.get("status") or "green").lower()
        if status not in STATUSES:
            return {"status": "must be green, yellow, or red"}
        if status in ("yellow", "red") and not (record.get("statusNote") or "").strip():
            return {"statusNote": "yellow/red status requires a reason"}
        return {}
