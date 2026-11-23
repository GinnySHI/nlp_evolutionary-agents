"""CLI integration tests using local sessions and a scripted model client."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evoagents import cli


class ScriptedClient:
    def __init__(self, actions):
        self.actions = list(actions)
        self.prompts = []
        self.closed = False
        self.stats = {"calls": 0}

    def complete(self, messages, *, json_mode=True):
        self.prompts.append(messages)
        self.stats["calls"] += 1
        try:
            context = json.loads(messages[-1]["content"])
        except (ValueError, TypeError):
            context = {}
        if isinstance(context, dict) and "evidence" in context and "agent" in context:
            return json.dumps({"lesson": "Review evidence before claiming completion."})
        assert self.actions, "CLI made an unexpected model request"
        action = self.actions.pop(0)
        return json.dumps(action) if isinstance(action, dict) else action

    def close(self):
        self.closed = True


@pytest.fixture
def local_cli(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key in ("HKGAI_API_KEY", "HKGAI_BASE_URL", "HKGAI_MODEL", "EVO_DATA_DIR", "EVO_SANDBOX", "EVO_MAX_STEPS", "EVO_MAX_OUTPUT_TOKENS", "EVO_REQUEST_TIMEOUT", "EVO_GITHUB_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / "settings.env"
    env.write_text("EVO_DATA_DIR=runtime\nHKGAI_API_KEY=\n", encoding="utf-8")

    def invoke(*args):
        return cli.main(["--env", str(env), *args])

    return invoke, tmp_path / "runtime"


def set_client(monkeypatch, actions):
    client = ScriptedClient(actions)
    monkeypatch.setattr(cli, "HKGAIClient", lambda settings: client)
    return client


def completion_actions():
    return [
        {"action": "delegate", "recipient": "dev", "task": "Confirm the answer", "success_criteria": "Peer checks the answer"},
        {"action": "complete", "summary": "The answer is 42.", "artifacts": [], "success": True},
        {"action": "review", "task_id": "subtask-1", "accepted": True, "reason": "Checked the stated answer."},
        {"action": "finish", "summary": "Verified answer: 42.", "success": True},
    ]


def test_help_is_english_and_documents_commands(capsys):
    with pytest.raises(SystemExit) as result:
        cli.main(["--help"])
    assert result.value.code == 0
    output = capsys.readouterr().out
    assert "Evolutionary multi-agent collaboration" in output
    assert "respond" in output and "evaluate" in output and "doctor" in output


def test_init_status_and_sessions_do_not_require_key_or_model(local_cli, monkeypatch, capsys):
    invoke, runtime = local_cli
    monkeypatch.setattr(cli, "HKGAIClient", lambda _: pytest.fail("Read-only/setup command created an API client"))
    assert invoke("init", "team", "--scenario", "software") == 0
    assert invoke("status", "team") == 0
    assert invoke("sessions") == 0
    output = capsys.readouterr().out
    assert "Created session: team" in output
    assert '"idle"' in output
    assert '"team"' in output
    state = json.loads((runtime / "sessions" / "team" / "state.json").read_text())
    assert len(state["agents"]) == 4
    assert "api_key" not in state


@pytest.mark.parametrize("name", ["../outside", "folder/name", "team name", "", "x" * 81])
def test_bad_session_names_are_rejected(local_cli, capsys, name):
    invoke, runtime = local_cli
    assert invoke("init", name) == 1
    assert "Session names must" in capsys.readouterr().err
    assert not (runtime / "sessions").exists()


def test_session_symlink_is_rejected(local_cli, tmp_path, capsys):
    invoke, runtime = local_cli
    (runtime / "sessions").mkdir(parents=True)
    (runtime / "sessions" / "linked").symlink_to(tmp_path)
    assert invoke("init", "linked") == 1
    assert "symlink" in capsys.readouterr().err


def test_run_question_and_respond_resume_persisted_session(local_cli, monkeypatch, capsys):
    invoke, runtime = local_cli
    assert invoke("init", "team") == 0
    first = set_client(monkeypatch, [{"action": "ask_human", "question": "Which audience?", "reason": "Audience is missing."}])
    assert invoke("run", "team", "--task", "Write a report") == 2
    assert first.closed
    pending = json.loads((runtime / "sessions" / "team" / "state.json").read_text())
    assert pending["status"] == "waiting_human"
    assert pending["pending"]["question"] == "Which audience?"
    second = set_client(monkeypatch, completion_actions())
    assert invoke("respond", "team", "Students and faculty") == 0
    final = json.loads((runtime / "sessions" / "team" / "state.json").read_text())
    assert final["status"] == "completed"
    assert final["metrics"]["peer_reviewed_completion"] is True
    assert "Students and faculty" in json.dumps(second.prompts)
    assert second.closed
    assert "Verified answer: 42." in capsys.readouterr().out


def test_pending_approval_is_not_auto_approved_and_can_be_denied(local_cli, monkeypatch):
    invoke, runtime = local_cli
    assert invoke("init", "team") == 0
    set_client(monkeypatch, [{"action": "tool", "name": "run_python", "arguments": {"path": "job.py"}}])
    assert invoke("run", "team", "--task", "Run a script") == 2
    state_file = runtime / "sessions" / "team" / "state.json"
    state = json.loads(state_file.read_text())
    assert state["pending"]["type"] == "tool_approval"
    set_client(monkeypatch, [{"action": "finish", "summary": "User declined code execution.", "success": False}])
    assert invoke("respond", "team", "Do not run", "--deny") == 2
    final = json.loads(state_file.read_text())
    assert final["status"] == "failed"
    assert final["pending"] is None


def test_invalid_document_format_never_calls_model(local_cli, monkeypatch, tmp_path, capsys):
    invoke, _ = local_cli
    assert invoke("init", "team") == 0
    document = tmp_path / "requirements.pdf"
    document.write_text("Not supported")
    client = set_client(monkeypatch, [])
    assert invoke("run", "team", "--task-file", str(document)) == 1
    assert ".md or .txt" in capsys.readouterr().err
    assert client.prompts == []
    assert client.closed


def test_step_budget_requires_explicit_extension(local_cli, monkeypatch):
    invoke, runtime = local_cli
    assert invoke("init", "team") == 0
    set_client(monkeypatch, completion_actions()[:2])
    assert invoke("run", "team", "--task", "A bounded task", "--steps", "2") == 2
    state_file = runtime / "sessions" / "team" / "state.json"
    assert json.loads(state_file.read_text())["status"] == "budget_exhausted"
    set_client(monkeypatch, completion_actions()[2:])
    assert invoke("run", "team", "--steps", "2") == 0
    assert json.loads(state_file.read_text())["status"] == "completed"


def test_noninteractive_private_message_does_not_enter_group_state(local_cli, monkeypatch):
    invoke, runtime = local_cli
    assert invoke("init", "team") == 0
    set_client(monkeypatch, ["Acknowledged privately."])
    assert invoke("dm", "team", "dev", "Private preference: cobalt") == 0
    root = runtime / "sessions" / "team"
    assert "cobalt" not in (root / "state.json").read_text()
    assert "cobalt" not in (root / "events.jsonl").read_text()
    assert "cobalt" in (root / "private" / "dev.jsonl").read_text()
