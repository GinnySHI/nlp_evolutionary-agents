import json
import os
from pathlib import Path

import pytest

import evoagents.engine as engine_module
from evoagents.engine import ActionError, AgentSpec, SessionEngine
from evoagents.memory import atomic_json


class FakeClient:
    def __init__(self, actions):
        self.actions = list(actions)
        self.prompts = []

    def complete(self, messages, *, json_mode=True):
        self.prompts.append(messages)
        if "Reflect on your collaboration" in messages[0]["content"]:
            return json.dumps({"lesson": "Check output before marking it complete."})
        if not self.actions:
            raise RuntimeError("No scripted actions remain")
        value = self.actions.pop(0)
        return json.dumps(value) if isinstance(value, dict) else value


class FakeTools:
    def __init__(self, root, *, agent_ids, **kwargs):
        self.root = root
        self.calls = []
        for agent_id in agent_ids:
            self.workspace(agent_id).mkdir(parents=True, exist_ok=True)

    def workspace(self, agent_id):
        return self.root / agent_id / "workspace"

    def specifications(self):
        return [
            {"name": "write_file", "parameters": {"type": "object", "required": ["path", "content"],
             "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "additionalProperties": False}},
            {"name": "run_python", "parameters": {"type": "object", "required": ["path"],
             "properties": {"path": {"type": "string"}}, "additionalProperties": False}},
            {"name": "read_file", "parameters": {"type": "object", "required": ["path"],
             "properties": {"path": {"type": "string"}}, "additionalProperties": False}},
        ]

    def requires_approval(self, name):
        return name == "run_python"

    def execute(self, agent_id, name, arguments, *, approved=False):
        self.calls.append((agent_id, name, arguments, approved))
        if name == "write_file":
            (self.workspace(agent_id) / arguments["path"]).write_text(arguments["content"])
        if name == "run_python" and not approved:
            raise AssertionError("Unapproved execution")
        if name == "read_file":
            return {"ok": True, "content": (self.workspace(agent_id) / arguments["path"]).read_text()}
        return {"ok": True, "result": "done"}


@pytest.fixture
def make_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_module, "ToolRunner", FakeTools)

    def factory(actions, max_steps=40):
        client = FakeClient(actions)
        engine = SessionEngine.create(tmp_path / "session", [AgentSpec("lead", "Lead", "Coordinate"),
                    AgentSpec("dev", "Developer", "Implement")], client, max_steps=max_steps)
        return engine, client
    return factory


def delegate(**extra):
    return {"action": "delegate", "recipient": "dev", "task": "Write a short report", "success_criteria": "Contains a verified result", **extra}


def complete(success=True):
    return {"action": "complete", "summary": "Report is ready", "artifacts": [], "success": success}


def review(task_id="subtask-1", accepted=True):
    return {"action": "review", "task_id": task_id, "accepted": accepted, "reason": "Checked the output"}


def finish(success=True):
    return {"action": "finish", "summary": "Work complete", "success": success}


def test_cooperation_review_and_memory_survive_new_task(make_engine):
    engine, client = make_engine([delegate(), complete(), review(), finish()])
    engine.start_task("First task")
    events = []
    engine.on_event = events.append
    status = engine.run()
    assert status["status"] == "completed"
    assert status["metrics"]["agent_turns"] == 4
    assert status["metrics"]["subtasks_accepted"] == 1
    assert status["metrics"]["peer_reviewed_completion"] is True
    assert engine.memories["dev"].stats()["successes"] == 1
    assert events
    reloaded = SessionEngine.load(engine.root, client)
    reloaded.start_task("Second task")
    assert reloaded.state["history"][0]["status"] == "completed"
    assert reloaded.state["metrics"]["agent_turns"] == 0
    assert reloaded.memories["dev"].stats()["successes"] == 1
    assert "First task" in json.dumps(reloaded._prompt("dev"))


def test_wait_resume_exact_approval_and_no_replay(make_engine):
    engine, client = make_engine([delegate(), {"action": "tool", "name": "run_python", "arguments": {"path": "test.py"}},
                                  complete(), review(), finish()])
    engine.start_task("Task")
    assert engine.run()["status"] == "waiting_human"
    assert engine.tools.calls == []
    pending_id = engine.state["pending"]["id"]
    reloaded = SessionEngine.load(engine.root, client)
    assert reloaded.state["pending"]["id"] == pending_id
    with pytest.raises(ValueError):
        reloaded.respond("yes")
    status = reloaded.respond("Run the displayed command", approved=True)
    assert status["status"] == "completed"
    assert len(reloaded.tools.calls) == 1
    assert reloaded.tools.calls[0][3] is True
    with pytest.raises(ValueError):
        reloaded.respond("again", approved=True)


def test_changed_file_invalidates_approval(make_engine):
    engine, client = make_engine([{"action": "tool", "name": "run_python", "arguments": {"path": "test.py"}}])
    engine.start_task("Task")
    engine.run()
    (engine.tools.workspace("lead") / "test.py").write_text("print('changed')")
    with pytest.raises(ValueError):
        engine.respond("Approve", approved=True)
    assert engine.tools.calls == []
    assert engine.state["status"] == "waiting_human"


def test_denial_does_not_execute_tool(make_engine):
    engine, client = make_engine([{"action": "tool", "name": "run_python", "arguments": {"path": "test.py"}}, finish(False)])
    engine.start_task("Task")
    engine.run()
    result = engine.respond("Do not run it", approved=False)
    assert result["status"] == "failed"
    assert engine.tools.calls == []


def test_human_question_preserves_execution_and_wait_is_not_active(make_engine):
    engine, client = make_engine([{"action": "ask_human", "question": "Which date?", "reason": "Missing date"},
                                  delegate(), complete(), review(), finish()])
    engine.start_task("Task")
    assert engine.run()["pending"]["type"] == "question"
    result = engine.respond("2026-11-15")
    assert result["status"] == "completed"
    assert result["metrics"]["elapsed_seconds"] >= result["metrics"]["active_seconds"] - 0.1
    assert "2026-11-15" in json.dumps(client.prompts)


def test_private_conversation_never_enters_shared_context(make_engine):
    secret_message = "Private scheduling preference: orange comet"
    engine, client = make_engine(["I will keep this in our private chat.", delegate(), complete(), review(), finish()])
    engine.direct_message("dev", secret_message)
    engine.start_task("Task")
    engine.run()
    shared = (engine.root / "state.json").read_text() + (engine.root / "events.jsonl").read_text()
    assert "orange comet" not in shared
    assert all("orange comet" not in json.dumps(prompt) for prompt in client.prompts[1:])
    assert "orange comet" in (engine.root / "private" / "dev.jsonl").read_text()
    assert not (engine.root / "private" / "lead.jsonl").exists()


def test_self_review_and_unverified_finish_cannot_succeed(make_engine):
    engine, _ = make_engine([delegate(), complete(), {"action": "message", "recipient": "dev", "content": "Review yourself"},
                             review(), review(), review()])
    engine.start_task("Task")
    result = engine.run()
    assert result["status"] == "failed"
    assert result["metrics"]["invalid_actions"] == 3
    assert result["metrics"]["peer_reviewed_completion"] is False


def test_budget_can_be_explicitly_extended(make_engine):
    engine, _ = make_engine([delegate(), complete(), review(), finish()], max_steps=2)
    engine.start_task("Task")
    assert engine.run()["status"] == "budget_exhausted"
    assert engine.run()["metrics"]["agent_turns"] == 2
    assert engine.run(max_steps=2)["status"] == "completed"


def test_failed_attempt_can_be_replaced_without_erasing_evidence(make_engine):
    engine, _ = make_engine([delegate(), complete(), review(accepted=False), delegate(retry_of="subtask-1"),
                             complete(), review("subtask-2"), finish()])
    engine.start_task("Task")
    result = engine.run()
    assert result["status"] == "completed"
    assert result["tasks"][0]["status"] == "superseded"
    assert result["tasks"][0]["review"]["accepted"] is False
    assert result["metrics"]["subtask_completion_rate"] == 0.5
    assert engine.memories["dev"].stats()["failures"] == 1


def test_malformed_actions_are_bounded_and_ui_error_is_nonfatal(make_engine):
    engine, _ = make_engine(["not JSON", "[]", '{"action":"unknown"}'])
    engine.on_event = lambda event: (_ for _ in ()).throw(RuntimeError("UI unavailable"))
    engine.start_task("Task")
    result = engine.run()
    assert result["status"] == "failed"
    assert result["metrics"]["agent_turns"] == 3


def test_interrupted_tool_requires_reconciliation_without_replay(make_engine):
    engine, client = make_engine([finish(False)])
    engine.start_task("Task")
    engine.state["inflight"] = {"agent_id": "lead", "name": "run_python", "arguments": {"path": "a.py"}}
    atomic_json(engine.root / "state.json", engine.state)
    reloaded = SessionEngine.load(engine.root, client)
    assert reloaded.state["pending"]["recovery"] is True
    assert reloaded.tools.calls == []
    result = reloaded.respond("The operation did not finish; end this task.")
    assert result["status"] == "failed"
    assert reloaded.tools.calls == []


def test_nonexistent_artifacts_rejected_and_real_artifacts_hashed(make_engine):
    engine, _ = make_engine([delegate(), {"action": "tool", "name": "write_file", "arguments": {"path": "report.md", "content": "Evidence"}},
                            {"action": "complete", "summary": "Done", "artifacts": ["missing.md"], "success": True},
                            {"action": "complete", "summary": "Done", "artifacts": ["report.md"], "success": True}, review(), finish()])
    engine.start_task("Task")
    result = engine.run()
    assert result["status"] == "completed"
    assert result["metrics"]["invalid_actions"] == 1
    artifact = result["tasks"][0]["artifacts"][0]
    assert artifact["path"] == "report.md"
    assert len(artifact["sha256"]) == 64


def test_invalid_tool_argument_never_executes(make_engine):
    bad = {"action": "tool", "name": "write_file", "arguments": {"path": 42, "content": "test"}}
    engine, _ = make_engine([bad, bad, bad])
    engine.start_task("Task")
    assert engine.run()["status"] == "failed"
    assert engine.tools.calls == []


def test_other_agents_cannot_see_private_tool_output(make_engine):
    marker = "CONFIDENTIAL-ORANGE-COMET"
    engine, client = make_engine([delegate(), {"action": "tool", "name": "read_file", "arguments": {"path": "notes.txt"}},
                                  complete(), review(), finish()])
    (engine.tools.workspace("dev") / "notes.txt").write_text(marker)
    engine.start_task("Task")
    assert engine.run()["status"] == "completed"
    for prompt in client.prompts:
        if "You are Lead (lead)" in prompt[0]["content"]:
            assert marker not in json.dumps(prompt)
    assert any(marker in json.dumps(prompt) for prompt in client.prompts if "You are Developer (dev)" in prompt[0]["content"])


def test_changed_submission_cannot_pass_review(make_engine):
    engine, client = make_engine([delegate(), {"action": "complete", "summary": "Done", "artifacts": ["report.md"], "success": True},
                                  {"action": "ask_human", "question": "Ready to review?", "reason": "Confirm scope"},
                                  review(), review(), review()])
    report = engine.tools.workspace("dev") / "report.md"
    report.write_text("Original evidence")
    engine.start_task("Task")
    assert engine.run()["status"] == "waiting_human"
    report.write_text("Different evidence")
    result = engine.respond("Review it")
    assert result["status"] == "failed"
    assert result["metrics"]["subtasks_accepted"] == 0


def test_unhashable_action_is_recoverable(make_engine):
    engine, _ = make_engine([{"action": []}, {"action": {}}, {"action": None}])
    engine.start_task("Task")
    result = engine.run()
    assert result["metrics"]["invalid_actions"] == 3


def test_nested_protocol_is_rejected_with_explicit_correction_and_safe_audit(make_engine):
    secret = "sk-" + "X" * 24
    nested = {"delegate": {"recipient": "dev", "task": secret, "success_criteria": "done"}}
    engine, client = make_engine([nested, delegate(), complete(), review(), finish()])
    engine.start_task("Task")
    result = engine.run()
    assert result["status"] == "completed"
    assert result["metrics"]["invalid_actions"] == 1
    events_text = (engine.root / "events.jsonl").read_text()
    assert secret not in events_text
    audits = [json.loads(line) for line in events_text.splitlines() if json.loads(line)["kind"] == "invalid_response"]
    assert len(audits) == 1
    assert "REDACTED" in audits[0]["response"]
    corrective_context = json.loads(client.prompts[1][1]["content"].split("\n", 1)[1])
    assert any('top-level "action"' in message["content"] for message in corrective_context["messages"])
    assert secret not in json.dumps(client.prompts)
    assert 'Correct: {"action":"delegate"' in client.prompts[0][0]["content"]


def test_failed_task_timing_includes_failure_bookkeeping(make_engine):
    engine, _ = make_engine(["bad", "bad", "bad"])
    engine.start_task("Task")
    result = engine.run()
    assert result["status"] == "failed"
    assert result["metrics"]["elapsed_seconds"] >= result["metrics"]["active_seconds"]


def test_long_message_audit_is_complete_but_context_explicitly_truncated(make_engine):
    engine, _ = make_engine([])
    sentinel = "END-OF-COMPLETE-TOOL-RESULT"
    secret = "sk-" + "Q" * 24
    content = "Evidence " * 2500 + secret + " " + sentinel
    engine._message("tool", content, recipient="dev", kind="tool_result")
    context_message = engine.state["messages"][-1]
    assert context_message["context_truncated"] is True
    assert len(context_message["content"]) <= 16_000
    assert "Context excerpt truncated" in context_message["content"]
    assert "full redacted audit" in context_message["content"]
    assert sentinel not in context_message["content"]
    events_text = (engine.root / "events.jsonl").read_text()
    audit = [json.loads(line) for line in events_text.splitlines() if json.loads(line)["kind"] == "message"][-1]
    assert audit["content"].endswith(sentinel)
    assert len(audit["content"]) > 16_000
    assert audit["context_excerpt_truncated"] is True
    assert secret not in events_text


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO support requires Unix")
def test_fingerprint_and_artifact_reject_fifo_without_opening_it(make_engine, monkeypatch):
    engine, _ = make_engine([])
    fifo = engine.tools.workspace("lead") / "pipe.txt"
    os.mkfifo(fifo)
    original_open = os.open

    def forbid_fifo_open(path, *args, **kwargs):
        if Path(path) == fifo:
            raise AssertionError("FIFO must be rejected before open")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", forbid_fifo_open)
    with pytest.raises(ActionError, match="special file"):
        engine._workspace_fingerprint("lead")
    with pytest.raises(ActionError, match="special files"):
        engine._artifact("lead", "pipe.txt")


def test_fingerprint_and_artifact_reject_hardlinks(make_engine):
    engine, _ = make_engine([])
    workspace = engine.tools.workspace("lead")
    original = workspace / "original.md"
    original.write_text("Evidence")
    os.link(original, workspace / "linked.md")
    with pytest.raises(ActionError, match="hardlink"):
        engine._workspace_fingerprint("lead")
    with pytest.raises(ActionError, match="hardlink"):
        engine._artifact("lead", "linked.md")


def test_chmod_changes_fingerprint_and_invalidates_approval(make_engine):
    engine, _ = make_engine([{"action": "tool", "name": "run_python", "arguments": {"path": "task.py"}}])
    script = engine.tools.workspace("lead") / "task.py"
    script.write_text("print('ok')")
    script.chmod(0o600)
    before = engine._workspace_fingerprint("lead")
    engine.start_task("Task")
    assert engine.run()["status"] == "waiting_human"
    script.chmod(0o700)
    assert engine._workspace_fingerprint("lead") != before
    with pytest.raises(ValueError, match="stale"):
        engine.respond("Approve", approved=True)
    assert engine.state["status"] == "waiting_human"
    assert engine.tools.calls == []


def test_unreadable_file_is_recoverable_action_error(make_engine, monkeypatch):
    engine, _ = make_engine([
        {"action": "tool", "name": "run_python", "arguments": {"path": "task.py"}},
        {"action": "ask_human", "question": "Please restore file readability", "reason": "Cannot verify the workspace"},
    ])
    protected = engine.tools.workspace("lead") / "task.py"
    protected.write_text("print('ok')")
    original_open = os.open

    def deny_protected(path, *args, **kwargs):
        if Path(path) == protected:
            raise PermissionError("Injected unreadable file")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", deny_protected)
    with pytest.raises(ActionError, match="PermissionError"):
        engine._artifact("lead", "task.py")
    engine.start_task("Task")
    result = engine.run()
    assert result["status"] == "waiting_human"
    assert result["pending"]["type"] == "question"
    assert result["metrics"]["invalid_actions"] == 1
    assert result["metrics"]["fatal_errors"] == 0


def test_unreadable_file_during_approval_preserves_pending_request(make_engine, monkeypatch):
    engine, _ = make_engine([{"action": "tool", "name": "run_python", "arguments": {"path": "task.py"}}])
    protected = engine.tools.workspace("lead") / "task.py"
    protected.write_text("print('ok')")
    engine.start_task("Task")
    assert engine.run()["status"] == "waiting_human"
    pending_id = engine.state["pending"]["id"]
    original_open = os.open

    def deny_protected(path, *args, **kwargs):
        if Path(path) == protected:
            raise PermissionError("Injected unreadable file")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", deny_protected)
    with pytest.raises(ValueError, match="PermissionError"):
        engine.respond("Approve", approved=True)
    assert engine.state["status"] == "waiting_human"
    assert engine.state["pending"]["id"] == pending_id
    assert engine.state["metrics"]["fatal_errors"] == 0
    assert engine.tools.calls == []
