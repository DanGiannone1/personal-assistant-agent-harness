"""Deterministic email dispatch for due personal reminders.

Redesign of the removed unattended scheduler, keeping its safe property
(at-most-once delivery via claim-before-send on the ETag-safe update path) and
removing its unsafe ones:

- the recipient is derived only from the owning actor's identity — Entra actors
  receive mail at their validated sign-in address, demo actors only at an
  explicitly configured test address; it is never read from a reminder record
  or any client-supplied field; and
- the email body is a deterministic rendering of the reminder itself. This
  module never creates sessions or runs agent turns; unattended agent-generated
  content is an explicitly excluded product decision (issue #18).

Deployment shape: `ReminderDispatcher.loop` ticks inside the API app while it
has a replica (local dev, always-on deployments). `scripts/dispatch_reminders.py`
runs one `run_due_once` pass for a cron/ACA Job when the API app scales to zero.

Config (env):
  REMINDER_DISPATCH        — auto (default: on iff ACS is configured) | loop | off
  REMINDER_TICK_SECONDS    — loop cadence, default 60
  REMINDER_DEMO_EMAIL      — the only address demo-actor reminders may go to
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Protocol
from zoneinfo import ZoneInfo

from . import acs_email

logger = logging.getLogger(__name__)

_MAX_STATUS_CHARS = 240


class PersonalStateStore(Protocol):
    """The appdb surface the dispatcher needs (see session-container/appdb.py)."""

    AbortWrite: type[Exception]

    def list_users(self) -> list[dict[str, Any]]: ...
    def load_personal_workspace(self, user_id: str) -> dict[str, Any] | None: ...
    def update_personal_workspace(self, user_id: str, mutator: Callable[[dict[str, Any]], Any]) -> Any: ...


def default_recipient(user: dict[str, Any]) -> str | None:
    """The only address a reminder may be delivered to, from validated identity.

    Entra actors: their sign-in username (a validated ``preferred_username``/
    ``upn``/``email`` claim) when it is an address. Demo actors: only the
    operator-configured ``REMINDER_DEMO_EMAIL``. Anything else: no delivery.
    """
    identity = user.get("identity")
    if identity == "entra":
        username = (user.get("username") or "").strip()
        return username if "@" in username else None
    if identity == "demo":
        return (os.getenv("REMINDER_DEMO_EMAIL") or "").strip() or None
    return None


def render_email(reminder: dict[str, Any]) -> tuple[str, str]:
    """Deterministic subject/body for a reminder — no model, no stored prompt."""
    title = reminder.get("title") or "Reminder"
    lines = []
    message = (reminder.get("message") or "").strip()
    if message:
        lines.append(message)
        lines.append("")
    lines.append(f"Due: {reminder.get('dueDate', '')} {reminder.get('time', '')} ({reminder.get('timezone', 'UTC')})")
    lines.append(f"Frequency: {reminder.get('frequency', '')}")
    lines.append("")
    lines.append("— CSA Workbench reminders")
    return f"Reminder: {title}", "\n".join(lines)


def next_occurrence_after(schedule: dict[str, Any], after: datetime) -> str | None:
    """The next slot strictly after ``after`` (None for a fired one-time reminder).

    Steps in UTC like the display-side ``PersonalWorkspaceService._next_due_at``
    so both paths agree on cadence math.
    """
    zone = ZoneInfo(schedule["timezone"])
    candidate = datetime.combine(
        date.fromisoformat(schedule["dueDate"]), time.fromisoformat(schedule["time"]), zone
    ).astimezone(timezone.utc)
    frequency = schedule["frequency"]
    if frequency == "once":
        return None
    if frequency == "daily":
        while candidate <= after:
            candidate += timedelta(days=1)
        return candidate.isoformat()
    days = set(schedule["daysOfWeek"])
    while candidate <= after or candidate.astimezone(zone).weekday() not in days:
        candidate += timedelta(days=1)
    return candidate.isoformat()


def _parse_iso(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class ReminderDispatcher:
    """Claim-before-send delivery of due reminders, one actor aggregate at a time."""

    def __init__(
        self,
        store: PersonalStateStore,
        *,
        resolve_recipient: Callable[[dict[str, Any]], str | None] = default_recipient,
        send_email: Callable[[str, str, str], str] = acs_email.send_email,
    ):
        self._store = store
        self._resolve_recipient = resolve_recipient
        self._send_email = send_email

    def run_due_once(self, now: datetime | None = None) -> int:
        """Deliver every actor's due reminders. Returns the count emailed.

        Blocking (Cosmos + ACS I/O) — call from a worker thread or a one-shot job.
        """
        now = now or datetime.now(timezone.utc)
        sent = 0
        for user in self._store.list_users():
            try:
                sent += self._run_due_for_user(user, now)
            except Exception:
                logger.error("reminder dispatch failed for actor %s", user.get("id"), exc_info=True)
        return sent

    async def loop(self, tick_seconds: int) -> None:
        logger.info("Reminder dispatch loop started (tick=%ss)", tick_seconds)
        while True:
            try:
                await asyncio.to_thread(self.run_due_once)
            except asyncio.CancelledError:
                logger.info("Reminder dispatch loop stopped")
                raise
            except Exception:
                logger.error("reminder dispatch tick failed", exc_info=True)
            await asyncio.sleep(tick_seconds)

    def _run_due_for_user(self, user: dict[str, Any], now: datetime) -> int:
        uid = user["id"]
        state = self._store.load_personal_workspace(uid)
        if state is None:
            return 0
        reminders = state.get("reminders") or []

        # Surface (don't silently drop) reminders with a corrupt nextDueAt.
        for reminder in reminders:
            if reminder.get("enabled") and reminder.get("nextDueAt") and _parse_iso(reminder.get("nextDueAt")) is None:
                self._record_status(uid, reminder["id"], "error: unparseable nextDueAt", disable=True)

        due = [
            r for r in reminders
            if r.get("enabled") and (due_at := _parse_iso(r.get("nextDueAt"))) and due_at <= now
        ]
        sent = 0
        for reminder in due:
            # Claim first (advance nextDueAt). A claim failure means nothing was
            # sent — retry next tick. A failure after claiming cannot re-fire the
            # slot, so delivery is at-most-once.
            try:
                claimed = self._store.update_personal_workspace(
                    uid, lambda st, rid=reminder["id"]: self._claim(st, rid, now))
            except Exception:
                logger.error("could not claim reminder %s — will retry next tick", reminder["id"], exc_info=True)
                continue
            if claimed is None:
                continue  # deleted, disabled, or already claimed elsewhere

            recipient = self._resolve_recipient(user)
            if not recipient:
                self._record_status(uid, reminder["id"], "skipped: no recipient address")
                continue

            try:
                subject, body = render_email(claimed)
                self._send_email(recipient, subject, body)
                self._record_status(uid, reminder["id"], "sent")
                sent += 1
            except Exception as exc:
                logger.error("reminder %s delivery failed", reminder["id"], exc_info=True)
                self._record_status(uid, reminder["id"], f"error: {exc}"[:_MAX_STATUS_CHARS])
        return sent

    def _claim(self, state: dict[str, Any], reminder_id: str, now: datetime) -> dict[str, Any]:
        reminder = next((r for r in state.get("reminders") or [] if r.get("id") == reminder_id), None)
        if reminder is None or not reminder.get("enabled"):
            raise self._store.AbortWrite(None)
        due_at = _parse_iso(reminder.get("nextDueAt"))
        if due_at is None or due_at > now:
            raise self._store.AbortWrite(None)  # already claimed by a concurrent pass
        reminder["lastSentAt"] = now.isoformat()
        reminder["lastStatus"] = "sending"
        try:
            reminder["nextDueAt"] = next_occurrence_after(reminder, now)
        except Exception:
            logger.error("cannot reschedule reminder %s — disabling it", reminder_id, exc_info=True)
            reminder["nextDueAt"] = None
            reminder["enabled"] = False
        if reminder.get("frequency") == "once":
            reminder["enabled"] = False
        return dict(reminder)

    def _record_status(self, uid: str, reminder_id: str, status: str, *, disable: bool = False) -> None:
        """Best-effort: the slot is already claimed, so a failure here only leaves
        the status stale — it can never double-send."""

        def mutate(state: dict[str, Any]) -> None:
            reminder = next((r for r in state.get("reminders") or [] if r.get("id") == reminder_id), None)
            if reminder is None:
                raise self._store.AbortWrite(None)
            reminder["lastStatus"] = status[:_MAX_STATUS_CHARS]
            if disable:
                reminder["enabled"] = False

        try:
            self._store.update_personal_workspace(uid, mutate)
        except Exception:
            logger.error("could not record status for reminder %s", reminder_id, exc_info=True)


def dispatch_mode() -> str:
    """Resolve the configured dispatch mode to ``loop`` or ``off`` — fail loud on nonsense."""
    mode = (os.getenv("REMINDER_DISPATCH") or "auto").strip().lower()
    if mode not in {"auto", "loop", "off"}:
        raise RuntimeError(f"REMINDER_DISPATCH must be auto, loop, or off (got {mode!r})")
    if mode == "auto":
        return "loop" if acs_email.is_configured() else "off"
    if mode == "loop" and not acs_email.is_configured():
        raise RuntimeError("REMINDER_DISPATCH=loop requires ACS_EMAIL_ENDPOINT and ACS_SENDER_ADDRESS")
    return mode


def tick_seconds() -> int:
    return int(os.getenv("REMINDER_TICK_SECONDS", "60"))
