---
name: calendar
description: "Create, move, delete, and review the user's private calendar events (meetings, focus blocks, personal time). USE FOR: scheduling, moving, or cancelling an event; listing the calendar or asking what's on it. DO NOT USE FOR: shared Engagement work, private tasks, or reminders."
compatibility:
  product: CSA Workbench
  tools: list_events, create_event, update_event, and delete_event
metadata:
  owner: csa-workbench
  version: "1.0.0"
allowed-tools: list_events create_event update_event delete_event
---

# Calendar

**UTILITY SKILL**

**INVOKES:** `list_events`, `create_event`, `update_event`, `delete_event`.

Use this skill for anything about the user's own private calendar. Typical requests: "schedule a
3pm meeting tomorrow", "move the design review to Thursday", "what's on my calendar today",
"cancel the standup", "block two hours for focus on Friday".

## USE FOR

- Creating, moving, or deleting a calendar event.
- Listing events or asking what is scheduled.

## DO NOT USE FOR

- Shared Engagement work (use the Engagement tools instead).
- Private tasks (use the tasks tools) or reminders (use the reminder tools).

## Tools

- `list_events()` — every event with its date, time, and type.
- `create_event(title, date, start, end, type, notes)` — `title` and `date` (YYYY-MM-DD) are
  required; `type` defaults to "Meeting".
- `update_event(event_id, ...)` — pass only the fields to change.
- `delete_event(event_id)` — cancel/remove an event.

## Exact IDs, not titles

`update_event` and `delete_event` take the event's exact ID (looks like `e-1`), not its title. If
the user names an event in words, call `list_events` first and match the wording to exactly one
event. If more than one plausibly matches, list the candidates and ask which one — never guess an
ID. If none match, say the event could not be found; don't invent one.

## Dates, times & types

- Dates are YYYY-MM-DD; times are 24-hour HH:MM. Resolve relative words ("today", "tomorrow",
  "Thursday") against the current date — never guess it.
- Event types are exactly: "Meeting", "Focus", "Personal".

## How to work

- For agenda questions, use `list_events` and cite the specific events. Tasks with due dates are
  a separate list — use `list_tasks` if the user asks about deadlines alongside events.
- Confirm only what the tool actually returned — never claim an event was created, moved, or
  deleted unless the call succeeded.
