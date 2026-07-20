# Testing Charter

> **HUMAN-OWNED GOVERNING SOURCE OF TRUTH**
>
> Agents must not edit, replace, move, delete, or create a competing version of
> this file unless the user explicitly authorizes changes to this named file in
> the current conversation.

Testing is evidence that user-relevant behavior satisfies a stated oracle: the
expected result for a defined action, input, or state. A green command is not
proof unless it exercises that behavior and asserts the expected result.

## Evidence standard

- State the behavior, starting conditions, action, expected result, and observed
  evidence.
- Verify behavior dynamically whenever it has an executable runtime surface.
- Cover failure paths, boundaries, permissions, data effects, and interactions
  when relevant to risk.
- Use static review to find defects, but label runtime behavior `UNVERIFIED`
  when dynamic execution was not possible.
- Report what ran, what it proved, failures, and what remains unverified.

## Repository verification

Use [../development.md](../development.md) as the canonical command source. The
primary behavioral proof is Playwright driving the real frontend and reconciling
screenshots with application state and traces. Relevant supporting checks
include frontend lint/build and focused backend tests, but they do not replace
the affected end-to-end behavior.

Choose verification depth by the consequence of error and changed surface.
Security, access, data, public contracts, concurrency, recovery, and deployment
changes require stronger independent proof.
