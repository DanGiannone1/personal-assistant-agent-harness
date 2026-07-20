"""OpenTelemetry tracing shim for the session container.

Handles optional OTel initialization, context propagation across SDK threads,
and provides no-op fallbacks if tracing is disabled or packages are missing.
"""

import logging
import os
from contextlib import contextmanager
from typing import Any, Generator, Optional

from fastapi import FastAPI

logger = logging.getLogger(__name__)

_enabled = False
_tracer = None


def _resource_attributes() -> dict[str, str]:
    """Build a stable OpenTelemetry resource description for the session app."""
    attrs = {
        "service.name": os.getenv("OTEL_SERVICE_NAME", "csa-workbench-session"),
        "service.namespace": os.getenv("OTEL_SERVICE_NAMESPACE", "csa-workbench"),
    }

    service_version = os.getenv("OTEL_SERVICE_VERSION") or os.getenv("SERVICE_VERSION")
    if service_version:
        attrs["service.version"] = service_version

    deployment_env = (
        os.getenv("OTEL_DEPLOYMENT_ENVIRONMENT")
        or os.getenv("DEPLOYMENT_ENVIRONMENT")
    )
    if deployment_env:
        attrs["deployment.environment.name"] = deployment_env

    return attrs


class _NoopSpan:
    """Stub span that absorbs all OTel calls silently."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def set_attribute(self, key: str, value: Any):
        pass

    def add_event(self, name: str, attributes: Optional[dict[str, Any]] = None):
        pass

    def record_exception(self, exception: Exception):
        pass

    def end(self, end_time: Optional[int] = None):
        pass

    def is_recording(self) -> bool:
        return False


class _NoopTracer:
    """Stub tracer that returns no-op spans."""

    def start_as_current_span(self, name: str, *args, **kwargs):
        return _NoopSpan()

    def start_span(self, name: str, *args, **kwargs):
        return _NoopSpan()


def setup_tracing(app: Optional[FastAPI] = None) -> None:
    """Initialize Azure Monitor tracing if connection string is present."""
    global _enabled, _tracer

    conn_str = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not conn_str:
        logger.debug("Tracing: No connection string found, tracing disabled.")
        return

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        from opentelemetry import trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource

        resource_attrs = _resource_attributes()

        # 1. Configure Azure Monitor (SDK + Exporter)
        configure_azure_monitor(
            connection_string=conn_str,
            resource=Resource.create(resource_attrs),
            disable_logging=True,
            disable_metrics=True,
            enable_live_metrics=False,
            instrumentation_options={"fastapi": {"enabled": False}},
        )

        # 2. Instrument FastAPI if app is provided
        if app:
            FastAPIInstrumentor.instrument_app(app)

        # 3. Initialize global tracer
        _tracer = trace.get_tracer("csa-workbench.session-container")
        _enabled = True
        logger.info(
            "Tracing enabled: service=%s version=%s env=%s",
            resource_attrs.get("service.name"),
            resource_attrs.get("service.version", "unknown"),
            resource_attrs.get("deployment.environment.name", "unknown"),
        )

    except ImportError:
        logger.warning(
            "Tracing: APPLICATIONINSIGHTS_CONNECTION_STRING is set but OTel packages are missing. "
            "Install with: uv sync --extra tracing"
        )
    except Exception:
        logger.exception("Tracing: Failed to initialize OpenTelemetry.")


def get_tracer() -> Any:
    """Return the active OTel tracer or a no-op stub."""
    return _tracer if _enabled else _NoopTracer()


def is_enabled() -> bool:
    """Return True if tracing is active."""
    return _enabled


def get_current_context() -> Optional[Any]:
    """Capture the current OTel context (used to propagate to SDK threads)."""
    if not _enabled:
        return None
    try:
        from opentelemetry import context
        return context.get_current()
    except ImportError:
        return None


@contextmanager
def attach_context(otel_ctx: Optional[Any]) -> Generator[None, None, None]:
    """Attach a previously captured OTel context to the current thread."""
    if not _enabled or otel_ctx is None:
        yield
        return

    try:
        from opentelemetry import context
        token = context.attach(otel_ctx)
        try:
            yield
        finally:
            context.detach(token)
    except ImportError:
        yield


@contextmanager
def use_span(span: Optional[Any]) -> Generator[None, None, None]:
    """Set a span as current without ending it on scope exit."""
    if not _enabled or span is None:
        yield
        return

    try:
        from opentelemetry.trace import use_span as otel_use_span

        with otel_use_span(span, end_on_exit=False):
            yield
    except ImportError:
        yield


def truncate(text: Any, limit: int = 1000) -> str:
    """Safely truncate text for span attributes to avoid the 8KB App Insights limit."""
    if not isinstance(text, str):
        text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + "... (truncated)"
