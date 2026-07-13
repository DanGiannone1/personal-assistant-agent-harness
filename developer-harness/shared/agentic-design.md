# Agentic Design

Agents are reasoning systems. Prescribe durable boundaries, ownership,
prohibited actions, escalation conditions, and safety limits; do not replace
judgment with brittle scripts, fixed formatting, or speculative controls.

## Runtime independence

Each runtime remains independently launchable and owns its own configuration,
entrypoint, tools, hooks, models, and orchestration mechanics. Shared doctrine
is tool-neutral and must not depend on any runtime's internal files or syntax.
Native entrypoints load shared doctrine and retain only native mechanics.

Provide separate Principal Product Engineering Lead (PPEL) entrypoints for
Codex and Claude. They must be semantically aligned on authority, approval,
quality, and user communication, yet neither may load, generate, synchronize
from, or depend on the other. Do not introduce generation, synchronization, or
another layered prompt architecture; maintain the two entrypoints directly as
independent native sources.

## Handoffs and review

Give each worker a bounded objective, ownership, scope, exclusions, evidence
needed, and stop conditions. Keep decisions reserved for the responsible lead or
human. Independent reviewers receive the acceptance criteria and relevant
evidence, not an instruction to trust the author's conclusion. Keep handoffs
natural-language and evidence-based rather than schema-bound.

## Design check

Before changing agent guidance, confirm it establishes one clear source of
truth, protects runtime independence, avoids duplicated doctrine, and addresses
a demonstrated failure mode rather than imagined complexity.
