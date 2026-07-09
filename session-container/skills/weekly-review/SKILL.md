---
name: weekly-review
description: Run the user's weekly review routine end to end — triage tasks, reschedule anything overdue, check the upcoming calendar, protect focus time, pick the top three priorities, and write a status-update document. Use when the user asks to "do my weekly review", "run my weekly review", "close out the week", or "plan my next week".
---

# Weekly Review

This is a deliberately **multi-step routine** — unlike most requests, you work through several
steps in a single turn, calling tools as you go, and finish by writing a status-update document.
Do not stop after one tool call; walk all five steps below (this mirrors the user's
`Weekly-Review-SOP.md`).

## When to use
"do my weekly review", "run my weekly review", "close out the week", "plan my next week".

## Steps (in order, using tools)
1. **Review the tasks.** Call `list_tasks` to see every task with its status, priority, group, due
   date, and the computed `overdue` flag.
2. **Triage what's overdue.** For each task the tool flags `overdue=yes`, reschedule it with
   `update_task`, giving it a new due date a few days out. Never leave a task silently overdue.
   Resolve relative dates against the "[Today: …]" context — never guess today's date.
3. **Check the calendar.** Call `list_events`. If the coming week has no focus block, `create_event`
   a 90-minute "Focus block" so deep work is protected before the calendar fills up.
4. **Pick the top three.** Choose the three most important open tasks for next week and mark each
   `High` priority with `update_task`. Everything else is secondary.
5. **Write the status update.** `write_file` a document named `Weekly-Review-<YYYY-MM-DD>.md` with
   three short sections — **Moved** (what progressed or was rescheduled), **Blocked** (anything
   stuck), **Next** (the top three for the coming week). Ground it in what the tools actually
   returned. If project context would sharpen it, `search_documents` first and cite the source.

## Rules
- Walk all five steps — don't stop after the first tool. This is a real routine, not a one-shot action.
- Only state what the tools actually returned. Confirm concretely what changed: which tasks were
  rescheduled, the focus block you added, the three you raised to High, and that you saved the
  status update.
- Keep the chat reply concise — a few sentences summarizing what you did; the detail lives in the
  document.
