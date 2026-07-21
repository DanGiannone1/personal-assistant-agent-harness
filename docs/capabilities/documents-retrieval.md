# Artifact and session-file boundary

> **Authority:** Focused current-boundary note.

Durable Engagement artifacts have two parts: metadata stored with the Engagement record and bytes stored by the configured artifact backend. In isolated local development, bytes use `.mvp-artifacts/<run-id>`; an Entra release requires the configured durable Blob account. Access goes through the application’s membership checks.

Assistant session files are different: they live in the session workspace, are ephemeral, and session uploads accept Markdown (`.md`) only. Do not describe them as durable Engagement artifacts.

There is no supported Library, Search, or generic retrieval surface in this MVP. Generic enterprise search is a future non-goal, not a current capability.
