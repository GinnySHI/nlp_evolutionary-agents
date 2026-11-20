"""Single-writer orchestration tests; do not require Unix file locking."""

import json
from contextlib import nullcontext

import pytest

from evoagents.engine import AgentSpec, SessionEngine


class ScriptedClient:
    def __init__(self, actions=()):
        self.actions = iter(actions)

    def complete(self, messages, *, json_mode=True):
        return json.dumps(next(self.actions))


def read(path="missing.md"):
    return {"action": "tool", "name": "read_file", "arguments": {"path": path}}


@pytest.fixture
def engine(tmp_path, monkeypatch):
    # Locking is tested separately on supported hosts. These deterministic tests
    # use one writer and exercise the real run loop, persistence and HITL flow.
    monkeypatch.setattr(SessionEngine, "_locked", lambda self: nullcontext())
    team = SessionEngine.create(tmp_path / "session", [
        AgentSpec("lead", "Lead", "Coordinate"), AgentSpec("dev", "Dev", "Implement"),
    ], ScriptedClient(), max_steps=20)
    team.start_task("Read the requested file")
    monkeypatch.setattr(team.tools, "execute", lambda *args, **kwargs: {"ok": False, "error": "File missing"})
    return team


def test_three_identical_failures_pause_and_human_can_resume(engine):
    engine.client = ScriptedClient([read(), read(), read()])
    result = engine.run()
    assert result["status"] == "waiting_human"
    assert result["pending"]["loop_guard"] is True
    assert result["pending"]["type"] == "question"
    assert result["metrics"]["tool_calls"] == 3
    assert result["metrics"]["fatal_errors"] == 0
    assert any(message["kind"] == "loop_warning" for message in engine.state["messages"])
    # Resuming grants no approval and starts a fresh failure streak.
    engine.client = ScriptedClient([read(), {"action": "ask_human", "question": "Which file?", "reason": "Need path"}])
    engine.respond("Try inspecting the directory first.")
    assert engine.state["pending"].get("loop_guard") is None
    assert engine.state["metrics"]["tool_calls"] == 4


def test_failure_streak_survives_session_reload(engine, monkeypatch):
    for _ in range(2):
        engine._apply("lead", read())
    restored = SessionEngine(engine.root, json.loads((engine.root / "state.json").read_text()), ScriptedClient([read()]))
    monkeypatch.setattr(restored.tools, "execute", lambda *args, **kwargs: {"ok": False, "error": "File missing"})
    assert restored.run()["pending"]["loop_guard"] is True


def test_different_arguments_errors_and_agents_do_not_share_streak(engine, monkeypatch):
    engine._apply("lead", read())
    engine._apply("dev", read())
    engine._apply("lead", read())
    assert engine.state["status"] == "running"
    engine._apply("lead", read("another.md"))
    assert engine.state["tool_failure_streaks"]["lead"]["count"] == 1
    monkeypatch.setattr(engine.tools, "execute", lambda *args, **kwargs: {"ok": False, "error": "Access denied"})
    engine._apply("lead", read("another.md"))
    assert engine.state["tool_failure_streaks"]["lead"]["count"] == 1


def test_success_and_strategy_change_reset_streak(engine, monkeypatch):
    for _ in range(2):
        engine._apply("lead", read())
    monkeypatch.setattr(engine.tools, "execute", lambda *args, **kwargs: {"ok": True, "content": "found"})
    engine._apply("lead", read())
    assert "lead" not in engine.state["tool_failure_streaks"]
    monkeypatch.setattr(engine.tools, "execute", lambda *args, **kwargs: {"ok": False, "error": "File missing"})
    engine._apply("lead", read())
    engine._apply("lead", {"action": "message", "recipient": "group", "content": "Please provide the file."})
    assert "lead" not in engine.state["tool_failure_streaks"]


def test_new_task_and_old_session_without_streak_field_are_supported(engine):
    engine.state.pop("tool_failure_streaks")
    engine._apply("lead", read())
    assert engine.state["tool_failure_streaks"]["lead"]["count"] == 1
    engine.state["status"] = "failed"
    engine.start_task("A new unrelated task")
    assert engine.state["tool_failure_streaks"] == {}


def test_signature_ignores_argument_key_order(engine):
    first = {"path": "a.md", "content": "text"}
    reordered = {"content": "text", "path": "a.md"}
    for arguments in (first, reordered, first):
        engine._apply("lead", {"action": "tool", "name": "write_file", "arguments": arguments})
    assert engine.state["pending"]["loop_guard"] is True


def test_loop_recovery_does_not_grant_critical_tool_approval(engine, monkeypatch):
    calls = []

    def execute(*args, **kwargs):
        calls.append(kwargs["approved"])
        return {"ok": False, "error": "Script failed"}

    monkeypatch.setattr(engine.tools, "execute", execute)
    monkeypatch.setattr(engine, "_run", lambda: engine.status())
    action = {"action": "tool", "name": "run_python", "arguments": {"path": "main.py"}}
    for _ in range(3):
        engine._apply("lead", action)
        assert engine.state["pending"]["type"] == "tool_approval"
        engine.respond("", approved=True)
    assert engine.state["pending"]["loop_guard"] is True
    assert calls == [True, True, True]
    engine.respond("Try a revised script.")
    assert "lead" not in engine.state["tool_failure_streaks"]
    engine._apply("lead", action)
    assert engine.state["pending"]["type"] == "tool_approval"
    assert len(calls) == 3
