"""Focused portable-instance contracts for deployment and Entra desired state."""
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
            display_name = unquote(path).split("displayName eq '", 1)[1].split("'", 1)[0]
            return {"value": [deepcopy(app) for app in self.apps if app["displayName"] == display_name]}
        if path.startswith("servicePrincipals?"):
            app_id = unquote(path).split("appId eq '", 1)[1].split("'", 1)[0]
            return {"value": [deepcopy(sp) for sp in self.sps if sp["appId"] == app_id]}
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
        app = next(item for item in self.apps if isinstance(item.get("id"), str) and path.endswith(item["id"]))
        app.update(deepcopy(body))
        return deepcopy(app)


def test_entra_creates_only_selected_instance_and_ignores_unsuffixed_legacy() -> None:
    graph = FakeGraph()
    graph.apps = [{"displayName": "CSA Workbench API"}, {"displayName": "CSA Workbench Web"}, {"displayName": "CSA Workbench Runtime"}]

    result = entra.ensure_entra(graph, "mvp1", "tenant", "https://frontend.example", "api-principal")

    names = entra.names_for_slug("mvp1")
    assert result.api_client_id == "client-4"
    assert {app["displayName"] for app in graph.apps} >= {names.web, names.api, names.runtime}
    assert len(graph.apps) == 6
    assert graph.assignments == [{"principalId": "api-principal", "resourceId": "sp-3", "appRoleId": entra.RUNTIME_ROLE_ID}]


def test_entra_fails_closed_for_duplicate_or_drifted_selected_registration_without_mutation() -> None:
    names = entra.names_for_slug("mvp1")
    graph = FakeGraph()
    graph.apps = [{"displayName": names.api}, {"displayName": names.api}]
    with pytest.raises(entra.GraphError, match="duplicate dedicated"):
        entra.ensure_entra(graph, "mvp1", "tenant", "https://frontend.example", "api-principal")
    assert graph.posts == [] and graph.patches == []

    graph = FakeGraph()
    created = entra.ensure_entra(graph, "mvp1", "tenant", "https://frontend.example", "api-principal")
    api = next(app for app in graph.apps if app["displayName"] == names.api)
    api["api"]["oauth2PermissionScopes"][0]["value"] = "drifted"
    before = (len(graph.posts), len(graph.patches))
    with pytest.raises(entra.GraphError, match="conflicting"):
        entra.ensure_entra(graph, "mvp1", "tenant", "https://frontend.example", "api-principal")
    assert (len(graph.posts), len(graph.patches)) == before
    assert created.api_client_id


@pytest.mark.parametrize("slug", ["ab", "Mvp1", "mvp-1", "mvp12345678"])
def test_entra_rejects_invalid_instance_slug_before_graph_mutation(slug: str) -> None:
    graph = FakeGraph()
    with pytest.raises(entra.GraphError, match="instance slug"):
        entra.ensure_entra(graph, slug, "tenant", "https://frontend.example", "api-principal")
    assert graph.posts == [] and graph.patches == []


def test_governance_nsg_is_instance_and_location_parameterized() -> None:
    spec = importlib.util.spec_from_file_location("governance_nsg", ROOT / "infra" / "governance_nsg.py")
    assert spec and spec.loader
    helper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = helper
    spec.loader.exec_module(helper)
    aca, private, vnet = helper.expected_names("mvp1", "westus3")
    base = "/subscriptions/sub/resourceGroups/csa-wb-mvp1-rg/providers/Microsoft.Network"
    inventory = [
        {"name": aca, "id": f"{base}/networkSecurityGroups/{aca}", "location": "WestUS3", "provisioningState": "Succeeded", "securityRules": [], "networkInterfaces": None, "subnets": []},
        {"name": private, "id": f"{base}/networkSecurityGroups/{private}", "location": "WestUS3", "provisioningState": "Succeeded", "securityRules": [], "networkInterfaces": None, "subnets": [{"id": f"{base}/virtualNetworks/{vnet}/subnets/private-endpoints"}]},
    ]
    selected = helper.select_governance_nsgs(inventory, "sub", "csa-wb-mvp1-rg", "westus3", "mvp1")
    assert selected["aca_nsg_id"].endswith(aca)
    with pytest.raises(ValueError, match="inventory drifted"):
        helper.select_governance_nsgs(inventory, "sub", "csa-wb-other-rg", "westus3", "other")


