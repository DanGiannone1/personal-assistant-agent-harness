"""Background reminder scheduler for the orchestrator.

Runs due reminders on a cadence and emails their output. Reuses the session
container's `appdb` (the single owner Cosmos doc is the source of truth for schedule
state + cadence math) and the orchestrator's `SessionManager` to run each saved prompt
as a headless agent turn — the agent produces the content, the scheduler delivers it.

The scheduler is the *only* always-on piece; in production this loop is replaced by an
ACA Job on a cron hitting the same `run_due_once`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Reuse the session-container appdb — single source of truth for schedules + cadence.
# (Requires azure-cosmos in the orchestrator venv; the import is intentional, not a copy.)
_SC = Path(__file__).resolve().parent / "session-container"
if str(_SC) not in sys.path:
    sys.path.insert(0, str(_SC))
import appdb  # noqa: E402

import email_acs  # noqa: E402

logger = logging.getLogger(__name__)

TICK_SECONDS = int(os.getenv("SCHEDULER_TICK_SECONDS", "60"))
# Client-side ceiling on a single headless turn, above the container's own
# CHAT_TIMEOUT_SECONDS (default 300) so a stuck turn can't head-of-line-block the loop.
_TURN_TIMEOUT_SECONDS = int(os.getenv("CHAT_TIMEOUT_SECONDS", "300")) + 30


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        # Fail loud rather than silently treating the reminder as never-due.
        logger.error("scheduler: schedule has unparseable nextRunAt %r — it will not fire", value)
        return None
    # Treat naive timestamps as UTC so comparisons are always tz-aware.
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _consume_turn(session_manager, sid: str, prompt: str, user: dict) -> str:
    """Consume one agent turn's SSE stream → assistant text. Raises if the turn errored."""
    parts: list[str] = []
    run_error: str | None = None
    async for chunk in session_manager.send_message(sid, prompt, user=user):
        for line in chunk.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            try:
                obj = json.loads(line[len("data:"):].strip())
            except json.JSONDecodeError:
                continue
            kind = obj.get("type")
            if kind == "TEXT_MESSAGE_CONTENT":
                parts.append(obj.get("delta", ""))
            elif kind == "RUN_ERROR":
                # The agent failure is a data event, not an exception — surface it (fail loud)
                # so the reminder is recorded as failed instead of emailing a blank body.
                run_error = obj.get("message") or "agent run failed"
    if run_error:
        raise RuntimeError(f"agent turn failed: {run_error}")
    return "".join(parts).strip()


async def _run_prompt(session_manager, prompt: str, user: dict) -> str:
    """Run `prompt` as a one-off headless agent turn AS `user`; return the assistant's text.

    Raises on agent error or timeout so the caller records the reminder as failed.
    """
    meta = await session_manager.create_session(user=user)
    sid = meta["session_id"]
    try:
        return await asyncio.wait_for(
            _consume_turn(session_manager, sid, prompt, user), timeout=_TURN_TIMEOUT_SECONDS
        )
    finally:
        try:
            await session_manager.delete_session(sid)
        except Exception:
            logger.warning("scheduler: failed to clean up session %s", sid, exc_info=True)


def _claim(doc: dict, schedule: dict, now: datetime) -> bool:
    """Mutator: claim a reminder's slot BEFORE sending — stamp lastRunAt and advance
    nextRunAt so a later send failure or crash can't re-fire it (delivery is at-most-once).
    Disables the reminder if its cadence can no longer be computed. Re-entrant for retry."""
    cur = appdb.find_schedule(doc, schedule["id"])
    if cur is None:  # deleted mid-run
        raise appdb.AbortWrite(False)
    cur["lastRunAt"] = now.isoformat()
    cur["lastStatus"] = "running"
    try:
        cur["nextRunAt"] = appdb.compute_next_run(
            cur["frequency"], cur["time"], cur.get("timezone", "UTC"),
            cur.get("daysOfWeek"), after=now,
        ).isoformat()
    except Exception:
        logger.error("scheduler: cannot reschedule %s — disabling it", schedule["id"], exc_info=True)
        cur["enabled"] = False
    return True


