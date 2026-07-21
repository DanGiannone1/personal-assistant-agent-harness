"""Run one reminder email dispatch pass and exit (for a cron/ACA Job).

Covers deployments where the API app scales to zero: a scheduled job invokes
the same claim-before-send path the in-process loop uses, against the same
Cosmos aggregates, with the same identity-derived recipients.

Requires the app's Cosmos configuration plus ACS_EMAIL_ENDPOINT and
ACS_SENDER_ADDRESS. Exits nonzero on misconfiguration so the job run is
visibly failed rather than silently idle.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for path in (_ROOT, _ROOT / "session-container"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import appdb  # noqa: E402
from workbench_core import acs_email, reminder_dispatch  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not acs_email.is_configured():
        print("ACS email is not configured — set ACS_EMAIL_ENDPOINT and ACS_SENDER_ADDRESS", file=sys.stderr)
        return 2
    sent = reminder_dispatch.ReminderDispatcher(appdb).run_due_once()
    print(f"dispatched {sent} reminder email(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
