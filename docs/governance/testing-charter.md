# Testing Charter

> **Human-owned document**
>
> Agents must not edit, replace, move, delete, or create another file that competes with this one
> unless the user explicitly approves changes to this named file in the current conversation.

Tests show whether user-relevant behavior matches a stated expectation for a defined action, input,
and starting state. A successful command matters only when it exercises the behavior being changed
and checks the expected result.

## Testing standard

- State the behavior, starting conditions, action, expected result, and observed result.
- Exercise running behavior whenever the repository provides a practical way to do so.
- Include failures, boundaries, permissions, stored changes, and component interactions when they
  matter to the risk.
- Use source review to find problems, but do not describe runtime behavior as checked when the
  application was not run.
- Report what ran, what passed, what failed, and what was not checked.

## Repository commands

Use the [local development guide](../guides/local-development.md) for current commands. Browser
checks should drive the real frontend and compare the displayed result with application state and
the structured assistant events. Supporting unit, contract, lint, and build checks do not replace an
affected end-to-end user journey.

Choose the amount of testing based on the likely impact of an error. Access control, stored data,
public contracts, concurrency, recovery, and deployment changes need stronger independent checks.
