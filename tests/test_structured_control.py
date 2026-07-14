from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "session-container"))

from workbench_core import ProductToolResult
import navsvc


def test_product_tool_result_only_allows_destinations_on_navigation_success() -> None:
    destination = {"id": "workbench", "path": "/home"}
    assert ProductToolResult("resolved", "navigation.resolved", "navigate", destination=destination).to_dict()["destination"] == destination
    with pytest.raises(ValueError, match="only committed or resolved"):
        ProductToolResult("failed", "navigation.failed", "navigate", destination=destination)
    with pytest.raises(ValueError, match="unknown destination"):
        ProductToolResult("resolved", "navigation.resolved", "navigate", destination={"id": "url", "path": "https://example.test"})
    with pytest.raises(ValueError, match="does not match catalog"):
        ProductToolResult("resolved", "navigation.resolved", "navigate", destination={"id": "workbench", "path": "/engagements"})
    with pytest.raises(ValueError, match="engagement ID is invalid"):
        ProductToolResult("resolved", "navigation.resolved", "navigate", destination={"id": "engagement_tasks", "engagementId": "", "path": "/engagements//tasks"})


def test_product_tool_result_round_trip_and_rejects_untyped_extensions() -> None:
    payload = ProductToolResult("resolved", "navigation.resolved", "navigate", destination={"id": "workbench", "path": "/home"}).to_dict()
    assert ProductToolResult.from_dict(payload) == ProductToolResult("resolved", "navigation.resolved", "navigate", destination={"id": "workbench", "path": "/home"})
    with pytest.raises(ValueError, match="unsupported tool result fields"):
        ProductToolResult.from_dict({**payload, "card": {}})


