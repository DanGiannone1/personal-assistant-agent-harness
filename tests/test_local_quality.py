from __future__ import annotations

import artifact_store


def test_artifact_blob_default_matches_the_provisioned_engagement_container(monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_ACCOUNT", "exampleaccount")
    monkeypatch.delenv("ARTIFACTS_CONTAINER", raising=False)
    assert artifact_store.DEFAULT_CONTAINER == "engagement-artifacts"
    assert artifact_store.describe() == "azure-blob:exampleaccount/engagement-artifacts"
