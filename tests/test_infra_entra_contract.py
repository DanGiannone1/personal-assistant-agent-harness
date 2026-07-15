"""Focused desired-state contracts for the deploy-only Entra helper and IaC."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("entra", ROOT / "infra" / "entra.py")
assert SPEC and SPEC.loader
entra = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = entra
SPEC.loader.exec_module(entra)


class FakeGraph:
    def __init__(self) -> None:
        self.apps: list[dict[str, Any]] = []
        self.sps: list[dict[str, Any]] = []
        self.assignments: list[dict[str, Any]] = []
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.patches: list[tuple[str, dict[str, Any]]] = []

    def get(self, path: str) -> dict[str, Any]:
        if path.startswith("applications?"):
            decoded = unquote(path)
            name = next(name for name in (entra.API_NAME, entra.WEB_NAME, entra.RUNTIME_NAME) if name in decoded)
            return {"value": [deepcopy(app) for app in self.apps if app["displayName"] == name]}
        if path.startswith("servicePrincipals?"):
            app_id = unquote(path).split("appId eq '", 1)[1].split("'", 1)[0]
            return {"value": [deepcopy(sp) for sp in self.sps if sp["appId"] == app_id]}
        if "/appRoleAssignedTo?" in path:
            principal = unquote(path).split("principalId eq ", 1)[1]
            return {"value": [deepcopy(item) for item in self.assignments if item["principalId"] == principal]}
        raise AssertionError(path)

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self.posts.append((path, deepcopy(body)))
        if path == "applications":
            app = {**deepcopy(body), "id": f"object-{len(self.apps) + 1}", "appId": f"client-{len(self.apps) + 1}", "identifierUris": []}
            self.apps.append(app)
            return deepcopy(app)
        if path == "servicePrincipals":
            sp = {"id": f"sp-{len(self.sps) + 1}", "appId": body["appId"]}
            self.sps.append(sp)
            return deepcopy(sp)
        if path.endswith("/appRoleAssignedTo"):
            self.assignments.append(deepcopy(body))
            return deepcopy(body)
        raise AssertionError(path)

    def patch(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self.patches.append((path, deepcopy(body)))
        app = next(item for item in self.apps if path.endswith(item["id"]))
        app.update(deepcopy(body))
        return deepcopy(app)


def test_entra_helper_creates_exact_dedicated_shapes_and_runtime_assignment() -> None:
    graph = FakeGraph()
    result = entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")

    assert result.api_client_id == "client-1"
    api = next(app for app in graph.apps if app["displayName"] == entra.API_NAME)
    web = next(app for app in graph.apps if app["displayName"] == entra.WEB_NAME)
    runtime = next(app for app in graph.apps if app["displayName"] == entra.RUNTIME_NAME)
    assert api["api"]["oauth2PermissionScopes"][0]["value"] == "access_as_user"
    assert api["api"]["requestedAccessTokenVersion"] == 2
    assert api["identifierUris"] == ["api://client-1"]
    assert web["spa"]["redirectUris"] == ["https://frontend.example"]
    assert web["requiredResourceAccess"][0]["resourceAppId"] == "client-1"
    assert runtime["appRoles"][0]["value"] == "invoke"
    assert runtime["identifierUris"] == ["api://client-3"]
    assert graph.assignments == [{"principalId": "api-uami-principal", "resourceId": "sp-3", "appRoleId": entra.RUNTIME_ROLE_ID}]
    preauth = api["api"]["preAuthorizedApplications"]
    assert {entry["appId"] for entry in preauth} == {"client-2", entra.AZURE_CLI_CLIENT_ID}


def test_entra_helper_is_idempotent_without_duplicate_graph_posts() -> None:
    graph = FakeGraph()
    first = entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")
    post_count = len(graph.posts)
    second = entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")
    assert second == first
    assert len(graph.posts) == post_count


def test_entra_helper_fails_closed_for_duplicate_or_conflicting_dedicated_apps() -> None:
    graph = FakeGraph()
    graph.apps = [{"displayName": entra.API_NAME}, {"displayName": entra.API_NAME}]
    with pytest.raises(entra.GraphError, match="duplicate dedicated"):
        entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")

    graph = FakeGraph()
    graph.apps = [{"displayName": entra.API_NAME, "signInAudience": "AzureADMultipleOrgs"}]
    with pytest.raises(entra.GraphError, match="conflicting"):
        entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")

    graph = FakeGraph()
    entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")
    runtime = next(app for app in graph.apps if app["displayName"] == entra.RUNTIME_NAME)
    runtime["identifierUris"] = ["api://wrong-runtime"]
    with pytest.raises(entra.GraphError, match="CSA Workbench Runtime has conflicting identifierUris"):
        entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")


def test_static_deployment_contract_has_no_legacy_or_secret_based_profile() -> None:
    foundation = (ROOT / "infra" / "platform.bicep").read_text()
    apps = (ROOT / "infra" / "apps.bicep").read_text()
    deploy = (ROOT / "infra" / "deploy.sh").read_text()
    workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    combined = "\n".join((foundation, apps, workflow)).lower()
    for excluded in ("dynamic sessions", "sessionpool", "azure_credentials", "publish profile", "appinsights", "log analytics", "azure search", "adls", "mcp", "front door", "apim", "nat gateway"):
        assert excluded not in combined
    assert ":latest" not in "\n".join((apps, deploy)).lower()
    assert "excluded resource present" in deploy.lower()
    assert "applogsconfiguration" in foundation.lower()
    assert "destination: null" in foundation.lower()
    assert "loganalyticsconfiguration: null" in foundation.lower()
    assert "loganalyticsworkspace" not in foundation.lower()
    assert "enableserverless" in foundation.lower()
    assert "allowsharedkeyaccess: false" in foundation.lower()
    assert "minreplicas: 0" in apps.lower() and "maxreplicas: 1" in apps.lower()
    assert "workload_auth_mode" in apps.lower() and "identity_mode" in apps.lower()
    assert "apply=true" in deploy.lower()
    assert "microsoft.documentdb/databaseaccounts/sqlroleassignments" in foundation.lower()
    assert "sqlroledefinitions" in foundation.lower() and "00000000-0000-0000-0000-000000000002" in foundation
    assert "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd" in (ROOT / "infra" / "openai-role.bicep").read_text()
    assert "a001fd3d-188f-4b5d-821b-7da978bf7442" not in (ROOT / "infra" / "openai-role.bicep").read_text()
    assert "openai.azure.com" not in apps.lower()
    assert "azureopenaiendpoint" in apps.lower() and "azureopenaideployment" in apps.lower()
    assert "sql role assignment list" in deploy.lower()
    assert "{ name: 'pool_auth_audience', value: 'api://${runtimeclientid}' }" in apps.lower()
    assert "{ name: 'workload_entra_audience', value: runtimeclientid }" in apps.lower()
    assert "properties['template']['scale'] !=" not in deploy
    assert "container['resources'] !=" not in deploy
    assert "${LOCATION:-eastus}" in deploy
    assert "param location string = 'eastus'" in (ROOT / "infra" / "foundation.bicep").read_text()


def test_embedded_inventory_verifier_tolerates_azure_fields_and_rejects_excluded_resources() -> None:
    script = (ROOT / "infra" / "deploy.sh").read_text()
    start = script.index("python3 - <<'PY'\n") + len("python3 - <<'PY'\n")
    verifier = script[start:script.index("\nPY\n}", start)]
    subscription, resource_group, acr_group, aoai_group = "sub", "csa-workbench-rg", "shared-services-rg", "flow-dev-rg"
    acr, cosmos, storage, aoai = "djgsharedacr", "csaworkbench9fc05183", "csaworkbench9fc05183", "rfpagent-ai"
    principals = {"FRONTEND_PRINCIPAL": "frontend", "API_PRINCIPAL": "api", "RUNTIME_PRINCIPAL": "runtime"}
    prefix = f"/subscriptions/{subscription}/resourceGroups"
    acr_scope = f"{prefix}/{acr_group}/providers/Microsoft.ContainerRegistry/registries/{acr}"
    cosmos_scope = f"{prefix}/{resource_group}/providers/Microsoft.DocumentDB/databaseAccounts/{cosmos}"
    storage_scope = f"{prefix}/{resource_group}/providers/Microsoft.Storage/storageAccounts/{storage}"
    aoai_scope = f"{prefix}/{aoai_group}/providers/Microsoft.CognitiveServices/accounts/{aoai}"

    def app(name: str, external: bool, image: str, cpu: float, memory: str) -> dict[str, Any]:
        return {"name": name, "properties": {"configuration": {"ingress": {"external": external}}, "template": {
            "scale": {"minReplicas": 0, "maxReplicas": 1, "cooldownPeriod": 300, "pollingInterval": 30, "rules": []},
            "containers": [{"image": f"{acr}.azurecr.io/{image}:{'a' * 40}", "resources": {"cpu": cpu, "memory": memory, "ephemeralStorage": "1Gi"}}],
        }}}

    apps = [app("csa-workbench-frontend", True, "csa-workbench-frontend", .25, "0.5Gi"), app("csa-workbench-api", True, "csa-workbench-api", .5, "1Gi"), app("csa-workbench-runtime", False, "csa-workbench-runtime", 1.0, "2Gi")]
    assignments = [
        [{"scope": acr_scope, "roleDefinitionName": "AcrPull", "principalId": "frontend"}],
        [{"scope": acr_scope, "roleDefinitionName": "AcrPull", "principalId": "api"}, {"scope": storage_scope, "roleDefinitionName": "Storage Blob Data Contributor", "principalId": "api"}],
        [{"scope": acr_scope, "roleDefinitionName": "AcrPull", "principalId": "runtime"}, {"scope": aoai_scope, "roleDefinitionName": "Cognitive Services OpenAI User", "principalId": "runtime"}],
    ]
    sql_role = f"{cosmos_scope}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
    environment = {**os.environ, "APPS": json.dumps(apps), "RESOURCES": json.dumps([{"type": "Microsoft.App/containerApps"}]), "ASSIGNMENTS": json.dumps(assignments), "COSMOS": json.dumps({"properties": {"disableLocalAuth": True, "publicNetworkAccess": "Enabled"}}), "COSMOS_SQL_ASSIGNMENTS": json.dumps([{"roleDefinitionId": sql_role, "scope": cosmos_scope, "principalId": "api"}, {"roleDefinitionId": sql_role, "scope": cosmos_scope, "principalId": "runtime"}]), "STORAGE": json.dumps({"properties": {"allowSharedKeyAccess": False, "allowBlobPublicAccess": False}}), "SUBSCRIPTION_ID": subscription, "RESOURCE_GROUP": resource_group, "ACR_RESOURCE_GROUP": acr_group, "AOAI_RESOURCE_GROUP": aoai_group, "ACR_NAME": acr, "AOAI_NAME": aoai, "COSMOS_ACCOUNT_NAME": cosmos, "STORAGE_ACCOUNT_NAME": storage, "FRONTEND_APP_NAME": "csa-workbench-frontend", "API_APP_NAME": "csa-workbench-api", "RUNTIME_APP_NAME": "csa-workbench-runtime", "SHA": "a" * 40, **principals}
    assert subprocess.run([sys.executable, "-c", verifier], env=environment, text=True, capture_output=True).returncode == 0
    environment["RESOURCES"] = json.dumps([{"type": "Microsoft.Search/searchServices"}])
    rejected = subprocess.run([sys.executable, "-c", verifier], env=environment, text=True, capture_output=True)
    assert rejected.returncode != 0
    assert "excluded resource present" in rejected.stderr
