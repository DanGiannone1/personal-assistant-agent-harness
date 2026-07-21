# Agent harness boundary

> **Authority:** Focused current-boundary note; [design](../design.md) and [requirements](../requirements.md) remain higher authority.

The product runtime uses Deep Agents with structured Engagement tools and structured stream events. The frontend accepts navigation and state effects only after validating the event contract and then refreshing application state. Assistant text is never a control protocol or commit receipt.

Copilot uses the same product-skill area only as a local portability/evaluation lane. It is not a release dependency or evidence that the Deep Agents product lane behaved correctly. The one product skill is `engagement-meeting-prep`; it is read-only meeting preparation and does not replace direct update or navigation operations.

Session state, chat, traces, and session files are ephemeral. See [session state](session-state.md), [navigation](navigation.md), and the [eval reference architecture](../evals-reference-architecture.md) for evidence boundaries.
