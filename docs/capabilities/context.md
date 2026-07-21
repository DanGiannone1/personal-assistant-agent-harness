# Assistant context boundary

> **Authority:** Focused current-boundary note.

Assistant context is scoped to the effective user, current authorized product state, and the current session. It must not turn user text, model text, marker-like content, or stale route strings into application control. Product reads and mutations remain subject to the same authorization and validation path as the UI.

Grounded meeting preparation reads the resolved authorized Engagement through `list_engagements` and `get_engagement`. Missing information must remain missing rather than be invented. This source boundary does not prove a live model response; see [testing and evals](testing-evals.md).