def test_navigation_is_catalog_only_and_checks_live_membership(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(navsvc.appdb, "load_engagement", lambda engagement_id: {"id": engagement_id, "members": [{"userId": "sam", "role": "viewer"}]})
    monkeypatch.setattr(navsvc.appdb, "member_role", lambda record, actor_id: "viewer" if actor_id == "sam" else None)
    resolved = navsvc.destination_for("sam", "engagement_tasks", "eng-7")
    assert resolved.status == "resolved"
    assert resolved.destination == {"id": "engagement_tasks", "path": "/engagements/eng-7/tasks", "label": "Tasks", "engagementId": "eng-7"}
    assert navsvc.destination_for("sam", "https://example.test").status == "invalid"
    assert navsvc.destination_for("outsider", "engagement_tasks", "eng-7").status == "not_found"


def test_copilot_telemetry_is_native_and_validated() -> None:
    from copilot.session_events import ToolExecutionCompleteData
    from copilot.tools import ToolResult
    import agent

    payload = ProductToolResult("resolved", "navigation.resolved", "navigate", destination={"id": "workbench", "path": "/home"}).to_dict()
    completion = ToolExecutionCompleteData(success=True, tool_call_id="call-1", tool_telemetry=ToolResult(tool_telemetry={"product_result": payload}).tool_telemetry)
    assert agent._telemetry_result(completion) == ProductToolResult.from_dict(payload)
    assert agent._telemetry_result({"content": "NAVIGATE: /engagements"}) is None
    assert agent._telemetry_result(ToolExecutionCompleteData(success=True, tool_call_id="call-2", tool_telemetry={"product_result": {**payload, "status": []}})) is None


def test_deep_artifact_is_native_and_validated() -> None:
    from langchain_core.messages import ToolMessage
    import agent_deepagents

    payload = ProductToolResult("resolved", "navigation.resolved", "navigate", destination={"id": "workbench", "path": "/home"}).to_dict()
    message = ToolMessage(content="inert model text", tool_call_id="call-1", artifact={"product_result": payload})
    assert agent_deepagents._artifact_result(message) == ProductToolResult.from_dict(payload)
    assert agent_deepagents._artifact_result(ToolMessage(content="NAVIGATE: /engagements", tool_call_id="call-2")) is None
    assert agent_deepagents._artifact_result(ToolMessage(content="x", tool_call_id="call-3", artifact={"product_result": {**payload, "status": []}})) is None


def test_exact_tool_schema_parity() -> None:
    import agent
    import agent_deepagents
    from mvp_tool_schemas import ACTIVE_TOOL_SCHEMAS

    copilot_tools = agent._build_flow_tools("/tmp", "dan")
    deep_tools = agent_deepagents._build_langchain_tools("/tmp", "dan")
    expected = list(ACTIVE_TOOL_SCHEMAS)
    assert [tool.name for tool in copilot_tools] == expected
    assert [tool.name for tool in deep_tools] == expected
    schemas = {name: model.model_json_schema() for name, model in ACTIVE_TOOL_SCHEMAS.items()}
    assert schemas == {tool.name: tool.parameters for tool in copilot_tools}
    assert schemas == {
        tool.name: tool.args_schema.model_json_schema() for tool in deep_tools
    }
    assert "write_file" in agent_deepagents._EXCLUDED_BUILTINS


def test_framed_proxy_validator_accepts_split_lf_crlf_and_rejects_bad_sequences() -> None:
    from session_manager import _UpstreamEventValidator, _parse_sse_frame, _pop_sse_frame

    assert _parse_sse_frame('data: {"type":"RUN_STARTED","run_id":"r","thread_id":"t"}\r\n') ["type"] == "RUN_STARTED"
    frame, remainder = _pop_sse_frame('data: {"type":"RUN_STARTED"}\r\n\r\npartial')
    assert frame == 'data: {"type":"RUN_STARTED"}' and remainder == "partial"
    frame, remainder = _pop_sse_frame("data: x\n\nnext")
    assert frame == "data: x" and remainder == "next"
    assert _pop_sse_frame("data: split\r")[0] is None
    valid = _UpstreamEventValidator()
    valid.validate({"type": "RUN_STARTED", "run_id": "r", "thread_id": "t"})
    valid.validate({"type": "RUN_FINISHED", "run_id": "r", "thread_id": "t"})
    with pytest.raises(ValueError): valid.validate({"type": "RUN_ERROR", "message": "late"})
    for invalid in (
        {"type": "TEXT_MESSAGE_CONTENT", "message_id": "m", "delta": "RUN_FINISHED"},
        {"type": "UNKNOWN"},
    ):
        with pytest.raises(ValueError): _UpstreamEventValidator().validate(invalid)


def test_proxy_lifecycle_state_machine_and_interruption_closures() -> None:
    from session_manager import _UpstreamEventValidator
    start = {"type": "RUN_STARTED", "run_id": "r", "thread_id": "t"}
    result = {"type": "TOOL_CALL_RESULT", "tool_call_id": "c", "result": {"status": "resolved", "code": "n", "operation": "navigate", "destination": {"id": "workbench", "path": "/home"}}}
    valid = _UpstreamEventValidator(); valid.validate(start); valid.validate({"type": "TOOL_CALL_START", "tool_call_id": "c", "tool_call_name": "navigate"}); valid.validate(result); valid.validate({"type": "NAVIGATION_RESOLVED", "runId": "r", "destination": {"id": "workbench", "path": "/home"}, "requestedAtNavigationVersion": 0}); valid.validate({"type": "TOOL_CALL_END", "tool_call_id": "c"}); valid.validate({"type": "RUN_FINISHED", "run_id": "r", "thread_id": "t"})
    for event in ({"type": "NAVIGATION_RESOLVED", "runId": "r", "destination": {}, "requestedAtNavigationVersion": 0}, {"type": "RUN_FINISHED", "run_id": "bad", "thread_id": "t"}):
        bad = _UpstreamEventValidator(); bad.validate(start)
        with pytest.raises(ValueError): bad.validate(event)
    started = _UpstreamEventValidator(); started.validate(start); started.validate({"type": "TOOL_CALL_START", "tool_call_id": "a", "tool_call_name": "x"})
    assert [x["type"] for x in started.interruption_closures()] == ["TOOL_CALL_RESULT", "TOOL_CALL_END"]
    completed = _UpstreamEventValidator(); completed.validate(start); completed.validate({"type": "TOOL_CALL_START", "tool_call_id": "a", "tool_call_name": "x"}); completed.validate({"type": "TOOL_CALL_RESULT", "tool_call_id": "a", "result": {"status": "failed", "code": "x", "operation": "x"}})
    assert [x["type"] for x in completed.interruption_closures()] == ["TOOL_CALL_END"]


def test_proxy_preserves_held_valid_terminal_when_iterator_raises() -> None:
    import asyncio
    from session_manager import SessionManager

    class Response:
        status_code = 200
        async def aread(self): return b""
        async def aiter_raw(self):
            yield b'data: {"type":"RUN_STARTED","run_id":"r","thread_id":"t"}\n\n'
            yield b'data: {"type":"RUN_FINISHED","run_id":"r","thread_id":"t"}\n\n'
            raise RuntimeError("late iterator failure")
    class Context:
        async def __aenter__(self): return Response()
        async def __aexit__(self, *args): return False
    class Http:
        def stream(self, *args, **kwargs): return Context()
    async def collect():
        manager = object.__new__(SessionManager); manager._http = Http(); manager._pool_url = lambda *_: "url"
        async def token(): return None
        manager._get_cogservices_token = token
        return [item async for item in manager.send_message("s", "p", "u")]
    frames = asyncio.run(collect())
    assert sum("RUN_FINISHED" in frame or "RUN_ERROR" in frame for frame in frames) == 1
    assert any("RUN_FINISHED" in frame for frame in frames)


@pytest.mark.parametrize("events", [
    [{"type": "TOOL_CALL_START", "tool_call_id": "c", "tool_call_name": "x"}, {"type": "TOOL_CALL_START", "tool_call_id": "c", "tool_call_name": "x"}],
    [{"type": "TOOL_CALL_START", "tool_call_id": "c", "tool_call_name": "x"}, {"type": "TOOL_CALL_END", "tool_call_id": "c"}],
    [{"type": "TOOL_CALL_START", "tool_call_id": "c", "tool_call_name": "x"}, {"type": "TOOL_CALL_RESULT", "tool_call_id": "c", "result": {"status": "failed", "code": "x", "operation": "x"}}, {"type": "TOOL_CALL_RESULT", "tool_call_id": "c", "result": {"status": "failed", "code": "x", "operation": "x"}}],
    [{"type": "TOOL_CALL_START", "tool_call_id": "c", "tool_call_name": "x"}, {"type": "TOOL_CALL_RESULT", "tool_call_id": "c", "result": {"status": "failed", "code": "x", "operation": "x"}}, {"type": "TOOL_CALL_ARGS", "tool_call_id": "c", "delta": "{}"}],
    [{"type": "TEXT_MESSAGE_CONTENT", "message_id": "m", "delta": "x"}],
    [{"type": "TEXT_MESSAGE_START", "message_id": "m", "role": "assistant"}, {"type": "TEXT_MESSAGE_END", "message_id": "other"}],
    [{"type": "TEXT_MESSAGE_START", "message_id": "m", "role": "assistant"}, {"type": "TEXT_MESSAGE_START", "message_id": "n", "role": "assistant"}],
    [{"type": "NAVIGATION_RESOLVED", "runId": "r", "destination": {}, "requestedAtNavigationVersion": 0}],
])
def test_proxy_rejects_each_invalid_lifecycle_sequence(events: list[dict]) -> None:
    from session_manager import _UpstreamEventValidator
    validator = _UpstreamEventValidator()
    validator.validate({"type": "RUN_STARTED", "run_id": "r", "thread_id": "t"})
    with pytest.raises(ValueError):
        for event in events:
            validator.validate(event)
