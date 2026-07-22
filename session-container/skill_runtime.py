"""Approved product-skill identities and native Deep Agents loading boundary.

The product exposes a small catalog of public CSA tools. Deep Agents additionally receives its
native ``read_file`` skill loader, rooted at the directory below and denied access to every path
except the approved ``SKILL.md`` files listed in ``SKILL_NAMES``. Skill loads are
diagnostic/evaluation evidence, never public control events.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemPermission


PRODUCT_SKILLS_ROOT = Path(__file__).resolve().parent / "product-skills"
SKILL_NAMES = ("engagement-meeting-prep", "tasks", "calendar", "weekly-review")
SKILL_SOURCES = ["/"]
INTERNAL_SKILL_TOOLS = frozenset({"read_file"})


def skill_path(name: str) -> Path:
    return PRODUCT_SKILLS_ROOT / name / "SKILL.md"


def skill_virtual_path(name: str) -> str:
    return f"/{name}/SKILL.md"


def skill_sha256(name: str) -> str:
    """Return the exact SHA-256 identity of the named skill asset under evaluation."""
    return hashlib.sha256(skill_path(name).read_bytes()).hexdigest()


def skill_identity(name: str) -> dict[str, str]:
    return {
        "name": name,
        "version": "1.0.0",
        "sha256": skill_sha256(name),
        "path": skill_virtual_path(name),
    }


def skill_identities() -> list[dict[str, str]]:
    """Identity of every approved skill, in catalog order."""
    return [skill_identity(name) for name in SKILL_NAMES]


def skill_name_for_read(arguments: Any) -> str | None:
    """Recognize only a full read of one of the approved skill files."""
    if not isinstance(arguments, dict):
        return None
    offset = arguments.get("offset", 0)
    limit = arguments.get("limit", 100)
    if not isinstance(offset, int) or offset != 0 or not isinstance(limit, int) or limit < 100:
        return None
    file_path = arguments.get("file_path")
    return next((name for name in SKILL_NAMES if file_path == skill_virtual_path(name)), None)


def deepagents_skill_config() -> dict[str, Any]:
    """Return the narrowly rooted backend, sources, and fail-closed permissions."""
    backend = FilesystemBackend(root_dir=PRODUCT_SKILLS_ROOT, virtual_mode=True)
    permissions = [
        FilesystemPermission(
            operations=["read"], paths=[skill_virtual_path(name) for name in SKILL_NAMES], mode="allow"),
        FilesystemPermission(operations=["read", "write"], paths=["/**"], mode="deny"),
    ]
    return {"backend": backend, "skills": list(SKILL_SOURCES), "permissions": permissions}
