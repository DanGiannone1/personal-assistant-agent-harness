# Current evidence record

> **Authority:** The single owner of current verification claims. Other documents summarize and
> link here; they must not restate a run result as their own fact. Add new entries with a date and
> revision; never rewrite an old entry to look current.

Every entry names the revision and environment it came from. A result is evidence for exactly that
revision and environment — nothing else. See the
[testing and evals boundary](capabilities/testing-evals.md) for what each kind of evidence can and
cannot prove.

## Latest verified results

| Evidence | Date | Revision | Environment | Result |
|---|---|---|---|---|
| Browser journey (`scripts/mvp_playwright.mjs`, run `f5d01ccc`) | 2026-07-21 | `f34a42e` | local-synthetic, demo actors, Cosmos emulator | **41/41** — full seven-page inventory, Engagement collaboration/roles, personal Task/subtask/Calendar/Reminder lifecycles against authoritative state, cross-actor isolation, live typed agent turn, responsive layouts, zero page errors |
| `npm run verify` | 2026-07-21 | `1040f9d` | deterministic local | Green — lock checks, 189 Python tests + 7 subtests (11 focused suites), 25 evidence-contract tests, Waza readiness, frontend contract/lint/build, shell syntax, Bicep compile |
| Live-model spot checks | 2026-07-21 | `c22cf43` | local stack, configured Azure OpenAI deployment | Typed `create_task` committed via chat with correct arguments and owner-only state change; full multi-step `weekly-review` routine (list → reschedule ×2 → calendar → focus block). Observational transcript, not a versioned eval run |
| Independent senior review | 2026-07-21 | scope `3c54547..c876306` | static + independent test re-runs | **ACCEPT-WITH-MINORS**; the single minor (documenting the reminder-recipient claim assumption) fixed in `24394e2`. Reviewer independently reproduced the pre-fix SSE failure and verified no weakened assertions |
| Prior browser journey (run `8dc696e4`) | 2026-07-21 | `c876306` | local-synthetic | 41/41 — first run of the extended journey; superseded by `f5d01ccc` |

Raw browser evidence bundles live under `evidence/mvp/local-synthetic/playwright/<run>/results.json`
(ignored local output, `sourceRevision`-stamped); they are inputs to this record, not durable
repository artifacts.

## Currently UNVERIFIED

No evidence exists yet — from any revision of the restored product — for:

- deployed-Azure behavior of the recovery code (no environment runs it; see
  [environments](environments.md));
- a real Entra sign-in against the recovery code;
- a real Azure Communication Services reminder email send (no ACS resource is provisioned);
- a live-model eval run of the `MVP-E8`/`MVP-E9` personal-work cases (the cases exist and are
  deterministically contract-checked); and
- at-most-once reminder delivery under real Cosmos concurrency (proven by claim-before-send
  semantics and tests over an in-memory store, not a live race).

State these as `UNVERIFIED` wherever they matter until a fresh, dated entry above says otherwise.
