# Identity and access boundary

> **Authority:** Focused current-boundary note; [design](../design.md) and [requirements](../requirements.md) remain higher authority.

## In plain language

CSA Workbench knows who is acting before it loads personal work, an Engagement, or an assistant
session. Each running instance chooses exactly one identity mode:

| Environment | `IDENTITY_MODE` | Actors and sign-in |
|---|---|---|
| Local development, CI, and isolated browser tests | `demo` | Deterministic synthetic actors (`dan`, `ava`, `sam`) through the demo login form only |
| Shared release | `entra` | Validated users from one configured Entra tenant through Microsoft sign-in only |

One instance accepts one credential kind and never chooses between them. `api_auth.APIAuthenticator`
rejects any request that carries the wrong-mode credential, both credentials, or neither with the
same `401`; `identity_config.IdentityConfig.validate()` fails application startup if the selected
mode's required configuration (`DEMO_PASSWORD` for demo; `ENTRA_TENANT_ID` and an API audience for
Entra) is missing.

Both modes resolve to the same application concept: an **actor**. An actor owns its own personal
work and may be a viewer, editor, or owner of any number of shared Engagements. The same
`EngagementService` and `PersonalWorkspaceService` supply role and ownership rules to REST handlers
and assistant tools alike — demo actors have no separate policy path.

## Local and release behavior

For local work, copy `.env.example`, keep `IDENTITY_MODE=demo`, and set `DEMO_PASSWORD` to a
local/test secret; never commit it or expose it in browser config. `dev.py` refuses to start a local
stack in any other mode.

The shared release uses `IDENTITY_MODE=entra` and requires `ENTRA_TENANT_ID` plus an API audience
(`ENTRA_API_CLIENT_ID` or an explicit `ENTRA_ALLOWED_AUDIENCES` list). `api_auth` validates bearer
signature, issuer, audience, expiry, tenant (`tid`), and the delegated `access_as_user` scope before
resolving an actor — an application-only token cannot be used as a browser credential.

## Application actors

Stable actor identifiers — not display names, emails, or browser storage keys — identify application
records. For a demo actor the stable subject is `demo:<uid>`; for an Entra actor it is the validated
`<tid>:<oid>` pair, exposed as actor ID `u-<oid>`. Name, sign-in username, and email are display
inputs derived from Entra claims (`name`, `preferred_username`/`upn`/`email`) on first sight and do
not change the stable actor afterward.

## Authentication and authorization

Authentication answers "which actor made this request?" Authorization answers "may that actor do
this operation now?" They stay separate:

- demo authentication validates a secret-backed synthetic login and issues a server-side token
  (`auth_users.py`), independent of the JWT path;
- Entra authentication validates the bearer token as described above;
- personal data (Tasks, Calendar, Reminders) uses exact actor ownership — no role matrix at all;
  and
- Engagement data uses current membership and the owner/editor/viewer role matrix in
  [CRUD](crud.md#roles).

An authenticated actor is not automatically an Engagement member. A role in browser input, model
text, route state, or a header is not authority; every Engagement operation re-reads current
membership from Cosmos.

## Trust boundaries

```text
browser / model intent (untrusted)
        v
API validates the selected credential and resolves the actor
        v
session binding verifies the same actor (write-once per session)
        v
application service re-reads live membership/ownership and role
        v
commit + activity + structured result
        v
authoritative refresh
```

The actor ID is never a model-visible tool argument. The session runtime receives the actor from the
authenticated API call and closes every tool over that binding before the model sees it, so a model
cannot select a different actor, session, or role by changing the prompt or a tool parameter.

## Reminder recipient trust

Reminder email is the one place identity directly drives an external side effect, so it reuses the
same actor-derived trust rather than a new one: `workbench_core.reminder_dispatch.default_recipient`
resolves only the owning actor's `identity` field — an Entra actor's validated sign-in address (must
contain `@`) or a demo actor's operator-configured `REMINDER_DEMO_EMAIL` — never a client-supplied or
reminder-stored address. See [design](../design.md#reminder-email-delivery) for the full delivery
contract.

## Failure semantics

| Condition | Result |
|---|---|
| Missing, wrong-mode, malformed, or dual credential | `401`, uniform "Unauthorized" (no reason leakage) |
| Unknown session, another actor's session, or non-member Engagement | `404` (does not reveal whether it exists) |
| Current member lacks a required role | `403` |
| Invalid field, or Yellow/Red status without a reason | `422` |
| Cross-actor personal-record access | `404`, same as a missing record |

## Evidence status

Focused tests cover mode selection, missing/dual/wrong credentials, required Entra `tid`/`oid`,
malformed claim types, write-once session binding, and role rules
(`tests/test_identity_modes.py`, `tests/test_engagement_core.py`,
`tests/test_infra_entra_contract.py`). A local browser journey passed 41/41 checks ([current evidence record](../evidence.md)) using the deterministic demo actors. **UNVERIFIED:** a real Entra sign-in against this code,
a second real tenant actor, and an interactive real-Entra browser journey — none has been observed
from this repository.

## Explicit non-goals

This MVP does not add account linking, tenant federation, guests, groups, SCIM, directory lookup, MFA
or Conditional Access lifecycle management, multi-tenant reminder recipient claims, or a
public/shared-key identity bypass.

## Related authority

- [Design](../design.md)
- [Requirements](../requirements.md)
- [CRUD](crud.md)
- [Session and state](session-state.md)
- [Testing and evals](testing-evals.md)
