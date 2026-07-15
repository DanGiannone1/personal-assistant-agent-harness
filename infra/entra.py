#!/usr/bin/env python3
"""Idempotently configure the three dedicated CSA Workbench Entra applications.

This intentionally uses only the Azure CLI's Microsoft Graph access (`az rest`)
instead of a Graph SDK or a client secret.  It never searches for or changes the
legacy Flow/RFP registrations: duplicate dedicated display names are a hard
failure, and an existing dedicated registration must match this contract.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

API_NAME = "CSA Workbench API"
WEB_NAME = "CSA Workbench Web"
RUNTIME_NAME = "CSA Workbench Runtime"
AZURE_CLI_CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
API_SCOPE_ID = "6f4a54b6-4c0d-4b22-bbeb-61b46fbcf5bf"
RUNTIME_ROLE_ID = "77bda31d-bef5-451a-a37f-84f2f5db10dd"


class GraphError(RuntimeError):
    pass


class GraphClient(Protocol):
    def get(self, path: str) -> dict[str, Any]: ...
    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]: ...
    def patch(self, path: str, body: dict[str, Any]) -> dict[str, Any]: ...


class AzureCliGraph:
    """Small injectable adapter so desired-shape behavior is mockable."""

    base_url = "https://graph.microsoft.com/v1.0/"

    def _run(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        command = ["az", "rest", "--method", method, "--url", self.base_url + path]
        if body is not None:
            command.extend(["--body", json.dumps(body, separators=(",", ":"))])
        completed = subprocess.run(command, check=False, text=True, capture_output=True)
        if completed.returncode:
            raise GraphError(completed.stderr.strip() or completed.stdout.strip() or f"Graph {method} failed")
        try:
            return json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise GraphError("Azure CLI returned invalid Graph JSON") from exc

    def get(self, path: str) -> dict[str, Any]:
        return self._run("GET", path)

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._run("POST", path, body)

    def patch(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._run("PATCH", path, body)


@dataclass(frozen=True)
class EntraIds:
    api_client_id: str
    api_object_id: str
    api_service_principal_id: str
    web_client_id: str
    web_object_id: str
    web_service_principal_id: str
    runtime_client_id: str
    runtime_object_id: str
    runtime_service_principal_id: str

    def as_json(self) -> dict[str, str]:
        return self.__dict__.copy()


def api_shape() -> dict[str, Any]:
    return {
        "displayName": API_NAME,
        "signInAudience": "AzureADMyOrg",
        "api": {"requestedAccessTokenVersion": 2, "oauth2PermissionScopes": [{
            "id": API_SCOPE_ID, "adminConsentDescription": "Access CSA Workbench on behalf of the signed-in user.",
            "adminConsentDisplayName": "Access CSA Workbench", "isEnabled": True,
            "type": "User", "userConsentDescription": "Access CSA Workbench on your behalf.",
            "userConsentDisplayName": "Access CSA Workbench", "value": "access_as_user",
        }]},
    }


def web_shape(api_client_id: str, redirect_uri: str) -> dict[str, Any]:
    return {
        "displayName": WEB_NAME,
        "signInAudience": "AzureADMyOrg",
        "spa": {"redirectUris": [redirect_uri]},
        "requiredResourceAccess": [{"resourceAppId": api_client_id, "resourceAccess": [{
            "id": API_SCOPE_ID, "type": "Scope",
        }]}],
    }


def runtime_shape() -> dict[str, Any]:
    return {
        "displayName": RUNTIME_NAME,
        "signInAudience": "AzureADMyOrg",
        "api": {"requestedAccessTokenVersion": 2},
        "appRoles": [{
            "allowedMemberTypes": ["Application"], "description": "Invoke the CSA Workbench runtime.",
            "displayName": "Invoke runtime", "id": RUNTIME_ROLE_ID, "isEnabled": True, "value": "invoke",
        }],
    }


def _one_application(graph: GraphClient, display_name: str) -> dict[str, Any] | None:
    query = "applications?$filter=" + quote(f"displayName eq '{display_name}'", safe="?$=&'")
    values = graph.get(query).get("value", [])
    if len(values) > 1:
        raise GraphError(f"duplicate dedicated Entra application display name: {display_name}")
    return values[0] if values else None


def _assert_shape(actual: dict[str, Any], desired: dict[str, Any]) -> None:
    for key, expected in desired.items():
        observed = actual.get(key)
        if isinstance(expected, dict) and isinstance(observed, dict):
            try:
                _assert_shape(observed, expected)
            except GraphError as exc:
                raise GraphError(f"{actual.get('displayName', 'application')} has conflicting {key}; refusing to mutate it") from exc
            continue
        if isinstance(expected, list) and isinstance(observed, list):
            if len(observed) != len(expected):
                raise GraphError(f"{actual.get('displayName', 'application')} has conflicting {key}; refusing to mutate it")
            for observed_item, expected_item in zip(observed, expected):
                if isinstance(expected_item, dict) and isinstance(observed_item, dict):
                    try:
                        _assert_shape(observed_item, expected_item)
                    except GraphError as exc:
                        raise GraphError(f"{actual.get('displayName', 'application')} has conflicting {key}; refusing to mutate it") from exc
                elif observed_item != expected_item:
                    raise GraphError(f"{actual.get('displayName', 'application')} has conflicting {key}; refusing to mutate it")
            continue
        if observed != expected:
            raise GraphError(f"{actual.get('displayName', 'application')} has conflicting {key}; refusing to mutate it")


def ensure_application(graph: GraphClient, desired: dict[str, Any]) -> dict[str, Any]:
    existing = _one_application(graph, desired["displayName"])
    if existing:
        _assert_shape(existing, desired)
        return existing
    return graph.post("applications", desired)


def ensure_service_principal(graph: GraphClient, app_id: str) -> dict[str, Any]:
    query = "servicePrincipals?$filter=" + quote(f"appId eq '{app_id}'", safe="?$=&'")
    values = graph.get(query).get("value", [])
    if len(values) > 1:
        raise GraphError(f"duplicate service principals for dedicated application {app_id}")
    return values[0] if values else graph.post("servicePrincipals", {"appId": app_id})


def ensure_identifier_uri(graph: GraphClient, application: dict[str, Any]) -> dict[str, Any]:
    expected = [f"api://{application['appId']}"]
    existing = application.get("identifierUris", [])
    if existing and existing != expected:
        raise GraphError(f"{application['displayName']} has conflicting identifierUris; refusing to mutate it")
    if existing != expected:
        graph.patch(f"applications/{application['id']}", {"identifierUris": expected})
        application = {**application, "identifierUris": expected}
    return application


def ensure_api_preauthorization(graph: GraphClient, api: dict[str, Any], web_client_id: str) -> None:
    expected = [
        {"appId": web_client_id, "delegatedPermissionIds": [API_SCOPE_ID]},
        {"appId": AZURE_CLI_CLIENT_ID, "delegatedPermissionIds": [API_SCOPE_ID]},
    ]
    api_configuration = api.get("api")
    if not isinstance(api_configuration, dict):
        raise GraphError("CSA Workbench API has malformed API configuration")
    if "preAuthorizedApplications" not in api_configuration or api_configuration["preAuthorizedApplications"] == []:
        graph.patch(f"applications/{api['id']}", {"api": {**api_shape()["api"], "preAuthorizedApplications": expected}})
        return
    actual = api_configuration["preAuthorizedApplications"]
    if _preauthorization_entries(actual) != _preauthorization_entries(expected):
        raise GraphError("CSA Workbench API has conflicting pre-authorized applications")


def _preauthorization_entries(entries: Any) -> frozenset[tuple[str, tuple[str, ...]]]:
    if not isinstance(entries, list):
        raise GraphError("CSA Workbench API has malformed pre-authorized applications")
    normalized: list[tuple[str, tuple[str, ...]]] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"appId", "delegatedPermissionIds"} or not isinstance(entry.get("appId"), str) or not isinstance(entry.get("delegatedPermissionIds"), list) or not all(isinstance(permission, str) for permission in entry["delegatedPermissionIds"]):
            raise GraphError("CSA Workbench API has malformed pre-authorized applications")
        normalized.append((entry["appId"], tuple(sorted(entry["delegatedPermissionIds"]))))
    if len(set(normalized)) != len(normalized):
        raise GraphError("CSA Workbench API has duplicate pre-authorized applications")
    return frozenset(normalized)


def ensure_runtime_assignment(graph: GraphClient, runtime_sp_id: str, api_uami_principal_id: str) -> None:
    assignments = [
        assignment for assignment in graph.get(f"servicePrincipals/{runtime_sp_id}/appRoleAssignedTo").get("value", [])
        if assignment.get("principalId") == api_uami_principal_id
    ]
    if len(assignments) > 1:
        raise GraphError("duplicate runtime application-role assignments for API managed identity")
    if assignments:
        assignment = assignments[0]
        if assignment.get("appRoleId") != RUNTIME_ROLE_ID or assignment.get("principalId") != api_uami_principal_id:
            raise GraphError("API managed identity has a conflicting runtime application-role assignment")
        return
    graph.post(f"servicePrincipals/{runtime_sp_id}/appRoleAssignedTo", {
        "principalId": api_uami_principal_id,
        "resourceId": runtime_sp_id,
        "appRoleId": RUNTIME_ROLE_ID,
    })


def ensure_entra(graph: GraphClient, tenant_id: str, frontend_redirect_uri: str, api_uami_principal_id: str) -> EntraIds:
    if not tenant_id or not frontend_redirect_uri.startswith("https://") or not api_uami_principal_id:
        raise GraphError("tenant id, HTTPS frontend redirect URI, and API managed-identity principal id are required")
    api = ensure_identifier_uri(graph, ensure_application(graph, api_shape()))
    web = ensure_application(graph, web_shape(api["appId"], frontend_redirect_uri))
    runtime = ensure_identifier_uri(graph, ensure_application(graph, runtime_shape()))
    ensure_api_preauthorization(graph, api, web["appId"])
    api_sp = ensure_service_principal(graph, api["appId"])
    web_sp = ensure_service_principal(graph, web["appId"])
    runtime_sp = ensure_service_principal(graph, runtime["appId"])
    ensure_runtime_assignment(graph, runtime_sp["id"], api_uami_principal_id)
    return EntraIds(api["appId"], api["id"], api_sp["id"], web["appId"], web["id"], web_sp["id"], runtime["appId"], runtime["id"], runtime_sp["id"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--frontend-redirect-uri", required=True)
    parser.add_argument("--api-uami-principal-id", required=True)
    args = parser.parse_args()
    try:
        result = ensure_entra(AzureCliGraph(), args.tenant_id, args.frontend_redirect_uri, args.api_uami_principal_id)
    except GraphError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result.as_json(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
