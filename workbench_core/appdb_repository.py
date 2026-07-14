"""Adapter that keeps legacy ``appdb`` persistence below the shared core."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from .engagements import _Mutation, Outcome


class AppdbEngagementRepository:
    def __init__(self, appdb: Any):
        self._appdb = appdb

    def create(self, actor_id: str, values: dict[str, Any]) -> dict[str, Any]:
        return self._appdb.new_engagement(
            actor_id,
            values.get("name", ""),
            values.get("description", ""),
            customer=values.get("customer", ""),
            status=values.get("status", ""),
            status_note=values.get("statusNote", ""),
            start_date=values.get("startDate", ""),
            target_date=values.get("targetDate", ""),
        )

    def load(self, engagement_id: str) -> dict[str, Any] | None:
        return self._appdb.load_engagement(engagement_id)

    def list_for(self, actor_id: str) -> list[dict[str, Any]]:
        return self._appdb.list_engagements_for(actor_id)

    def update(self, engagement_id: str, mutator: Callable[[dict[str, Any]], _Mutation]) -> Outcome:
        def wrapped(record: dict[str, Any]) -> Outcome:
            mutation = mutator(record)
            if not mutation.commit:
                raise self._appdb.AbortWrite(mutation.outcome)
            return mutation.outcome
        outcome = self._appdb.update_engagement(engagement_id, wrapped)
        if outcome.record is not None:
            return replace(outcome, record={key: value for key, value in outcome.record.items() if not key.startswith("_")})
        return outcome

    def log_activity(self, engagement: dict[str, Any], actor_id: str, action: str, detail: str) -> None:
        self._appdb.log_activity(engagement, actor_id, action, detail)
