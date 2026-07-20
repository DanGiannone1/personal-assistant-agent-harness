# Portable Developer Harness

This is an **inactive-by-default** governance bundle. It changes nothing until
an adopter deliberately installs and maps it into a repository's own instruction
and documentation locations.

## Adoption

1. Choose one local home for the shared documents and map the files in `shared/`
   there without changing their meaning.
2. Adapt the templates in `repository/` to the repository's native agent
   entrypoints. Keep only loading, tool, and runtime mechanics in those files.
3. Copy the applicable native skill wrappers from `codex/skills/` or
   `claude/skills/` into the repository's corresponding skill location.
4. Replace every bracketed local placeholder with the repository's actual
   location, workflow owner, and approved delivery mechanics.
5. Confirm the local documentation index names one canonical source for each
   rule before enabling the entrypoints.

Recommended mapping when the adopter uses the conventional layout:

| Bundle source | Adopted destination |
|---|---|
| `shared/README.md` | `docs/README.md` |
| `shared/*.md` | matching `docs/*.md` |
| `repository/AGENTS.md` | root `AGENTS.md` |
| `repository/CLAUDE.md` | root `CLAUDE.md` |
| `codex/skills/*` | the repository's Codex skill directory |
| `claude/skills/*` | `.claude/skills/*` |
| `claude/agents/*` | `.claude/agents/*` |

The Codex PPEL profile is user-level rather than repository-active. Review the
files, then run `codex/install-profile.sh`; use `--force` only for an intentional
refresh. Start it with `codex --profile PPEL`. Claude uses the adopted native
agent and starts with `claude --agent ppel`.

Do not overwrite existing instructions, workflows, or documentation by default.
Compare them first, retain local rules that do not conflict, and resolve any
conflict with the responsible human. This bundle supplies principles, not an
automatic migration or a competing source of truth.

The canonical authority, alignment, and living-document rules are in
[`shared/README.md`](shared/README.md); do not restate them in runtime files.

## What must be customized locally

The adopter must define the local product-intent and architecture sources,
documentation paths, issue and approval mechanism, isolation model,
verification commands and environments, branch and release policy,
protected-change rules, and each runtime's native mechanics. Never place
credentials, access instructions, machine details, or operational prompts in
this portable bundle.

## Contents

- `shared/README.md` — documentation authority map
- `shared/master-sdlc.md` — work-item lifecycle
- `shared/testing-charter.md` — proof standard
- `shared/engineering-operating-standards.md` — execution safeguards
- `shared/agentic-design.md` — runtime-independent agent doctrine
- `repository/AGENTS.md` and `repository/CLAUDE.md` — installation templates
- `codex/` — PPEL profile, Luna/Terra/Sol workers, native skill wrappers, and a
  user-home profile installer; it refuses existing files unless `--force` is
  supplied explicitly
- `claude/` — native PPEL, Haiku/Sonnet/Opus workers, and skill wrappers for
  deliberate repository adoption
