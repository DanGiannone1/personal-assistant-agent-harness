# Reference architectures

> **Authority:** These are TARGET designs. They do not change the current MVP boundary;
> [../design.md](../design.md) and [../capabilities/](../capabilities/) own what exists today.

## Why target designs live apart from capability docs

The [capability](../capabilities/) documents are the honest, evidenced record of what CSA Workbench
does today: implemented tools, current outcomes, and what has (and has not) been verified. Mixing
forward-looking design into that record would blur the MVP boundary that
[requirements](../requirements.md) and the
[reference eval architecture](../evals-reference-architecture.md) depend on.

This directory holds the opposite kind of document: design intent for capabilities the product does
not yet have, or has only partly built. Each file states what a mature version of a capability should
look like — the rules, the data shapes, the failure modes — without asserting that any of it exists,
is scheduled, or has been verified. When a target design becomes real, that fact belongs in the
matching capability document, not here.

## Shared foundations

Every design in this directory assumes the same foundation the current MVP already establishes, and
none of them relax it:

- **Typed tools and structured outcomes only.** The model calls narrow, typed tools and receives a
  structured result; nothing is inferred by parsing chat text.
- **Actor identity is bound outside the model.** The acting user, session, and role are never a
  model-visible tool argument.
- **One shared application service backs every caller.** The manual UI and the assistant reach the
  same authorization, validation, and mutation logic through thin adapters, never two competing
  implementations.
- **State is re-read, not assumed.** Every operation re-checks live authorization and durable state at
  execution time; a permission or context snapshot is a hint, never a cached grant.
- **A claim never outruns reality.** The UI applies a result only after a committed outcome, and it
  refreshes from authoritative state rather than trusting assistant wording.

## The five designs

| Design | Scope |
|---|---|
| [context.md](context.md) | One composed per-turn context snapshot, projected differently for the prompt, the tool layer, UI ranking, and an explainability inspector. |
| [navigation.md](navigation.md) | Personalized quick links plus natural-language destination resolution over one grounded, permission-trimmed catalog. |
| [crud.md](crud.md) | Create/update/delete from any screen, with scope resolved from context instead of requiring pre-navigation, through one application service. |
| [document-ai.md](document-ai.md) | Broad-format document intake, conversion to normalized markdown, and typed extraction/summarization tools over Engagement-scoped storage. |
| [rag-qa.md](rag-qa.md) | Citation-grounded question answering over per-actor and per-Engagement corpora with membership-checked retrieval. |

Context is the foundation the other four build on: navigation and CRUD both rank or default from the
same context snapshot, and the retrieval scoping in `document-ai.md` and `rag-qa.md` follows the same
actor/Engagement authorization boundary context establishes.

## How each design is structured

Every file in this directory follows the same shape so the current/target boundary stays legible
without re-deriving it per document:

1. An authority banner at the top stating it is a target design and naming the capability document
   that owns current behavior.
2. A plain-language description of the experience the design targets.
3. The rules and data shapes that make the design safe — authorization, typed contracts, and
   structured outcomes, not prose.
4. A closing section — usually "Where the current MVP stands" — that honestly states what already
   exists, what is partial, and what does not exist at all, linking the matching capability document.

A reader who wants to know what CSA Workbench does right now should start at that closing section, or
skip straight to the linked capability document; the rest of the file describes where the capability
could go, not where it currently is.

## What this directory is not

- Not a roadmap or a schedule. No dates, no phase numbers, no "next" claims.
- Not a record of Azure resources, deployments, or run results. See
  [Infrastructure](../capabilities/infrastructure.md) and [deployment](../deployment.md) for what is
  actually provisioned.
- Not a second design authority. Where a target design and [design.md](../design.md) appear to
  disagree about current scope, design.md wins; these documents describe a possible future state, not
  a competing present one.

## Authority

These are **target designs**. They do not change the current MVP boundary.
[../design.md](../design.md) and [../capabilities/](../capabilities/) own what exists today; treat
every statement in this directory as intent, not implementation, unless the linked capability document
confirms otherwise.
