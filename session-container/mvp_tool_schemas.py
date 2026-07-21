"""The one model-visible MVP tool schema catalog, shared by both adapters."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


DestinationId = Literal[
    "engagements", "engagement_overview", "engagement_tasks", "engagement_artifacts",
    "home", "tasks", "calendar", "reminders",
]

TaskStatus = Literal["To do", "In progress", "Blocked", "Done"]
TaskPriority = Literal["Low", "Medium", "High"]
EventType = Literal["Meeting", "Focus", "Personal"]
ReminderFrequency = Literal["once", "daily", "weekly"]


class NavigateCommand(BaseModel):
    destination_id: DestinationId = Field(description="CSA Workbench catalog destination ID.")
    engagement_id: str | None = Field(default=None, description="Required for engagement destinations.")


class ListEngagementsCommand(BaseModel):
    pass


class CreateEngagementCommand(BaseModel):
    name: str = Field(description="Engagement name.")
    description: str = Field(default="", description="Optional engagement description.")
    customer: str = Field(default="", description="Optional customer name.")
    target_date: str = Field(default="", description="Optional target date in YYYY-MM-DD form.")


class GetEngagementCommand(BaseModel):
    engagement_id: str = Field(description="Stable Engagement ID.")


class UpdateEngagementCommand(GetEngagementCommand):
    name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    customer: str | None = Field(default=None)
    start_date: str | None = Field(default=None)
    target_date: str | None = Field(default=None)


class SetEngagementStatusCommand(GetEngagementCommand):
    status: str = Field(description="green, yellow, or red")
    note: str = Field(default="", description="Required reason for yellow or red.")


class ShareEngagementCommand(GetEngagementCommand):
    user: str = Field(description="User ID to share with.")
    role: str = Field(default="viewer", description="viewer, editor, or owner")


# ── Personal workspace: the actor's own private Tasks, Calendar, and Reminders.
# Never shared and never scoped to an Engagement; the actor is always the
# session's bound identity, never a model-supplied argument.

class ListTasksCommand(BaseModel):
    pass


class CreateTaskCommand(BaseModel):
    title: str = Field(description="Task title.")
    status: TaskStatus = Field(default="To do", description="Task status.")
    priority: TaskPriority = Field(default="Medium", description="Task priority.")
    group: str = Field(default="General", description="Optional grouping label.")
    due_date: str = Field(default="", description="Optional due date in YYYY-MM-DD form.")
    notes: str = Field(default="", description="Optional private notes.")


class UpdateTaskCommand(BaseModel):
    task_id: str = Field(description="Stable task ID (e.g. t-1). Omit fields below to leave them unchanged.")
    title: str | None = Field(default=None)
    status: TaskStatus | None = Field(default=None)
    priority: TaskPriority | None = Field(default=None)
    group: str | None = Field(default=None)
    due_date: str | None = Field(default=None)
    notes: str | None = Field(default=None)


class DeleteTaskCommand(BaseModel):
    task_id: str = Field(description="Stable task ID (e.g. t-1).")


class AddSubtaskCommand(BaseModel):
    task_id: str = Field(description="Stable task ID (e.g. t-1).")
    text: str = Field(description="Subtask text.")


class ListEventsCommand(BaseModel):
    pass


class CreateEventCommand(BaseModel):
    title: str = Field(description="Event title.")
    date: str = Field(description="Event date in YYYY-MM-DD form.")
    start: str = Field(default="", description="Optional start time in 24-hour HH:MM form.")
    end: str = Field(default="", description="Optional end time in 24-hour HH:MM form.")
    type: EventType = Field(default="Meeting", description="Event type.")
    notes: str = Field(default="", description="Optional notes.")


class UpdateEventCommand(BaseModel):
    event_id: str = Field(description="Stable event ID (e.g. e-1). Omit fields below to leave them unchanged.")
    title: str | None = Field(default=None)
    date: str | None = Field(default=None)
    start: str | None = Field(default=None)
    end: str | None = Field(default=None)
    type: EventType | None = Field(default=None)
    notes: str | None = Field(default=None)


class DeleteEventCommand(BaseModel):
    event_id: str = Field(description="Stable event ID (e.g. e-1).")


class ListRemindersCommand(BaseModel):
    pass


class CreateReminderCommand(BaseModel):
    title: str = Field(description="Reminder title.")
    message: str = Field(default="", description="Optional reminder message.")
    frequency: ReminderFrequency = Field(description="once, daily, or weekly.")
    due_date: str = Field(description="Anchor date in YYYY-MM-DD form.")
    time: str = Field(description="Delivery time in 24-hour HH:MM form.")
    timezone: str = Field(description="IANA time zone, e.g. America/Los_Angeles.")
    days_of_week: list[int] = Field(
        default_factory=list,
        description="Required for weekly (0=Monday..6=Sunday); must be empty for once/daily.",
    )


class UpdateReminderCommand(BaseModel):
    reminder_id: str = Field(description="Stable reminder ID (e.g. s-1). Omit fields below to leave them unchanged.")
    title: str | None = Field(default=None)
    message: str | None = Field(default=None)
    frequency: ReminderFrequency | None = Field(default=None)
    due_date: str | None = Field(default=None)
    time: str | None = Field(default=None)
    timezone: str | None = Field(default=None)
    days_of_week: list[int] | None = Field(default=None)
    enabled: bool | None = Field(default=None)


class DeleteReminderCommand(BaseModel):
    reminder_id: str = Field(description="Stable reminder ID (e.g. s-1).")


ACTIVE_TOOL_SCHEMAS = {
    "navigate": NavigateCommand,
    "list_engagements": ListEngagementsCommand,
    "create_engagement": CreateEngagementCommand,
    "get_engagement": GetEngagementCommand,
    "update_engagement": UpdateEngagementCommand,
    "set_engagement_status": SetEngagementStatusCommand,
    "share_engagement": ShareEngagementCommand,
    "list_tasks": ListTasksCommand,
    "create_task": CreateTaskCommand,
    "update_task": UpdateTaskCommand,
    "delete_task": DeleteTaskCommand,
    "add_subtask": AddSubtaskCommand,
    "list_events": ListEventsCommand,
    "create_event": CreateEventCommand,
    "update_event": UpdateEventCommand,
    "delete_event": DeleteEventCommand,
    "list_reminders": ListRemindersCommand,
    "create_reminder": CreateReminderCommand,
    "update_reminder": UpdateReminderCommand,
    "delete_reminder": DeleteReminderCommand,
}
