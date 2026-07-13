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

# Ports are env-overridable so multiple checkouts/worktrees can run stacks side by side.
FE_PORT = os.getenv("DEV_FE_PORT", "3000")
API_PORT = os.getenv("DEV_API_PORT", "8000")
SC_PORT = os.getenv("DEV_SC_PORT", "8080")

os.environ["POOL_MANAGEMENT_ENDPOINT"] = f"http://localhost:{SC_PORT}"
os.environ["WORKSPACE"] = str(ROOT / "workspace")
os.environ.setdefault("FRONTEND_URL", f"http://localhost:{FE_PORT}")
os.environ.setdefault("NEXT_PUBLIC_API_URL", f"http://localhost:{API_PORT}")

# Trace logging — fresh file each dev session
logs_dir = ROOT / "logs"
logs_dir.mkdir(exist_ok=True)
trace_file = logs_dir / "trace.jsonl"
trace_file.write_text("")  # truncate
os.environ["LOG_TRACE"] = "true"
os.environ["LOG_TRACE_DIR"] = str(logs_dir)
os.environ["LOG_RAW_SDK_EVENTS"] = "true"
os.environ["LOG_RAW_SDK_EVENTS_DIR"] = str(logs_dir)
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

print(f"Starting session container on :{SC_PORT}...")
procs.append(subprocess.Popen(
    ["uv", "run", "uvicorn", "server:app", "--port", SC_PORT],
    cwd=ROOT / "session-container",
))

print(f"Starting orchestrator on :{API_PORT}...")
procs.append(subprocess.Popen(
    ["uv", "run", "uvicorn", "app:app", "--port", API_PORT],
    cwd=ROOT,
))

print(f"Starting frontend on :{FE_PORT}...")
procs.append(subprocess.Popen(
    ["npm", "run", "dev", "--", "-p", FE_PORT],
    cwd=ROOT / "frontend",
))

print()
print(f"  Frontend:  http://localhost:{FE_PORT}")
print(f"  API:       http://localhost:{API_PORT}")
print(f"  Session:   http://localhost:{SC_PORT}")
print(f"  Trace log: {trace_file}")
print()

for p in procs:
    p.wait()
