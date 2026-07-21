# /// script
# requires-python = ">=3.12"
# dependencies = ["python-dotenv"]
# ///
"""Local development launcher for the runtime, API, and frontend.

The default invocation preserves the established ``workspace/`` and ``logs/``
locations. Set ``CSA_LOCAL_RUN_ID`` to run an isolated stack: launcher-owned
mutable paths then live beneath ignored per-run directories.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
FRONTEND_ROOT = ROOT / "frontend"
LOCAL_RUNS_ROOT = ROOT / ".local-runs"
MVP_ARTIFACT_ROOT = ROOT / ".mvp-artifacts"
LOCAL_NEXT_DIST_ROOT = FRONTEND_ROOT / ".next-local-runs"
DEFAULT_RUNTIME_PORT = 8080
DEFAULT_API_PORT = 8000
DEFAULT_FRONTEND_PORT = 3000
_RUN_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


@dataclass(frozen=True)
class LocalRunConfig:
    """Validated local launcher configuration, independent of process startup."""

    run_id: str | None
    runtime_port: int
    api_port: int
    frontend_port: int
    workspace: Path
    logs: Path
    artifacts: Path | None
    next_dist_dir: Path | None

    @property
    def runtime_url(self) -> str:
        return f"http://127.0.0.1:{self.runtime_port}"

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    @property
    def frontend_url(self) -> str:
        return f"http://127.0.0.1:{self.frontend_port}"


def validate_run_id(value: str) -> str:
    """Return a conservative local-run slug or reject path/control characters."""
    if not _RUN_ID_RE.fullmatch(value):
        raise ValueError(
            "CSA_LOCAL_RUN_ID must be 1-63 lowercase letters, digits, or hyphens "
            "and cannot begin or end with a hyphen"
        )
    return value


def _port(env: Mapping[str, str], name: str, default: int) -> int:
    value = env.get(name, str(default)).strip()
    try:
        port = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer port") from exc
    if not 1024 <= port <= 65535:
        raise ValueError(f"{name} must be an unprivileged port between 1024 and 65535")
    return port


def _loopback_cosmos_endpoint(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("isolated runs require COSMOS_ENDPOINT to be a loopback http(s) endpoint")


def build_config(env: Mapping[str, str]) -> LocalRunConfig:
    """Validate local safety constraints without touching files or processes."""
    if env.get("IDENTITY_MODE", "").strip().lower() != "demo":
        raise ValueError("dev.py runs deterministic local stacks only; set IDENTITY_MODE=demo")
    if not env.get("DEMO_PASSWORD", "").strip():
        raise ValueError("DEMO_PASSWORD is required for the demo identity mode")

    runtime_port = _port(env, "CSA_RUNTIME_PORT", DEFAULT_RUNTIME_PORT)
    api_port = _port(env, "CSA_API_PORT", DEFAULT_API_PORT)
    frontend_port = _port(env, "CSA_FRONTEND_PORT", DEFAULT_FRONTEND_PORT)
    if len({runtime_port, api_port, frontend_port}) != 3:
        raise ValueError("CSA_RUNTIME_PORT, CSA_API_PORT, and CSA_FRONTEND_PORT must be distinct")

    raw_run_id = env.get("CSA_LOCAL_RUN_ID", "")
    if not raw_run_id:
        return LocalRunConfig(
            None,
            runtime_port,
            api_port,
            frontend_port,
            ROOT / "workspace",
            ROOT / "logs",
            None,
            None,
        )

    run_id = validate_run_id(raw_run_id)
    _loopback_cosmos_endpoint(env.get("COSMOS_ENDPOINT", "").strip())
    for name in ("COSMOS_DATABASE", "COSMOS_CONTAINER"):
        value = env.get(name, "").strip().lower()
        if run_id not in value or not ("demo" in value or "local" in value):
            raise ValueError(
                f"isolated runs require {name} to include CSA_LOCAL_RUN_ID and a demo/local marker"
            )
    run_root = LOCAL_RUNS_ROOT / run_id
    return LocalRunConfig(
        run_id, runtime_port, api_port, frontend_port,
        run_root / "workspace",
        run_root / "logs",
        MVP_ARTIFACT_ROOT / run_id,
        LOCAL_NEXT_DIST_ROOT / run_id,
    )


def child_environment(config: LocalRunConfig, env: Mapping[str, str]) -> dict[str, str]:
    """Build the exact environment shared by all three local child processes."""
    child = dict(env)
    child.update({
        "POOL_MANAGEMENT_ENDPOINT": config.runtime_url,
        "FRONTEND_URL": config.frontend_url,
        "NEXT_PUBLIC_API_URL": config.api_url,
        "NEXT_PUBLIC_IDENTITY_MODE": "demo",
        "WORKSPACE": str(config.workspace),
        "LOG_TRACE": "true",
        "LOG_TRACE_DIR": str(config.logs),
        "LOG_RAW_SDK_EVENTS": "true",
        "LOG_RAW_SDK_EVENTS_DIR": str(config.logs),
    })
    child.pop("NEXT_DIST_DIR", None)
    if config.artifacts is not None:
        child["ARTIFACTS_DIR"] = str(config.artifacts)
    if config.next_dist_dir is not None:
        child["NEXT_DIST_DIR"] = str(config.next_dist_dir.relative_to(FRONTEND_ROOT))
    return child


def preflight_ports(config: LocalRunConfig) -> None:
    """Fail before cleanup/spawn when any loopback port is already in use."""
    for name, port in (("runtime", config.runtime_port), ("API", config.api_port), ("frontend", config.frontend_port)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(f"Cannot start local {name}: 127.0.0.1:{port} is already in use") from exc


def prepare_run(config: LocalRunConfig) -> Path:
    """Prepare launcher-owned paths, including isolated Next type configuration."""
    for path in (config.workspace, config.logs / "sdk-events"):
        if path.exists():
            shutil.rmtree(path)
    config.workspace.mkdir(parents=True, exist_ok=True)
    config.logs.mkdir(parents=True, exist_ok=True)
    (config.logs / "sdk-events").mkdir(exist_ok=True)
    trace_file = config.logs / "trace.jsonl"
    trace_file.write_text("", encoding="utf-8")
    if config.artifacts is not None:
        config.artifacts.mkdir(parents=True, exist_ok=True)
    if config.next_dist_dir is not None:
        config.next_dist_dir.mkdir(parents=True, exist_ok=True)
        config.next_dist_dir.with_suffix(".tsconfig.json").write_text(
            '{"extends":"../tsconfig.json"}\n', encoding="utf-8"
        )
    return trace_file


def commands(config: LocalRunConfig) -> list[tuple[str, list[str], Path]]:
    """Return child commands so tests can inspect ports without launching services."""
    return [
        ("session container", ["uv", "run", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(config.runtime_port)], ROOT / "session-container"),
        ("orchestrator", ["uv", "run", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(config.api_port)], ROOT),
        ("frontend", ["npm", "run", "dev", "--", "--hostname", "127.0.0.1", "--port", str(config.frontend_port)], ROOT / "frontend"),
    ]


def run(config: LocalRunConfig, env: Mapping[str, str]) -> int:
    """Start and supervise only the child processes created by this invocation."""
    preflight_ports(config)
    trace_file = prepare_run(config)
    child_env = child_environment(config, env)
    procs: list[subprocess.Popen[object]] = []

    def cleanup() -> None:
        for process in procs:
            if process.poll() is None:
                process.terminate()
        for process in procs:
            if process.poll() is None:
                process.wait()

    previous_sigint = signal.signal(signal.SIGINT, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))
    previous_sigterm = signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))
    try:
        for name, command, cwd in commands(config):
            print(f"Starting {name} on {command[-1]}...")
            procs.append(subprocess.Popen(command, cwd=cwd, env=child_env))
        print(f"\n  Frontend:  {config.frontend_url}\n  API:       {config.api_url}\n  Session:   {config.runtime_url}\n  Trace log: {trace_file}\n")
        while True:
            for process in procs:
                code = process.poll()
                if code is not None:
                    print(f"A local child process exited with status {code}; shutting down.", file=sys.stderr)
                    return code or 1
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nShutting down...")
        return 0
    finally:
        cleanup()
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)


def main() -> int:
    dotenv_path = ROOT / ".env"
    if not dotenv_path.exists():
        print("Error: .env not found. Copy .env.example to .env and fill in values.", file=sys.stderr)
        return 1
    load_dotenv(dotenv_path)
    try:
        return run(build_config(os.environ), os.environ)
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
