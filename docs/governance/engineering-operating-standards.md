# Engineering Operating Standards

> **HUMAN-OWNED GOVERNING SOURCE OF TRUTH**
>
> Agents must not edit, replace, move, delete, or create a competing version of
> this file unless the user explicitly authorizes changes to this named file in
> the current conversation.

The Master SDLC controls lifecycle and approval. Runtime instructions control
native tools and permissions. These standards govern hands-on work inside those
bounds.

## Work from evidence

Verify scope, applicable instructions, affected code and documentation,
existing work, interfaces, and expected behavior before acting. Support factual
claims with direct evidence and mark unsupported claims `UNVERIFIED`. When an
approach repeatedly fails, stop and reconsider it.

## Keep changes safe and small

Follow local architecture and nearby patterns. Prefer the smallest complete
change. Do not add speculative layers, silent fallbacks, compatibility shims,
or unrelated cleanup. Preserve concurrent and pre-existing work.

## Respect authority and stop conditions

Act only inside approved scope and assigned permissions. Stop when intent is
ambiguous, risk acceptance or a product decision is required, an architectural
boundary changes, or the work affects data, security, permissions, public
contracts, delivery, or external systems beyond approval.

Do not perform unauthorized repository, Git-hosting, release, data, or external
mutations. Read-only Git inspection is permitted when it is relevant evidence.

## Verify and report

Match verification to changed behavior and risk. Inspect the final change
against acceptance criteria and report files changed, evidence gathered, checks
performed, failures, remaining risk, and unverified items. Confidence or
completion language is not proof.
