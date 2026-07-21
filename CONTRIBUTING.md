# Contributing to CSA Workbench

CSA Workbench is an internal MVP POC. Before meaningful work, read [AGENTS.md](AGENTS.md), the [documentation index](docs/README.md), and [governance](docs/governance/README.md). Those sources define the lifecycle, engineering standard, and testing standard.

Work from the current checkout, preserve unrelated changes, and keep changes scoped. Inspect source before repeating a documentation or behavior claim. Use an isolated local run when running the stack, and run the nonsecret deterministic verification appropriate to the change; the repository-wide command is:

```bash
npm run verify
```

Do not treat a source check as proof of browser, Entra, Azure, or model behavior. Live evals and Azure apply require deliberate human authorization. See [coding-agent setup](docs/coding-agent-setup.md) and the [deployment runbook](docs/deployment.md).

Do not add an external-sharing, license, security-contact, or release policy without a human decision.
