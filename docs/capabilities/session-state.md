# Session-state boundary

> **Authority:** Focused current-boundary note.

An assistant session owns its conversation, working files, and traces. These are ephemeral and may need a new session after a runtime/API restart. An Engagement record and its durable artifact metadata are not session state; their byte storage follows the configured durable artifact backend.

`dev.py` scopes launcher-owned workspace/logs to `.local-runs/<id>` and local durable artifact bytes to `.mvp-artifacts/<id>` when `CSA_LOCAL_RUN_ID` is set. It does not stop independently started processes.
