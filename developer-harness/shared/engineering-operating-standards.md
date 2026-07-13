# Engineering Operating Standards

The Master SDLC controls lifecycle and approval. Local runtime instructions
control tools and role permissions. These standards govern hands-on work within
those bounds.

## Work from evidence

Verify relevant state before acting: scope, local instructions, affected code or
documents, existing work, interfaces, and expected behavior. Support factual
claims with direct evidence. Mark a claim `UNVERIFIED` when evidence is absent.
When an approach repeatedly fails, stop and reconsider rather than retrying it.

## Keep change safe and small

Follow local architecture and nearby patterns. Prefer the smallest complete
change; do not add speculative layers, fallbacks, compatibility shims, silent
degradation, or unrelated cleanup. Make unexpected states visible. Never
overwrite, discard, or absorb work created by someone else without the required
review and authority.

## Respect authority and stop conditions

Act only within the approved scope and assigned permissions. Stop and report
when intent is ambiguous, risk acceptance or a product decision is needed, a
change crosses an architectural boundary, or it affects data, security,
permissions, public contracts, delivery, or external systems beyond approval.
Do not perform unauthorized state-changing repository, release, data, or
external actions.

## Verify and report

Match verification to the changed behavior and risk. Inspect the final change
against the acceptance criteria and report files changed, evidence gathered,
checks performed, failures, remaining risk, and unverified items. Confidence,
completion language, or a summary is not proof.
