# Context Capability

> **Authority:** Canonical context detail subordinate to the [authoritative design](../design.md)
>
> **Deployed application revision:** `ce251fbbe03c6b99bc38e676a8be88e9f199f777`
>
> **Applies to:** Actor/session grounding, browser-composed turn hints, persona and conventions, current-view handling, and the context inspector
>
> **Issue:** [#18](https://github.com/DanGiannone1/csa-workbench/issues/18)

## In plain language

CSA Workbench has two different kinds of context:

- **Trusted runtime binding** identifies the authenticated actor and the actor's ephemeral session.
  Server code establishes this binding before model use, and product tools close over the actor rather
  than accepting an actor, role, or session as a model argument.
- **Display and interpretation hints** help the model understand the date, visible area, persona, and
  applicable Engagement conventions. The browser currently assembles these hints into a bracketed
  preamble and sends that preamble and the person's words as one prompt string.

Only the first kind participates in the security boundary. A route, persona, convention, prior visit,
prompt statement, or model choice never grants access. Engagement tools and navigation reread current
state and membership when they run.

The second kind is useful but deliberately modest. It is not a canonical server-side context
snapshot, a durable memory system, or proof of what a historical turn used.

## The implemented turn path

For each assistant turn, the deployed application revision does the following:

1. The API authenticates the request and verifies that the actor owns the session.
2. The browser captures its current navigation version, derives a simple label for the visible route,
   and computes the current UTC date with `new Date().toISOString()`.
3. The browser calls authenticated `GET /context-bundle?view=...` with its current route as an
   untrusted hint.
4. The API reads the actor profile and per-actor context record. If the route looks like
   `/engagements/{id}/...`, it loads that Engagement and includes its name and conventions only when
   the current actor is a member.
5. The browser concatenates date, view label, display name, persona, applicable conventions, and a
   simple precedence instruction with the user's message. If the bundle request fails, the turn still
   runs with date and view only.
6. The API forwards only `prompt` and `navigation_version` in the request body. The trusted actor is
   forwarded separately on the workload-authenticated runtime call and must match the runtime's
   write-once session binding.
7. The runtime sends the combined prompt to the selected harness. Its tools are already bound to the
   actor and session workspace, and Engagement operations reread current Cosmos state.
8. The browser keeps the last successfully fetched bundle in reducer state and may show its limited
   inspector after the turn.

The browser preamble is therefore model-visible text, not a separate trusted message or typed context
projection. The runtime cannot distinguish its fields from other text in the submitted prompt.

## What context exists today

| Value | Current source and use | Important limit |
|---|---|---|
| Authenticated actor | The public API resolves the credential, owns the session-to-actor map, and forwards the actor to Runtime outside the request body | The browser, message, and model cannot select or replace it |
| Runtime session actor | Runtime binds the new session ID to the forwarded actor and rejects mismatches before acquiring the turn lock | The binding is process-local and ephemeral |
| Harness actor grounding | Each harness appends the actor's display name and stable actor ID to its system prompt when the live harness is created | This is model-visible grounding; authorization still comes from the bound tool closure and live service checks |
| Date | Browser UTC date in a bracketed `[Today: ...]` prefix | It is not server-derived or persona-time-zone-aware |
| Current view | A browser-derived label such as `Engagements`, `Engagement`, `Tasks`, `Calendar`, or `Documents` | It is a coarse, untrusted label rather than a validated destination object |
| Persona | Authenticated actor record returned by `/context-bundle`; optional `role`, `tone`, `outputPrefs`, and `language` fields are inserted by the browser | No inferred profile, rich personalization, time zone, or persona provenance exists |
| Engagement conventions | Browser route hint is parsed for an Engagement ID; the API rereads that record and checks current membership before returning conventions | Conventions affect prompt wording only and do not bind a tool target or permission |
| Engagement name | Returned with scoped conventions and used in the convention preamble/inspector | The active Engagement ID is not attached to the runtime or tools as trusted context |
| Visits | Authenticated route changes are stored newest-first with a 50-entry cap and can rank known manual quick links | Visit paths are not validated before storage, are not inserted into the prompt, and cannot create an assistant destination |
| Working context | A per-actor object is returned in the bundle | The current frontend neither inserts it into the prompt nor renders it in the inspector; the setter has no active caller |
| Navigation version | Browser monotonic counter sent as a non-negative integer and echoed on structured navigation effects | It prevents an older assistant route from replacing newer manual navigation; it is not identity or authorization context |

### Current Engagement handling

The browser's route is a hint, not proof that an Engagement is active. The context endpoint recognizes
an Engagement-shaped route, reloads the record, and checks membership before returning its name or
conventions. A forged or stale route for a missing or inaccessible Engagement therefore supplies no
Engagement data.

That checked result is still returned to the browser and composed there. The runtime receives no
trusted `activeEngagementId`, selected-resource object, or canonical current destination. A model tool
that needs an Engagement must use a stable ID in the typed command, normally after an authorized
`list_engagements` or `get_engagement` read. The tool then checks current membership again.

Assistant navigation follows a separate structured path. The model calls `navigate` with a catalog
destination ID and, when required, a stable Engagement ID. The resolver validates the catalog shape
and current membership. The UI applies the resulting `NAVIGATION_RESOLVED` event only when its run,
navigation version, destination, cancellation state, and actor-filtered application state agree. See
[Navigation](navigation.md) for that contract.

## Prompt, tools, and live facts

Both harnesses contain the same small static product prompt. It names the seven approved tools,
requires stable Engagement IDs, describes the Yellow/Red reason rule, and says not to claim a change
or navigation before a typed result succeeds. Skills are disabled in this release.

At harness creation, the runtime adds an actor-grounding line. At each turn, it submits the browser's
combined prompt as a normal user message. Deep Agents keeps in-process conversation continuity with
`InMemorySaver`; Copilot keeps its live SDK session. Neither path creates durable context or memory.

Mutable product facts do not come from the persona or convention preamble. Engagement tools close
over the trusted actor and call `workbench_core.EngagementService`, which rereads the current record
and applies current membership, role, validation, and mutation rules. The typed tool result and later
authoritative state refresh govern the UI. If prompt context and a live tool result disagree, the tool
read wins.

The navigation tool uses the same rule: the current browser label does not authorize or resolve a
destination. The tool receives an explicit catalog ID and, for an Engagement destination, performs a
live membership check.

## Persona and convention precedence

When a bundle supplies persona or conventions, the browser adds this instruction to the prompt:

```text
instruction in this message
  > Engagement conventions for the route-scoped Engagement
  > actor persona defaults
  > application default
```

This is the simple response-style convention currently implemented. It does not override application
policy, live records, typed tool results, or authorization. Conventions and persona fields are free
text; there is no semantic conflict detector or guarantee that the model can prove which phrase won.
When neither persona nor conventions contributes a value, the browser does not add the precedence
line and the static prompt's concise, professional style remains the default.

Persona is explicitly edited in Settings and stored on the actor record. Ordinary conversation does
not infer, save, or update it. Engagement conventions are edited on the Engagement under the normal
role rules.

## The current inspector

The assistant panel can show **What personalized the last turn** from the browser's `lastBundle`
state. It displays:

- the actor's display name;
- persona role, tone, and output preferences when present;
- returned Engagement conventions and Engagement name; and
- the flat precedence list returned by the endpoint.

This is a transient convenience view, not a durable or complete turn record. It does not show the
date, current-view label, language, working context, prompt bytes, source timestamps, freshness, or
omitted-source reasons. It is populated before the stream starts, has no `runId` or `contextId`, and
is not rehydrated from a server receipt. If the bundle fetch fails, the reducer clears it and the
inspector is absent even though date and view were still sent.

Changing profile or Engagement data does not rewrite an inspector already held in that browser state,
but no historical guarantee follows: reload, sign-out, new browser state, or a later turn can replace
or remove it.

## Privacy and failure behavior

- Authentication or session-ownership failure rejects the request before model use.
- A runtime actor mismatch returns the same not-found behavior as an unavailable session and cannot
  rebind the session.
- A missing or inaccessible Engagement route contributes no Engagement name or conventions.
- A context-bundle failure removes optional personalization but does not bypass live authorization.
- The context endpoint returns only the authenticated actor's profile/context and conventions from an
  Engagement that actor can currently read.
- The actor ID is not a model-visible tool argument, but it is included in the runtime's system-prompt
  grounding line. The browser preamble uses the display name rather than the ID.
- Local trace configuration may capture a prompt preview or full raw SDK prompt. Those process-local
  diagnostics are ephemeral and are not a durable user-facing context audit.

The current fallback is silent beyond the missing inspector: it has no typed degraded-source event or
reason code. That is an evidence and legibility limit, not an authorization fallback.

## Explicitly not implemented

The deployed application revision does **not** implement:

- one canonical server-side immutable context snapshot per turn;
- separate `user_text` and trusted context fields at the harness boundary;
- a `contextId`, composition timestamp, source provenance, freshness policy, or omission framework;
- `CONTEXT_APPLIED` or any equivalent streamed context event;
- a durable turn receipt or durable inspector projection;
- a server-validated selected resource, canonical current destination, or active Engagement binding
  supplied to tools;
- actor-time-zone-aware date composition;
- durable free-form memory, conversation-derived profile inference, memory CRUD, or proactive memory;
- standing approvals, approval tokens, or policy grants in context;
- rich personalization beyond the four editable persona strings and Engagement conventions;
- a semantic layer, connector context, retrieval namespace, or automatic document injection; or
- cross-Engagement context aggregation, background context refresh, or multi-agent context sharing.

The per-actor Cosmos context document still contains default `memories` and `standingApprovals`
arrays, but no current endpoint, prompt composer, tool, or UI activates them. Their stored shape is
legacy scaffolding, not an MVP capability.

## Evidence status

### Verified supporting boundaries

Focused release-candidate tests prove the hard boundaries that context relies on:

- write-once runtime session-to-actor binding, fail-closed orphan workspaces, and cross-actor chat and
  file denial in [identity-mode tests](../../tests/test_identity_modes.py);
- model-visible tool-schema parity, actor-closed tool adapters, live Engagement membership checks,
  destination validation, and structured navigation correlation in
  [structured-control tests](../../tests/test_structured_control.py); and
- active-run, navigation-version, cancellation, destination-path, and actor-filtered Engagement checks
  in the [frontend navigation contract](../../frontend/src/lib/navigation.contract.ts).

The deployed release smoke recorded in the [authoritative design](../design.md#quality-and-evidence)
proved one real-Entra actor could create a session and complete a typed, actor-bound Engagement list
turn. It supports the trusted binding and live-read claims; it does not prove persona, conventions,
current-view interpretation, or inspector behavior.

### Remaining evidence gaps

- No focused release-candidate test directly covers `/context-bundle`, the exact browser preamble, its
  fetch-failure fallback, or the inspector projection.
- The historical [Engagement browser script](../../scripts/engagements_e2e.mjs) contains a persona,
  convention, and inspector scenario, but it is not part of the current MVP release command set and
  no current release-candidate result is linked. That behavior remains **UNVERIFIED** dynamically.
- There is no captured adversarial turn proving that a forged inaccessible Engagement route leaks no
  name or convention through every prompt/trace surface.
- There is no race test showing a membership or Engagement fact changes between bundle fetch and tool
  use. Live service checks are covered separately, but the complete turn relationship is
  **UNVERIFIED**.
- Because no durable applied-context record exists, historical inspector immutability, provenance,
  context-event ordering, and harness parity for context cannot be tested as current behavior.

The current evidence commands and release profiles are owned by
[Testing and evals](testing-evals.md).

## Related authority

- [Authoritative design](../design.md)
- [MVP success criteria](../requirements.md)
- [Identity and access](identity-access.md)
- [Agent harness](agent-harness.md)
- [Navigation](navigation.md)
- [CRUD](crud.md)
- [Session and state](session-state.md)
- [Testing and evals](testing-evals.md)
