---
name: weekly-review
description: "Run the user's weekly review routine end to end -- triage tasks, reschedule anything overdue, check the upcoming calendar, protect focus time, and pick the top three priorities. USE FOR: 'do my weekly review', 'run my weekly review', 'close out the week', 'plan my next week'. DO NOT USE FOR: a single task/event change or a plain list request."
compatibility:
  product: CSA Workbench
  tools: list_tasks, update_task, list_events, and create_event
metadata:
  owner: csa-workbench
  version: "1.0.0"
allowed-tools: list_tasks update_task list_events create_event
---

# Weekly review

**WORKFLOW SKILL — MULTI-STEP**

**INVOKES:** `list_tasks`, `update_task`, `list_events`, `create_event`.

This is a deliberate multi-step routine: work through all four steps below in one turn, calling
tools as you go, rather than stopping after the first tool call.

## USE FOR

- "Do my weekly review." / "Run my weekly review." / "Close out the week." / "Plan my next week."

## DO NOT USE FOR

- A single task or event change, or a plain "list my tasks" / "what's on my calendar" request —
  use the tasks or calendar tools directly for those.

## Steps (in order)

1. **Review the tasks.** Call `list_tasks` to see every task with its status, priority, group,
   due date, and the server-computed `overdue` flag.
2. **Triage what's overdue.** For each task flagged `overdue=yes`, reschedule it with
   `update_task` to a new due date a few days out. Never leave a task silently overdue. Resolve
   relative dates ("next Monday", "in three days") against the current date — never guess it.
3. **Check the calendar.** Call `list_events`. If the coming week has no focus block, create one
   with `create_event` (type "Focus", roughly 60-90 minutes) so deep work is protected before the
   calendar fills up.
4. **Pick the top three.** Choose the three most important open (non-"Done") tasks for next week
   and raise each to priority "High" with `update_task`. Leave everything else as-is.

## Finish with a chat summary

This assistant has no document-writing tool, so end the review in the chat reply itself — do not
claim to have saved or written a file anywhere. Keep it short: what you rescheduled, the focus
block you added (or that one already existed), and the three tasks you raised to High. Ground
every claim in what the tools actually returned.

## Rules

- Walk all four steps — don't stop after the first tool call. This is a routine, not a one-shot
  action.
- Only state what the tools actually returned. Never claim a task was rescheduled, a focus block
  was added, or a priority was raised unless the corresponding call succeeded.
