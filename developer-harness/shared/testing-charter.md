# Testing Charter

> **HUMAN-OWNED GOVERNING SOURCE OF TRUTH**
>
> After adoption, agents must not edit, replace, move, delete, or create a
> competing version of this file unless a human explicitly authorizes changes
> to this named file in the current conversation.

Testing is evidence that a user-relevant behavior satisfies its stated oracle:
the expected result for a defined action, input, or state. A green check is not
proof unless it exercises that behavior and asserts the expected outcome.

## What counts as proof

- State the behavior, starting conditions, action, expected result, and evidence.
- Verify the behavior dynamically whenever it has an executable runtime surface.
- Cover failure paths, boundaries, permissions, data effects, and interactions
  when they are relevant to the risk.
- Use static review to find defects, but label runtime behavior unverified when
  dynamic execution was not authorized or possible.
- Treat a passing test as limited evidence: identify the defect it would still
  miss when that matters to the change.

## Proportionate verification

Choose depth by the consequences of being wrong, the changed surface, and the
strength of existing evidence. Changes affecting security, access, data,
financial effects, public contracts, concurrency, or recovery need stronger,
independent proof. Unrelated passing checks do not offset a missing behavioral
test.

## Honest results

Report what ran, what it proved, failures and their relevance, and what remains
unverified. Never hide a failure, substitute an assertion about implementation
details for behavior proof, or claim end-to-end behavior from inspection alone.
