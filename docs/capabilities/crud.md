# Engagement record boundary

> **Authority:** Focused current-boundary note.

Engagements are the durable shared product record. The application exposes authorized create, list, get, update, status-change, and membership operations through shared product rules. The manual Engagements UI and Assistant use those product rules rather than separate state models.

An authorized status change requires a status and reason where the command contract requires one; invalid and unauthorized attempts are expected to leave the target state unchanged. The versioned atomic evidence covers list, read, typed navigation, exact status update, missing reason, outsider rejection, and inert marker prose.

Some Engagement record fields can hold delivery detail, but Engagement records are not the personal task/calendar/reminder surface. Private, actor-owned Tasks, Calendar events, and Reminders exist as a separate "My work" surface, held on their own per-actor aggregate and never scoped to or shared through an Engagement; see [design](../design.md).
