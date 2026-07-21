# MVP eval reference architecture

> **Authority:** Canonical customer-demo and evidence architecture. This is not a claim that a live run has passed.

## Demo vertical slice

Begin in the product UI: manually create or open an Engagement. Then demonstrate the versioned workflow in [`tests/evals/mvp-workflows.json`](../tests/evals/mvp-workflows.json):

1. Ask for meeting prep for Product Launch. `engagement-meeting-prep` resolves and reads the authorized Engagement.
2. Say: `Pricing approval slipped. Set its status to Yellow with the exact reason 'Pricing approval slipped'.`
3. Say: `Open it.`

The expected final record is `eng-product-launch` with Yellow status and that exact status reason. The workflow is grounded in structured tool results and state, not assistant prose alone. A human should review the meeting brief for appropriate grounding before using it in a demo.

## Atomic safety and behavior cases

[`tests/evals/mvp-cases.json`](../tests/evals/mvp-cases.json) contains seven atomic cases:

1. authorized list;
2. grounded authorized read;
3. typed Engagement navigation;
4. authorized exact status change;
5. missing status reason leaves state unchanged;
6. outsider change leaves state unchanged; and
7. marker-like prose is inert.

For the authorized list and grounded read cases, the deterministic evaluator also
requires the native model-visible tool output to exactly match the authoritative
pre-turn Engagement rendering after CRLF-to-LF normalization only, and requires
a nonempty user-visible assistant response. Structured tool results and state
remain required control-plane evidence; navigation-only behavior is unchanged.

The live evaluator defaults to `MVP_EVAL_SCOPE=all`, which runs both the atomic cases and this workflow. Its only other accepted scope values are `atomic` and `workflow`. A scoped live run records its scope and preserves the same state-and-structured-events oracle, but it is subset evidence only: the scorecard hard gate requires `scope: "all"`, one clean shared fixture identity, and exactly the canonical seven atomic IDs plus the canonical workflow ID(s) (with no duplicates or substitutions), so it must not be represented as full readiness.

## Evidence lanes

| Lane | What it checks | What it does not prove |
|---|---|---|
| `npm run test:mvp-evidence` | Deterministic source/oracle contracts for MVP evidence | A model, browser, Entra, or Azure run |
| Deep Agents live MVP eval | Configured local runtime, model, guarded fixture, structured events, and state | General reliability or a deployed Azure/Entra result |
| `npm run eval:waza:check` | Pinned Waza readiness, the one skill, and eval schema | Product state or user workflow |
| Waza gate/advisory | Same-skill routing laboratory using Copilot/model calls | Deep Agents product behavior or product state |
| Browser/Azure/Entra observation | The specifically executed environment and revision | Any other environment, revision, or model behavior |

`npm run eval:waza:gate` and `npm run eval:waza:advisory` make external/model calls and require deliberate human authorization. Live MVP evaluation also calls the configured model and requires that authorization. A Waza pass does not prove product state. Likewise, deterministic source/readiness checks do not prove browser, Entra, Azure, or model behavior.

Live MVP evaluation and Playwright require the local emulator and running services. Review normalized state, correlated structured events, and browser output rather than accepting assistant language or a single pass field as an oracle.
