"""Deterministic evaluation checks; no network or paid model requests."""

import json

import pytest

from evoagents.engine import AgentSpec, SessionEngine
from evoagents.evaluation import check_artifacts, evaluate
from evoagents.scenarios import scenario
from evoagents.tools import ToolRunner


class ScriptedClient:
    def __init__(self, actions=()):
        self.actions = list(actions)
        self.prompts = []

    def complete(self, messages, *, json_mode=True):
        self.prompts.append(messages)
        if "Reflect on your collaboration" in messages[0]["content"]:
            return json.dumps({"lesson": "Read actual output before accepting it."})
        if not self.actions:
            raise AssertionError("Evaluation requested an unexpected model call")
        return json.dumps(self.actions.pop(0))


def successful_task(path="result.md", content="verified"):
    return [
        {"action": "delegate", "recipient": "writer", "task": f"Write {path}", "success_criteria": content},
        {"action": "tool", "name": "write_file", "arguments": {"path": path, "content": content}},
        {"action": "complete", "summary": "File produced", "artifacts": [path], "success": True},
        {"action": "review", "task_id": "subtask-1", "accepted": True, "reason": "Accepted by peer"},
        {"action": "finish", "summary": "Delivered", "success": True},
    ]


def check(path="result.md", text="verified", **kwargs):
    return {"type": "text_equals", "agent": "writer", "path": path, "text": text, **kwargs}


def run_dataset(tmp_path, cases, client):
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps({"cases": cases}), encoding="utf-8")
    return evaluate(dataset, tmp_path / "evaluation", client, max_steps=30)


def test_independent_checks_use_actual_file_content_and_reject_unknown_targets(tmp_path):
    engine = SessionEngine.create(tmp_path / "session", [AgentSpec(**a) for a in scenario("smoke")["agents"]], ScriptedClient())
    assert engine.tools.execute("writer", "write_file", {"path": "evidence.md", "content": "actual evidence\n"})["ok"]
    outcomes = check_artifacts(engine, [
        check("evidence.md", "actual evidence"),
        check("evidence.md", "fabricated evidence"),
        {"type": "text_contains", "agent": "writer", "path": "evidence.md", "text": "evidence"},
        {"type": "file_exists", "agent": "writer", "path": "evidence.md"},
        {"type": "file_exists", "agent": "writer", "path": "missing.md"},
        {"type": "file_exists", "agent": "nonexistent", "path": "evidence.md"},
        {"type": "file_exists", "agent": "writer", "path": "../evidence.md"},
        {"type": "unknown_check", "agent": "writer", "path": "evidence.md"},
    ])
    assert [row["passed"] for row in outcomes] == [True, False, True, True, False, False, False, False]
    assert all("error" in row for row in outcomes[4:])


def test_mixed_cases_distinguish_peer_completion_from_independent_truth(tmp_path):
    cases = [
        {"id": "correct", "task": "Produce verified evidence", "checks": [check()]},
        {"id": "incorrect", "task": "Produce verified evidence", "checks": [check()]},
        {"id": "manual", "task": "A human must grade this", "checks": []},
    ]
    client = ScriptedClient(successful_task() + successful_task(content="wrong") + successful_task())
    result = run_dataset(tmp_path, cases, client)
    assert [row["status"] for row in result["cases"]] == ["completed"] * 3
    assert [row["verified_success"] for row in result["cases"]] == [True, False, False]
    assert result["summary"]["verified_task_completion_rate"] == pytest.approx(1 / 3)
    assert result["summary"]["peer_reviewed_subtask_completion_rate"] == 1
    assert result["summary"]["manual_review_cases"] == 1
    persisted = json.loads((tmp_path / "evaluation" / "results.json").read_text())
    assert persisted == result
    assert (tmp_path / "evaluation" / "report.md").is_file()


