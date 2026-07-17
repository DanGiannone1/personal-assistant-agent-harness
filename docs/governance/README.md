# Developer Governance Index

> **HUMAN-OWNED GOVERNING SOURCE OF TRUTH**
>
> Agents must not edit, replace, move, delete, or create a competing version of
> this file unless the user explicitly authorizes changes to this named file in
> the current conversation.

This directory is the canonical, runtime-neutral governance home for this
repository. Native Claude and Codex files load these documents and keep only
runtime mechanics in their own definitions.

| Concern | Canonical source |
|---|---|
| Work lifecycle, approval, isolation, review, and integration | [master-sdlc.md](master-sdlc.md) |
| Behavioral proof and testing | [testing-charter.md](testing-charter.md) |
| Safe hands-on engineering execution | [engineering-operating-standards.md](engineering-operating-standards.md) |
| Agent, skill, and handoff design | [agentic-design.md](agentic-design.md) |
| Product and architecture documentation map | [../README.md](../README.md) |
| Product intent and behavior | [../spec.md](../spec.md) and [../use-cases.md](../use-cases.md) |
| Current architecture | [../architecture.md](../architecture.md) and the reference architectures linked from [../README.md](../README.md) |
| Local development and verification | [../development.md](../development.md) |
| Deployment and operational constraints | [../deployment.md](../deployment.md) |

Each rule has one canonical home. Runtime prompts, skills, templates, issues,
and pull requests may point to a rule but must not restate it as a competing
authority. When sources conflict, stop and obtain a human decision rather than
blending them.

Living guidance keeps a stable path and is updated in place. Records of past
decisions or evidence are not current guidance without re-verification.
