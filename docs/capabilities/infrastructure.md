# Infrastructure boundary

> **Authority:** Focused deployment-shape note. The executable [deployment runbook](../deployment.md) controls operation.

`infra/deploy.sh` creates an isolated instance from explicit `INSTANCE_SLUG` and explicit model inputs. Its resource group is `csa-wb-<slug>-rg`. The script plans by default, performs guarded Azure reads/what-if, and requires a human-provided exact confirmation before apply.

The deployment source defines a frontend, API, internal runtime, durable data services, managed identities, and supporting network resources. Its source contract is not proof that a current Azure instance exists, has the same inventory, can authenticate users, or can reach a model. Fresh-instance foundation what-if cannot preview later Entra creation, image builds, or app deployment.

Never infer a fixed model, model version, resource name, cost, public URL, or live security property from historical documentation. Use the current script and a human-reviewed plan.