def test_same_session_two_tasks_keep_memory_history_and_old_artifacts(tmp_path):
    client = ScriptedClient(successful_task("first.md", "first evidence") + successful_task("second.md", "second evidence"))
    cases = [
        {"id": "first", "session": "same-team", "task": "First task", "checks": [check("first.md", "first evidence")]},
        {"id": "second", "session": "same-team", "task": "Build on the first task", "checks": [
            check("first.md", "first evidence"), check("second.md", "second evidence")
        ]},
    ]
    result = run_dataset(tmp_path, cases, client)
    assert result["summary"]["verified_successes"] == 2
    first, second = result["cases"]
    assert first["memory_after"] == second["memory_before"]
    assert second["memory_after"]["writer"]["successes"] > second["memory_before"]["writer"]["successes"]
    assert second["metrics"]["agent_turns"] == 5
    session = tmp_path / "evaluation" / "sessions" / "same-team"
    state = json.loads((session / "state.json").read_text())
    assert len(state["history"]) == 1
    assert state["history"][0]["task"] == "First task"
    assert (session / "agents" / "writer" / "workspace" / "first.md").read_text() == "first evidence"
    assert len(list((session / "runs").glob("*.json"))) == 1


def test_batch_never_automatically_approves_critical_operation(tmp_path, monkeypatch):
    calls = []
    original = ToolRunner.execute

    def spy(self, agent_id, name, arguments, *, approved=False):
        calls.append((name, approved))
        return original(self, agent_id, name, arguments, approved=approved)

    monkeypatch.setattr(ToolRunner, "execute", spy)
    client = ScriptedClient([{"action": "tool", "name": "run_python", "arguments": {"path": "task.py"}}])
    result = run_dataset(tmp_path, [
        {"id": "requires-approval", "session": "same-team", "task": "Execute code", "human_responses": ["yes"], "checks": [check()]},
        {"id": "blocked", "session": "same-team", "task": "Continue after prior task", "checks": [check()]},
    ], client)
    assert result["cases"][0]["status"] == "waiting_human"
    assert result["cases"][0]["pending"]["type"] == "tool_approval"
    assert result["cases"][1]["status"] == "blocked_by_previous_case"
    assert result["summary"]["verified_successes"] == 0
    assert result["summary"]["human_pending_cases"] == 1
    assert not any(name == "run_python" or approved for name, approved in calls)


def test_clarification_response_is_used_without_treating_it_as_approval(tmp_path):
    client = ScriptedClient([{"action": "ask_human", "question": "What should the file say?", "reason": "Missing requirement"},
                             *successful_task()])
    result = run_dataset(tmp_path, [{"id": "clarification", "task": "Write a file", "human_responses": ["verified"], "checks": [check()]}], client)
    assert result["summary"]["verified_successes"] == 1
    state = json.loads((tmp_path / "evaluation" / "sessions" / "clarification" / "state.json").read_text())
    assert any(message["kind"] == "clarification" and message["content"] == "verified" for message in state["messages"])


@pytest.mark.parametrize("cases", [
    [{"id": "../escape", "task": "A task"}],
    [{"id": "same", "task": "One"}, {"id": "same", "task": "Two"}],
    [{"id": "a", "task": "A task", "scenario": "nonexistent"}],
    [{"id": "a", "task": "A task", "session": "t", "scenario": "smoke"},
     {"id": "b", "task": "Another task", "session": "t", "scenario": "software"}],
    [{"id": "a", "task": ""}],
    [{"id": "a", "task": "Task", "checks": {}}],
])
def test_bad_case_identifiers_and_schema_rejected_before_model_calls(tmp_path, cases):
    client = ScriptedClient()
    with pytest.raises(ValueError):
        run_dataset(tmp_path, cases, client)
    assert client.prompts == []
    assert not (tmp_path / "evaluation").exists()


@pytest.mark.parametrize("bad_check", [None, "not an object", {"type": "text_contains", "agent": "writer", "path": "result.md", "text": 7}])
def test_invalid_check_schema_is_rejected_before_model_calls(tmp_path, bad_check):
    client = ScriptedClient(successful_task())
    with pytest.raises(ValueError):
        run_dataset(tmp_path, [{"id": "a", "task": "Write evidence", "checks": [bad_check]}], client)
    assert client.prompts == []
    assert not (tmp_path / "evaluation").exists()


def test_dataset_root_must_be_an_object(tmp_path):
    dataset = tmp_path / "dataset.json"
    dataset.write_text("[]")
    client = ScriptedClient()
    with pytest.raises(ValueError):
        evaluate(dataset, tmp_path / "evaluation", client)
    assert client.prompts == []
