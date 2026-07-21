# Navigation boundary

> **Authority:** Focused current-boundary note.

The host UI has three supported top-level surfaces: Engagements, Assistant, and Settings. Engagement routes may identify an authorized Engagement and its supported detail area; they do not create a personal home, Library, Search, quick-links, calendar, reminder, or scheduler surface.

Assistant navigation uses a typed destination and validated structured event. The frontend checks destination shape, active run identity, and navigation version before applying an event, and discards stale or malformed effects. Route-looking prose, tool names, and marker strings cannot navigate the UI by themselves.
