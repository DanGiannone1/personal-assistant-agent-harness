# Identity and Access Capability

> **Authority:** Capability detail subordinate to the [authoritative design](../design.md)
> **Applies to:** Sign-in, application actors, session ownership, Engagement roles, privacy, and service identity
> **Issue:** [#18](https://github.com/DanGiannone1/csa-workbench/issues/18)
> **Evidence state:** Focused local checks exist; live Cosmos and deployed behavior are **UNVERIFIED**

## Start here

CSA Workbench knows who is acting before it loads personal work, an Engagement, or an assistant session. Each running instance chooses exactly one identity mode.

| Environment | `IDENTITY_MODE` | Sign-in surface |
|---|---|---|
| Local development, CI, and isolated browser tests | `demo` | Synthetic demo sign-in only |
| Shared release | `entra` | Microsoft sign-in only |

This is deliberately smaller than an identity platform. One instance accepts one credential kind. It never chooses between demo and Entra credentials. Missing, wrong-mode, malformed, or dual credentials receive the same unauthenticated result.

Both modes resolve to the same application concept: an **actor**. An actor owns personal work and may be a viewer, editor, or owner of a shared Engagement. The existing Engagement service supplies the same role and validation rules to browser APIs and assistant tools; demo users have no separate policy.

## Local and release behavior

For local work, copy `.env.example`, keep `IDENTITY_MODE=demo`, and set `DEMO_PASSWORD` to a local/test secret. Do not commit it, publish it in UI text, or use it for a release. `dev.py` rejects a local launch without those values.

The shared release uses `IDENTITY_MODE=entra` and requires an Entra tenant and API audience. It does not show a demo form or accept a demo token. The frontend is built with the same selected mode through `NEXT_PUBLIC_IDENTITY_MODE`, so it attaches exactly the matching credential.

Sign out before changing people. The client clears actor-namespaced session and conversation references, then the server establishes a new actor. Client cleanup avoids confusing screens; server checks enforce the boundary. All demo content is synthetic. An Entra sign-in identifies an employee; it does not imply that real customer data belongs in this showcase.

## Application actors and configured data stores

Stable actor identifiers—not display names, email addresses, or browser storage keys—identify application records.

```text
Actor
  actorId
  identity: demo | entra
  identitySubject
  displayName
  persona
```

For a demo actor, `identitySubject` is `demo:<actorId>`. For an Entra actor, it is validated `<tid>:<oid>` and the actor ID is `u-<oid>`. Name, UPN, and email are display inputs only; they do not change the stable actor.

The environment is the MVP isolation boundary. Local demo/CI stacks and the shared Entra release use separately configured Cosmos databases/containers. Startup rejects a reused actor registry with the wrong actor kind, malformed subject, or different Entra tenant rather than seeding around or serving it.

## Authentication and authorization

Authentication answers “which actor made this request?” Authorization answers “may that actor do this operation now?” They remain separate.

- Demo authentication validates a secret-backed synthetic sign-in and resolves a demo actor.
- Entra authentication validates bearer signature, issuer, audience, expiry, tenant, and string `tid`/`oid` claims before resolving an Entra actor.
- Personal data uses exact actor ownership.
- Engagement data uses current membership and the role matrix below.
- Session, workspace, chat, upload, and file requests use the exact bound actor.

An authenticated actor is not automatically an Engagement member. A role in browser input, model text, route state, or a header is not authority.

## Final Engagement role matrix

Roles are cumulative: owner includes editor and viewer capabilities; editor includes viewer capabilities. Yellow and Red require a non-empty reason. Setting Green clears the old reason.

| Operation | Viewer | Editor | Owner |
|---|---:|---:|---:|
| List and open the Engagement | Yes | Yes | Yes |
| Read delivery data, members, activity, and artifacts | Yes | Yes | Yes |
| Create an Engagement and become its first owner | Yes | Yes | Yes |
| Change customer, description, target date, or status/reason | No | Yes | Yes |
| Create, update, or delete Engagement tasks and conventions | No | Yes | Yes |
| Upload, save, replace, or remove Engagement artifacts | No | Yes | Yes |
| Change the Engagement name | No | No | Yes |
| Add, remove, promote, or demote members | No | No | Yes |
| Remove or demote the last owner | No | No | No |

Personal records do not use Engagement roles. Only the authenticated actor may access that actor's personal profile, conversations, uploads, drafts, visits, or preferences.

## Trust boundaries

```text
browser/model intent (untrusted)
        ↓
orchestrator validates selected credential and resolves actor
        ↓
session binding verifies the same actor
        ↓
application service reads live membership and role
        ↓
commit + activity + structured result
        ↓
authoritative refresh
```

### Browser and orchestrator

Routes, IDs, form values, local storage, and model prompts are untrusted. The browser can hide a control for clarity but cannot establish identity or effective permission. The orchestrator is the public boundary: it accepts only the selected credential kind, maps it to an actor, and fails closed for application endpoints. Health checks may remain anonymous.

### Sessions and runtime

Creating a runtime session binds its opaque ID to one actor. Later chat, file, state, reset, and delete requests must match it. A forwarded actor header is an internal orchestrator assertion, not a replacement for the existing binding. A mismatch receives the same not-found response as an unknown session; it cannot rebind, destroy, recreate, read, or overwrite the original session. If a runtime restart leaves an old workspace without its process-local binding, it fails closed and the actor starts a new session.

The baseline remains limited while bindings and locks are process-local. Durable multi-replica ownership is outside this MVP.

### Model, storage, and service identity

The model receives neither credentials nor model-selectable actor, session owner, or role arguments. The bound adapter passes trusted runtime context to the shared application service, which rechecks membership at operation time.

Cosmos, Blob, Azure OpenAI, and optional Search are service resources, not browser stores. Managed identity authenticates workloads to those services; it does not replace end-user actor checks. Blob bytes flow through the authenticated application API rather than an anonymous URL. Search remains off until its authorization contract has separate evidence.

Operational logs and user-visible diagnostics must not include passwords, demo tokens, Entra access tokens, raw prompts, documents, or hidden reasoning.

## Failure semantics

| Condition | Result | Privacy rule |
|---|---|---|
| Missing, expired, invalid, wrong-mode, malformed, or dual credential | `401` | Do not identify the failing component |
| Unknown session, another actor's session, or non-member Engagement | `404` | Do not reveal whether it exists |
| Current member lacks a required role | `403` | Required role may be stated to that member |
| Invalid field or Yellow/Red without a reason | `422` | Do not expose unrelated records |
| Required identity or authorization dependency unavailable | `503` or startup failure | Never choose an anonymous/default actor |
| Reused registry has wrong mode, malformed subject, or wrong tenant | startup failure | Do not repair it automatically |

Authentication failure language is intentionally uniform. A caller cannot learn whether a token, password, subject claim, or stored actor caused the rejection.

## Focused verification and remaining evidence

Focused tests cover mode selection, missing/dual/wrong credentials, required Entra `tid`/`oid`, malformed claim types, absent demo secret, clean Entra registry creation, rejected wrong-mode/wrong-tenant registries, write-once session binding, stale workspace rejection, and bound file/chat access. Shared Engagement and structured-control suites exercise the unchanged role rules.

| Journey | Required evidence | Current state |
|---|---|---|
| Demo sign-in and two synthetic actors | Browser journey proves personal isolation and Engagement roles | **UNVERIFIED** live Cosmos/browser run |
| Entra sign-in | Configured tenant token creates/loads one stable actor; failures return `401` | **UNVERIFIED** live/deployed smoke |
| Session ownership | Another actor cannot chat, read, upload, edit, reset, or delete a bound session | Focused local tests; **UNVERIFIED** deployed runtime |
| Engagement roles | Viewer/editor/owner agree across UI, REST, and harnesses | Existing focused tests; **UNVERIFIED** live multi-user journey |
| Service identity and storage privacy | Deployed service access uses managed identity and no anonymous artifact path exists | **UNVERIFIED** deployed inspection |

## Explicit non-goals

This MVP does not add account linking, tenant federation, guests, groups, SCIM, directory lookup, MFA or Conditional Access lifecycle management, cross-environment data migration, a general identity framework, multi-replica session coordination, or a public/shared-key identity bypass. It does not claim production hardening beyond the focused behavior described here.
