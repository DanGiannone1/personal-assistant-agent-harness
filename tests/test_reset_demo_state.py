from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "reset_demo_state", Path(__file__).resolve().parents[1] / "scripts" / "reset_demo_state.py"
)
assert SPEC and SPEC.loader
reset_demo_state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reset_demo_state)


def valid_env() -> dict[str, str]:
    return {
        "IDENTITY_MODE": "demo",
        "DEMO_PASSWORD": "test-secret",
        "CONFIRM_DEMO_RESET": "YES",
        "COSMOS_ENDPOINT": "https://localhost:8081",
        "COSMOS_DATABASE": "csa_workbench_demo",
        "COSMOS_CONTAINER": "appstate_demo",
        "ARTIFACTS_DIR": ".mvp-artifacts",
        "WORKSPACE": str(Path(__file__).resolve().parents[1] / "workspace"),
    }


def test_reset_guard_accepts_explicit_local_demo_target() -> None:
    target = reset_demo_state.reset_guard(valid_env())
    assert target["database"] == "csa_workbench_demo"


def test_reset_guard_allows_only_the_dedicated_artifact_subtree() -> None:
    env = valid_env()
    env["ARTIFACTS_DIR"] = str(Path(__file__).resolve().parents[1] / ".mvp-artifacts" / "run-1")
    assert reset_demo_state.reset_guard(env)["artifacts_dir"].endswith(".mvp-artifacts/run-1")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("IDENTITY_MODE", "entra", "IDENTITY_MODE=demo"),
        ("DEMO_PASSWORD", "", "DEMO_PASSWORD"),
        ("CONFIRM_DEMO_RESET", "no", "CONFIRM_DEMO_RESET=YES"),
        ("COSMOS_ENDPOINT", "https://example.documents.azure.com:443", "non-loopback"),
        ("COSMOS_ENDPOINT", "https://127.attacker.example:8081", "non-loopback"),
        ("COSMOS_DATABASE", "flow", "local/demo"),
        ("ARTIFACTS_ACCOUNT", "realblob", "ARTIFACTS_ACCOUNT"),
        ("ARTIFACTS_DIR", "/tmp/other-artifacts", "dedicated .mvp-artifacts subtree"),
        ("WORKSPACE", "/tmp/someone-elses-workspace", "repository-local WORKSPACE"),
    ],
)
def test_reset_guard_refuses_ambiguous_or_nonlocal_targets(field: str, value: str, message: str) -> None:
    env = valid_env()
    env[field] = value
    with pytest.raises(ValueError, match=message):
        reset_demo_state.reset_guard(env)


@pytest.mark.parametrize(
    "artifact_dir",
    [
        Path(__file__).resolve().parents[1],
        Path(__file__).resolve().parents[1] / "scripts",
        Path(__file__).resolve().parents[1] / "session-container",
        Path(__file__).resolve().parents[1] / ".mvp-artifacts" / ".." / "scripts",
    ],
)
def test_reset_guard_refuses_repository_or_source_artifact_paths(artifact_dir: Path) -> None:
    env = valid_env()
    env["ARTIFACTS_DIR"] = str(artifact_dir)
    with pytest.raises(ValueError, match="dedicated .mvp-artifacts subtree"):
        reset_demo_state.reset_guard(env)
