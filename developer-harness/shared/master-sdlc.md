# Master SDLC

> **HUMAN-OWNED GOVERNING SOURCE OF TRUTH**
>
> After adoption, agents must not edit, replace, move, delete, or create a
> competing version of this file unless a human explicitly authorizes changes
> to this named file in the current conversation.

This lifecycle governs tracked work after an adopter installs it and maps its
local mechanics. The issue record is the source of truth for scope,
approval, evidence, and current state.

## 1. Intake

Create an issue before implementation for product behavior, defects,
data changes, delivery work, external-system changes, and material operational
or security changes. It states the objective, acceptance criteria, scope,
owner, risk, and known constraints.

Locally authorized issue intake and triage may create or improve proposed work,
add evidence, classify priority, and link duplicates without implementation
approval. Triage must not approve, assign, close, or move work into execution;
implementation still requires the explicit approval in the next stage.

**Narrow exception:** internal agent configuration, prompts, skills, and process
documentation may be issue-free only when a human explicitly approves that
named scope in the current conversation. The exception never covers product or
application behavior, data, delivery, external systems, security, or work that
needs issue-based status tracking.

## 2. Investigation and approval

Investigate read-only first. Record the proposed approach, affected areas, risk,
verification plan, and decisions still needed. A human must explicitly approve
implementation after seeing that record. Existence of an issue, prior
discussion, urgency, or an agent's readiness claim is not approval.

## 3. Isolated implementation

Use an isolation method selected by the adopter so concurrent changes do not
share mutable work or overlapping affected areas. Keep work within approved
scope. If new scope, a protected area, or a material risk appears, stop and
return to approval. The author performs a static self-review but does not accept
their own work.

## 4. Independent review and verification

An independent reviewer evaluates every acceptance criterion against the change,
including what a test or review could still miss. The review depth and verification
methods match risk: higher-risk work receives stronger, multi-angle scrutiny.
Dynamic verification proves the affected behavior where a runtime surface exists;
static inspection alone does not prove runtime behavior. Record criterion-level
evidence and unresolved gaps before integration.

## 5. Integration, release, and closure

An authorized integrator combines approved work under the local branch-safety
policy, verifies the integrated result, and prepares the pull-request or
equivalent review path and release path.
Do not directly change protected history, discard others' work, force an update,
or change branches without the authority and checks the local policy requires.
Release only through an approved path. Close the issue only when its
acceptance criteria, required evidence, and delivery state are complete.

## Minimum issue record

- objective and acceptance criteria;
- approach, affected areas, risk, and verification plan;
- explicit human approval to implement;
- implementation and independent-review evidence;
- integrated or released state, next action, and blockers.
