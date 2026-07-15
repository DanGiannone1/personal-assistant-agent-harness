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
            raise AssertionError("runtime app-role relationship queries must not use Graph filters")
        if "/appRoleAssignedTo" in path:
            return {"value": deepcopy(self.assignments)}
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
    assert any(path.endswith("/appRoleAssignedTo") for path, _ in graph.posts)


def test_entra_helper_updates_one_existing_web_redirect_once_then_is_idempotent() -> None:
    graph = FakeGraph()
    entra.ensure_entra(graph, "tenant", "https://old-frontend.example", "api-uami-principal")
    patch_count = len(graph.patches)

    result = entra.ensure_entra(graph, "tenant", "https://new-frontend.example", "api-uami-principal")

    web = next(app for app in graph.apps if app["displayName"] == entra.WEB_NAME)
    assert web["spa"]["redirectUris"] == ["https://new-frontend.example"]
    assert result.web_client_id == web["appId"]
    assert graph.patches[patch_count:] == [(f"applications/{web['id']}", {"spa": {"redirectUris": ["https://new-frontend.example"]}})]

    entra.ensure_entra(graph, "tenant", "https://new-frontend.example", "api-uami-principal")
    assert len(graph.patches) == patch_count + 1


@pytest.mark.parametrize("redirect_uris", [
    ["https://old-frontend.example", "https://new-frontend.example"],
    ["http://frontend.example"],
    "https://frontend.example",
])
def test_entra_helper_rejects_multiple_or_malformed_web_redirects_without_patching(redirect_uris: object) -> None:
    graph = FakeGraph()
    entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")
    web = next(app for app in graph.apps if app["displayName"] == entra.WEB_NAME)
    web["spa"]["redirectUris"] = redirect_uris
    patch_count = len(graph.patches)

    with pytest.raises(entra.GraphError, match="redirectUris"):
        entra.ensure_entra(graph, "tenant", "https://new-frontend.example", "api-uami-principal")

    assert len(graph.patches) == patch_count


def test_entra_helper_rejects_web_required_permission_drift_without_patching() -> None:
    graph = FakeGraph()
    entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")
    web = next(app for app in graph.apps if app["displayName"] == entra.WEB_NAME)
    web["requiredResourceAccess"][0]["resourceAccess"][0]["id"] = "wrong-scope"
    patch_count = len(graph.patches)

    with pytest.raises(entra.GraphError, match="conflicting requiredResourceAccess"):
        entra.ensure_entra(graph, "tenant", "https://new-frontend.example", "api-uami-principal")

    assert len(graph.patches) == patch_count


def test_entra_preflight_rejects_runtime_drift_before_web_redirect_patch_or_other_mutation() -> None:
    graph = FakeGraph()
    entra.ensure_entra(graph, "tenant", "https://old-frontend.example", "api-uami-principal")
    runtime = next(app for app in graph.apps if app["displayName"] == entra.RUNTIME_NAME)
    runtime["appRoles"][0]["value"] = "drifted"
    post_count, patch_count = len(graph.posts), len(graph.patches)

    with pytest.raises(entra.GraphError, match="conflicting appRoles"):
        entra.ensure_entra(graph, "tenant", "https://new-frontend.example", "api-uami-principal")

    assert len(graph.posts) == post_count
    assert len(graph.patches) == patch_count


def test_entra_preflight_rejects_api_preauthorization_when_web_is_absent_without_mutation() -> None:
    graph = FakeGraph()
    api = {**entra.api_shape(), "id": "api-object", "appId": "api-client", "identifierUris": ["api://api-client"]}
    api["api"] = {**api["api"], "preAuthorizedApplications": [{"appId": "old-web", "delegatedPermissionIds": [entra.API_SCOPE_ID]}]}
    graph.apps = [api]

    with pytest.raises(entra.GraphError, match="Web is absent"):
        entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")

    assert graph.posts == []
    assert graph.patches == []


