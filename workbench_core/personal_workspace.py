"""Rules for an actor's durable, private Tasks, Calendar, and Reminders."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


TASK_STATUSES = ("To do", "In progress", "Blocked", "Done")
TASK_PRIORITIES = ("Low", "Medium", "High")
EVENT_TYPES = ("Meeting", "Focus", "Personal")
SCHEDULE_FREQUENCIES = ("once", "daily", "weekly")

MAX_TASKS = 500
MAX_EVENTS = 500
MAX_SCHEDULES = 100
MAX_SUBTASKS = 50
MAX_TITLE_CHARS = 300
MAX_NOTES_CHARS = 4_000
MAX_GROUP_CHARS = 120
MAX_REMINDER_MESSAGE_CHARS = 2_000

_ID_RE = re.compile(r"^[tes]-[a-z0-9]{1,64}$")
_TIME_RE = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")


class PersonalWorkspaceRepository(Protocol):
    def load(self, actor_id: str) -> dict[str, Any] | None: ...
    def update(self, actor_id: str, mutator: Callable[[dict[str, Any]], Any]) -> Any: ...
    def new_id(self, prefix: str, values: list[dict[str, Any]]) -> str: ...
    def now_iso(self) -> str: ...


class PersonalWorkspaceError(ValueError):
    """A client-safe invalid-input error."""


class PersonalNotFound(LookupError):
    """A resource is absent from the authenticated actor's aggregate."""


@dataclass(frozen=True)
class PersonalOutcome:
    record: dict[str, Any]
    changed: bool = True


