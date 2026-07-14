# Identity and Access Capability

> **Authority:** Canonical capability detail subordinate to [CSA Workbench — Authoritative Product and System Design](../design.md)  
> **State:** Target design, reconciled with integrated `master@1fcaac6`  
> **Applies to:** Actors, sign-in, realms, session ownership, authorization policy and role matrix, privacy, audit attribution, and service identity  
> **Last reviewed:** 2026-07-14  
> **Issue:** [#15](https://github.com/DanGiannone1/personal-assistant-agent-harness/issues/15)

## The short version

CSA Workbench knows who is acting before it loads personal work, an Engagement, or an assistant session. An
internal employee signs in with Microsoft Entra ID. Automated journeys and controlled demonstrations
may instead use synthetic demo identities, which are isolated in their own realm and can be disabled
immediately by configuration. The two credentials are alternatives; a request that presents both is
rejected rather than choosing one silently.

After sign-in, both paths produce the same small application concept: an **actor**. Personal state and
private workbench material belong to that actor. Shared state belongs to an **Engagement**, whose
current membership supplies one of three roles. A viewer reads, an editor changes delivery work, and
an owner also controls the Engagement name and membership. The UI, manual API, and assistant tools
enforce that same matrix through one versioned application-core package.

The browser and model can express intent, but neither can choose an actor, session owner, realm,
role, or retrieval filter. Those values are bound by the authenticated runtime. Azure managed
identity authenticates CSA Workbench to its infrastructure; it does not replace end-user authorization.

This is deliberately a professional-showcase identity design, not an enterprise IAM program. It
proves internal Entra sign-in, disable-able synthetic identities, per-user isolation, Engagement
roles, actor-bound tools, private data paths, and attributable outcomes. External identities,
fine-grained policy, and identity-lifecycle programs remain out of scope.

## What the user experiences

### Sign in with Microsoft

An employee selects **Sign in with Microsoft**, completes the tenant's normal Entra flow, and lands
in their own Engagement portfolio. CSA Workbench accepts only a token issued by the configured internal
tenant for the CSA Workbench API audience. The employee's email or display name may change without changing
their CSA Workbench identity.

The first valid sign-in may create the corresponding CSA Workbench actor record. It does not grant membership
to an existing Engagement. The user sees only Engagements to which an owner has added that actor, or
new Engagements they create themselves.

### Use a synthetic demo identity

When the server-side demo switch is enabled, the sign-in screen may offer seeded synthetic actors for
automated tests and controlled demonstrations. Their credentials come from deployment secrets or the
test environment, not from source code or explanatory UI text. Demo identities can access only the
synthetic demo realm. Disabling the switch blocks new demo sign-ins and invalidates existing demo
sessions without a code deployment.

All showcase and demo content is synthetic. A real Entra identity demonstrates organizational
authentication; it does not imply that real customer data belongs in the showcase.

### Change identity safely

Changing from one actor to another is a sign-out followed by a new sign-in, not an in-place identity
override. The frontend tears down the old runtime session and clears actor-namespaced conversation
and session references before rendering the new actor's workspace. The server still enforces every
boundary; client cleanup prevents confusing flashes, but is not the security control.

## Actors and realms

### Canonical actor

Domain records refer to an opaque, stable `actorId`. They do not use display names, email addresses,
usernames, browser storage keys, or model text as authorization identifiers.

```text
Actor
  actorId
  identityKind: entra | demo
  realmId
  identitySubject
  displayName
  enabled
  persona
```

For an Entra actor, `identitySubject` is the validated pair `(tid, oid)`. Both claims are required.
The configured tenant ID must match `tid`; the token's signature, issuer, audience, and expiry must
also validate. `preferred_username`, `upn`, `email`, and `name` are display/profile inputs only.

For a demo actor, `identitySubject` is a seeded synthetic subject. Demo and Entra subjects occupy
different namespaces even if their visible usernames happen to match.

### Realms

A realm is the coarse boundary that prevents synthetic credentials from being invited into a
non-demo workspace:

```text
realm:tenant:<tid>       internal Entra actors and their Engagements
realm:demo:<environment> synthetic demo actors and seeded Engagements
```

Each actor and Engagement has one immutable `realmId`. Owners can add only actors from the same
realm. User search and member pickers are realm-filtered, and a direct cross-realm actor reference is
treated as not found. There is no cross-realm sharing, actor linking, account merging, or realm
administration in the first release.

Separate realms are defense against a future environment containing non-demo data. They do not
change the current release rule that all showcase data is synthetic.

## Authentication and authorization are different

Authentication answers **which actor made this request?** Authorization answers **may that actor do
this operation in this scope now?** CSA Workbench keeps the decisions separate:

- Entra or demo authentication produces an immutable `ActorContext`.
- Personal data is authorized by exact actor ownership.
- Engagement data is authorized by current same-realm membership and role.
- Session and conversation data is authorized by exact actor ownership.
- Infrastructure access is authenticated with managed identity and then still constrained by the
  application's actor and scope checks.

An authenticated actor is not automatically an Engagement member. A role copied into prompt context
is not authority. A successful managed-identity call to Cosmos or Blob is not proof that the user was
allowed to request it.

## Final Engagement role matrix

Roles are cumulative: owner includes editor and viewer capabilities; editor includes viewer
capabilities. Viewer is strictly read-only.

| Operation | Viewer | Editor | Owner |
|---|---:|---:|---:|
| List and open the Engagement | Yes | Yes | Yes |
| Read status, tasks, conventions, members, activity, and artifacts | Yes | Yes | Yes |
| Create a new Engagement and become its first owner | Any signed-in actor | Any signed-in actor | Any signed-in actor |
| Change customer, description, target date, or Green/Yellow/Red status | No | Yes | Yes |
| Create, update, or delete Engagement tasks | No | Yes | Yes |
| Add or remove working conventions | No | Yes | Yes |
| Save, upload, replace, or remove Engagement artifacts | No | Yes | Yes |
| Change the Engagement name | No | No | Yes |
| Add, remove, promote, or demote members | No | No | Yes |
| Remove or demote the last owner | No | No | No |
| Delete the Engagement | Not a v1 operation | Not a v1 operation | Not a v1 operation |

Yellow and Red require a non-empty reason through every surface. Setting Green clears the old
warning reason. This is domain validation, not an extra role.

Personal records do not use Engagement roles. The authenticated actor alone can read or change their
personal profile, conversations, chat uploads, drafts, visits, and preferences.

## Trust boundaries

```text
browser and model intent (untrusted)
        ↓
public orchestrator: validate credential and bind actor
        ↓
owned conversation/session and validated UI hint
        ↓
local application-core instance: resolve scope, authorize live role, validate
        ↓
Cosmos / Blob / optional Search through managed identity
        ↓
commit, activity receipt, structured outcome, authoritative refetch
```

### Browser boundary

Routes, actor-looking strings, Engagement IDs, form fields, local-storage values, and assistant
prompts are untrusted input. The browser may hide forbidden controls for clarity, but backend
enforcement is authoritative. It never sends an effective role or trusted identity for the backend
to accept.

### Orchestrator boundary

The FastAPI orchestrator is the public authentication boundary. It validates exactly one credential,
maps it to an enabled actor, and supplies the resulting context to manual endpoints and the turn
coordinator. Anonymous health checks may be exposed separately; application data endpoints fail
closed.

### Session-runtime boundary

The session runtime is internal and accepts calls only from the orchestrator's workload identity.
Creating a runtime session binds its opaque session ID to one actor, conversation, and workspace.
Every later chat, file, state, reset, and delete request must match that binding. A forwarded actor
header is an orchestrator assertion, not sufficient evidence by itself, and it cannot replace an
existing binding.

The baseline runs at most one orchestrator replica and one session-runtime replica while ownership
or locks remain process-local. On restart, the process-local runtime binding is lost and fails
closed; the authenticated actor creates a new runtime session and rehydrates durable conversation
and upload state. Scale-out is prohibited until session ownership and concurrency coordination are
durably shared.

### Model and tool boundary

The model does not receive actor ID, session owner, effective permission, retrieval filter, or a
credential as a tool argument. It supplies only typed intent such as target reference, desired
changes, or an optional scope hint. A bound adapter passes trusted runtime context to the shared
application-core instance, which re-resolves and reauthorizes the operation.

### Data and observability boundaries

Cosmos, Blob, Azure OpenAI, and optional Search are service resources, not direct browser stores.
Operational logs are a separate privacy boundary: they receive redacted identifiers and outcomes,
not raw credentials, prompts, document content, hidden reasoning, or unrestricted tool arguments.

## Actor, session, turn, and tool propagation

### Runtime contracts

```text
ActorContext
  actorId
  identityKind
  realmId
  authSessionId

SessionBinding
  sessionId
  actorId
  conversationId
  workspaceId
  createdAt

TurnContext
  contextId
  actorId
  sessionId
  conversationId
  turnId
  requestId
  validatedUiContext
  authorizedScopeHint?

ToolContext
  actorId
  realmId
  sessionId
  conversationId
  workspaceId
  turnId
  requestId
  contextId
```

Only the safe prompt projection contains a display identity, current role label, or active
Engagement label. The complete runtime structures stay outside model-visible schemas.

### Per-turn flow

1. Validate one Entra or demo credential and load the enabled actor.
2. Verify that the conversation and runtime session belong to that actor.
3. Resolve client-provided UI context against the actor's current authorized destination catalog.
4. Compose and persist one immutable `TurnContext` and emit its safe `CONTEXT_APPLIED` projection.
5. Invoke the harness with user text separate from trusted context.
6. Bind `ToolContext` in the adapter outside the model's arguments.
7. Build target candidates only from the actor's personal scope or current same-realm memberships.
8. Recheck membership and role immediately before the operation and on every ETag retry.
9. Commit state and attribution together where the aggregate permits it.
10. Persist the structured outcome and return only authorized data to the harness and UI.

Long turns may outlive a membership change. The immutable context explains what was composed, but a
tool's fresh authorization decision is authoritative. Revocation therefore prevents the next tool
read or write even when the turn began with access.

## Scope and data isolation

### Personal scope

Personal Cosmos documents are keyed by `actorId`; conversation and chat-upload metadata also carry
that owner. APIs derive the key from `ActorContext`, never from a user ID in the URL or model input.
Personal navigation, context history, and preferences follow the same rule.

Private workbench uploads and generated drafts remain private even when the conversation mentions or
is tagged to an Engagement. Association helps context; it does not share bytes.

### Engagement scope

An Engagement aggregate contains its immutable `realmId` and stable actor memberships. Every list,
detail, navigation, context, mutation, activity, and artifact operation permission-trims against
that membership. Display names in member lists are presentation only.

An explicit **Save to Engagement** promotes a reviewed private file into the shared scope. The actor
must still be an editor or owner at commit time. The new artifact receives its own stable ID and
shared metadata; it is not an alias to private workspace bytes.

### Artifacts

Blob names are opaque or keyed by stable system IDs, not user-supplied paths. Metadata records:

```text
artifactId, realmId, engagementId, filename, contentType, size,
createdByActorId, createdChannel: manual | agent, createdAt, requestId, turnId?
```

All list, upload, open, and delete operations stream through the authenticated application API.
There is no anonymous URL, public container, shared storage key, or model-controlled SAS path.
Viewers may list and open artifacts but cannot upload, save, replace, or delete them.

### Retrieval

Search is disabled in the baseline. Before it can be enabled, every indexed chunk must carry an
authorization scope such as:

```text
realmId, scopeKind: personal | engagement, ownerActorId?, engagementId?, artifactId
```

The retrieval service constructs mandatory filters from `ActorContext` and live membership. The
model may provide a query and an intent-level scope hint; it cannot provide or widen the filter.
Personal retrieval is exact-owner only. Engagement retrieval is limited to an explicitly selected or
active authorized Engagement. Cross-Engagement retrieval is not a default first-release capability.

Identical filenames, titles, and text across actors or Engagements must remain isolated. Search
results, candidate counts, citations, spelling suggestions, and errors must not reveal an
unauthorized source. The index is a rebuildable projection, never an authorization source.

The legacy externally reachable, shared-key MCP service remains disabled. A future internal MCP or
IDA adapter must authenticate a delegated actor, bind the same runtime context, and call the same
application core. It receives no global owner, shared-key, or authorization-bypass path.

## Error and privacy contract

### Status behavior

| Condition | HTTP / structured behavior | Privacy rule |
|---|---|---|
| Missing, expired, invalid, disabled, or dual credentials | `401` / unauthenticated | Do not reveal which credential component failed |
| Unknown session, another actor's session, unknown Engagement, or non-member Engagement | `404` / `not_found` | Non-membership is indistinguishable from non-existence |
| Current member lacks the required role | `403` / `forbidden` | It is safe to name the required role to that member |
| Invalid field, cross-realm member reference, or Yellow/Red without a reason | `422` / `invalid` | Do not reveal a cross-realm actor record |
| Session busy or bounded optimistic-concurrency failure | `409` / `conflict` | Do not silently retry into last-write-wins |
| Identity or authorization dependency unavailable | `503` / `failed` | Never fall back to anonymous, demo, or a default actor |
| Commit outcome cannot be established | `failed` with unknown/no mutation | Refetch before making any success claim |

Collection endpoints return only authorized records. Navigation, ambiguity candidates, quick links,
context composition, retrieval, and inspector projections are permission-trimmed before ranking or
rendering. A denial must not leak inaccessible resource names through logs, model prose, alternate
chips, or timing-dependent follow-up behavior.

Authentication events use uniform failure language. Passwords, demo tokens, Entra access tokens,
managed-identity tokens, confirmation secrets, and internal authorization context are never returned
in diagnostics or context projections.

### Attribution and traces

The bounded Engagement activity feed is member-visible product history. Durable per-turn receipts and
operational telemetry serve different needs; neither replaces the other.

A committed mutation records, at minimum:

```text
activityId, timestamp, actorId, channel: manual | agent,
engagementId or personal scope, operation, targetId,
requestId, sessionId?, turnId?, toolCallId?, outcome,
safe changed-field summary
```

`manual` covers an actor's direct application/API action; `agent` covers a product-tool command.
The exact activity shape, bounded feed, and commit semantics are owned by
[CRUD](crud.md#activity-receipts-and-trace). Identity owns the actor and channel attribution rule,
not a second activity schema.

The mutation and its activity entry should share the Engagement aggregate commit. Turn receipts link
the actor, context ID, tool names, structured outcomes, terminal state, and resulting resource IDs.
Denied attempts may be recorded operationally with authorized identifiers and a reason code.

Raw prompt text and raw document content are excluded from traces by default. Tool arguments and
results are reduced to typed, redacted summaries. Credentials and hidden chain-of-thought are never
logged. A user-retrievable turn receipt exposes only that actor's safe evidence; the Engagement
activity feed exposes only shared mutation facts to current members.

## Demo identity controls

Demo access is intentionally small:

- a server-side runtime configuration is the authoritative kill switch;
- the frontend flag controls only whether the option is displayed;
- credentials are supplied through deployment/test secrets and stored only as password verifiers;
- authentication failure does not distinguish unknown username from wrong password;
- tokens are opaque, short-lived, revocable on logout, and rejected whenever the kill switch is off;
- demo actors, personal state, Engagements, artifacts, and test fixtures all remain in the demo realm;
- no demo actor has an implicit elevated role; seeded roles exercise owner, editor, and viewer paths;
- reset tooling operates only on the synthetic realm and is not a public application endpoint; and
- automated tests receive credentials through their environment, not from rendered help text.

Refresh-token rotation, self-service password reset, account recovery, adaptive lockout, and MFA are
not built for demo identities. If the synthetic path becomes a public long-lived service rather than
a controlled showcase feature, that changed risk requires a fresh design decision.

## Service identity and private data paths

The deployed workload uses managed identity for Cosmos, Blob, Azure OpenAI, image pull, and
orchestrator-to-session access. Each workload receives only the resource roles needed by its
responsibility. End-user Entra tokens are validated at the public boundary and are not forwarded to
the model, Cosmos, Blob, or Search as general service credentials.

Cosmos and Blob remain behind private endpoints with public network access disabled. No production
configuration uses Cosmos keys, Blob keys, SAS links, a shared API key, or the legacy external MCP
key. Local emulators may use local credentials because they contain only synthetic developer data.

Search remains off until it supports managed identity, the required private/network posture, and
the actor/Engagement filters above. Infrastructure RBAC limits what CSA Workbench's service principal can
reach; application authorization limits which part of that data a particular actor can request.

## Deliberate simplifications and non-goals

The first release intentionally has:

- one configured internal Entra tenant;
- direct user membership, not Entra groups or app-role synchronization;
- exactly owner, editor, and viewer roles;
- application-level authorization rather than per-user Azure data-plane RBAC;
- one realm per actor and Engagement, with no migration or linking workflow;
- short-lived demo sessions without refresh, recovery, or MFA lifecycle;
- at most one orchestrator and session-runtime replica until ownership is durably coordinated;
- a bounded activity feed and product receipts, not an enterprise audit/SIEM program; and
- Search and external MCP disabled rather than weakened to fit the demo.

Out of scope are external tenants, guests, customer federation, group policy, SCIM, conditional-
access administration, MFA enrollment or recovery, privileged-access workflows, resource-level
custom roles, attribute policy, consent administration, legal hold, DLP, and cross-region identity
resilience. CSA Workbench relies on the tenant to operate its organizational identity controls.

## Current integrated state versus target

The following is static evidence from `master@1fcaac6`, not a claim of runtime proof:

| Current foundation or gap | Target direction |
|---|---|
| `api_auth.py:132-151` validates signature, audience, tenant, and issuer; `auth_users.py:81-94` maps a validated `oid` | Retain validation and make `(tid, oid)` the stored Entra subject inside a realm |
| `auth_users.py:40-78` has a runtime demo switch and opaque in-memory tokens | Retain the kill switch; add demo realm, secret-supplied credentials, and explicit revocation semantics |
| `session-container/appdb.py:90-127` hard-codes a shared demo password and `frontend/src/components/AppAuthProvider.tsx:146-148` displays it | Remove credential material and password instructions from source/UI; inject controlled secrets |
| `api_auth.py:91-126` protects all non-health paths when required, while `frontend/src/lib/appAuth.ts:79-86` asks for Entra auth before demo login | Make Entra and demo true alternative sign-in paths at the application boundary |
| `auth_users.py:97-112` silently gives a demo token precedence when both credentials are present | Reject dual credentials with 401 |
| `session-container/appdb.py:292-388` keys personal state by user; `appdb.py:659-716` does the same for context | Preserve this per-actor shape and add explicit realm ownership |
| `session-container/appdb.py:509-545` implements stable-ID Engagement membership, three roles, and a bounded attributed activity feed | Preserve the primitives behind one shared `workbench_core` package and richer receipts |
| `app.py:877-906` distinguishes hidden non-membership from insufficient member role and rechecks inside ETag retries | Use this behavior consistently for REST, agent tools, artifacts, and retrieval |
| `app.py:933-958` makes name/description owner-only, while `session-container/agent_deepagents.py:467-489` lets editors change both | Reconcile to the final matrix: name owner-only; description editor-or-owner; one core package for both surfaces |
| `app.py:1118-1149` and `frontend/src/components/workbench/EngagementScreens.tsx:560-617` let viewers upload artifacts | Change all surfaces to strict viewer read-only and editor-or-owner artifact mutation |
| `session_manager.py:109-112,161-203` stores ownership in process memory; `infra/deploy.sh:641-665` permits three orchestrator replicas | Cap replicas at one and fail closed until durable binding and distributed coordination exist |
| `session-container/server.py:87-99,185-195,252-255` accepts a forwarded user header and can overwrite its remembered session actor | Bind the actor once at session creation and reject every mismatch; require authenticated workload transport |
| `frontend/src/hooks/useAgentSession.ts:484-507` builds trusted-looking context text in the browser | Compose actor and context server-side and keep trusted context separate from user text |
| Tool closures bind `user_id` and recheck roles in `agent_deepagents.py:313-406` | Keep runtime binding, but route tools and REST through the same application-core package |
| `session-container/library.py:89-109,225-257` has no actor/Engagement fields or query filter and uses a Search admin key | Keep Search off until scope fields, mandatory filters, managed identity, and deployment evidence exist |
| `artifact_store.py:1-9,52-71` uses managed identity and `app.py:1112-1186` gates bytes through the orchestrator | Retain the storage boundary; add realm metadata, final editor role, and receipt correlation |
| `session-container/appdb.py:540-545` activity contains timestamp, user, action, and detail; `session-container/server.py:266-273` traces a prompt preview but omits actor on many records | Add correlated safe receipts and remove raw prompt/document content from default tracing |
| `mcp_server.py:1-14,45-118,183-200` exposes global operations behind one shared key | Disable the legacy service; any later adapter must be delegated-actor and application-core bound |

The integrated runtime remains **UNVERIFIED** for this target until the behavioral evidence below is
captured. Existing auth, API, and Engagement probes are useful inputs but do not prove the complete
cross-surface or deployed contract.

## Behavioral oracles

Each oracle states the starting condition, action, and externally observable result. Product-level
proof uses the real frontend and authoritative state/receipts; focused contract tests support it.

| Behavior | Starting condition and action | Required result |
|---|---|---|
| Entra sign-in | Valid internal-tenant API token with known `tid + oid` | One stable actor is loaded or provisioned; only that actor's personal state and memberships render |
| Entra rejection | Bad signature, issuer, audience, expiry, tenant, or missing `oid` | 401; no actor, session, state read, or fallback is created |
| Demo switch | Sign in with configured demo credentials, then disable demo access | Initial sign-in succeeds in the demo realm; after disable, new and existing demo tokens fail immediately |
| Demo secret hygiene | Build and run the deployed sign-in experience | No demo password is present in source-derived UI, network responses, logs, screenshots, or traces |
| Dual credentials | Send a valid Entra token and valid demo token together | 401 ambiguous credentials; neither actor is selected and no action runs |
| Realm isolation | As a demo owner, search for or directly add an Entra actor, and vice versa | The actor is not discoverable/addable; no membership or data changes |
| Account switch | Actor A has an active conversation and files; sign out and authenticate as B | A's runtime session is torn down; B sees none of A's session, transcript, files, personal state, or context |
| Session ownership | Use B's credential against every endpoint for A's session and against a random ID | Both cases return identical 404 behavior; no container call or state read occurs for B |
| Internal actor binding | After a session is created for A, call the internal runtime with the same ID but actor B | The runtime rejects the mismatch and does not recreate/rebind the agent or workspace |
| Personal isolation | Create equal-named personal records and uploads for A and B | UI, REST, tools, navigation, and receipts return only the calling actor's objects |
| Membership hiding | A non-member uses a known Engagement, artifact, and task ID through UI, REST, tools, navigation, and context | All paths behave as not found and reveal no title, candidate, count, convention, citation, or route |
| Viewer contract | Viewer opens every Engagement surface and attempts every mutation through direct API and agent wording | Reads succeed; all mutation affordances are absent and all direct/tool mutations return forbidden with no commit |
| Editor contract | Editor changes description, customer, date, status/why, tasks, conventions, and artifacts; then attempts name and membership changes | Delivery changes commit and are attributed; name/membership changes are forbidden |
| Owner contract | Owner changes name and membership, then attempts to remove or demote the final owner | Authorized changes commit; the final-owner operation is invalid and leaves membership unchanged |
| Surface parity | Repeat each allowed and denied role action through manual UI/REST and both harness tool adapters | Same authorization, validation, structured status, state effect, and activity attribution |
| Revocation during a turn | Remove or downgrade the actor after context composition or before an ETag retry | The next live tool check/retry observes the new role and does not commit stale authority |
| Private-to-shared promotion | Viewer and editor each try **Save to Engagement** on a private draft | Viewer is forbidden and draft stays private; editor creates a distinct durable artifact and receipt |
| Artifact privacy | Member and non-member request the same artifact bytes | Member read follows role rules; non-member receives hidden 404; no anonymous or direct Blob path works |
| Retrieval isolation | Index identical filenames/text for two actors and two Engagements, then query from each scope | Only exact-owner or selected authorized-Engagement passages and citations return |
| Model cannot widen scope | Tool call includes a forged actor, role, realm, or inaccessible Engagement filter | Forged authority is ignored or rejected; bound runtime context controls the result |
| Attribution | Commit one manual mutation and one agent mutation | State, activity, and turn receipt agree on actor, scope, operation, channel, request/turn IDs, and outcome |
| Trace privacy | Exercise sign-in, prompts, tool calls, and document operations, then inspect logs and receipts | No password, token, raw prompt, raw document, hidden reasoning, or inaccessible resource name is present by default |
| Service identity | Inspect and probe the deployed Azure profile | Public access ends at frontend/orchestrator; session calls and data services use managed identity; Cosmos/Blob public access and shared keys are disabled |
| Scale-to-zero recovery | Persist conversation/upload state, allow compute to scale in, then return as the same actor | New runtime session reauthenticates and rehydrates only that actor's durable state without trusting an old client binding |

The deployed Deep Agents path must satisfy the identity, role, artifact, receipt, and private-service
oracles. The Copilot adapter must satisfy the same application-core authorization contract locally; exact
model wording or SDK event shape is not an identity criterion.
