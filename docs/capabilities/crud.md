# Engagement record boundary

> **Authority:** Focused current-boundary note.

Engagements are the durable shared product record. The application exposes authorized create, list, get, update, status-change, and membership operations through shared product rules. The manual Engagements UI and Assistant use those product rules rather than separate state models.

An authorized status change requires a status and reason where the command contract requires one; invalid and unauthorized attempts are expected to leave the target state unchanged. The versioned atomic evidence covers list, read, typed navigation, exact status update, missing reason, outsider rejection, and inert marker prose.

This does not make CSA Workbench a personal task manager. Some Engagement record fields can hold delivery detail, but there is no supported personal task, calendar, reminder, scheduler, or home surface.
