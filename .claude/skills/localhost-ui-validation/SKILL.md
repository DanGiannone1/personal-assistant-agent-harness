---
name: localhost-ui-validation
description: Validate user-visible localhost behavior in the browser. Use when testing the real frontend, starter prompts, artifacts, or execution-log behavior on localhost and reconcile screenshots with trace.jsonl and logs/sdk-events/<session_id>.jsonl.
---

# Localhost UI Validation

Use this skill when verifying anything the user sees in the localhost app.

## Core Workflow

1. Start or restart the local stack with `uv run dev.py`.
2. Use Playwright against the real frontend, not API-only checks.
3. Start each scenario from a fresh session with only one uploaded `.md` source file in the workspace.
4. Save screenshots to `screenshots/<run-id>/`.
5. Tie the browser run to one concrete session by matching upload filenames and timestamps in `logs/trace.jsonl`.
6. Confirm the same session in `logs/sdk-events/<session_id>.jsonl`.
7. Report separately:
   - what the browser showed
   - what `logs/trace.jsonl` showed
   - what `logs/sdk-events/<session_id>.jsonl` showed

## Preferred Entry Points

- `tests/starter-prompts-ui.spec.ts`: run the four starter prompts end-to-end after upload
- `tests/artifact_debug.spec.ts`: debug one artifact flow in detail
- `tests/visual-verification.spec.ts`: broader UI sanity and screenshot coverage

## Expectations

- Validate the rendered UI, not just network success.
- Inspect the execution log for sane steps and looping or rereads.
- Open generated artifacts and read their contents.
- Verify the workspace, UI, and traces agree.
- If behavior is wrong, fix the product and rerun the same browser path until it is clean.
