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
    SKILL_NAMES,
    deepagents_skill_config,
    skill_identities,
    skill_identity,
    skill_name_for_read,
    skill_path,
    skill_virtual_path,
)


class SkillRuntimeTests(unittest.TestCase):
    def test_identity_is_exact_for_every_checked_in_skill(self):
        identities = {identity["name"]: identity for identity in skill_identities()}
        self.assertEqual(set(identities), set(SKILL_NAMES))
        for name in SKILL_NAMES:
            identity = skill_identity(name)
            self.assertEqual(identity, identities[name])
            self.assertEqual(identity["path"], skill_virtual_path(name))
            self.assertEqual(identity["sha256"], hashlib.sha256(skill_path(name).read_bytes()).hexdigest())

    def test_native_discovery_finds_every_approved_skill(self):
        config = deepagents_skill_config()
        discovered = {skill["name"]: skill for skill in _list_skills(config["backend"], "/")}
        self.assertEqual(set(discovered), set(SKILL_NAMES))
        self.assertIn("USE FOR: meeting prep", discovered["engagement-meeting-prep"]["description"])
        self.assertIn("CSA Workbench", discovered["engagement-meeting-prep"]["compatibility"])
        self.assertIn("list_engagements and get_engagement", discovered["engagement-meeting-prep"]["compatibility"])
        self.assertIn("USE FOR", discovered["tasks"]["description"])
        self.assertIn("USE FOR", discovered["calendar"]["description"])
        self.assertIn("USE FOR", discovered["weekly-review"]["description"])
        self.assertEqual(Path(config["backend"].cwd), PRODUCT_SKILLS_ROOT)
        self.assertTrue(config["backend"].virtual_mode)

    def test_skill_loader_permissions_allow_every_approved_skill_and_fail_closed_elsewhere(self):
        permissions = deepagents_skill_config()["permissions"]
        for name in SKILL_NAMES:
            self.assertEqual(_check_fs_permission(permissions, "read", skill_virtual_path(name)), "allow")
            self.assertEqual(_check_fs_permission(permissions, "write", skill_virtual_path(name)), "deny")
        self.assertEqual(_check_fs_permission(permissions, "read", "/other/SKILL.md"), "deny")
        self.assertEqual(INTERNAL_SKILL_TOOLS, frozenset({"read_file"}))
        self.assertNotIn("read_file", _EXCLUDED_BUILTINS)
        self.assertIn("internal `read_file` loader only to load an available product skill", SYSTEM_PROMPT)

    def test_only_a_full_read_is_recorded_as_skill_invocation(self):
        for name in SKILL_NAMES:
            self.assertEqual(
                skill_name_for_read({"file_path": skill_virtual_path(name), "offset": 0, "limit": 1000}),
                name,
            )
        self.assertIsNone(skill_name_for_read({"file_path": "/other/SKILL.md", "offset": 0, "limit": 1000}))
        self.assertIsNone(
            skill_name_for_read({"file_path": skill_virtual_path(SKILL_NAMES[0]), "offset": 1, "limit": 1000}))

    def test_model_visible_tool_output_is_preserved(self):
        class Result:
            content = "exact tool output"

        self.assertEqual(_model_visible_text(Result()), "exact tool output")


if __name__ == "__main__":
    unittest.main()
