# Development governance

> **Human-owned document**
>
> Agents must not edit, replace, move, delete, or create another file that competes with this one
> unless the user explicitly approves changes to this named file in the current conversation.

These documents define how repository work is approved, carried out, checked, and reviewed. Claude
and Codex keep their runtime settings in their own directories and use these shared rules.

| Question | Document |
|---|---|
| How does work move from request to completion? | [Master SDLC](master-sdlc.md) |
| How should repository work be carried out safely? | [Engineering Operating Standards](engineering-operating-standards.md) |
| How should behavior be checked? | [Testing Charter](testing-charter.md) |
| How should agents, skills, and handoffs be designed? | [Agentic Design](agentic-design.md) |
| What is the product expected to do? | [Product requirements](../product/requirements.md) |
| How does the application work today? | [Architecture overview](../architecture/README.md) |
| How is it run locally? | [Local development](../guides/local-development.md) |
| How is it deployed? | [Azure deployment](../guides/deployment.md) |

Each rule has one home. Runtime prompts and contributor guides should link here instead of copying
the same rule. If two required documents disagree, stop and ask the user which direction to follow.
