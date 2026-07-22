# Assistant context boundary

> **Authority:** Focused current-boundary note; [design](../design.md) remains higher authority.

## In plain language

CSA Workbench has two different kinds of context:

- **The actor-and-session binding** identifies the authenticated actor and the actor's ephemeral
  session. Server code establishes this binding before the model runs, and every tool is already tied
  to one actor — the model cannot pick a different actor, role, or session by passing one as an
  argument.
- **Display and interpretation hints** help the model understand the date, visible area, persona, and
  applicable Engagement conventions. The browser assembles these hints into a bracketed preamble and
  sends that preamble and the person's words as one prompt string.

Only the first kind participates in the security boundary. A route, persona, convention, or prompt
statement never grants access — Engagement and personal-workspace tools re-read current state and
membership/ownership when they run. The second kind is useful but deliberately modest: it is not an
official saved snapshot of server-side context or a permanent memory system.

## The turn path

1. The API authenticates the request and verifies the actor owns the session.
2. The browser computes its current navigation version, a coarse label for the visible route, and
   the current UTC date.
3. The browser calls authenticated `GET /context-bundle?view=...` with its current route as an
   untrusted hint.
4. The API reads the actor's profile/persona. If the route looks like `/engagements/{id}/...`, it
   reloads that Engagement and includes its name and conventions only when the current actor is a
   member.
5. The browser concatenates date, view label, display name, persona, applicable conventions, and a
   precedence instruction with the user's message. If the bundle request fails, the turn still runs
   with date and view only.
6. The API forwards only the combined prompt and navigation version to the runtime; the verified
   actor is forwarded separately, outside the request body, and must match the runtime's write-once
   session binding.

The browser's preamble is therefore just model-visible text, not a separate verified message or a
structured object the server tracks.

## What context exists today

| Value | Source | Important limit |
|---|---|---|
| Authenticated actor | API resolves the credential and forwards the actor outside the request body | The browser, message, and model cannot select or replace it |
| Actor grounding in the prompt | Each harness appends the actor's display name to its system prompt at session creation | Model-visible text only; authorization comes from tool binding and live service checks |
| Date | Browser UTC date in a bracketed `[Today: ...]` prefix | Not server-derived or persona-time-zone-aware |
| Current view | A browser-derived coarse label | Untrusted hint, not a validated destination object |
| Persona | `role`, `tone`, `outputPrefs`, `language` fields, editable at `PUT /settings/persona` and returned by `/context-bundle` | Free text; no inferred profile or time zone |
| Engagement conventions | `/context-bundle` re-loads the route-hinted Engagement and checks current membership before returning conventions | Affects prompt wording only; does not bind a tool target or permission |
| Navigation version | Browser monotonic counter, echoed on structured navigation effects | Prevents a stale assistant route from replacing newer manual navigation; not identity or authorization |
| Working context | `{}` placeholder returned in the bundle | No current writer or reader; legacy scaffolding |

A forged or stale route for a missing or inaccessible Engagement supplies no Engagement name or
conventions — the endpoint only returns to the browser what the actor can currently read.

## Precedence

When persona or conventions are present, `/context-bundle` returns a flat precedence list —
`["turn instruction", "engagement convention", "user persona", "app default"]` — and the browser adds
it to the prompt as a plain instruction. This is the response-style convention currently implemented;
it does not override application policy, live records, or typed tool results. If prompt context and a
live tool result disagree, the tool read wins: Engagement and personal-workspace tools always re-read
authoritative state rather than trusting the preamble.

Persona is explicitly edited in Settings; ordinary conversation does not infer, save, or update it.
Engagement conventions are edited on the Engagement under the normal editor/owner role rules.

## Explicitly not implemented

The current turn path does **not** implement a `contextId`, a `CONTEXT_APPLIED` stream event, a
permanent record of what context was applied to a given turn, actor-time-zone-aware date composition,
persistent free-form memory, standing approvals, or context that combines across multiple
Engagements.

## Evidence status

Focused tests prove the hard boundaries context relies on: write-once runtime session-to-actor
binding, cross-actor denial, model-visible tool-schema parity, and live Engagement
membership/personal-ownership checks (`tests/test_identity_modes.py`,
`tests/test_structured_control.py`). Grounded meeting preparation is proven end to end by the
`engagement-meeting-prep` skill reading through `list_engagements`/`get_engagement` only; missing
information stays missing rather than being invented. **UNVERIFIED:** no focused test directly drives
`/context-bundle`, the exact browser preamble, or its fetch-failure fallback.

## Related authority

- [Design](../design.md)
- [Identity and access](identity-access.md)
- [Agent harness](agent-harness.md)
- [Navigation](navigation.md)
- [CRUD](crud.md)
- [Testing and evals](testing-evals.md)