def _set_status(doc: dict, schedule: dict, status: str) -> None:
    """Mutator: record a reminder's final run status (best-effort; no effect on scheduling)."""
    cur = appdb.find_schedule(doc, schedule["id"])
    if cur is None:
        raise appdb.AbortWrite(None)
    cur["lastStatus"] = status[:240]


def _disable_broken(doc: dict, schedule: dict) -> None:
    """Mutator: surface a reminder whose nextRunAt is unparseable — disable it + record why,
    instead of silently never firing (only the log would show it otherwise)."""
    cur = appdb.find_schedule(doc, schedule["id"])
    if cur is None:
        raise appdb.AbortWrite(None)
    cur["lastStatus"] = "error: unparseable nextRunAt"
    cur["enabled"] = False


async def run_due_once(session_manager, *, now: datetime | None = None) -> int:
    """Run every user's due reminders (schedules live in per-user docs). Total emailed."""
    now = now or datetime.now(timezone.utc)
    users = await asyncio.to_thread(appdb.list_users)
    total = 0
    for u in users:
        user = {"id": u["id"], "username": u.get("username", ""),
                "displayName": u.get("displayName", "")}
        # Bind the user for this slice of the tick — contextvars propagate into to_thread,
        # so every appdb.load/update below operates on THIS user's document.
        ctx = appdb.set_current_user(user["id"])
        try:
            total += await _run_due_for_user(session_manager, user, now)
        except Exception:
            logger.error("scheduler: tick failed for user %s", user["id"], exc_info=True)
        finally:
            appdb.reset_current_user(ctx)
    return total


async def _run_due_for_user(session_manager, user: dict, now: datetime) -> int:
    """Run the bound user's due reminders. Returns the count emailed."""
    data = await asyncio.to_thread(appdb.load)
    schedules = data.get("schedules", [])

    # Surface (don't silently drop) reminders with a corrupt nextRunAt — disable + record so
    # the dead state shows on the reminder itself, not just in a log line every tick.
    for s in schedules:
        if s.get("enabled") and s.get("nextRunAt") and _parse_iso(s.get("nextRunAt")) is None:
            try:
                await asyncio.to_thread(appdb.update, lambda doc, sc=s: _disable_broken(doc, sc))
            except Exception:
                logger.error("scheduler: could not disable broken reminder %s", s["id"], exc_info=True)

    due = [
        s for s in schedules
        if s.get("enabled") and (dt := _parse_iso(s.get("nextRunAt"))) and dt <= now
    ]
    emailed = 0
    for s in due:
        # Claim the slot first (advance nextRunAt). A write failure here means we simply
        # haven't sent yet — retry next tick, no duplicate. A send/crash after claiming
        # cannot re-fire, so delivery is at-most-once (no duplicate emails).
        try:
            await asyncio.to_thread(appdb.update, lambda doc, sc=s: _claim(doc, sc, now))
        except Exception:
            logger.error("scheduler: could not claim reminder %s — will retry next tick", s["id"], exc_info=True)
            continue

        status = "ok"
        try:
            body = await _run_prompt(session_manager, s["prompt"], user)
            if not body:
                raise RuntimeError("agent produced no content")
            recipient = os.getenv("REMINDER_EMAIL", "")
            msg_id = await asyncio.to_thread(email_acs.send_email, recipient, s["title"], body)
            logger.info("scheduler: emailed reminder %s (acs id=%s)", s["id"], msg_id)
            emailed += 1
        except Exception as exc:
            status = f"error: {exc}"
            logger.error("scheduler: reminder %s failed: %s", s["id"], exc, exc_info=True)

        # Record the outcome (best-effort — already claimed, so a failure here only leaves the
        # status stale, never double-sends).
        try:
            await asyncio.to_thread(appdb.update, lambda doc, sc=s, st=status: _set_status(doc, sc, st))
        except Exception:
            logger.error("scheduler: could not record status for %s", s["id"], exc_info=True)
    return emailed


async def scheduler_loop(session_manager) -> None:
    """Tick forever, running due reminders each interval."""
    logger.info("Reminder scheduler started (tick=%ss)", TICK_SECONDS)
    while True:
        try:
            await run_due_once(session_manager)
        except asyncio.CancelledError:
            logger.info("Reminder scheduler stopped")
            raise
        except Exception:
            logger.error("scheduler tick failed", exc_info=True)
        await asyncio.sleep(TICK_SECONDS)
