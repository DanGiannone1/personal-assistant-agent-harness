# Engineering Operating Standards

> **Human-owned document**
>
> Agents must not edit, replace, move, delete, or create another file that competes with this one
> unless the user explicitly approves changes to this named file in the current conversation.

The Master SDLC controls approval and review. Runtime instructions control tools and permissions.
These standards guide work inside those limits.

## Understand before changing

Confirm the requested scope, repository instructions, affected source and documentation, existing
worktree changes, interfaces, and expected behavior. Support factual statements with direct source
references. Say clearly when something has not been checked.

If the same approach repeatedly fails, stop and reconsider it.

## Keep changes safe and focused

Follow the current architecture and nearby code patterns. Prefer the smallest complete change. Do
not add speculative abstractions, silent fallbacks, compatibility code without a current need, or
unrelated cleanup. Preserve existing and concurrent work.

## Respect decisions and limits

Work only within the approved scope and available permissions. Stop when the requested outcome is
ambiguous, a product or architecture decision is missing, or the work would change data, security,
permissions, public contracts, delivery, or external systems beyond the approval already given.

Do not make unapproved repository, Git-hosting, release, data, or external-system changes. Read-only
Git inspection is allowed when it helps answer the current question.

## Check and report

Choose checks that match the changed behavior and the cost of an error. Review the final change
against every success criterion. Report files changed, checks run, failures, remaining risks, and
anything that still needs confirmation.