def _write_command_stubs(tmp_path: Path, recovery: bool = False, bad_recovery: bool = False, recovery_apps_order: str = 'expected') -> tuple[Path, Path]:
    bin_dir, log = tmp_path / "bin", tmp_path / "az.log"
    bin_dir.mkdir(parents=True)
    (bin_dir / "git").write_text("""#!/usr/bin/env bash
case "$1" in rev-parse) echo 0123456789abcdef0123456789abcdef01234567 ;; status) exit 0 ;; *) exit 1 ;; esac
""")
    mode = "recovery" if recovery else "absent"
    recovery_apps = {
        'expected': '[{"name":"csa-wb-mvp1-frontend","properties":{"managedEnvironmentId":"env-id"}},{"name":"csa-wb-mvp1-api","properties":{"managedEnvironmentId":"env-id"}},{"name":"csa-wb-mvp1-runtime","properties":{"managedEnvironmentId":"env-id"}}]',
        'reordered': '[{"name":"csa-wb-mvp1-runtime","properties":{"managedEnvironmentId":"env-id"}},{"name":"csa-wb-mvp1-frontend","properties":{"managedEnvironmentId":"env-id"}},{"name":"csa-wb-mvp1-api","properties":{"managedEnvironmentId":"env-id"}}]',
        'missing': '[]',
        'extra': '[{"name":"csa-wb-mvp1-frontend","properties":{"managedEnvironmentId":"env-id"}},{"name":"csa-wb-mvp1-api","properties":{"managedEnvironmentId":"env-id"}},{"name":"csa-wb-mvp1-runtime","properties":{"managedEnvironmentId":"env-id"}},{"name":"unrelated","properties":{"managedEnvironmentId":"env-id"}}]',
    }['missing' if bad_recovery else recovery_apps_order]
    (bin_dir / "az").write_text(f"""#!/usr/bin/env bash
set -eu
echo "$*" >> "$AZ_LOG"
case "$*" in
  "account show --only-show-errors") echo '{{}}' ;;
  "account show --query tenantId -o tsv") echo tenant ;;
  "account show --query id -o tsv") echo subscription ;;
  "bicep version"|"bicep build "*) exit 0 ;;
  "group exists -n csa-wb-mvp1-rg -o tsv") echo {'true' if recovery else 'false'} ;;
  "network nsg list "*) echo '[]' ;;
  "containerapp env list "*) {'echo \'[{"name":"csa-wb-mvp1-env","id":"env-id"}]\'' if recovery else "echo '[]'"} ;;
  "containerapp env show "*) echo '{{"name":"csa-wb-mvp1-env","properties":{{"vnetConfiguration":{{}},"workloadProfiles":[]}}}}' ;;
  "containerapp list "*) echo '{recovery_apps}' ;;
  "deployment sub create "*) exit 9 ;;
  *) exit 0 ;;
esac
""")
    for command in bin_dir.iterdir():
        command.chmod(0o755)
    return bin_dir, log


def _run_deploy(tmp_path: Path, *args: str, recovery: bool = False, bad_recovery: bool = False, recovery_apps_order: str = 'expected', overrides: dict[str, str] | None = None) -> tuple[subprocess.CompletedProcess[str], str]:
    bin_dir, log = _write_command_stubs(tmp_path, recovery, bad_recovery, recovery_apps_order)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}", "AZ_LOG": str(log), "INSTANCE_SLUG": "mvp1",
        "MODEL_DEPLOYMENT_NAME": "deployment", "MODEL_NAME": "model", "MODEL_VERSION": "2026-01-01",
        "MODEL_SKU_NAME": "GlobalStandard", "MODEL_CAPACITY": "30",
        **(overrides or {}),
    }
    result = subprocess.run(["bash", "infra/deploy.sh", *args], cwd=ROOT, env=env, text=True, capture_output=True)
    return result, log.read_text() if log.exists() else ""