@pytest.mark.parametrize("redirect_uri", [
    "http://frontend.example",
    "https://user@frontend.example",
    "https://frontend.example:443",
    "https://frontend.example/path",
    "https://frontend.example?query=value",
    "https://frontend.example#fragment",
    "https://frontend.example\n",
])
def test_entra_helper_rejects_non_root_or_malformed_frontend_redirect_uri_before_mutation(redirect_uri: str) -> None:
    graph = FakeGraph()

    with pytest.raises(entra.GraphError, match="HTTPS frontend redirect URI"):
        entra.ensure_entra(graph, "tenant", redirect_uri, "api-uami-principal")

    assert graph.posts == []
    assert graph.patches == []


def test_entra_helper_tolerates_server_app_role_metadata_but_rejects_role_drift_or_extra_items() -> None:
    graph = FakeGraph()
    entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")
    runtime = next(app for app in graph.apps if app["displayName"] == entra.RUNTIME_NAME)
    runtime["appRoles"][0]["origin"] = "Application"
    post_count, patch_count = len(graph.posts), len(graph.patches)
    entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")
    assert len(graph.posts) == post_count and len(graph.patches) == patch_count
    runtime["appRoles"][0]["value"] = "wrong-role"
    with pytest.raises(entra.GraphError, match="conflicting appRoles"):
        entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")

    graph = FakeGraph()
    entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")
    runtime = next(app for app in graph.apps if app["displayName"] == entra.RUNTIME_NAME)
    runtime["appRoles"].append(deepcopy(runtime["appRoles"][0]))
    with pytest.raises(entra.GraphError, match="conflicting appRoles"):
        entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")


def test_entra_helper_accepts_reordered_preauthorization_entries_without_patching() -> None:
    graph = FakeGraph()
    entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")
    api = next(app for app in graph.apps if app["displayName"] == entra.API_NAME)
    api["api"]["preAuthorizedApplications"].reverse()
    patch_count = len(graph.patches)
    entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")
    assert len(graph.patches) == patch_count
    api["api"]["preAuthorizedApplications"][0]["delegatedPermissionIds"] = ["wrong-permission"]
    with pytest.raises(entra.GraphError, match="conflicting pre-authorized"):
        entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")


@pytest.mark.parametrize("malformed", [None, {}, ""])
def test_entra_helper_rejects_falsey_malformed_preauthorization_without_patching(malformed: object) -> None:
    graph = FakeGraph()
    entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")
    api = next(app for app in graph.apps if app["displayName"] == entra.API_NAME)
    api["api"]["preAuthorizedApplications"] = malformed
    patch_count = len(graph.patches)
    with pytest.raises(entra.GraphError, match="malformed pre-authorized"):
        entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")
    assert len(graph.patches) == patch_count


