# /// script
# requires-python = ">=3.12"
# dependencies = ["python-dotenv"]
# ///
"""Local dev server — starts session container, orchestrator, and frontend."""

import os
import signal
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent

if not (ROOT / ".env").exists():
    print("Error: .env not found. Copy .env.example to .env and fill in values.")
    sys.exit(1)

load_dotenv(ROOT / ".env")
if os.environ.get("IDENTITY_MODE", "").strip().lower() != "demo":
    print("Error: dev.py runs deterministic local stacks only; set IDENTITY_MODE=demo.")
    sys.exit(1)
if not os.environ.get("DEMO_PASSWORD"):
    print("Error: DEMO_PASSWORD is required for the demo identity mode.")
    sys.exit(1)
os.environ["POOL_MANAGEMENT_ENDPOINT"] = "http://localhost:8080"
os.environ["WORKSPACE"] = str(ROOT / "workspace")

# Trace logging — fresh file each dev session
logs_dir = ROOT / "logs"
logs_dir.mkdir(exist_ok=True)
trace_file = logs_dir / "trace.jsonl"
trace_file.write_text("")  # truncate
os.environ["LOG_TRACE"] = "true"
os.environ["LOG_TRACE_DIR"] = str(logs_dir)
os.environ["LOG_RAW_SDK_EVENTS"] = "true"
os.environ["LOG_RAW_SDK_EVENTS_DIR"] = str(logs_dir)
os.environ["NEXT_PUBLIC_IDENTITY_MODE"] = "demo"
workspace = ROOT / "workspace"
# Clean workspace on startup so sessions don't see stale files
if workspace.exists():
    import shutil
    shutil.rmtree(workspace)
workspace.mkdir(exist_ok=True)
sdk_events_dir = logs_dir / "sdk-events"
if sdk_events_dir.exists():
    import shutil
    shutil.rmtree(sdk_events_dir)
sdk_events_dir.mkdir(exist_ok=True)

procs: list[subprocess.Popen] = []


def cleanup(*_):
    print("\nShutting down...")
    for p in procs:
        p.terminate()
    for p in procs:
        p.wait()
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

print("Starting session container on :8080...")
procs.append(subprocess.Popen(
    ["uv", "run", "uvicorn", "server:app", "--port", "8080"],
    cwd=ROOT / "session-container",
))

print("Starting orchestrator on :8000...")
procs.append(subprocess.Popen(
    ["uv", "run", "uvicorn", "app:app", "--port", "8000"],
    cwd=ROOT,
))

print("Starting frontend on :3000...")
procs.append(subprocess.Popen(
    ["npm", "run", "dev"],
    cwd=ROOT / "frontend",
))

print()
print("  Frontend:  http://localhost:3000")
print("  API:       http://localhost:8000")
print("  Session:   http://localhost:8080")
print(f"  Trace log: {trace_file}")
print()

for p in procs:
    p.wait()
