from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SESSION = ROOT / "session-container"
for path in (ROOT, SESSION):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from deepagents.middleware.filesystem import _check_fs_permission  # noqa: E402
from deepagents.middleware.skills import _list_skills  # noqa: E402

from agent_deepagents import SYSTEM_PROMPT, _EXCLUDED_BUILTINS, _model_visible_text  # noqa: E402
from skill_runtime import (  # noqa: E402
    INTERNAL_SKILL_TOOLS,
    PRODUCT_SKILLS_ROOT,
    SKILL_NAME,
    SKILL_PATH,
    SKILL_VIRTUAL_PATH,
    deepagents_skill_config,
    skill_identity,
    skill_name_for_read,
)


class SkillRuntimeTests(unittest.TestCase):
    def test_identity_is_the_exact_checked_in_skill(self):
        identity = skill_identity()
        self.assertEqual(identity["name"], SKILL_NAME)
        self.assertEqual(identity["path"], SKILL_VIRTUAL_PATH)
        self.assertEqual(identity["sha256"], hashlib.sha256(SKILL_PATH.read_bytes()).hexdigest())

    def test_native_discovery_finds_only_the_approved_skill(self):
        config = deepagents_skill_config()
        discovered = _list_skills(config["backend"], "/")
        self.assertEqual([skill["name"] for skill in discovered], [SKILL_NAME])
        self.assertIn("USE FOR: meeting prep", discovered[0]["description"])
        self.assertIn("CSA Workbench", discovered[0]["compatibility"])
        self.assertIn("list_engagements and get_engagement", discovered[0]["compatibility"])
        self.assertEqual(Path(config["backend"].cwd), PRODUCT_SKILLS_ROOT)
        self.assertTrue(config["backend"].virtual_mode)

    def test_skill_loader_permissions_fail_closed(self):
        permissions = deepagents_skill_config()["permissions"]
        self.assertEqual(_check_fs_permission(permissions, "read", SKILL_VIRTUAL_PATH), "allow")
        self.assertEqual(_check_fs_permission(permissions, "read", "/other/SKILL.md"), "deny")
        self.assertEqual(_check_fs_permission(permissions, "write", SKILL_VIRTUAL_PATH), "deny")
        self.assertEqual(INTERNAL_SKILL_TOOLS, frozenset({"read_file"}))
        self.assertNotIn("read_file", _EXCLUDED_BUILTINS)
        self.assertIn("internal `read_file` loader only to load an available product skill", SYSTEM_PROMPT)

    def test_only_a_full_read_is_recorded_as_skill_invocation(self):
        self.assertEqual(
            skill_name_for_read({"file_path": SKILL_VIRTUAL_PATH, "offset": 0, "limit": 1000}),
            SKILL_NAME,
        )
        self.assertIsNone(skill_name_for_read({"file_path": "/other/SKILL.md", "offset": 0, "limit": 1000}))
        self.assertIsNone(skill_name_for_read({"file_path": SKILL_VIRTUAL_PATH, "offset": 1, "limit": 1000}))

    def test_model_visible_tool_output_is_preserved(self):
        class Result:
            content = "exact tool output"

        self.assertEqual(_model_visible_text(Result()), "exact tool output")


if __name__ == "__main__":
    unittest.main()
