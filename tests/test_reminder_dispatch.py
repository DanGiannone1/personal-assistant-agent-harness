"""Behavioral evidence for reminder email dispatch.

Proves the redesigned delivery path: identity-derived recipients only,
at-most-once claim-before-send, recorded failures, and no unattended agent
execution — against an in-memory store implementing the appdb contract.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from workbench_core import reminder_dispatch
from workbench_core.reminder_dispatch import ReminderDispatcher, default_recipient

NOW = datetime(2030, 1, 7, 9, 30, tzinfo=timezone.utc)  # a Monday


class AbortWrite(Exception):
    def __init__(self, result=None):
        super().__init__("aborted")
        self.result = result


class MemoryStore:
    """Implements the PersonalStateStore contract with ETag-free apply-in-place."""

    AbortWrite = AbortWrite

    def __init__(self, users, workspaces):
        self.users = users
        self.workspaces = workspaces

    def list_users(self):
        return deepcopy(self.users)

    def load_personal_workspace(self, user_id):
        state = self.workspaces.get(user_id)
        return deepcopy(state) if state is not None else None

    def update_personal_workspace(self, user_id, mutator):
        state = self.workspaces[user_id]
        candidate = deepcopy(state)
        try:
            result = mutator(candidate)
        except AbortWrite as abort:
            return abort.result
        self.workspaces[user_id] = candidate
        return result


class SendRecorder:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def __call__(self, to, subject, body):
        if self.fail:
            raise RuntimeError("ACS unavailable")
        self.sent.append((to, subject, body))
        return "acs-op-1"


def _weekly_reminder(**overrides):
    reminder = {
        "id": "s-1", "title": "Weekly review", "message": "Plan the week.",
        "frequency": "weekly", "dueDate": "2030-01-07", "time": "09:00",
        "timezone": "UTC", "daysOfWeek": [0], "enabled": True,
        "nextDueAt": "2030-01-07T09:00:00+00:00", "createdAt": "2030-01-01T00:00:00+00:00",
    }
    reminder.update(overrides)
    return reminder


def _store(reminder, user=None):
    user = user or {"id": "u-abc", "username": "dan@contoso.com", "identity": "entra"}
    return MemoryStore(
        [user],
        {user["id"]: {"currentRoute": "/home", "personalTasks": [], "calendarEvents": [],
                      "reminders": [reminder]}},
    )


def test_due_reminder_emails_owner_and_advances_at_most_once() -> None:
    store = _store(_weekly_reminder())
    send = SendRecorder()
    dispatcher = ReminderDispatcher(store, send_email=send)

    assert dispatcher.run_due_once(NOW) == 1
    to, subject, body = send.sent[0]
    assert to == "dan@contoso.com"
    assert subject == "Reminder: Weekly review"
    assert "Plan the week." in body and "Frequency: weekly" in body

    saved = store.workspaces["u-abc"]["reminders"][0]
    assert saved["lastStatus"] == "sent"
    assert saved["lastSentAt"] == NOW.isoformat()
    assert saved["nextDueAt"] == "2030-01-14T09:00:00+00:00"  # strictly the next Monday

    # The same tick re-run delivers nothing: the slot was claimed before sending.
    assert dispatcher.run_due_once(NOW) == 0
    assert len(send.sent) == 1


def test_send_failure_is_recorded_and_never_refires_the_slot() -> None:
    store = _store(_weekly_reminder())
    send = SendRecorder(fail=True)
    dispatcher = ReminderDispatcher(store, send_email=send)

    assert dispatcher.run_due_once(NOW) == 0
    saved = store.workspaces["u-abc"]["reminders"][0]
    assert saved["lastStatus"].startswith("error: ACS unavailable")
    assert saved["nextDueAt"] == "2030-01-14T09:00:00+00:00"  # claimed → no duplicate email later
    assert dispatcher.run_due_once(NOW) == 0


def test_one_time_reminder_fires_once_then_disables() -> None:
    store = _store(_weekly_reminder(frequency="once", daysOfWeek=[]))
    send = SendRecorder()
    assert ReminderDispatcher(store, send_email=send).run_due_once(NOW) == 1
    saved = store.workspaces["u-abc"]["reminders"][0]
    assert saved["enabled"] is False and saved["nextDueAt"] is None


def test_recipient_comes_only_from_identity_never_from_the_record(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REMINDER_DEMO_EMAIL", raising=False)

    # A forged recipient-looking field on the reminder is ignored.
    rogue = _weekly_reminder()
    rogue["recipient"] = "attacker@evil.example"
    rogue["email"] = "attacker@evil.example"
    store = _store(rogue)
    send = SendRecorder()
    ReminderDispatcher(store, send_email=send).run_due_once(NOW)
    assert [to for to, _s, _b in send.sent] == ["dan@contoso.com"]

    # A demo actor without an operator-configured address gets no email — recorded, advanced.
    demo_store = _store(_weekly_reminder(), user={"id": "dan", "username": "dan", "identity": "demo"})
    demo_send = SendRecorder()
    assert ReminderDispatcher(demo_store, send_email=demo_send).run_due_once(NOW) == 0
    saved = demo_store.workspaces["dan"]["reminders"][0]
    assert saved["lastStatus"] == "skipped: no recipient address"
    assert saved["nextDueAt"] == "2030-01-14T09:00:00+00:00"
    assert demo_send.sent == []

    # With the override set, demo reminders go only to that address.
    monkeypatch.setenv("REMINDER_DEMO_EMAIL", "qa@example.test")
    demo_store2 = _store(_weekly_reminder(), user={"id": "dan", "username": "dan", "identity": "demo"})
    demo_send2 = SendRecorder()
    assert ReminderDispatcher(demo_store2, send_email=demo_send2).run_due_once(NOW) == 1
    assert demo_send2.sent[0][0] == "qa@example.test"

    # An Entra actor whose username is not an address gets no email.
    assert default_recipient({"identity": "entra", "username": "not-an-address"}) is None
    assert default_recipient({"identity": "other", "username": "x@y.example"}) is None


def test_disabled_future_and_corrupt_reminders_do_not_send() -> None:
    user = {"id": "u-abc", "username": "dan@contoso.com", "identity": "entra"}
    reminders = [
        _weekly_reminder(id="s-1", enabled=False),
        _weekly_reminder(id="s-2", nextDueAt="2031-01-05T09:00:00+00:00"),
        _weekly_reminder(id="s-3", nextDueAt="not-a-timestamp"),
    ]
    store = MemoryStore([user], {"u-abc": {"reminders": deepcopy(reminders)}})
    send = SendRecorder()
    assert ReminderDispatcher(store, send_email=send).run_due_once(NOW) == 0
    assert send.sent == []
    corrupt = store.workspaces["u-abc"]["reminders"][2]
    assert corrupt["enabled"] is False
    assert corrupt["lastStatus"] == "error: unparseable nextDueAt"


def test_daily_cadence_advances_strictly_past_now() -> None:
    reminder = _weekly_reminder(frequency="daily", daysOfWeek=[], nextDueAt="2030-01-07T09:00:00+00:00")
    store = _store(reminder)
    send = SendRecorder()
    ReminderDispatcher(store, send_email=send).run_due_once(NOW)
    assert store.workspaces["u-abc"]["reminders"][0]["nextDueAt"] == "2030-01-08T09:00:00+00:00"


def test_dispatch_mode_resolution_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("REMINDER_DISPATCH", "ACS_EMAIL_ENDPOINT", "ACS_SENDER_ADDRESS"):
        monkeypatch.delenv(var, raising=False)
    assert reminder_dispatch.dispatch_mode() == "off"

    monkeypatch.setenv("ACS_EMAIL_ENDPOINT", "https://acs.example")
    monkeypatch.setenv("ACS_SENDER_ADDRESS", "DoNotReply@example.test")
    assert reminder_dispatch.dispatch_mode() == "loop"

    monkeypatch.setenv("REMINDER_DISPATCH", "off")
    assert reminder_dispatch.dispatch_mode() == "off"

    monkeypatch.setenv("REMINDER_DISPATCH", "loop")
    monkeypatch.delenv("ACS_EMAIL_ENDPOINT", raising=False)
    with pytest.raises(RuntimeError, match="requires ACS"):
        reminder_dispatch.dispatch_mode()

    monkeypatch.setenv("REMINDER_DISPATCH", "sometimes")
    with pytest.raises(RuntimeError, match="auto, loop, or off"):
        reminder_dispatch.dispatch_mode()


def test_dispatch_never_runs_agent_turns_or_stored_prompts() -> None:
    """The excluded unattended-agent design must not silently return (issue #18)."""
    source = (Path(__file__).resolve().parent.parent / "workbench_core" / "reminder_dispatch.py").read_text()
    for forbidden in ("SessionManager", "session_manager", "create_session", "send_message", '"prompt"'):
        assert forbidden not in source, f"reminder dispatch must not reference {forbidden}"
