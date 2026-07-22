---
name: tasks
description: "Create, update, delete, and review the user's private to-do tasks and their subtasks. USE FOR: adding, changing, listing, or removing tasks; marking work done; checking what's due or overdue; adding a subtask. DO NOT USE FOR: shared Engagement tasks, calendar events, or reminders."
compatibility:
  product: CSA Workbench
  tools: list_tasks, create_task, update_task, delete_task, and add_subtask
metadata:
  owner: csa-workbench
  version: "1.0.0"
allowed-tools: list_tasks create_task update_task delete_task add_subtask
---

# Tasks

**UTILITY SKILL**

**INVOKES:** `list_tasks`, `create_task`, `update_task`, `delete_task`, `add_subtask`.

Use this skill for anything about the user's own private to-do list — never a shared
Engagement's tasks. Typical requests: "add a task to review the proposal by Friday", "mark the
planning doc in progress", "what's overdue on my list", "delete the gym task", "add a subtask to
the design slides task".

## USE FOR

- Creating, updating, or deleting a private task.
- Listing tasks or asking what is due or overdue.
- Adding a subtask to an existing task.

## DO NOT USE FOR

- Shared Engagement tasks (use the Engagement tools instead).
- Calendar events or reminders (use the calendar or reminder tools instead).

## Tools

- `list_tasks()` — every task with its status, priority, group, due date, a server-computed
  `overdue` flag, and subtask progress. `overdue` is only true for a task with a due date in the
  past whose status is not "Done".
- `create_task(title, status, priority, group, due_date, notes)` — only `title` is required; new
  tasks default to status "To do", priority "Medium", group "General", and no due date.
- `update_task(task_id, ...)` — pass only the fields to change.
- `delete_task(task_id)` — remove a task.
- `add_subtask(task_id, text)` — append a subtask to a task.

## Exact IDs, not titles

`update_task`, `delete_task`, and `add_subtask` take the task's exact ID (looks like `t-1`), not
its title. If the user names a task in words, call `list_tasks` first and match the wording to
exactly one task. If more than one task plausibly matches, list the candidates and ask which one
— never guess an ID. If none match, say the task could not be found; don't invent one.

## Statuses & priorities

- Statuses are exactly: "To do", "In progress", "Blocked", "Done".
- Priorities are exactly: "Low", "Medium", "High".
- Map the user's phrasing to these exact values (e.g. "in progress" -> "In progress", "high pri"
  -> "High").

## How to work

- Dates are YYYY-MM-DD. Resolve relative words ("today", "tomorrow", "Friday") against the
  current date rather than guessing it.
- For "what's overdue", use the `overdue` flag from `list_tasks` and cite the specific tasks —
  never judge dates yourself.
- Confirm only what the tool actually returned — never claim a task was created, updated, or
  deleted unless the call succeeded.