def test_plan_requires_explicit_inputs_and_never_mutates(tmp_path: Path) -> None:
    result, log = _run_deploy(tmp_path)
    assert result.returncode == 0, result.stderr
    assert 'PLAN_ID=' in result.stdout and 'CONFIRM=apply:' in result.stdout
    assert 'deployment sub what-if' in log
    assert '--result-format FullResourcePayloads' in log
    for forbidden in ('deployment sub create', 'containerapp delete', 'containerapp env delete', 'acr build', 'rest --method POST', 'rest --method PATCH', 'deployment group create'):
        assert forbidden not in log

    env = {**os.environ, "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}"}
    missing = subprocess.run(["bash", "infra/deploy.sh"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert missing.returncode != 0 and 'INSTANCE_SLUG is required' in missing.stderr
    whitespace, whitespace_log = _run_deploy(tmp_path / 'whitespace', overrides={'MODEL_NAME': 'bad model'})
    assert whitespace.returncode != 0 and 'MODEL_NAME must not contain whitespace' in whitespace.stderr
    assert whitespace_log == ''


def test_malformed_or_stale_confirmation_cannot_mutate(tmp_path: Path) -> None:
    plan, _ = _run_deploy(tmp_path / "plan")
    plan_id = next(line.split("=", 1)[1] for line in plan.stdout.splitlines() if line.startswith("PLAN_ID="))
    malformed, malformed_log = _run_deploy(tmp_path / "malformed", "apply", "--confirm", "not-a-confirmation")
    assert malformed.returncode != 0
    assert 'create' not in malformed_log and 'delete' not in malformed_log
    stale, stale_log = _run_deploy(tmp_path / "stale", "apply", "--confirm", f"apply:{'0' * 64}:csa-wb-mvp1-rg")
    assert stale.returncode != 0
    assert 'create' not in stale_log and 'delete' not in stale_log
    assert len(plan_id) == 64


@pytest.mark.parametrize('overrides', [
    {'ACR_LOCATION': 'westus3'},
    {'IDENTITY_MODE': 'demo', 'DEMO_PASSWORD': 'different-demo-secret'},
])
def test_mutable_plan_configuration_change_invalidates_confirmation_without_mutation(tmp_path: Path, overrides: dict[str, str]) -> None:
    plan, _ = _run_deploy(tmp_path / 'plan')
    plan_id = next(line.split('=', 1)[1] for line in plan.stdout.splitlines() if line.startswith('PLAN_ID='))
    changed, log = _run_deploy(tmp_path / 'changed', 'apply', '--confirm', f'apply:{plan_id}:csa-wb-mvp1-rg', overrides=overrides)
    assert changed.returncode != 0
    assert 'create' not in log and 'delete' not in log


def test_entra_shape_redirect_and_runtime_assignment_contracts_are_idempotent_and_fail_closed() -> None:
    graph = FakeGraph(); names = entra.names_for_slug('mvp1')
    first = entra.ensure_entra(graph, 'mvp1', 'tenant', 'https://frontend.example', 'api-principal')
    post_count = len(graph.posts)
    assert entra.ensure_entra(graph, 'mvp1', 'tenant', 'https://frontend.example', 'api-principal') == first
    assert len(graph.posts) == post_count
    api = next(app for app in graph.apps if app['displayName'] == names.api)
    web = next(app for app in graph.apps if app['displayName'] == names.web)
    runtime = next(app for app in graph.apps if app['displayName'] == names.runtime)
    assert api['identifierUris'] == [f"api://{api['appId']}"] and runtime['identifierUris'] == [f"api://{runtime['appId']}"]
    assert {item['appId'] for item in api['api']['preAuthorizedApplications']} == {web['appId'], entra.AZURE_CLI_CLIENT_ID}
    entra.ensure_entra(graph, 'mvp1', 'tenant', 'https://new.example', 'api-principal')
    assert web['spa']['redirectUris'] == ['https://new.example']
    web['spa']['redirectUris'] = ['https://one.example', 'https://two.example']; before = (len(graph.posts), len(graph.patches))
    with pytest.raises(entra.GraphError, match='redirectUris'):
        entra.ensure_entra(graph, 'mvp1', 'tenant', 'https://third.example', 'api-principal')
    assert (len(graph.posts), len(graph.patches)) == before
    web['spa']['redirectUris'] = ['https://new.example']
    graph.assignments.append({'principalId': 'api-principal', 'resourceId': 'sp-3', 'appRoleId': entra.RUNTIME_ROLE_ID})
    with pytest.raises(entra.GraphError, match='duplicate runtime'):
        entra.ensure_entra(graph, 'mvp1', 'tenant', 'https://new.example', 'api-principal')


def test_runtime_audience_contract_uses_the_runtime_identifier_uri_for_request_and_verification() -> None:
    apps = (ROOT / 'infra' / 'apps.bicep').read_text()
    entra_source = (ROOT / 'infra' / 'entra.py').read_text()
    workload_auth = (ROOT / 'session-container' / 'workload_auth.py').read_text()
    session_manager = (ROOT / 'session_manager.py').read_text()

    expected = "api://${runtimeClientId}"
    assert f"{{ name: 'POOL_AUTH_AUDIENCE', value: '{expected}' }}" in apps
    assert f"{{ name: 'WORKLOAD_ENTRA_AUDIENCE', value: '{expected}' }}" in apps
    assert 'expected = [f"api://{application[\'appId\']}"]' in entra_source
    assert 'audience=self.config.audience' in workload_auth
    assert 'os.getenv("POOL_AUTH_AUDIENCE", "").strip().rstrip("/")' in session_manager
    assert 'return f"{audience}/.default"' in session_manager


def test_deployment_what_if_replaces_only_the_operation_token_and_preserves_create_model_values(tmp_path: Path) -> None:
    result, log = _run_deploy(tmp_path, overrides={'MODEL_NAME': 'create'})

    assert result.returncode == 0, result.stderr
    foundation_preview = next(line for line in log.splitlines() if line.startswith('deployment sub what-if'))
    assert 'azureOpenAiModelName=create' in foundation_preview
    assert 'azureOpenAiModelName=what-if' not in foundation_preview

    deploy_source = (ROOT / 'infra' / 'deploy.sh').read_text()
    assert 'command[3]=\'what-if\'' in deploy_source
    assert 'deployment_what_if "${FOUNDATION[@]}"' in deploy_source
    assert 'deployment_what_if "${APPS[@]}"' in deploy_source
    assert '${FOUNDATION[@]/create/what-if}' not in deploy_source
    assert '${APPS[@]/create/what-if}' not in deploy_source


def test_deployment_workflow_runs_the_canonical_host_suite_with_containerized_bicep() -> None:
    workflow = (ROOT / '.github' / 'workflows' / 'deploy.yml').read_text()
    package = json.loads((ROOT / 'package.json').read_text())
    verifier = (ROOT / 'scripts' / 'verify.sh').read_text()

    assert 'actions/setup-node@v4' in workflow
    assert "node-version: '22'" in workflow
    assert 'npm ci' in workflow and '(cd frontend && npm ci)' in workflow
    assert 'astral-sh/setup-uv@v6' in workflow
    assert 'uv sync --locked' in workflow
    assert '(cd session-container && uv sync --locked)' in workflow
    assert 'npm run verify:ci' in workflow
    assert 'azure/cli@v2' in workflow and 'az bicep build --file infra/foundation.bicep' in workflow
    assert 'pytest' not in workflow
    assert 'pip install pytest' not in workflow
    assert package['scripts']['verify:ci'] == 'CSA_VERIFY_SKIP_BICEP=1 bash scripts/verify.sh'
    assert 'CSA_VERIFY_SKIP_BICEP must be exactly 0 or 1' in verifier
    assert 'if [[ "${verify_skip_bicep}" == \'0\' ]]; then\n  require_command az' in verifier


def test_ci_verifier_rejects_an_invalid_bicep_skip_value_before_running_checks() -> None:
    result = subprocess.run(['bash', 'scripts/verify.sh'], cwd=ROOT, env={**os.environ, 'CSA_VERIFY_SKIP_BICEP': 'true'}, text=True, capture_output=True)

    assert result.returncode == 2
    assert 'CSA_VERIFY_SKIP_BICEP must be exactly 0 or 1' in result.stderr


def test_governance_nsg_rejects_extra_wrong_state_and_association() -> None:
    spec = importlib.util.spec_from_file_location('governance_nsg_cases', ROOT / 'infra' / 'governance_nsg.py'); assert spec and spec.loader
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    aca, private, vnet = helper.expected_names('mvp1', 'eastus2'); base = '/subscriptions/sub/resourceGroups/csa-wb-mvp1-rg/providers/Microsoft.Network'
    def item(name: str) -> dict[str, Any]: return {'name': name, 'id': f'{base}/networkSecurityGroups/{name}', 'location': 'eastus2', 'provisioningState': 'Succeeded', 'securityRules': [], 'networkInterfaces': None, 'subnets': []}
    good = [item(aca), item(private)]
    for bad in (good + [item('extra')], [{**item(aca), 'provisioningState': 'Failed'}, item(private)], [item(aca), {**item(private), 'subnets': [{'id': f'{base}/virtualNetworks/{vnet}/subnets/aca-infrastructure'}]}]):
        with pytest.raises(ValueError): helper.select_governance_nsgs(bad, 'sub', 'csa-wb-mvp1-rg', 'eastus2', 'mvp1')


def test_confirmed_recovery_deletes_only_ordered_targets_before_foundation_mutation(tmp_path: Path) -> None:
    plan, _ = _run_deploy(tmp_path / "plan", recovery=True)
    plan_id = next(line.split("=", 1)[1] for line in plan.stdout.splitlines() if line.startswith("PLAN_ID="))
    apply, log = _run_deploy(tmp_path / "apply", "apply", "--confirm", f"apply:{plan_id}:csa-wb-mvp1-rg", recovery=True)
    assert apply.returncode != 0  # the stub stops at the first foundation create
    actions = [line for line in log.splitlines() if 'containerapp delete' in line or 'containerapp env delete' in line or 'deployment sub what-if' in line or 'deployment sub create' in line]
    assert actions == [
        'containerapp delete -g csa-wb-mvp1-rg -n csa-wb-mvp1-frontend --yes --only-show-errors',
        'containerapp delete -g csa-wb-mvp1-rg -n csa-wb-mvp1-api --yes --only-show-errors',
        'containerapp delete -g csa-wb-mvp1-rg -n csa-wb-mvp1-runtime --yes --only-show-errors',
        'containerapp env delete -g csa-wb-mvp1-rg -n csa-wb-mvp1-env --yes --only-show-errors',
        next(action for action in actions if 'deployment sub what-if' in action),
        next(action for action in actions if 'deployment sub create' in action),
    ]


def test_recovery_accepts_expected_apps_in_any_azure_list_order(tmp_path: Path) -> None:
    result, log = _run_deploy(tmp_path, recovery=True, recovery_apps_order='reordered')

    assert result.returncode == 0, result.stderr
    assert '"recovery_state":"incompatible"' in result.stdout
    assert 'containerapp delete' not in log and 'containerapp env delete' not in log
    assert 'deployment sub what-if' not in log


@pytest.mark.parametrize('recovery_apps_order', ['missing', 'extra'])
def test_recovery_rejects_missing_or_extra_attached_apps_before_mutation(tmp_path: Path, recovery_apps_order: str) -> None:
    result, log = _run_deploy(tmp_path, recovery=True, recovery_apps_order=recovery_apps_order)

    assert result.returncode != 0
    assert 'containerapp delete' not in log and 'containerapp env delete' not in log and 'deployment sub what-if' not in log


def test_malformed_recovery_inventory_fails_before_deletion_even_when_optimized(tmp_path: Path) -> None:
    for optimized in ('', '1'):
        result, log = _run_deploy(tmp_path / (optimized or 'normal'), recovery=True, bad_recovery=True, overrides={'PYTHONOPTIMIZE': optimized})
        assert result.returncode != 0
        assert 'containerapp delete' not in log and 'containerapp env delete' not in log and 'deployment sub what-if' not in log


def test_static_portable_contract_has_no_legacy_names_or_model_defaults() -> None:
    files = {path.name: path.read_text() for path in (ROOT / 'infra').glob('*') if path.suffix in {'.bicep', '.py', '.sh'}}
    source = '\n'.join(files.values()).lower()
    assert 'csa-workbench-rg' not in source and 'djgsharedacr' not in source
    assert "gpt-4.1" not in source and "gpt-5.6-terra" not in source
    assert "param azureopenaimodelname string" in files['platform.bicep'].lower()
    assert "param azureopenaimodelcapacity int" in files['platform.bicep'].lower()
    assert "param databaseName string" in files['apps.bicep']
    assert "param frontendIdentityId string" in files['apps.bicep']
    assert "azureOpenAiDeploymentName: azureOpenAiDeploymentName" in files['foundation.bicep']
    assert "{ name: 'AZURE_DEPLOYMENT', value: azureOpenAiDeployment }" in files['apps.bicep']
    assert "--instance-slug" in files['entra.py'] and "apply=true" not in files['deploy.sh'].lower()


def test_parameterized_verifier_rejects_cross_instance_identity_drift() -> None:
    script = (ROOT / 'infra' / 'deploy.sh').read_text()
    start = script.index("import json, os\napps = json.loads")
    verifier = script[start:script.index("\nPY\n}", start)]
    slug = 'mvp1'
    sha = '0123456789abcdef0123456789abcdef01234567'
    apps = []
    for name, external, port, image in ((f'csa-wb-{slug}-frontend', True, 3000, 'csa-workbench-frontend'), (f'csa-wb-{slug}-api', True, 8000, 'csa-workbench-api'), (f'csa-wb-{slug}-runtime', False, 8080, 'csa-workbench-runtime')):
        container: dict[str, Any] = {'image': f'acr.azurecr.io/{image}:{sha}'}
        if name.endswith('runtime'):
            container['env'] = [{'name': 'AZURE_DEPLOYMENT', 'value': 'deployment'}, {'name': 'AZURE_ENDPOINT', 'value': 'https://ai/openai/v1/'}]
        apps.append({'name': name, 'properties': {'provisioningState': 'Succeeded', 'workloadProfileName': 'Consumption', 'configuration': {'ingress': {'external': external, 'targetPort': port, 'transport': 'auto'}}, 'template': {'scale': {'minReplicas': 0, 'maxReplicas': 1}, 'containers': [container]}}})
    env = {
        **os.environ,
        'APPS': json.dumps(apps), 'DEPLOYMENTS': json.dumps([{'name': 'deployment', 'properties': {'provisioningState': 'Succeeded', 'model': {'format': 'OpenAI', 'name': 'model', 'version': 'version'}} , 'sku': {'name': 'GlobalStandard', 'capacity': 30}}]),
        'IDENTITIES': json.dumps([{'name': 'csa-wb-other-frontend-identity'}]), 'RESOURCES': '[]', 'ACR': '{}', 'AZURE_OPEN_AI': json.dumps({'properties': {'endpoint': 'https://ai/'}}), 'COSMOS': '{}', 'STORAGE': '{}', 'VNET': '{}', 'PRIVATE_ENDPOINTS': '[]', 'PRIVATE_DNS_ZONES': '[]', 'MANAGED_ENVIRONMENT': '{}', 'NETWORK_SECURITY_GROUPS': '[]', 'COSMOS_DNS_LINKS': '[]', 'STORAGE_DNS_LINKS': '[]', 'COSMOS_DNS_GROUPS': '[]', 'STORAGE_DNS_GROUPS': '[]', 'COSMOS_DNS_RECORDS': '[]', 'STORAGE_DNS_RECORDS': '[]', 'ASSIGNMENTS': '[]', 'COSMOS_SQL_ASSIGNMENTS': '[]',
        'FRONTEND_APP_NAME': f'csa-wb-{slug}-frontend', 'API_APP_NAME': f'csa-wb-{slug}-api', 'RUNTIME_APP_NAME': f'csa-wb-{slug}-runtime', 'FRONTEND_IDENTITY_NAME': f'csa-wb-{slug}-frontend-identity', 'API_IDENTITY_NAME': f'csa-wb-{slug}-api-identity', 'RUNTIME_IDENTITY_NAME': f'csa-wb-{slug}-runtime-identity', 'MODEL_DEPLOYMENT_NAME': 'deployment', 'MODEL_NAME': 'model', 'MODEL_VERSION': 'version', 'MODEL_SKU_NAME': 'GlobalStandard', 'MODEL_CAPACITY': '30', 'SHA': sha, 'RESOURCE_GROUP': f'csa-wb-{slug}-rg', 'SUBSCRIPTION_ID': 'sub', 'ENVIRONMENT_NAME': f'csa-wb-{slug}-env', 'DATABASE_NAME': f'csa-wb-{slug}-entra', 'VNET_NAME': f'csa-wb-{slug}-vnet', 'COSMOS_ACCOUNT_NAME': 'cosmos', 'STORAGE_ACCOUNT_NAME': 'storage', 'ACR_NAME': 'acr', 'AOAI_NAME': 'ai', 'COSMOS_PRIVATE_ENDPOINT_NAME': f'csa-wb-{slug}-cosmos-pe', 'STORAGE_PRIVATE_ENDPOINT_NAME': f'csa-wb-{slug}-storage-pe', 'COSMOS_PRIVATE_DNS_ZONE': 'privatelink.documents.azure.com', 'STORAGE_PRIVATE_DNS_ZONE': 'privatelink.blob.core.windows.net', 'PRIVATE_DNS_VNET_LINK_NAME': f'csa-wb-{slug}-vnet-link', 'FRONTEND_PRINCIPAL': 'frontend', 'API_PRINCIPAL': 'api', 'RUNTIME_PRINCIPAL': 'runtime', 'LOCATION': 'eastus2',
    }
    result = subprocess.run([sys.executable, '-c', verifier], env=env, text=True, capture_output=True)
    assert result.returncode != 0
    assert 'managed identity inventory drifted' in result.stderr


def _verifier_fixture() -> tuple[str, dict[str, str]]:
    script = (ROOT / 'infra' / 'deploy.sh').read_text(); start = script.index("import json, os\napps = json.loads")
    code = script[start:script.index("\nPY\n}", start)]; slug, sha, sub = 'mvp1', '0123456789abcdef0123456789abcdef01234567', 'sub'
    rg, base, vnet, cosmos, storage, acr, ai = f'csa-wb-{slug}-rg', f'csa-wb-{slug}', f'csa-wb-{slug}-vnet', 'cosmos', 'storage', 'acr', 'ai'
    root = f'/subscriptions/{sub}/resourceGroups/{rg}/providers'; ids = {k: f'{root}/Microsoft.ManagedIdentity/userAssignedIdentities/{base}-{k}-identity' for k in ('frontend','api','runtime')}
    principal = {'frontend':'frontend','api':'api','runtime':'runtime'}
    apps = []
    for kind, external, port, repo in [('frontend',True,3000,'csa-workbench-frontend'),('api',True,8000,'csa-workbench-api'),('runtime',False,8080,'csa-workbench-runtime')]:
        container = {'image': f'acr.azurecr.io/{repo}:{sha}'}
        if kind == 'runtime': container['env'] = [{'name':'AZURE_DEPLOYMENT','value':'deployment'},{'name':'AZURE_ENDPOINT','value':'https://ai/openai/v1/'}]
        apps.append({'name':f'{base}-{kind}','identity':{'userAssignedIdentities':{ids[kind]:{}}},'properties':{'provisioningState':'Succeeded','workloadProfileName':'Consumption','managedEnvironmentId':f'{root}/Microsoft.App/managedEnvironments/{base}-env','configuration':{'ingress':{'external':external,'targetPort':port,'transport':'auto'},'registries':[{'server':'acr.azurecr.io','identity':ids[kind]}]},'template':{'scale':{'minReplicas':0,'maxReplicas':1},'containers':[container]}}})
    zones = ['privatelink.documents.azure.com','privatelink.blob.core.windows.net']; endpoints = []
    for name, target, group, nic in [(f'{base}-cosmos-pe',f'{root}/Microsoft.DocumentDB/databaseAccounts/{cosmos}','Sql','nic1'),(f'{base}-storage-pe',f'{root}/Microsoft.Storage/storageAccounts/{storage}','blob','nic2')]:
        endpoints.append({'name':name,'provisioningState':'Succeeded','subnet':{'id':f'{root}/Microsoft.Network/virtualNetworks/{vnet}/subnets/private-endpoints'},'networkInterfaces':[{'id':f'{root}/Microsoft.Network/networkInterfaces/{nic}'}],'privateLinkServiceConnections':[{'privateLinkServiceId':target,'groupIds':[group],'privateLinkServiceConnectionState':{'status':'Approved'}}]})
    def links(zone: str): return [{'name':f'{base}-vnet-link','provisioningState':'Succeeded','virtualNetworkLinkState':'Completed','registrationEnabled':False,'virtualNetwork':{'id':f'{root}/Microsoft.Network/virtualNetworks/{vnet}'}}]
    def groups(zone: str, names: list[str]): return [{'name':'default','provisioningState':'Succeeded','privateDnsZoneConfigs':[{'privateDnsZoneId':f'{root}/Microsoft.Network/privateDnsZones/{zone}','recordSets':[{'recordSetName':n,'ipAddresses':[{'ipAddress':f'10.42.0.{40+i}'}]} for i,n in enumerate(names)]}]}]
    cosmos_names=[cosmos,f'{cosmos}-eastus2']; storage_names=[storage]
    def records(names: list[str]): return [{'name':n,'aRecords':[{'ipv4Address':f'10.42.0.{40+i}'}]} for i,n in enumerate(names)]
    direct = [('microsoft.app/managedenvironments',f'{base}-env'),* [('microsoft.app/containerapps',f'{base}-{x}') for x in ('frontend','api','runtime')],* [('microsoft.managedidentity/userassignedidentities',f'{base}-{x}-identity') for x in ('frontend','api','runtime')],('microsoft.containerregistry/registries',acr),('microsoft.cognitiveservices/accounts',ai),('microsoft.documentdb/databaseaccounts',cosmos),('microsoft.storage/storageaccounts',storage),('microsoft.network/virtualnetworks',vnet),('microsoft.network/privateendpoints',f'{base}-cosmos-pe'),('microsoft.network/privateendpoints',f'{base}-storage-pe'),* [('microsoft.network/privatednszones',z) for z in zones],('microsoft.network/networkinterfaces','nic1'),('microsoft.network/networkinterfaces','nic2')]
    children=[('microsoft.documentdb/databaseaccounts/sqldatabases',f'{cosmos}/{base}-entra'),('microsoft.documentdb/databaseaccounts/sqldatabases/containers',f'{cosmos}/{base}-entra/appstate'),('microsoft.cognitiveservices/accounts/deployments',f'{ai}/deployment'),* [('microsoft.network/privatednszones/virtualnetworklinks',f'{z}/{base}-vnet-link') for z in zones],('microsoft.network/privateendpoints/privatednszonegroups',f'{base}-cosmos-pe/default'),('microsoft.network/privateendpoints/privatednszonegroups',f'{base}-storage-pe/default'),('microsoft.storage/storageaccounts/blobservices',f'{storage}/default'),('microsoft.storage/storageaccounts/blobservices/containers',f'{storage}/default/engagement-artifacts')]
    scope = f'/subscriptions/{sub}/resourceGroups/{rg}/'; roles=[]
    for p in ('frontend','api','runtime'): roles.append({'scope':f'{scope}providers/Microsoft.ContainerRegistry/registries/{acr}','roleDefinitionName':'AcrPull','principalId':principal[p]})
    roles += [{'scope':f'{scope}providers/Microsoft.Storage/storageAccounts/{storage}','roleDefinitionName':'Storage Blob Data Contributor','principalId':'api'},{'scope':f'{scope}providers/Microsoft.CognitiveServices/accounts/{ai}','roleDefinitionName':'Cognitive Services OpenAI User','principalId':'runtime'}]
    cscope=f'{scope}providers/Microsoft.DocumentDB/databaseAccounts/{cosmos}'; croles=[{'roleDefinitionId':f'{cscope}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002','scope':cscope,'principalId':p} for p in ('api','runtime')]
    env={**os.environ,'APPS':json.dumps(apps),'DEPLOYMENTS':json.dumps([{'name':'deployment','properties':{'provisioningState':'Succeeded','model':{'format':'OpenAI','name':'model','version':'version'}},'sku':{'name':'GlobalStandard','capacity':30}}]),'IDENTITIES':json.dumps([{'name':f'{base}-{k}-identity','id':ids[k]} for k in ('frontend','api','runtime')]),'RESOURCES':json.dumps([{'type':t,'name':n} for t,n in direct+children]),'ACR':json.dumps({'name':acr,'sku':{'name':'Basic'},'adminUserEnabled':False}),'AZURE_OPEN_AI':json.dumps({'name':ai,'kind':'OpenAI','sku':{'name':'S0'},'properties':{'disableLocalAuth':True,'endpoint':'https://ai/'}}),'COSMOS':json.dumps({'disableLocalAuth':True,'publicNetworkAccess':'Disabled'}),'STORAGE':json.dumps({'publicNetworkAccess':'Disabled','allowSharedKeyAccess':False,'allowBlobPublicAccess':False}),'VNET':json.dumps({'name':vnet,'addressSpace':{'addressPrefixes':['10.42.0.0/24']},'subnets':[{'name':'aca-infrastructure','addressPrefix':'10.42.0.0/27'},{'name':'private-endpoints','addressPrefix':'10.42.0.32/27','privateEndpointNetworkPolicies':'Disabled'}]}),'PRIVATE_ENDPOINTS':json.dumps(endpoints),'PRIVATE_DNS_ZONES':json.dumps([{'name':z} for z in zones]),'MANAGED_ENVIRONMENT':json.dumps({'name':f'{base}-env','properties':{'vnetConfiguration':{'infrastructureSubnetId':f'{root}/Microsoft.Network/virtualNetworks/{vnet}/subnets/aca-infrastructure'}}}),'NETWORK_SECURITY_GROUPS':'[]','COSMOS_DNS_LINKS':json.dumps(links(zones[0])),'STORAGE_DNS_LINKS':json.dumps(links(zones[1])),'COSMOS_DNS_GROUPS':json.dumps(groups(zones[0],cosmos_names)),'STORAGE_DNS_GROUPS':json.dumps(groups(zones[1],storage_names)),'COSMOS_DNS_RECORDS':json.dumps(records(cosmos_names)),'STORAGE_DNS_RECORDS':json.dumps(records(storage_names)),'ASSIGNMENTS':json.dumps([roles]),'COSMOS_SQL_ASSIGNMENTS':json.dumps(croles),'FRONTEND_APP_NAME':f'{base}-frontend','API_APP_NAME':f'{base}-api','RUNTIME_APP_NAME':f'{base}-runtime','FRONTEND_IDENTITY_NAME':f'{base}-frontend-identity','API_IDENTITY_NAME':f'{base}-api-identity','RUNTIME_IDENTITY_NAME':f'{base}-runtime-identity','MODEL_DEPLOYMENT_NAME':'deployment','MODEL_NAME':'model','MODEL_VERSION':'version','MODEL_SKU_NAME':'GlobalStandard','MODEL_CAPACITY':'30','SHA':sha,'RESOURCE_GROUP':rg,'SUBSCRIPTION_ID':sub,'ENVIRONMENT_NAME':f'{base}-env','DATABASE_NAME':f'{base}-entra','VNET_NAME':vnet,'COSMOS_ACCOUNT_NAME':cosmos,'STORAGE_ACCOUNT_NAME':storage,'ACR_NAME':acr,'AOAI_NAME':ai,'COSMOS_PRIVATE_ENDPOINT_NAME':f'{base}-cosmos-pe','STORAGE_PRIVATE_ENDPOINT_NAME':f'{base}-storage-pe','COSMOS_PRIVATE_DNS_ZONE':zones[0],'STORAGE_PRIVATE_DNS_ZONE':zones[1],'PRIVATE_DNS_VNET_LINK_NAME':f'{base}-vnet-link','FRONTEND_PRINCIPAL':'frontend','API_PRINCIPAL':'api','RUNTIME_PRINCIPAL':'runtime','LOCATION':'eastus2'}
    return code, env


def test_portable_verifier_accepts_complete_fixture_and_rejects_wiring_roles_and_inventory() -> None:
    code, env = _verifier_fixture()
    assert subprocess.run([sys.executable,'-c',code],env=env,text=True,capture_output=True).returncode == 0
    cases = [('APPS', lambda value: value.replace('acr.azurecr.io/csa-workbench-frontend:', 'wrong/')), ('COSMOS_DNS_RECORDS', lambda value: value.replace('10.42.0.40','10.42.0.99')), ('RESOURCES', lambda value: value[:-1]+',{"type":"Microsoft.Search/searchServices","name":"extra"}]'), ('ASSIGNMENTS', lambda value: value[:-2]+',{"scope":"/subscriptions/sub/resourceGroups/csa-wb-mvp1-rg/providers/Microsoft.Storage/storageAccounts/storage","roleDefinitionName":"Reader","principalId":"api"}]]'), ('COSMOS_SQL_ASSIGNMENTS', lambda value: value[:-1]+',{"roleDefinitionId":"x","scope":"x","principalId":"api"}]')]
    for key, mutate in cases:
        changed={**env,key:mutate(env[key])}; assert subprocess.run([sys.executable,'-c',code],env=changed,text=True,capture_output=True).returncode != 0


def test_portable_verifier_accepts_only_the_optional_governance_nsg_resource_pair() -> None:
    code, env = _verifier_fixture()
    vnet = 'csa-wb-mvp1-vnet'
    names = [f'{vnet}-aca-infrastructure-nsg-eastus2', f'{vnet}-private-endpoints-nsg-eastus2']
    network_security_groups = [
        {'name': name, 'provisioningState': 'Succeeded', 'securityRules': [], 'networkInterfaces': None}
        for name in names
    ]
    resources = json.loads(env['RESOURCES']) + [
        {'type': 'Microsoft.Network/networkSecurityGroups', 'name': name}
        for name in names
    ]
    governed = {**env, 'NETWORK_SECURITY_GROUPS': json.dumps(network_security_groups), 'RESOURCES': json.dumps(resources)}

    assert subprocess.run([sys.executable, '-c', code], env=governed, text=True, capture_output=True).returncode == 0
    unrelated = {**governed, 'RESOURCES': json.dumps(resources + [{'type': 'Microsoft.Search/searchServices', 'name': 'extra'}])}
    assert subprocess.run([sys.executable, '-c', code], env=unrelated, text=True, capture_output=True).returncode != 0
    extra_nsg = {'name': 'unrelated', 'provisioningState': 'Succeeded', 'securityRules': [], 'networkInterfaces': None}
    assert subprocess.run([sys.executable, '-c', code], env={**governed, 'NETWORK_SECURITY_GROUPS': json.dumps(network_security_groups + [extra_nsg]), 'RESOURCES': json.dumps(resources + [{'type': 'Microsoft.Network/networkSecurityGroups', 'name': 'unrelated'}])}, text=True, capture_output=True).returncode != 0
    for malformed in ('null', '{}', 'false', '0', '""'):
        assert subprocess.run([sys.executable, '-c', code], env={**env, 'NETWORK_SECURITY_GROUPS': malformed}, text=True, capture_output=True).returncode != 0


def test_browser_validation_runbook_uses_the_isolated_demo_parent_shell_values() -> None:
    development = (ROOT / 'docs' / 'guides' / 'local-development.md').read_text()

    for value in ('## Run the browser journey', 'CSA_LOCAL_RUN_ID=demo1', 'WORKSPACE=.local-runs/demo1/workspace', 'ARTIFACTS_DIR=.mvp-artifacts/demo1', "MVP_APP_URL='http://localhost:13000'", "MVP_API_URL='http://localhost:18000'", "MVP_RAW_TRACE_ROOT='.local-runs/demo1/logs/sdk-events'", 'MVP_RESET_BEFORE_RUN=1', 'npm run playwright:mvp'):
        assert value in development
