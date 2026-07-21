from __future__ import annotations

from copy import deepcopy
import unittest

from workbench_core import EngagementService


class FakeRepository:
    def __init__(self):
        self.records: dict[str, dict] = {}
        self.activities: list[tuple[str, str, str]] = []
        self._sequence = 0

    def create(self, actor_id: str, values: dict) -> dict:
        self._sequence += 1
        record = {
            "id": f"eng-{self._sequence}", "name": values["name"],
            "description": values.get("description", ""), "customer": values.get("customer", ""),
            "status": values.get("status", "green") or "green", "statusNote": values.get("statusNote", ""),
            "startDate": values.get("startDate", ""), "targetDate": values.get("targetDate", ""),
            "createdBy": actor_id, "members": [{"userId": actor_id, "role": "owner"}], "activity": [],
        }
        self.records[record["id"]] = record
        return deepcopy(record)

    def load(self, engagement_id: str) -> dict | None:
        record = self.records.get(engagement_id)
        return deepcopy(record) if record else None

    def list_for(self, actor_id: str) -> list[dict]:
        return [deepcopy(record) for record in self.records.values()
                if any(member["userId"] == actor_id for member in record["members"])]

    def update(self, engagement_id: str, mutator):
        record = self.records[engagement_id]
        result = mutator(record)
        if result.commit:
            self.records[engagement_id] = record
        return result.outcome

    def log_activity(self, engagement: dict, actor_id: str, action: str, detail: str) -> None:
        engagement["activity"].append({"userId": actor_id, "action": action, "detail": detail})
        self.activities.append((actor_id, action, detail))


class EngagementServiceTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeRepository()
        self.users = {user: {"id": user} for user in ("owner", "editor", "viewer", "outsider", "other")}
        self.lookup_calls: list[str] = []

        def lookup(ref: str):
            self.lookup_calls.append(ref)
            return self.users.get(ref)

        self.service = EngagementService(self.repo, lookup)
        created = self.service.create("owner", {"name": "Northstar", "description": "Initial"})
        self.engagement_id = created.record["id"]

    def share(self, user: str, role: str):
        return self.service.share("owner", self.engagement_id, user, role)

    def test_create_list_get_and_hidden_non_member(self):
        created = self.service.create("editor", {"name": "Second", "customer": "Contoso"})
        self.assertEqual(created.status, "committed")
        self.assertEqual(self.service.list("editor").record["engagements"][0]["id"], created.record["id"])
        self.assertEqual(self.service.get("owner", self.engagement_id).status, "succeeded")
        self.assertEqual(self.service.get("outsider", self.engagement_id).status, "not_found")
        self.assertEqual(self.service.get("outsider", "eng-missing").status, "not_found")

    def test_owner_created_create_replay_is_noop_but_shared_same_name_is_allowed(self):
        replay = self.service.create("owner", {"name": " northstar "})
        self.assertEqual(replay.status, "noop")
        self.assertEqual(replay.record["id"], self.engagement_id)

        shared = self.service.create("outsider", {"name": "Shared name"})
        self.assertEqual(self.service.share("outsider", shared.record["id"], "owner", "viewer").status, "committed")
        created = self.service.create("owner", {"name": "shared name"})
        self.assertEqual(created.status, "committed")

    def test_role_matrix_and_resulting_state_guard(self):
        self.assertEqual(self.share("editor", "editor").status, "committed")
        self.assertEqual(self.share("viewer", "viewer").status, "committed")
        self.assertEqual(self.service.update("editor", self.engagement_id, {"description": "Edited"}).status, "committed")
        self.assertEqual(self.service.update("editor", self.engagement_id, {"name": "Nope"}).status, "forbidden")
        self.assertEqual(self.service.update("owner", self.engagement_id, {"name": "Renamed"}).status, "committed")
        self.assertEqual(self.service.update("viewer", self.engagement_id, {"customer": "Nope"}).status, "forbidden")
        invalid = self.service.update("editor", self.engagement_id, {"status": "yellow"})
        self.assertEqual(invalid.status, "invalid")
        self.assertEqual(self.repo.load(self.engagement_id)["status"], "green")
        self.assertEqual(self.service.update("owner", self.engagement_id, {"status": "yellow", "statusNote": "Blocked"}).status, "committed")
        blank_reason = self.service.update("editor", self.engagement_id, {"statusNote": ""})
        self.assertEqual(blank_reason.status, "invalid")
        self.assertEqual(self.repo.load(self.engagement_id)["statusNote"], "Blocked")

    def test_green_clears_reason_and_noop(self):
        self.assertEqual(self.service.update("owner", self.engagement_id, {"status": "red", "statusWhy": "Risk"}).status, "committed")
        green = self.service.update("owner", self.engagement_id, {"status": "green"})
        self.assertEqual(green.status, "committed")
        self.assertEqual(self.repo.load(self.engagement_id)["statusNote"], "")
        self.assertEqual(self.service.update("owner", self.engagement_id, {"status": "green"}).status, "noop")

    def test_optional_delivery_fields_can_be_explicitly_cleared(self):
        self.share("editor", "editor")
        self.assertEqual(self.service.update("editor", self.engagement_id, {
            "description": "Details", "customer": "Contoso", "startDate": "2026-01-01", "targetDate": "2026-02-01",
        }).status, "committed")
        cleared = self.service.update("editor", self.engagement_id, {
            "description": "", "customer": "", "startDate": "", "targetDate": "",
        })
        self.assertEqual(cleared.status, "committed")
        record = self.repo.load(self.engagement_id)
        self.assertEqual({field: record[field] for field in ("description", "customer", "startDate", "targetDate")},
                         {"description": "", "customer": "", "startDate": "", "targetDate": ""})

    def test_authorization_precedes_update_validation_and_share_lookup(self):
        self.share("editor", "editor")
        self.share("viewer", "viewer")
        self.assertEqual(self.service.update("viewer", self.engagement_id, {}).status, "forbidden")
        self.assertEqual(self.service.update("viewer", self.engagement_id, {"status": "chartreuse"}).status, "forbidden")
        before = list(self.lookup_calls)
        self.assertEqual(self.service.share("editor", self.engagement_id, "owner", "not-a-role").status, "forbidden")
        self.assertEqual(self.service.share("editor", self.engagement_id, "missing", "viewer").status, "forbidden")
        self.assertEqual(self.lookup_calls, before)

    def test_core_length_limits_are_shared_by_all_callers(self):
        self.share("editor", "editor")
        cases = (
            ("owner", {"name": "n" * 121}, "name"),
            ("editor", {"description": "d" * 501}, "description"),
            ("editor", {"customer": "c" * 121}, "customer"),
            ("editor", {"statusNote": "s" * 301}, "statusNote"),
            ("editor", {"targetDate": "2026-01-011"}, "targetDate"),
            ("editor", {"startDate": "20260721"}, "startDate"),
            ("editor", {"targetDate": "20260721"}, "targetDate"),
        )
        for actor, values, field in cases:
            with self.subTest(field=field):
                outcome = self.service.update(actor, self.engagement_id, values)
                self.assertEqual(outcome.status, "invalid")
                self.assertIn(field, outcome.errors)

    def test_unknown_forbidden_and_final_owner_invariant(self):
        self.assertEqual(self.service.share("owner", self.engagement_id, "nobody", "viewer").status, "invalid")
        self.assertEqual(self.service.share("outsider", self.engagement_id, "editor", "viewer").status, "not_found")
        self.assertEqual(self.service.share("owner", self.engagement_id, "owner", "editor").status, "invalid")
        self.assertEqual(self.service.remove_member("owner", self.engagement_id, "owner").status, "invalid")
        self.assertEqual(self.share("other", "owner").status, "committed")
        self.assertEqual(self.service.remove_member("owner", self.engagement_id, "owner").status, "committed")

    def test_share_outcome_carries_target_user_for_committed_and_noop(self):
        committed = self.share("editor", "editor")
        self.assertEqual((committed.status, committed.target_user_id), ("committed", "editor"))
        noop = self.share("editor", "editor")
        self.assertEqual((noop.status, noop.target_user_id), ("noop", "editor"))

    def test_service_outcomes_are_stable_for_adapter_translation(self):
        # Adapters translate this one service result; this is not an adapter execution test.
        self.share("editor", "editor")
        self.share("viewer", "viewer")
        outcomes = [
            self.service.update("editor", self.engagement_id, {"customer": "Contoso"}),
            self.service.update("editor", self.engagement_id, {"customer": "Contoso"}),
        ]
        self.assertEqual([outcome.status for outcome in outcomes], ["committed", "noop"])
        denied = [self.service.update("viewer", self.engagement_id, {"customer": "No"}) for _adapter in ("rest", "copilot", "deepagents")]
        self.assertEqual([outcome.status for outcome in denied], ["forbidden", "forbidden", "forbidden"])
        replay = self.service.create("owner", {"name": "Northstar"})
        self.assertEqual((replay.status, replay.record["id"]), ("noop", self.engagement_id))


if __name__ == "__main__":
    unittest.main()
