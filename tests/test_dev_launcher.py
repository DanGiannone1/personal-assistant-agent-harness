from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location("dev_launcher", Path(__file__).resolve().parents[1] / "dev.py")
assert SPEC and SPEC.loader
dev_launcher = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dev_launcher
SPEC.loader.exec_module(dev_launcher)


def base_env() -> dict[str, str]:
    return {"IDENTITY_MODE": "demo", "DEMO_PASSWORD": "local-test-secret"}


def isolated_env() -> dict[str, str]:
    return {
        **base_env(),
        "CSA_LOCAL_RUN_ID": "case-7",
        "CSA_RUNTIME_PORT": "18080",
        "CSA_API_PORT": "18000",
        "CSA_FRONTEND_PORT": "13000",
        "COSMOS_ENDPOINT": "https://localhost:8081",
        "COSMOS_DATABASE": "csa_local_case-7",
        "COSMOS_CONTAINER": "appstate_demo_case-7",
    }


def test_isolated_config_uses_only_run_scoped_paths_and_coordinates_urls() -> None:
    config = dev_launcher.build_config(isolated_env())
    assert config.workspace == dev_launcher.LOCAL_RUNS_ROOT / "case-7" / "workspace"
    assert config.logs == dev_launcher.LOCAL_RUNS_ROOT / "case-7" / "logs"
    assert config.artifacts == dev_launcher.MVP_ARTIFACT_ROOT / "case-7"
    assert config.next_dist_dir == dev_launcher.LOCAL_NEXT_DIST_ROOT / "case-7"
    child = dev_launcher.child_environment(config, isolated_env())
    assert child["POOL_MANAGEMENT_ENDPOINT"] == "http://127.0.0.1:18080"
    assert child["FRONTEND_URL"] == "http://127.0.0.1:13000"
    assert child["NEXT_PUBLIC_API_URL"] == "http://127.0.0.1:18000"
    assert child["ARTIFACTS_DIR"] == str(dev_launcher.MVP_ARTIFACT_ROOT / "case-7")
    assert child["NEXT_DIST_DIR"] == ".next-local-runs/case-7"
    assert all("--port" in command for _, command, _ in dev_launcher.commands(config))


def test_default_run_does_not_reconfigure_the_shared_next_output() -> None:
    config = dev_launcher.build_config({**base_env(), "NEXT_DIST_DIR": "custom-output"})

    assert config.next_dist_dir is None
    assert dev_launcher.child_environment(config, {**base_env(), "NEXT_DIST_DIR": "custom-output"}).get("NEXT_DIST_DIR") is None
    assert (dev_launcher.FRONTEND_ROOT / ".next") != dev_launcher.LOCAL_NEXT_DIST_ROOT


def test_prepare_run_keeps_next_types_config_within_the_selected_isolated_output(tmp_path: Path) -> None:
    next_dist_dir = tmp_path / "frontend" / ".next-local-runs" / "case-7"
    config = dev_launcher.LocalRunConfig(
        "case-7",
        18080,
        18000,
        13000,
        tmp_path / "workspace",
        tmp_path / "logs",
        tmp_path / "artifacts",
        next_dist_dir,
    )

    dev_launcher.prepare_run(config)

    assert next_dist_dir.with_suffix(".tsconfig.json").read_text(encoding="utf-8") == '{"extends":"../tsconfig.json"}\n'
    assert not (tmp_path / "frontend" / ".next").exists()


@pytest.mark.parametrize("run_id", ["", " case-7", "UPPER", "two--dashes-", "../escape", "has_space", "a" * 64])
def test_isolated_config_rejects_unsafe_run_ids(run_id: str) -> None:
    env = isolated_env()
    env["CSA_LOCAL_RUN_ID"] = run_id
    if not run_id:
        assert dev_launcher.build_config(env).run_id is None
    else:
        with pytest.raises(ValueError, match="CSA_LOCAL_RUN_ID"):
            dev_launcher.build_config(env)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("COSMOS_ENDPOINT", "https://example.documents.azure.com", "loopback"),
        ("COSMOS_DATABASE", "csa_local_other", "COSMOS_DATABASE"),
        ("COSMOS_CONTAINER", "appstate_demo_other", "COSMOS_CONTAINER"),
        ("CSA_API_PORT", "18080", "distinct"),
        ("CSA_API_PORT", "80", "unprivileged"),
    ],
)
def test_isolated_config_refuses_shared_cosmos_or_invalid_ports(field: str, value: str, message: str) -> None:
    env = isolated_env()
    env[field] = value
    with pytest.raises(ValueError, match=message):
        dev_launcher.build_config(env)


def test_preflight_ports_refuses_an_existing_loopback_listener() -> None:
    config = dev_launcher.build_config(isolated_env())
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", config.api_port))
        listener.listen()
        with pytest.raises(RuntimeError, match="already in use"):
            dev_launcher.preflight_ports(config)
