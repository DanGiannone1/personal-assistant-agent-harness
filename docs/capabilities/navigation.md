# Navigation boundary

> **Authority:** Focused current-boundary note.

The host UI has supported top-level surfaces for Engagements (default landing), the private "My work" group (Home, Tasks, Calendar, Reminders), Assistant, and Settings. Engagement routes may identify an authorized Engagement and its supported detail area. There is no global Library, Search, or quick-links surface, and My work never scopes to or shares across an Engagement.

Assistant navigation uses a typed destination and validated structured event. The frontend checks destination shape, active run identity, and navigation version before applying an event, and discards stale or malformed effects. Route-looking prose, tool names, and marker strings cannot navigate the UI by themselves.
