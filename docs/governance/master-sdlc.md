# Master SDLC

> **HUMAN-OWNED GOVERNING SOURCE OF TRUTH**
>
> Agents must not edit, replace, move, delete, or create a competing version of
> this file unless the user explicitly authorizes changes to this named file in
> the current conversation.

This lifecycle governs tracked repository work. When an issue exists, it is the
source of truth for scope, approval, evidence, and current state.

## 1. Intake

Create or identify an issue before implementing product behavior, defects, data
changes, delivery work, external-system changes, or material operational or
security changes. Record the objective, acceptance criteria, scope, owner,
risk, and known constraints.

Read-only intake and triage may improve proposed work without approving or
starting implementation.

Internal agent configuration, prompts, skills, and process documentation may be
issue-free only when the user explicitly approves that named scope in the
current conversation. This exception never covers application behavior, data,
delivery, external systems, or security changes.

## 2. Investigation and approval

Investigate read-only first. Record the proposed approach, affected areas,
risks, verification plan, and unresolved decisions. Implementation begins only
after the repository's responsible human approves that record. For tracked
work, preserve the approval in the issue; for the narrow internal-governance
exception, the current conversation is the record.

Return for fresh approval if evidence materially changes scope, behavior,
architecture, or risk.

## 3. Isolated implementation

Keep mutating work serial in the primary worktree. Parallel workers may be
read-only. When parallel mutation is necessary, use separate worktrees with
non-overlapping ownership and an explicit integration plan. Never absorb,
overwrite, or discard unrelated worktree changes.

The author performs static self-review but does not accept their own work.

## 4. Independent review and verification

An independent reviewer evaluates every acceptance criterion against the final
change and identifies what the evidence could still miss. Review depth and
verification strength scale with risk, but independent review is not optional.
Dynamic verification proves behavior when an executable surface exists; static
inspection alone does not prove runtime behavior.

Record criterion-level evidence, failures, and unresolved gaps before
integration.

## 5. Integration, release, and closure

An authorized integrator combines accepted work under the repository's branch
policy, verifies the integrated result, and uses the approved pull-request and
release paths. Do not switch the primary branch, rewrite protected history,
force an update, or mutate Git hosting without explicit authority.

Close tracked work only after its acceptance criteria, required evidence, and
delivery state are complete.

## Minimum work record

- objective, acceptance criteria, scope, and owner;
- approach, affected areas, risks, and verification plan;
- explicit implementation approval;
- implementation and independent-review evidence; and
- integration or release state, next action, and blockers.
