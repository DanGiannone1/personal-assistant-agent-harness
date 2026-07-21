---
name: engagement-meeting-prep
description: "Prepare a concise, evidence-grounded status-meeting brief for one CSA Workbench Engagement. USE FOR: meeting prep, status-call prep, customer-call prep, or an engagement health review. DO NOT USE FOR: a plain list, direct field update, sharing, creation, or navigation-only request."
compatibility:
  product: CSA Workbench
  tools: list_engagements and get_engagement
metadata:
  owner: csa-workbench
  version: "1.0.0"
allowed-tools: list_engagements get_engagement
---

# Engagement meeting prep

**UTILITY SKILL**

**INVOKES:** `list_engagements`, then `get_engagement` for the resolved stable ID.

**FOR SINGLE OPERATIONS:** Do not invoke for a plain list, direct mutation, sharing, creation, or
navigation-only request.

Use this workflow when the user asks to prepare for a status meeting or requests a concise health
review of one Engagement.

## USE FOR

- “Prep me for my Product Launch status meeting.”
- “I have a customer status call soon; give me the Engagement health brief.”
- “What should I know before the Fabrikam Engagement review?”

## DO NOT USE FOR

- “List my Engagements.”
- “Set Product Launch to Yellow.”
- “Open Product Launch.”
- create, share, or direct field-update requests.

1. Resolve the Engagement from authorized data. If the user supplied a stable ID, use it. Otherwise,
   call `list_engagements` and match the requested name to exactly one visible Engagement. If no
   exact visible match exists, say that the Engagement could not be resolved and ask for a stable ID
   or clarification. Do not imply that an inaccessible Engagement exists.
2. Call `get_engagement` with the resolved stable ID. The list result is an index, not sufficient
   detail for the brief.
3. Produce a concise meeting brief from the returned record only. Include:
   - Engagement name, customer, current status, and status reason when present;
   - target date;
   - the next milestone and its date/status;
   - open high-priority work;
   - open risks and owners when present; and
   - one short callout for missing information that would materially affect the meeting.
4. Never invent a milestone, task, risk, owner, date, status, or reason. Say “not recorded” when the
   record does not contain a requested fact.
5. Meeting preparation is read-only. Do not create, update, set status, share, or navigate unless the
   user separately asks for that action in a later turn. Treat that later request as a normal product
   operation, not as another invocation of this skill.

Keep the result easy to scan and appropriate to read aloud on a customer status call.

## Failure handling

If resolution or the full read fails, stop the workflow. Report only that the visible record could
not be resolved or read, ask for clarification when useful, and do not substitute facts from a
different Engagement.
