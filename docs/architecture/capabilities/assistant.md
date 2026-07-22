# Assistant

The assistant reads and changes application records through typed product tools. The server binds
the user and session before the model runs, so the model cannot choose another user, role, or
session.

## One assistant turn

1. The API authenticates the user and confirms ownership of the session.
2. The browser adds the current date, page, saved persona, and relevant Engagement conventions to
   the request.
3. The API sends the request and navigation version to the assistant runtime.
4. The runtime locks the session for the turn.
5. The model calls supported product tools when needed.
6. Each tool checks current application data and permissions through a shared service.
7. The runtime sends structured events to the browser.
8. The browser applies valid navigation events and reloads application data after tool activity.

The current context is a small prompt addition, not a saved or trusted permission record. A failed
context request still allows the turn to proceed with the date and current page. Tools always load
current records before acting.

## Product tools

The model can call twenty tools:

| Group | Tools |
|---|---|
| Navigation | `navigate` |
| Engagements | `list_engagements`, `create_engagement`, `get_engagement`, `update_engagement`, `set_engagement_status`, `share_engagement` |
| Tasks | `list_tasks`, `create_task`, `update_task`, `delete_task`, `add_subtask` |
| Calendar | `list_events`, `create_event`, `update_event`, `delete_event` |
| Reminders | `list_reminders`, `create_reminder`, `update_reminder`, `delete_reminder` |

All tool schemas come from `session-container/mvp_tool_schemas.py`. No tool accepts a user ID, role,
or session ID.

## Product skills

Deep Agents can load four approved skills:

- `engagement-meeting-prep` prepares a read-only meeting brief from one authorized Engagement.
- `tasks` manages the user's private task list.
- `calendar` manages the user's private calendar.
- `weekly-review` reviews tasks, reschedules overdue work, checks the calendar, protects focus time,
  and selects three priorities.

The skill loader can read only those four `SKILL.md` files. It cannot read arbitrary repository or
workspace files through the internal loader.

## Structured results

Product tools return a `ProductToolResult` with a status, code, operation, message, and optional
resource or destination. The result is carried in native tool metadata. The application does not
interpret assistant sentences as saved results or navigation commands.

Possible statuses include successful reads, committed changes, no change, invalid input, not found,
forbidden, conflict, and failure. Only a successful navigation result can carry a destination.

## Streaming

The runtime sends AG-UI events over server-sent events. A turn begins with `RUN_STARTED` and ends
with `RUN_FINISHED` or `RUN_ERROR`. Tool events identify their run and call. The API and browser both
reject malformed or incorrectly ordered event sequences.

Manual navigation after a turn starts takes priority over a delayed navigation result from that
turn. Stopping the stream prevents later buffered events from changing the page, but it does not
reverse a saved operation.

## Runtime choices

Deep Agents is the product runtime and uses Azure OpenAI. The Copilot adapter implements the same
product tool catalog for local comparison. Runtime selection is fixed when the process starts;
failed turns are not retried automatically through another adapter.
