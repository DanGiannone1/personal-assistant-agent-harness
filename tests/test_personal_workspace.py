"""Focused behavioral evidence for private personal-workspace records."""

from __future__ import annotations

from copy import deepcopy

from fastapi import HTTPException
from fastapi.testclient import TestClient

import app as orchestrator
import appdb
from workbench_core.personal_workspace import MAX_TASKS, PersonalNotFound, PersonalWorkspaceError, PersonalWorkspaceService


def _state() -> dict:
    return {"currentRoute": "/home", "personalTasks": [], "calendarEvents": [], "reminders": []}


class MemoryPersonalRepository:
    def __init__(self) -> None:
        self.states = {"dan": _state(), "ava": _state()}
        self.retry_once = False

    def load(self, actor_id: str) -> dict | None:
        state = self.states.get(actor_id)
        return deepcopy(state) if state is not None else None

    def update(self, actor_id: str, mutator):
        state = self.states.get(actor_id)
        if state is None:
            raise PersonalNotFound()
        if self.retry_once:
            self.retry_once = False
            discarded = deepcopy(state)
            mutator(discarded)  # an ETag-losing attempt never becomes authoritative
            state["personalTasks"].append({
                "id": "t-concurrent", "title": "Concurrent write", "status": "To do",
                "priority": "Low", "group": "General", "dueDate": "", "notes": "",
                "createdAt": "2030-01-01T00:00:00+00:00",
            })
        return mutator(state)

    @staticmethod
    def new_id(prefix: str, values: list[dict]) -> str:
        ids = {value["id"] for value in values}
        number = 1
        while f"{prefix}-{number}" in ids:
            number += 1
        return f"{prefix}-{number}"

    @staticmethod
    def now_iso() -> str:
        return "2030-01-01T00:00:00+00:00"


class AllowRequest:
    async def authenticate(self, _request):
        return None


def _client(monkeypatch, repository: MemoryPersonalRepository):
    actor = {"id": "dan"}
    owners = {"session-dan": "dan", "session-ava": "ava"}

    async def owned(session_id: str, uid: str) -> None:
        if owners.get(session_id) != uid:
            raise HTTPException(status_code=404, detail="Session not found")

    monkeypatch.setattr(orchestrator, "api_authenticator", AllowRequest())
    monkeypatch.setattr(orchestrator, "_require_owned_session", owned)
    monkeypatch.setattr(
        orchestrator, "_personal_workspace_service", PersonalWorkspaceService(repository))
    orchestrator.app.dependency_overrides[orchestrator.current_user] = lambda: actor["id"]
    client = TestClient(orchestrator.app)
    return client, actor


def test_owner_can_crud_private_tasks_events_and_reminders(monkeypatch) -> None:
    repository = MemoryPersonalRepository()
    client, _actor = _client(monkeypatch, repository)
    try:
        task = client.post("/sessions/session-dan/tasks", json={
            "title": f"  {'x' * 300}  ", "status": "To do", "priority": "High",
            "group": "  Work ", "dueDate": "2030-02-28", "notes": "  private  ",
        })
        assert task.status_code == 201
        assert task.json() | {"createdAt": "ignored"} == {
            "id": "t-1", "title": "x" * 300, "status": "To do", "priority": "High",
            "group": "Work", "dueDate": "2030-02-28", "notes": "private", "createdAt": "ignored",
        }
        assert client.patch("/sessions/session-dan/tasks/t-1", json={"status": "Done"}).json()["status"] == "Done"
        assert client.delete("/sessions/session-dan/tasks/t-1").status_code == 204

        event = client.post("/sessions/session-dan/events", json={
            "title": "Planning", "date": "2030-02-28", "start": "09:00", "end": "10:00",
            "type": "Focus", "notes": "private",
        })
        assert event.status_code == 201
        assert event.json()["id"] == "e-1"
        assert client.patch("/sessions/session-dan/events/e-1", json={"end": "10:30"}).json()["end"] == "10:30"
        assert client.delete("/sessions/session-dan/events/e-1").status_code == 204

        reminder = client.post("/sessions/session-dan/schedules", json={
            "title": "Weekly review", "frequency": "weekly",
            "dueDate": "2030-01-07", "time": "09:00", "timezone": "UTC", "daysOfWeek": [0],
        })
        assert reminder.status_code == 201
        assert reminder.json()["id"] == "s-1"
        assert reminder.json()["message"] == ""
        assert reminder.json()["nextDueAt"]
        assert client.patch("/sessions/session-dan/schedules/s-1", json={"enabled": False}).json()["nextDueAt"] is None
        assert client.delete("/sessions/session-dan/schedules/s-1").status_code == 204
        assert repository.states["dan"] == _state()
    finally:
        orchestrator.app.dependency_overrides.clear()
        client.close()