def test_entra_helper_rejects_unexpected_preauthorization_keys_without_patching() -> None:
    graph = FakeGraph()
    entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")
    api = next(app for app in graph.apps if app["displayName"] == entra.API_NAME)
    api["api"]["preAuthorizedApplications"][0]["unexpected"] = "value"
    patch_count = len(graph.patches)
    with pytest.raises(entra.GraphError, match="malformed pre-authorized"):
        entra.ensure_entra(graph, "tenant", "https://frontend.example", "api-uami-principal")
    assert len(graph.patches) == patch_count


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
    assert "publicnetworkaccess: 'disabled'" in foundation.lower()
    assert "infrastructuresubnetid" in foundation.lower()
    assert "workloadprofiles:" in foundation.lower()
    assert "privateendpointnetworkpolicies: 'disabled'" in foundation.lower()
    assert "privatelink.documents.azure.com" in foundation.lower()
    assert "privatelink.blob.core.windows.net" in foundation.lower()
    assert "microsoft.network/privateendpoints" in foundation.lower()
    assert "microsoft.network/privatednszones" in foundation.lower()
    assert "minreplicas: 0" in apps.lower() and "maxreplicas: 1" in apps.lower()
    assert apps.lower().count("workloadprofilename: 'consumption'") == 3
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
    assert "${LOCATION:-eastus2}" in deploy
    assert "param location string = 'eastus2'" in (ROOT / "infra" / "foundation.bicep").read_text()
    assert "remove_incompatible_environment" in deploy
    assert "if ! truthy \"$APPLY\"; then" in deploy
    assert "event-subscription list -g \"$RESOURCE_GROUP\" --system-topic-name \"$event_topic_name\"" in deploy
    assert 'RUNTIME_FQDN="${RUNTIME_APP_NAME}.internal.${ENVIRONMENT_DOMAIN}"' in deploy


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

    environment_name, vnet_name = "csa-workbench-env", "csa-workbench-vnet"
    aca_subnet, pe_subnet = "aca-infrastructure", "private-endpoints"
    cosmos_zone, storage_zone = "privatelink.documents.azure.com", "privatelink.blob.core.windows.net"
    cosmos_pe, storage_pe = "csa-workbench-cosmos-pe", "csa-workbench-storage-pe"
    vnet_id = f"{prefix}/{resource_group}/providers/Microsoft.Network/virtualNetworks/{vnet_name}"
    environment_id = f"{prefix}/{resource_group}/providers/Microsoft.App/managedEnvironments/{environment_name}"

    def app(name: str, external: bool, image: str, cpu: float, memory: str) -> dict[str, Any]:
        return {"name": name, "properties": {"provisioningState": "Succeeded", "managedEnvironmentId": environment_id, "workloadProfileName": "Consumption", "configuration": {"ingress": {"external": external, "targetPort": {"csa-workbench-frontend": 3000, "csa-workbench-api": 8000, "csa-workbench-runtime": 8080}[name], "transport": "auto"}}, "template": {
            "scale": {"minReplicas": 0, "maxReplicas": 1, "cooldownPeriod": 300, "pollingInterval": 30, "rules": []},
            "containers": [{"image": f"{acr}.azurecr.io/{image}:{'a' * 40}", "resources": {"cpu": cpu, "memory": memory, "ephemeralStorage": "1Gi"}}],
        }}}

    apps = [app("csa-workbench-frontend", True, "csa-workbench-frontend", .25, "0.5Gi"), app("csa-workbench-api", True, "csa-workbench-api", .5, "1Gi"), app("csa-workbench-runtime", False, "csa-workbench-runtime", 1.0, "2Gi")]
    assignment_scope = lambda scope: scope.replace("/resourceGroups/", "/resourcegroups/")
    assignments = [
        [{"scope": assignment_scope(acr_scope), "roleDefinitionName": "AcrPull", "principalId": "frontend"}],
        [{"scope": assignment_scope(acr_scope), "roleDefinitionName": "AcrPull", "principalId": "api"}, {"scope": assignment_scope(storage_scope), "roleDefinitionName": "Storage Blob Data Contributor", "principalId": "api"}],
        [{"scope": assignment_scope(acr_scope), "roleDefinitionName": "AcrPull", "principalId": "runtime"}, {"scope": assignment_scope(aoai_scope), "roleDefinitionName": "Cognitive Services OpenAI User", "principalId": "runtime"}],
    ]
    sql_role = f"{cosmos_scope}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
    vnet = {"name": vnet_name, "provisioningState": "Succeeded", "addressSpace": {"addressPrefixes": ["10.42.0.0/24"]}, "subnets": [
        {"name": aca_subnet, "provisioningState": "Succeeded", "addressPrefix": "10.42.0.0/27", "delegations": [{"name": "aca-environment", "serviceName": "Microsoft.App/environments", "provisioningState": "Succeeded"}]},
        {"name": pe_subnet, "provisioningState": "Succeeded", "addressPrefix": "10.42.0.32/27", "privateEndpointNetworkPolicies": "Disabled"},
    ]}

    def endpoint(name: str, target: str, group_id: str) -> dict[str, Any]:
        return {"name": name, "provisioningState": "Succeeded", "networkInterfaces": [{"id": f"{prefix}/{resource_group}/providers/Microsoft.Network/networkInterfaces/{name}-nic"}], "subnet": {"id": f"{vnet_id}/subnets/{pe_subnet}"}, "privateLinkServiceConnections": [
            {"name": f"{name}-connection", "provisioningState": "Succeeded", "privateLinkServiceId": target, "groupIds": [group_id], "privateLinkServiceConnectionState": {"status": "Approved"}},
        ]}

    private_endpoints = [endpoint(cosmos_pe, cosmos_scope, "Sql"), endpoint(storage_pe, storage_scope, "blob")]
    private_dns_zones = [{"name": cosmos_zone, "numberOfRecordSets": 1}, {"name": storage_zone, "numberOfRecordSets": 1}]

    def dns_link() -> list[dict[str, Any]]:
        return [{"name": "csa-workbench-vnet-link", "provisioningState": "Succeeded", "virtualNetwork": {"id": vnet_id}, "registrationEnabled": False, "virtualNetworkLinkState": "Completed"}]

    def dns_group(zone: str, record_names: list[str]) -> list[dict[str, Any]]:
        return [{"name": "default", "provisioningState": "Succeeded", "privateDnsZoneConfigs": [{"name": "config", "privateDnsZoneId": f"{prefix}/{resource_group}/providers/Microsoft.Network/privateDnsZones/{zone}", "recordSets": [{"recordSetName": record_name, "provisioningState": "Succeeded", "ipAddresses": ["10.42.0.36"]} for record_name in record_names]}]}]

    managed_environment = {"name": environment_name, "properties": {"provisioningState": "Succeeded", "vnetConfiguration": {"infrastructureSubnetId": f"{vnet_id}/subnets/{aca_subnet}"}, "workloadProfiles": [{"name": "Consumption", "workloadProfileType": "Consumption", "enableFips": False}]}}
    records = lambda name: [{"name": name, "provisioningState": "Succeeded", "aRecords": [{"ipv4Address": "10.42.0.36"}]}]
    event_topics = [{"name": "storage-antimalware", "source": storage_scope, "topicType": "microsoft.storage.storageaccounts", "provisioningState": "Succeeded"}]
    resource_entries = [("Microsoft.ManagedIdentity/userAssignedIdentities", name) for name in ("csa-workbench-frontend-identity", "csa-workbench-api-identity", "csa-workbench-runtime-identity")]
    resource_entries += [("Microsoft.App/managedEnvironments", environment_name)] + [("Microsoft.App/containerApps", name) for name in ("csa-workbench-frontend", "csa-workbench-api", "csa-workbench-runtime")]
    resource_entries += [("Microsoft.DocumentDB/databaseAccounts", cosmos), ("Microsoft.Storage/storageAccounts", storage), ("Microsoft.Network/virtualNetworks", vnet_name), ("Microsoft.Network/privateEndpoints", cosmos_pe), ("Microsoft.Network/privateEndpoints", storage_pe), ("Microsoft.Network/privateDnsZones", cosmos_zone), ("Microsoft.Network/privateDnsZones", storage_zone), ("Microsoft.Network/networkInterfaces", f"{cosmos_pe}-nic"), ("Microsoft.Network/networkInterfaces", f"{storage_pe}-nic"), ("Microsoft.EventGrid/systemTopics", "storage-antimalware"), ("Microsoft.Network/privateDnsZones/virtualNetworkLinks", f"{cosmos_zone}/csa-workbench-vnet-link"), ("Microsoft.Network/privateDnsZones/virtualNetworkLinks", f"{storage_zone}/csa-workbench-vnet-link")]
    resources = [{"type": resource_type, "name": name} for resource_type, name in resource_entries]
    environment = {**os.environ, "APPS": json.dumps(apps), "RESOURCES": json.dumps(resources), "ASSIGNMENTS": json.dumps(assignments), "COSMOS": json.dumps({"disableLocalAuth": True, "publicNetworkAccess": "Disabled"}), "COSMOS_SQL_ASSIGNMENTS": json.dumps([{"roleDefinitionId": sql_role, "scope": cosmos_scope, "principalId": "api"}, {"roleDefinitionId": sql_role, "scope": cosmos_scope, "principalId": "runtime"}]), "STORAGE": json.dumps({"publicNetworkAccess": "Disabled", "allowSharedKeyAccess": False, "allowBlobPublicAccess": False}), "MANAGED_ENVIRONMENT": json.dumps(managed_environment), "VNET": json.dumps(vnet), "PRIVATE_ENDPOINTS": json.dumps(private_endpoints), "PRIVATE_DNS_ZONES": json.dumps(private_dns_zones), "COSMOS_DNS_LINKS": json.dumps(dns_link()), "STORAGE_DNS_LINKS": json.dumps(dns_link()), "COSMOS_DNS_GROUPS": json.dumps(dns_group(cosmos_zone, [cosmos, f"{cosmos}-eastus2"])), "STORAGE_DNS_GROUPS": json.dumps(dns_group(storage_zone, [storage])), "COSMOS_DNS_RECORDS": json.dumps(records(cosmos) + records(f"{cosmos}-eastus2")), "STORAGE_DNS_RECORDS": json.dumps(records(storage)), "EVENT_TOPICS": json.dumps(event_topics), "EVENT_SUBSCRIPTIONS": json.dumps([{"name": "StorageAntimalwareSubscription", "provisioningState": "Succeeded"}]), "SUBSCRIPTION_ID": subscription, "RESOURCE_GROUP": resource_group, "ACR_RESOURCE_GROUP": acr_group, "AOAI_RESOURCE_GROUP": aoai_group, "ACR_NAME": acr, "AOAI_NAME": aoai, "COSMOS_ACCOUNT_NAME": cosmos, "STORAGE_ACCOUNT_NAME": storage, "FRONTEND_APP_NAME": "csa-workbench-frontend", "API_APP_NAME": "csa-workbench-api", "RUNTIME_APP_NAME": "csa-workbench-runtime", "ENVIRONMENT_NAME": environment_name, "VNET_NAME": vnet_name, "ACA_INFRASTRUCTURE_SUBNET_NAME": aca_subnet, "PRIVATE_ENDPOINT_SUBNET_NAME": pe_subnet, "COSMOS_PRIVATE_ENDPOINT_NAME": cosmos_pe, "STORAGE_PRIVATE_ENDPOINT_NAME": storage_pe, "COSMOS_PRIVATE_DNS_ZONE": cosmos_zone, "STORAGE_PRIVATE_DNS_ZONE": storage_zone, "LOCATION": "eastus2", "SHA": "a" * 40, **principals}
    assert subprocess.run([sys.executable, "-c", verifier], env=environment, text=True, capture_output=True).returncode == 0
    environment["RESOURCES"] = json.dumps([{"type": "Microsoft.Search/searchServices"}])
    rejected = subprocess.run([sys.executable, "-c", verifier], env=environment, text=True, capture_output=True)
    assert rejected.returncode != 0
    assert "excluded resource present" in rejected.stderr
    environment["RESOURCES"] = json.dumps([{"type": "Microsoft.App/containerApps"}])
    environment["PRIVATE_ENDPOINTS"] = json.dumps(private_endpoints[:1])
    rejected = subprocess.run([sys.executable, "-c", verifier], env=environment, text=True, capture_output=True)
    assert rejected.returncode != 0
    assert "unexpected private endpoint inventory" in rejected.stderr
    environment["PRIVATE_ENDPOINTS"] = json.dumps(private_endpoints)
    environment["COSMOS_DNS_GROUPS"] = json.dumps([])
    rejected = subprocess.run([sys.executable, "-c", verifier], env=environment, text=True, capture_output=True)
    assert rejected.returncode != 0
    assert "private DNS zone group inventory drifted" in rejected.stderr
    environment["COSMOS_DNS_GROUPS"] = json.dumps(dns_group(cosmos_zone, [cosmos, f"{cosmos}-eastus2"]))
    managed_environment["properties"]["vnetConfiguration"]["infrastructureSubnetId"] = f"{vnet_id}/subnets/{pe_subnet}"
    environment["MANAGED_ENVIRONMENT"] = json.dumps(managed_environment)
    rejected = subprocess.run([sys.executable, "-c", verifier], env=environment, text=True, capture_output=True)
    assert rejected.returncode != 0
    assert "Container Apps environment private-network profile drifted" in rejected.stderr
    managed_environment["properties"]["vnetConfiguration"]["infrastructureSubnetId"] = f"{vnet_id}/subnets/{aca_subnet}"
    environment["MANAGED_ENVIRONMENT"] = json.dumps(managed_environment)
    private_endpoints[0]["privateLinkServiceConnections"][0]["privateLinkServiceConnectionState"]["status"] = "Pending"
    environment["PRIVATE_ENDPOINTS"] = json.dumps(private_endpoints)
    rejected = subprocess.run([sys.executable, "-c", verifier], env=environment, text=True, capture_output=True)
    assert rejected.returncode != 0
    assert "private endpoint profile drifted" in rejected.stderr
    private_endpoints[0]["privateLinkServiceConnections"][0]["privateLinkServiceConnectionState"]["status"] = "Approved"
    environment["PRIVATE_ENDPOINTS"] = json.dumps(private_endpoints)
    environment["COSMOS_DNS_RECORDS"] = json.dumps(records(cosmos))
    rejected = subprocess.run([sys.executable, "-c", verifier], env=environment, text=True, capture_output=True)
    assert rejected.returncode != 0
    assert "private DNS A-record inventory drifted" in rejected.stderr
    environment["COSMOS_DNS_RECORDS"] = json.dumps(records(cosmos) + records(f"{cosmos}-eastus2"))
    bad_storage_records = records(storage)
    bad_storage_records[0]["aRecords"][0]["ipv4Address"] = "10.42.0.2"
    environment["STORAGE_DNS_RECORDS"] = json.dumps(bad_storage_records)
    rejected = subprocess.run([sys.executable, "-c", verifier], env=environment, text=True, capture_output=True)
    assert rejected.returncode != 0
    assert "private DNS A-record address drifted" in rejected.stderr
    environment["STORAGE_DNS_RECORDS"] = json.dumps(records(storage))
    environment["RESOURCES"] = json.dumps([{"type": "Microsoft.Network/azureFirewalls"}])
    rejected = subprocess.run([sys.executable, "-c", verifier], env=environment, text=True, capture_output=True)
    assert rejected.returncode != 0
    assert "forbidden network resource present" in rejected.stderr
    environment["RESOURCES"] = json.dumps(resources)
    for resource_type, name in (("Microsoft.Network/virtualNetworks", "extra-vnet"), ("Microsoft.App/managedEnvironments", "extra-env"), ("Microsoft.App/containerApps", "extra-app"), ("Microsoft.Network/privateEndpoints", "extra-pe"), ("Microsoft.Network/privateDnsZones", "extra.zone"), ("Microsoft.Network/networkInterfaces", "extra-nic"), ("Microsoft.Network/virtualNetworkGateways", "extra-vpn"), ("Microsoft.Network/networkSecurityGroups", "extra-nsg"), ("Microsoft.Network/routeTables", "extra-route"), ("Contoso.Unknown/widgets", "extra")):
        environment["RESOURCES"] = json.dumps(resources + [{"type": resource_type, "name": name}])
        rejected = subprocess.run([sys.executable, "-c", verifier], env=environment, text=True, capture_output=True)
        assert rejected.returncode != 0
        assert "unexpected resource inventory" in rejected.stderr or "forbidden network resource present" in rejected.stderr

    environment["RESOURCES"] = json.dumps(resources)
    failures = [
        ("APPS", lambda value: value[0]["properties"].__setitem__("provisioningState", "Failed")),
        ("MANAGED_ENVIRONMENT", lambda value: value["properties"].__setitem__("provisioningState", "Failed")),
        ("VNET", lambda value: value.__setitem__("provisioningState", "Failed")),
        ("VNET", lambda value: value["subnets"][0].__setitem__("provisioningState", "Failed")),
        ("VNET", lambda value: value["subnets"][1].__setitem__("provisioningState", "Failed")),
        ("PRIVATE_ENDPOINTS", lambda value: value[0].__setitem__("provisioningState", "Failed")),
        ("PRIVATE_ENDPOINTS", lambda value: value[0]["privateLinkServiceConnections"][0].__setitem__("provisioningState", "Failed")),
        ("COSMOS_DNS_LINKS", lambda value: value[0].__setitem__("provisioningState", "Failed")),
        ("COSMOS_DNS_LINKS", lambda value: value[0].__setitem__("virtualNetworkLinkState", "InProgress")),
        ("COSMOS_DNS_GROUPS", lambda value: value[0].__setitem__("provisioningState", "Failed")),
        ("COSMOS_DNS_GROUPS", lambda value: value[0]["privateDnsZoneConfigs"][0]["recordSets"][0].__setitem__("provisioningState", "Failed")),
    ]
    baseline = {key: json.loads(environment[key]) for key in {item[0] for item in failures}}
    for key, mutate in failures:
        environment[key] = json.dumps(deepcopy(baseline[key]))
        mutate_value = json.loads(environment[key])
        mutate(mutate_value)
        environment[key] = json.dumps(mutate_value)
        rejected = subprocess.run([sys.executable, "-c", verifier], env=environment, text=True, capture_output=True)
        assert rejected.returncode != 0
        environment[key] = json.dumps(baseline[key])
    mismatched_group = deepcopy(baseline["COSMOS_DNS_GROUPS"])
    mismatched_group[0]["privateDnsZoneConfigs"][0]["recordSets"][0]["ipAddresses"][0] = "10.42.0.37"
    environment["COSMOS_DNS_GROUPS"] = json.dumps(mismatched_group)
    rejected = subprocess.run([sys.executable, "-c", verifier], env=environment, text=True, capture_output=True)
    assert rejected.returncode != 0
    assert "private DNS zone group records do not match" in rejected.stderr
    environment["COSMOS_DNS_GROUPS"] = json.dumps(baseline["COSMOS_DNS_GROUPS"])
    environment["EVENT_TOPICS"] = json.dumps([])
    environment["EVENT_SUBSCRIPTIONS"] = json.dumps([])
    environment["RESOURCES"] = json.dumps([resource for resource in resources if resource["type"] != "Microsoft.EventGrid/systemTopics"])
    assert subprocess.run([sys.executable, "-c", verifier], env=environment, text=True, capture_output=True).returncode == 0
    environment["EVENT_TOPICS"] = json.dumps([{**event_topics[0], "source": "wrong"}])
    rejected = subprocess.run([sys.executable, "-c", verifier], env=environment, text=True, capture_output=True)
    assert rejected.returncode != 0
    assert "Defender Storage Event Grid system topic drifted" in rejected.stderr
    environment["EVENT_TOPICS"] = json.dumps(event_topics)
    environment["EVENT_SUBSCRIPTIONS"] = json.dumps([{"name": "wrong", "provisioningState": "Succeeded"}])
    environment["RESOURCES"] = json.dumps(resources)
    rejected = subprocess.run([sys.executable, "-c", verifier], env=environment, text=True, capture_output=True)
    assert rejected.returncode != 0
    assert "Defender Storage Event Grid subscription drifted" in rejected.stderr


