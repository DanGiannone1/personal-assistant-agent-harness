# Agentic Design

> **HUMAN-OWNED GOVERNING SOURCE OF TRUTH**
>
> Agents must not edit, replace, move, delete, or create a competing version of
> this file unless the user explicitly authorizes changes to this named file in
> the current conversation.

Agents are reasoning systems. Define durable authority, ownership, prohibited
actions, escalation conditions, and safety limits without replacing judgment
with brittle scripts or speculative controls.

## Runtime independence

Claude and Codex remain independently launchable and own their native profile,
tools, permissions, models, skills, and orchestration mechanics. Shared doctrine
lives only in `docs/governance/`; native files reference it without generating
or synchronizing one runtime from the other.

## Handoffs and review

Give each worker a bounded objective, ownership or responsibility, scope,
exclusions, relevant sources, required evidence, and stop conditions. Workers
provide evidence; the responsible lead or human makes product, architecture,
risk, and acceptance decisions.

Independent reviewers receive acceptance criteria and evidence, not an
instruction to trust the author's conclusion. A worker that implements a change
must not be its accepting reviewer.

## Capability boundaries

Prefer native permission and tool restrictions for hard safety boundaries, then
reinforce them in instructions. Treat prompt-only prohibitions as behavioral
constraints, not enforcement. Verify actual tool exposure and delegation depth
when agent definitions change.

## Design check

Before changing agent guidance, confirm one canonical source owns each rule,
runtime independence remains intact, duplicated doctrine is removed, and the
change addresses a demonstrated need.
