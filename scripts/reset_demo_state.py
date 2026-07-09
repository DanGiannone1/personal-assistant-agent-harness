"""Reset the owner's app-state to a clean, controlled demo set for UI fixtures.

App state is owner-keyed in Cosmos (not per-session), so a new chat does NOT reset it.
This overwrites the owner doc with a fresh seed plus a deterministic task/event set
(two tasks overdue relative to 2026-06-25) so the weekly-review fixture is isolated and
reproducible. Run from the session-container env:

    (cd session-container && uv run python ../scripts/reset_demo_state.py)
"""
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "session-container"))
import appdb  # noqa: E402

now = appdb._now_iso()
data = appdb._seed()              # fresh: empty tasks/events/schedules, seeded Library + routes
data["currentRoute"] = "/todo"
data["tasks"] = [
    {"id": "t-1", "title": "Finish Northstar budget memo", "status": "In progress", "priority": "Medium", "group": "Work", "dueDate": "2026-06-20", "subtasks": [], "notes": "", "createdAt": now},  # overdue
    {"id": "t-2", "title": "Email vendor about renewal", "status": "To do", "priority": "Medium", "group": "Work", "dueDate": "2026-06-22", "subtasks": [], "notes": "", "createdAt": now},          # overdue
    {"id": "t-3", "title": "Review design mockups", "status": "To do", "priority": "Medium", "group": "Work", "dueDate": "2026-06-30", "subtasks": [], "notes": "", "createdAt": now},
    {"id": "t-4", "title": "Draft Q3 planning doc", "status": "To do", "priority": "Medium", "group": "Work", "dueDate": "2026-06-29", "subtasks": [], "notes": "", "createdAt": now},
    {"id": "t-5", "title": "Book team offsite venue", "status": "To do", "priority": "Low", "group": "Personal", "dueDate": "", "subtasks": [], "notes": "", "createdAt": now},
]
data["events"] = [
    {"id": "e-1", "title": "Northstar sync", "date": "2026-06-26", "start": "10:00", "end": "10:30", "type": "Meeting", "notes": ""},
]
data["schedules"] = []
appdb.save(data)
print(f"reset OK — tasks={len(data['tasks'])} (2 overdue), events={len(data['events'])}, library={len(data['library'])}")
