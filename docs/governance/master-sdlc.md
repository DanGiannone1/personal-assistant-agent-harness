# Master SDLC

> **Human-owned document**
>
> Agents must not edit, replace, move, delete, or create another file that competes with this one
> unless the user explicitly approves changes to this named file in the current conversation.

This process applies to tracked repository work. When an issue exists, it records the agreed scope,
approval, progress, and completion state.

## 1. Define the work

Create or identify an issue before changing product behavior, stored data, deployment, security,
permissions, or external systems. Record the goal, success criteria, scope, owner, risks, and known
constraints.

Read-only investigation may improve the proposed work without starting implementation.

Internal agent settings, prompts, skills, and process documents may proceed without an issue only
when the user explicitly approves that named scope in the current conversation.

This exception does not cover product behavior, stored data, deployment, external systems, security,
or permission changes.

## 2. Investigate and obtain approval

Inspect the repository before editing. Record the proposed approach, affected areas, risks, planned
checks, and unresolved decisions. Implementation starts only after the responsible human approves
that record.

Ask for fresh approval if investigation materially changes the agreed behavior, architecture, risk,
or scope.

## 3. Implement safely

Keep file-changing work serial in the primary worktree. Read-only workers may work in parallel. If
parallel edits are necessary, use separate worktrees with non-overlapping file ownership and a clear
integration plan.

Preserve unrelated work. The author reviews their own changes but does not give final approval.

## 4. Independent review and checks

A reviewer who did not write the change evaluates every success criterion against the final files.
The reviewer also identifies what the completed checks might have missed. Run the application when
the changed behavior can be exercised; reading source alone is not enough for runtime behavior.

Record results, failures, and unresolved gaps before integration.

## 5. Integrate and close

An authorized integrator combines accepted work under the repository's branch rules, checks the
combined result, and follows the approved pull-request and release process. Do not switch the primary
branch, rewrite protected history, force an update, or change Git hosting without explicit approval.

Close the work only after the success criteria, required checks, and delivery state are complete.

## Minimum work record

- goal, success criteria, scope, and owner;
- approach, affected areas, risks, and planned checks;
- implementation approval;
- implementation and independent-review results; and
- integration state, next action, and blockers.