def test_other_actor_cannot_use_session_or_forge_private_record_id(monkeypatch) -> None:
    repository = MemoryPersonalRepository()
    client, actor = _client(monkeypatch, repository)
    try:
        created = client.post("/sessions/session-dan/tasks", json={"title": "Dan only"})
        assert created.status_code == 201
        actor["id"] = "ava"
        assert client.get("/sessions/session-dan/app/state").status_code == 404
        assert client.patch("/sessions/session-ava/tasks/t-1", json={"title": "forged"}).status_code == 404
        assert repository.states["dan"]["personalTasks"][0]["title"] == "Dan only"
        assert repository.states["ava"]["personalTasks"] == []
    finally:
        orchestrator.app.dependency_overrides.clear()
        client.close()


def test_personal_validation_rejects_invalid_data_without_mutation(monkeypatch) -> None:
    repository = MemoryPersonalRepository()
    client, _actor = _client(monkeypatch, repository)
    try:
        assert client.post("/sessions/session-dan/tasks", json={"title": "  "}).status_code == 422
        assert client.post("/sessions/session-dan/tasks", json={"title": "x" * 301}).status_code == 422
        assert client.post("/sessions/session-dan/tasks", json={"title": "ok", "status": "Unknown"}).status_code == 422
        assert client.post("/sessions/session-dan/tasks", json={"title": "ok", "owner": "ava"}).status_code == 422
        assert client.post("/sessions/session-dan/events", json={
            "title": "bad", "date": "2030-02-30", "start": "10:00", "end": "09:00",
        }).status_code == 422
        assert client.post("/sessions/session-dan/events", json={"title": "bad", "date": "2030-02-28", "type": "Other"}).status_code == 422
        assert client.post("/sessions/session-dan/schedules", json={
            "title": "bad", "frequency": "weekly", "dueDate": "2030-01-07", "time": "9:00",
            "timezone": "Not/AZone", "daysOfWeek": [7],
        }).status_code == 422
        assert client.post("/sessions/session-dan/schedules", json={
            "title": "bad", "frequency": "monthly", "dueDate": "2030-01-07", "time": "09:00",
        }).status_code == 422
        assert client.patch("/sessions/session-dan/tasks/not-an-id", json={"title": "no"}).status_code == 422
        assert repository.states["dan"] == _state()
    finally:
        orchestrator.app.dependency_overrides.clear()
        client.close()


def test_retrying_etag_safe_mutation_preserves_concurrent_private_write() -> None:
    repository = MemoryPersonalRepository()
    service = PersonalWorkspaceService(repository)
    repository.retry_once = True
    created = service.create_task("dan", {"title": "Retry-safe", "status": "To do", "priority": "Medium"})
    assert created.record["id"] == "t-1"
    assert {item["id"] for item in repository.states["dan"]["personalTasks"]} == {"t-concurrent", "t-1"}


def test_private_collection_limits_are_enforced() -> None:
    repository = MemoryPersonalRepository()
    repository.states["dan"]["personalTasks"] = [{"id": f"t-{index}"} for index in range(MAX_TASKS)]
    service = PersonalWorkspaceService(repository)
    try:
        service.create_task("dan", {"title": "one too many", "status": "To do", "priority": "Medium"})
    except PersonalWorkspaceError as exc:
        assert "limit" in str(exc)
    else:
        raise AssertionError("task collection limit must reject a new task")


def test_supported_app_state_includes_private_and_engagement_records(monkeypatch) -> None:
    user = {"id": "dan", "username": "dan", "displayName": "Dan", "persona": {}}
    personal = {
        "currentRoute": "/home", "personalTasks": [{"id": "t-1"}],
        "calendarEvents": [{"id": "e-1"}], "reminders": [{"id": "s-1"}],
    }
    monkeypatch.setattr(appdb, "get_user", lambda uid: user if uid == "dan" else None)
    monkeypatch.setattr(appdb, "load_personal_workspace", lambda uid: personal if uid == "dan" else None)
    monkeypatch.setattr(appdb, "list_engagements_for", lambda uid: [{"id": "eng-1"}] if uid == "dan" else [])
    state = appdb.supported_app_state_for("dan")
    assert state["personalTasks"] == personal["personalTasks"]
    assert state["calendarEvents"] == personal["calendarEvents"]
    assert state["reminders"] == personal["reminders"]
    assert state["engagements"] == [{"id": "eng-1"}]
    assert not {"tasks", "events", "schedules"} & set(state)
