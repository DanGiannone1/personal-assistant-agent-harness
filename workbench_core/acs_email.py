"""Azure Communication Services email transport for reminder delivery.

AAD-only (``DefaultAzureCredential``), consistent with the Cosmos store — no
keys. Fails loud if unconfigured or if a send does not succeed so the
dispatcher records the failure on the reminder instead of silently dropping it.

The recipient is always supplied by the caller from the owning actor's
identity. There is deliberately no global recipient configuration: a reminder
can only ever be delivered to the actor who owns it.

Config (env):
  ACS_EMAIL_ENDPOINT   — ACS resource endpoint, e.g. https://<name>.unitedstates.communication.azure.com
  ACS_SENDER_ADDRESS   — verified sender, e.g. DoNotReply@<guid>.azurecomm.net
"""

from __future__ import annotations

import html
import logging
import os

logger = logging.getLogger(__name__)

_client = None


def is_configured() -> bool:
    return bool(os.getenv("ACS_EMAIL_ENDPOINT")) and bool(os.getenv("ACS_SENDER_ADDRESS"))


def _config() -> tuple[str, str]:
    endpoint = os.getenv("ACS_EMAIL_ENDPOINT")
    sender = os.getenv("ACS_SENDER_ADDRESS")
    if not endpoint or not sender:
        raise RuntimeError("ACS email not configured — set ACS_EMAIL_ENDPOINT and ACS_SENDER_ADDRESS")
    return endpoint, sender


def _get_client(endpoint: str):
    # Lazy SDK import: only a runtime with dispatch enabled needs the ACS package.
    from azure.communication.email import EmailClient
    from azure.identity import DefaultAzureCredential

    global _client
    if _client is None:
        _client = EmailClient(endpoint, DefaultAzureCredential())
    return _client


def _to_html(subject: str, body_text: str) -> str:
    safe = html.escape(body_text)
    return (
        f"<div style=\"font-family:system-ui,Segoe UI,Arial,sans-serif;font-size:14px;"
        f"line-height:1.5;color:#111\"><h2 style=\"margin:0 0 12px\">{html.escape(subject)}</h2>"
        f"<pre style=\"white-space:pre-wrap;font-family:inherit;margin:0\">{safe}</pre></div>"
    )


def send_email(to: str, subject: str, body_text: str) -> str:
    """Send a plain-text+HTML email via ACS. Blocking — call via a worker thread.

    Returns the ACS operation id. Raises on any misconfiguration or send failure.
    """
    endpoint, sender = _config()
    if not to:
        raise RuntimeError("no recipient address")
    client = _get_client(endpoint)
    message = {
        "senderAddress": sender,
        "recipients": {"to": [{"address": to}]},
        "content": {
            "subject": subject,
            "plainText": body_text,
            "html": _to_html(subject, body_text),
        },
    }
    poller = client.begin_send(message)
    result = poller.result()  # blocks until the send operation completes
    status = result.get("status") if isinstance(result, dict) else getattr(result, "status", None)
    msg_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", "unknown")
    # Anything other than Succeeded (including a missing status from an unexpected
    # result shape) is a failure — fail loud so the dispatcher records an error
    # instead of reporting a phantom success.
    if str(status).lower() != "succeeded":
        raise RuntimeError(f"ACS send did not succeed (status={status}, id={msg_id})")
    logger.info("ACS email sent (id=%s, status=%s)", msg_id, status)
    return msg_id
