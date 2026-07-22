# Agentic Design

> **Human-owned document**
>
> Agents must not edit, replace, move, delete, or create another file that competes with this one
> unless the user explicitly approves changes to this named file in the current conversation.

Agents make judgments. Give them clear responsibility, limits, prohibited actions, escalation
conditions, and safety rules without replacing judgment with brittle scripts.

## Runtime independence

Claude and Codex remain independently launchable and own their native profiles, tools, permissions,
models, skills, and delegation settings. Shared development rules live only in `docs/governance/`.
Each runtime links to those rules without generating or synchronizing the other runtime's files.

## Handoffs and review

Give each worker a bounded goal, file ownership or responsibility, scope, exclusions, relevant
sources, required results, and stop conditions. Workers gather facts or implement assigned changes;
the responsible lead or human makes product, architecture, risk, and final-approval decisions.

An independent reviewer receives the success criteria and completed results. A worker that writes a
change cannot be the reviewer who gives final approval.

## Tool and permission limits

Use native tool and permission restrictions for rules that must be enforced, then repeat the intent
in instructions. A prompt restriction guides behavior but does not enforce a technical boundary.
When agent definitions change, confirm the tools and delegation depth actually available at runtime.

## Design check

Before changing agent guidance, confirm that each rule has one shared home, Claude and Codex remain
independent, repeated instructions have been removed, and the change solves an observed problem.