class PersonalWorkspaceService:
    """Validation and mutation rules for one actor-owned aggregate.

    The actor ID is deliberately an argument to every operation: transport code
    supplies it solely from authenticated identity, while the repository maps it
    to a single private Cosmos document. No resource lookup crosses aggregates.
    """

    def __init__(self, repository: PersonalWorkspaceRepository):
        self._repository = repository

    def state(self, actor_id: str) -> dict[str, Any]:
        record = self._repository.load(actor_id)
        if record is None:
            raise PersonalNotFound("personal workspace not found")
        return record

    def create_task(self, actor_id: str, values: dict[str, Any]) -> PersonalOutcome:
        normalized = self._task_values(values, creating=True)
        created: dict[str, Any] = {}

        def mutate(state: dict[str, Any]) -> None:
            tasks = state.setdefault("personalTasks", [])
            self._bounded(tasks, MAX_TASKS, "tasks")
            task = {
                "id": self._repository.new_id("t", tasks),
                **normalized,
                "subtasks": [],
                "createdAt": self._repository.now_iso(),
            }
            tasks.append(task)
            created.clear()
            created.update(task)

        self._repository.update(actor_id, mutate)
        return PersonalOutcome(dict(created))

    def update_task(self, actor_id: str, task_id: str, values: dict[str, Any]) -> PersonalOutcome:
        self._valid_id(task_id, "t")
        normalized = self._task_values(values, creating=False)
        updated: dict[str, Any] = {}

        def mutate(state: dict[str, Any]) -> None:
            task = self._find(state.setdefault("personalTasks", []), task_id)
            if task is None:
                raise PersonalNotFound("task not found")
            task.update(normalized)
            updated.clear()
            updated.update(task)

        self._repository.update(actor_id, mutate)
        return PersonalOutcome(dict(updated))

    def delete_task(self, actor_id: str, task_id: str) -> None:
        self._delete(actor_id, "personalTasks", task_id, "t")

    def add_subtask(self, actor_id: str, task_id: str, text: Any) -> PersonalOutcome:
        self._valid_id(task_id, "t")
        normalized = self._text(text, "text", MAX_TITLE_CHARS, required=True)

        def change(subtasks: list[dict[str, Any]]) -> None:
            self._bounded(subtasks, MAX_SUBTASKS, "subtasks")
            subtasks.append({"text": normalized, "done": False})

        return self._mutate_subtasks(actor_id, task_id, change)

    def set_subtask(self, actor_id: str, task_id: str, index: Any, done: Any) -> PersonalOutcome:
        self._valid_id(task_id, "t")
        if not isinstance(done, bool):
            raise PersonalWorkspaceError("done must be a boolean")

        def change(subtasks: list[dict[str, Any]]) -> None:
            self._subtask_at(subtasks, index)["done"] = done

        return self._mutate_subtasks(actor_id, task_id, change)

    def delete_subtask(self, actor_id: str, task_id: str, index: Any) -> PersonalOutcome:
        self._valid_id(task_id, "t")

        def change(subtasks: list[dict[str, Any]]) -> None:
            subtasks.remove(self._subtask_at(subtasks, index))

        return self._mutate_subtasks(actor_id, task_id, change)

    def _mutate_subtasks(self, actor_id: str, task_id: str, change) -> PersonalOutcome:
        updated: dict[str, Any] = {}

        def mutate(state: dict[str, Any]) -> None:
            task = self._find(state.setdefault("personalTasks", []), task_id)
            if task is None:
                raise PersonalNotFound("task not found")
            change(task.setdefault("subtasks", []))
            updated.clear()
            updated.update(task)

        self._repository.update(actor_id, mutate)
        return PersonalOutcome(dict(updated))

    @staticmethod
    def _subtask_at(subtasks: list[dict[str, Any]], index: Any) -> dict[str, Any]:
        if isinstance(index, bool) or not isinstance(index, int) or index < 0 or index >= len(subtasks):
            raise PersonalNotFound("subtask not found")
        return subtasks[index]

    def create_event(self, actor_id: str, values: dict[str, Any]) -> PersonalOutcome:
        normalized = self._event_values(values, creating=True)
        created: dict[str, Any] = {}

        def mutate(state: dict[str, Any]) -> None:
            events = state.setdefault("calendarEvents", [])
            self._bounded(events, MAX_EVENTS, "events")
            event = {"id": self._repository.new_id("e", events), **normalized}
            events.append(event)
            created.clear()
            created.update(event)

        self._repository.update(actor_id, mutate)
        return PersonalOutcome(dict(created))

    def update_event(self, actor_id: str, event_id: str, values: dict[str, Any]) -> PersonalOutcome:
        self._valid_id(event_id, "e")
        normalized = self._event_values(values, creating=False)
        updated: dict[str, Any] = {}

        def mutate(state: dict[str, Any]) -> None:
            event = self._find(state.setdefault("calendarEvents", []), event_id)
            if event is None:
                raise PersonalNotFound("event not found")
            candidate = dict(event)
            candidate.update(normalized)
            self._validate_event_range(candidate)
            event.update(normalized)
            updated.clear()
            updated.update(event)

        self._repository.update(actor_id, mutate)
        return PersonalOutcome(dict(updated))

    def delete_event(self, actor_id: str, event_id: str) -> None:
        self._delete(actor_id, "calendarEvents", event_id, "e")

    def create_schedule(self, actor_id: str, values: dict[str, Any]) -> PersonalOutcome:
        normalized = self._schedule_values(values, creating=True)
        created: dict[str, Any] = {}

        def mutate(state: dict[str, Any]) -> None:
            schedules = state.setdefault("reminders", [])
            self._bounded(schedules, MAX_SCHEDULES, "schedules")
            schedule = {
                "id": self._repository.new_id("s", schedules),
                **normalized,
                "enabled": True,
                "nextDueAt": self._next_due_at(normalized),
                "createdAt": self._repository.now_iso(),
            }
            schedules.append(schedule)
            created.clear()
            created.update(schedule)

        self._repository.update(actor_id, mutate)
        return PersonalOutcome(dict(created))

    def update_schedule(self, actor_id: str, schedule_id: str, values: dict[str, Any]) -> PersonalOutcome:
        self._valid_id(schedule_id, "s")
        normalized = self._schedule_values(values, creating=False)
        updated: dict[str, Any] = {}

        def mutate(state: dict[str, Any]) -> None:
            schedule = self._find(state.setdefault("reminders", []), schedule_id)
            if schedule is None:
                raise PersonalNotFound("reminder not found")
            candidate = dict(schedule)
            candidate.update(normalized)
            self._validate_schedule(candidate)
            if {"frequency", "dueDate", "time", "timezone", "daysOfWeek", "enabled"} & set(normalized):
                normalized["nextDueAt"] = self._next_due_at(candidate)
            schedule.update(normalized)
            updated.clear()
            updated.update(schedule)

        self._repository.update(actor_id, mutate)
        return PersonalOutcome(dict(updated))

    def delete_schedule(self, actor_id: str, schedule_id: str) -> None:
        self._delete(actor_id, "reminders", schedule_id, "s")

    def _delete(self, actor_id: str, collection: str, resource_id: str, prefix: str) -> None:
        self._valid_id(resource_id, prefix)

        def mutate(state: dict[str, Any]) -> None:
            values = state.setdefault(collection, [])
            if self._find(values, resource_id) is None:
                raise PersonalNotFound("resource not found")
            state[collection] = [item for item in values if item.get("id") != resource_id]

        self._repository.update(actor_id, mutate)

    def _task_values(self, values: dict[str, Any], *, creating: bool) -> dict[str, Any]:
        allowed = {"title", "status", "priority", "group", "dueDate", "notes"}
        self._unknown(values, allowed)
        out: dict[str, Any] = {}
        for field in allowed & set(values):
            value = values[field]
            if field == "title":
                out[field] = self._text(value, field, MAX_TITLE_CHARS, required=True)
            elif field == "notes":
                out[field] = self._text(value, field, MAX_NOTES_CHARS)
            elif field == "group":
                out[field] = self._text(value, field, MAX_GROUP_CHARS) or "General"
            elif field == "dueDate":
                out[field] = self._date(value, field, optional=True)
            else:
                out[field] = self._enum(value, field, TASK_STATUSES if field == "status" else TASK_PRIORITIES)
        if creating:
            missing = {"title", "status", "priority"} - set(out)
            if missing:
                raise PersonalWorkspaceError(f"{sorted(missing)[0]} is required")
            out.setdefault("group", "General")
            out.setdefault("dueDate", "")
            out.setdefault("notes", "")
        if not creating and not out:
            raise PersonalWorkspaceError("at least one field is required")
        return out

    def _event_values(self, values: dict[str, Any], *, creating: bool) -> dict[str, Any]:
        allowed = {"title", "date", "start", "end", "type", "notes"}
        self._unknown(values, allowed)
        out: dict[str, Any] = {}
        for field in allowed & set(values):
            value = values[field]
            if field == "title":
                out[field] = self._text(value, field, MAX_TITLE_CHARS, required=True)
            elif field == "date":
                out[field] = self._date(value, field)
            elif field in {"start", "end"}:
                out[field] = self._time(value, field)
            elif field == "type":
                out[field] = self._enum(value, field, EVENT_TYPES)
            else:
                out[field] = self._text(value, field, MAX_NOTES_CHARS)
        if creating:
            missing = {"title", "date"} - set(out)
            if missing:
                raise PersonalWorkspaceError(f"{sorted(missing)[0]} is required")
            out.setdefault("start", "")
            out.setdefault("end", "")
            out.setdefault("type", "Meeting")
            out.setdefault("notes", "")
            self._validate_event_range(out)
        if not creating and not out:
            raise PersonalWorkspaceError("at least one field is required")
        return out

    def _schedule_values(self, values: dict[str, Any], *, creating: bool) -> dict[str, Any]:
        allowed = {"title", "message", "frequency", "dueDate", "time", "timezone", "daysOfWeek", "enabled"}
        self._unknown(values, allowed)
        out: dict[str, Any] = {}
        for field in allowed & set(values):
            value = values[field]
            if field == "title":
                out[field] = self._text(value, field, MAX_TITLE_CHARS, required=True)
            elif field == "message":
                out[field] = self._text(value, field, MAX_REMINDER_MESSAGE_CHARS)
            elif field == "frequency":
                out[field] = self._enum(value, field, SCHEDULE_FREQUENCIES, lower=True)
            elif field == "dueDate":
                out[field] = self._date(value, field)
            elif field == "time":
                out[field] = self._time(value, field, required=True)
            elif field == "timezone":
                out[field] = self._timezone(value)
            elif field == "daysOfWeek":
                out[field] = self._days(value)
            elif not isinstance(value, bool):
                raise PersonalWorkspaceError("enabled must be a boolean")
            else:
                out[field] = value
        if creating:
            missing = {"title", "frequency", "dueDate", "time", "timezone", "daysOfWeek"} - set(out)
            if missing:
                raise PersonalWorkspaceError(f"{sorted(missing)[0]} is required")
            self._validate_schedule(out)
        if not creating and not out:
            raise PersonalWorkspaceError("at least one field is required")
        return out

    @staticmethod
    def _find(values: list[dict[str, Any]], resource_id: str) -> dict[str, Any] | None:
        return next((value for value in values if value.get("id") == resource_id), None)

    @staticmethod
    def _bounded(values: list[dict[str, Any]], maximum: int, field: str) -> None:
        if len(values) >= maximum:
            raise PersonalWorkspaceError(f"{field} limit reached")

    @staticmethod
    def _unknown(values: dict[str, Any], allowed: set[str]) -> None:
        unknown = set(values) - allowed
        if unknown:
            raise PersonalWorkspaceError(f"unknown field: {sorted(unknown)[0]}")

    @staticmethod
    def _text(value: Any, field: str, maximum: int, *, required: bool = False) -> str:
        if not isinstance(value, str):
            raise PersonalWorkspaceError(f"{field} must be a string")
        value = value.strip()
        if required and not value:
            raise PersonalWorkspaceError(f"{field} must not be blank")
        if len(value) > maximum:
            raise PersonalWorkspaceError(f"{field} must be at most {maximum} characters")
        return value

    @staticmethod
    def _enum(value: Any, field: str, choices: tuple[str, ...], *, lower: bool = False) -> str:
        value = PersonalWorkspaceService._text(value, field, 64, required=True)
        candidate = value.lower() if lower else value
        if candidate not in choices:
            raise PersonalWorkspaceError(f"{field} must be one of {list(choices)}")
        return candidate

    @staticmethod
    def _date(value: Any, field: str, *, optional: bool = False) -> str:
        value = PersonalWorkspaceService._text(value, field, 10)
        if optional and not value:
            return ""
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise PersonalWorkspaceError(f"{field} must be a valid YYYY-MM-DD date") from exc
        if parsed.isoformat() != value:
            raise PersonalWorkspaceError(f"{field} must be a valid YYYY-MM-DD date")
        return value

    @staticmethod
    def _time(value: Any, field: str, *, required: bool = False) -> str:
        value = PersonalWorkspaceService._text(value, field, 5)
        if not value and not required:
            return ""
        if not _TIME_RE.fullmatch(value):
            raise PersonalWorkspaceError(f"{field} must be a valid HH:MM time")
        return value

    @staticmethod
    def _timezone(value: Any) -> str:
        value = PersonalWorkspaceService._text(value, "timezone", 128, required=True)
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise PersonalWorkspaceError("timezone must be a valid IANA time zone") from exc
        return value

    @staticmethod
    def _days(value: Any) -> list[int]:
        if not isinstance(value, list) or len(value) > 7:
            raise PersonalWorkspaceError("daysOfWeek must contain at most seven days")
        if any(isinstance(day, bool) or not isinstance(day, int) or day < 0 or day > 6 for day in value):
            raise PersonalWorkspaceError("daysOfWeek must contain integers from 0 to 6")
        if len(set(value)) != len(value):
            raise PersonalWorkspaceError("daysOfWeek must not contain duplicates")
        return sorted(value)

    @staticmethod
    def _validate_event_range(event: dict[str, Any]) -> None:
        start, end = event.get("start", ""), event.get("end", "")
        if start and end and end < start:
            raise PersonalWorkspaceError("end must not be before start")

    @staticmethod
    def _validate_schedule(schedule: dict[str, Any]) -> None:
        frequency = schedule.get("frequency")
        days = schedule.get("daysOfWeek")
        if frequency == "weekly" and not days:
            raise PersonalWorkspaceError("weekly reminder needs at least one day")
        if frequency == "daily" and days:
            raise PersonalWorkspaceError("daily reminder must not include daysOfWeek")
        if frequency == "once" and days:
            raise PersonalWorkspaceError("one-time reminder must not include daysOfWeek")

    @staticmethod
    def _next_due_at(schedule: dict[str, Any]) -> str | None:
        """Calculate display-only next due time; this never schedules work or delivery."""
        if not schedule.get("enabled", True):
            return None
        zone = ZoneInfo(schedule["timezone"])
        due_time = time.fromisoformat(schedule["time"])
        anchor = date.fromisoformat(schedule["dueDate"])
        now = datetime.now(timezone.utc)
        candidate = datetime.combine(anchor, due_time, zone).astimezone(timezone.utc)
        frequency = schedule["frequency"]
        if frequency == "once":
            return candidate.isoformat() if candidate >= now else None
        if frequency == "daily":
            while candidate < now:
                candidate += timedelta(days=1)
            return candidate.isoformat()
        days = set(schedule["daysOfWeek"])
        while candidate < now or candidate.astimezone(zone).weekday() not in days:
            candidate += timedelta(days=1)
        return candidate.isoformat()

    @staticmethod
    def _valid_id(value: Any, prefix: str) -> None:
        if not isinstance(value, str) or not _ID_RE.fullmatch(value) or not value.startswith(f"{prefix}-"):
            raise PersonalWorkspaceError("malformed resource ID")
