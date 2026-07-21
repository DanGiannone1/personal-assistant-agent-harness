"""Cosmos adapter for the private personal-workspace aggregate."""

from __future__ import annotations

from typing import Any, Callable


class AppdbPersonalWorkspaceRepository:
    def __init__(self, appdb: Any):
        self._appdb = appdb

    def load(self, actor_id: str) -> dict[str, Any] | None:
        return self._appdb.load_personal_workspace(actor_id)

    def update(self, actor_id: str, mutator: Callable[[dict[str, Any]], Any]) -> Any:
        return self._appdb.update_personal_workspace(actor_id, mutator)

    def new_id(self, prefix: str, values: list[dict[str, Any]]) -> str:
        return self._appdb.new_id(prefix, values)

    def now_iso(self) -> str:
        return self._appdb._now_iso()
