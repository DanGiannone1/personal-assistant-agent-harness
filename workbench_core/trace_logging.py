"""Local JSONL trace logging shared by the orchestrator and the session runtime.

Diagnostic only: enabled with LOG_TRACE=true and LOG_TRACE_DIR, appends one JSON
record per event, and never raises into the request path. Nothing in the product
or the test oracles parses these files; humans read them when debugging a run.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _trace_path() -> Path | None:
    if os.getenv("LOG_TRACE", "").lower() != "true":
        return None
    trace_dir = os.getenv("LOG_TRACE_DIR", "")
    if not trace_dir:
        return None
    return Path(trace_dir).resolve() / "trace.jsonl"


def setup_trace_logging() -> None:
    """Prepare the trace directory once at startup; a failure only warns."""
    path = _trace_path()
    if not path:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        logger.warning("Failed to prepare trace directory", exc_info=True)


def trace_event(component: str, event: str, **data) -> None:
    """Append one structured trace record if tracing is enabled."""
    path = _trace_path()
    if not path:
        return
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "component": component,
        "event": event,
        **data,
    }
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True, default=str) + "\n")
    except Exception:
        logger.warning("Failed to write trace event", exc_info=True)