def test_recovery_preflight_fails_closed_and_orders_apply_deletion_before_foundation(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "az.log"
    (bin_dir / "git").write_text("#!/bin/sh\ncase \"$1\" in rev-parse) printf '%040d\\n' 0 ;; status) exit 0 ;; esac\n")
    (bin_dir / "az").write_text("""#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$AZ_LOG"
case "$*" in
  "account show --only-show-errors") exit 0 ;;
  *"account show --query tenantId"*) echo tenant ;;
  *"account show --query id"*) echo sub ;;
  "bicep version") exit 0 ;;
  *"bicep build"*) exit 0 ;;
  "group exists"*) echo true ;;
  *"containerapp env list"*)
    [ "${RECOVERY_MODE:-ok}" = list_fail ] && exit 9
    [ "${RECOVERY_MODE:-ok}" = invalid_env ] && { echo '{'; exit 0; }
    echo '[{"name":"csa-workbench-env","id":"/subscriptions/sub/resourceGroups/csa-workbench-rg/providers/Microsoft.App/managedEnvironments/csa-workbench-env"}]' ;;
  *"containerapp env show"*) [ "${RECOVERY_MODE:-ok}" = env_show_fail ] && exit 8; echo '{"name":"csa-workbench-env","id":"/subscriptions/sub/resourceGroups/csa-workbench-rg/providers/Microsoft.App/managedEnvironments/csa-workbench-env","properties":{}}' ;;
  *"containerapp list"*)
    [ "${RECOVERY_MODE:-ok}" = invalid_apps ] && { echo '{'; exit 0; }
    apps='[{"name":"csa-workbench-frontend","properties":{"managedEnvironmentId":"/subscriptions/sub/resourceGroups/csa-workbench-rg/providers/Microsoft.App/managedEnvironments/csa-workbench-env"}},{"name":"csa-workbench-api","properties":{"managedEnvironmentId":"/subscriptions/sub/resourceGroups/csa-workbench-rg/providers/Microsoft.App/managedEnvironments/csa-workbench-env"}},{"name":"csa-workbench-runtime","properties":{"managedEnvironmentId":"/subscriptions/sub/resourceGroups/csa-workbench-rg/providers/Microsoft.App/managedEnvironments/csa-workbench-env"}}]'
    [ "${RECOVERY_MODE:-ok}" = missing ] && apps='[]'
    [ "${RECOVERY_MODE:-ok}" = unexpected ] && apps='[{"name":"other","properties":{"managedEnvironmentId":"/subscriptions/sub/resourceGroups/csa-workbench-rg/providers/Microsoft.App/managedEnvironments/csa-workbench-env"}}]'
    echo "$apps" ;;
  *"containerapp delete"*|*"containerapp env delete"*|*"deployment sub what-if"*|*"deployment sub create"*) exit 0 ;;
  *"deployment sub show"*) exit 7 ;;
  *) exit 0 ;;
esac
""")
    for executable in bin_dir.iterdir():
        executable.chmod(0o755)

    def run(mode: str, apply: bool, optimized: bool = False) -> subprocess.CompletedProcess[str]:
        log.write_text("")
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "AZ_LOG": str(log), "RECOVERY_MODE": mode, "APPLY": str(apply).lower(), "PYTHONOPTIMIZE": "1" if optimized else ""}
        return subprocess.run(["bash", "infra/deploy.sh"], cwd=ROOT, env=env, text=True, capture_output=True)

    for mode in ("list_fail", "env_show_fail", "invalid_env", "invalid_apps", "missing", "unexpected"):
        result = run(mode, False)
        assert result.returncode != 0
        assert "containerapp delete" not in log.read_text()
    result = run("unexpected", False, optimized=True)
    assert result.returncode != 0
    optimized_log = log.read_text()
    assert "containerapp delete" not in optimized_log and "deployment sub what-if" not in optimized_log and "deployment sub create" not in optimized_log

    result = run("ok", False)
    assert result.returncode == 0
    dry_log = log.read_text()
    assert "containerapp delete" not in dry_log and "deployment sub what-if" not in dry_log and "deployment sub create" not in dry_log

    result = run("ok", True)
    assert result.returncode != 0
    events = log.read_text().splitlines()
    ordered = [event for event in events if "containerapp delete" in event or "containerapp env delete" in event or "deployment sub what-if" in event or "deployment sub create" in event]
    assert ordered[:5] == [
        "containerapp delete -g csa-workbench-rg -n csa-workbench-frontend --yes --only-show-errors",
        "containerapp delete -g csa-workbench-rg -n csa-workbench-api --yes --only-show-errors",
        "containerapp delete -g csa-workbench-rg -n csa-workbench-runtime --yes --only-show-errors",
        "containerapp env delete -g csa-workbench-rg -n csa-workbench-env --yes --only-show-errors",
        next(event for event in ordered if "deployment sub what-if" in event),
    ]
    assert "deployment sub create" in ordered[5]
