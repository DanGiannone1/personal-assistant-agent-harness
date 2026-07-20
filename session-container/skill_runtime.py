"""Approved product-skill identity and native Deep Agents loading boundary.

The product exposes seven public CSA tools. Deep Agents additionally receives its native
``read_file`` skill loader, rooted at the directory below and denied access to every path except the
single approved SKILL.md. Skill loads are diagnostic/evaluation evidence, never public control
events.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemPermission


SKILL_NAME = "engagement-meeting-prep"
PRODUCT_SKILLS_ROOT = Path(__file__).resolve().parent / "product-skills"
SKILL_PATH = PRODUCT_SKILLS_ROOT / SKILL_NAME / "SKILL.md"
SKILL_VIRTUAL_PATH = f"/{SKILL_NAME}/SKILL.md"
SKILL_SOURCES = ["/"]
INTERNAL_SKILL_TOOLS = frozenset({"read_file"})


def skill_sha256(path: Path = SKILL_PATH) -> str:
    """Return the exact SHA-256 identity of the skill asset under evaluation."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def skill_identity() -> dict[str, str]:
    return {
        "name": SKILL_NAME,
        "version": "1.0.0",
        "sha256": skill_sha256(),
        "path": SKILL_VIRTUAL_PATH,
    }


def skill_name_for_read(arguments: Any) -> str | None:
    """Recognize only a full read of the one approved skill file."""
    if not isinstance(arguments, dict):
        return None
    if arguments.get("file_path") != SKILL_VIRTUAL_PATH:
        return None
    offset = arguments.get("offset", 0)
    limit = arguments.get("limit", 100)
    if not isinstance(offset, int) or offset != 0 or not isinstance(limit, int) or limit < 100:
        return None
    return SKILL_NAME


def deepagents_skill_config() -> dict[str, Any]:
    """Return the narrowly rooted backend, sources, and fail-closed permissions."""
    backend = FilesystemBackend(root_dir=PRODUCT_SKILLS_ROOT, virtual_mode=True)
    permissions = [
        FilesystemPermission(operations=["read"], paths=[SKILL_VIRTUAL_PATH], mode="allow"),
        FilesystemPermission(operations=["read", "write"], paths=["/**"], mode="deny"),
    ]
    return {"backend": backend, "skills": list(SKILL_SOURCES), "permissions": permissions}
