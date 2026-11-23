"""A billing stop must pause for a human, not destroy accepted work.

Observed twice in the course run: DeepSeek returned HTTP 402 mid-task and the
engine marked the task failed, discarding two peer-accepted subtasks that had
already been paid for. 402 is operator-fixable, so it belongs on the pause
path with 429/5xx -- but unlike those it is never retried, because a balance
does not refill on its own.
"""
from __future__ import annotations

import httpx
import pytest

from evoagents.config import Settings
from evoagents.engine import AgentSpec, SessionEngine
from evoagents.provider import HKGAIClient, ProviderError, ProviderUnavailable


def _settings(**over) -> Settings:
    base = {"api_key": "sk-test-key-value", "base_url": "https://api.deepseek.com",
            "model": "deepseek-flash", "provider": "deepseek"}
    return Settings(**{**base, **over})


def _insufficient_balance(request: httpx.Request) -> httpx.Response:
    return httpx.Response(402, json={"error": {"message": "Insufficient Balance",
                                               "type": "insufficient_balance_error",
                                               "code": "invalid_request_error"}})


def test_402_raises_the_recoverable_error_type():
    client = HKGAIClient(_settings(), transport=httpx.MockTransport(_insufficient_balance))
    with pytest.raises(ProviderUnavailable, match="balance or credit exhausted"):
        client.complete([{"role": "user", "content": "x"}])


def test_402_is_not_retried_because_a_balance_does_not_refill():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _insufficient_balance(request)

    client = HKGAIClient(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderUnavailable):
        client.complete([{"role": "user", "content": "x"}])
    assert calls["n"] == 1


def test_401_remains_a_hard_configuration_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    client = HKGAIClient(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as caught:
        client.complete([{"role": "user", "content": "x"}])
    assert not isinstance(caught.value, ProviderUnavailable)


def test_balance_stop_preserves_accepted_subtasks_and_waits_for_a_human(tmp_path):
    """The regression that motivated this: fund-2 lost 2/2 accepted subtasks."""
    script = [
        '{"action":"delegate","recipient":"w","task":"Write notes.md","success_criteria":"exists"}',
        '{"action":"tool","name":"write_file","arguments":{"path":"notes.md","content":"evidence\\n"}}',
        '{"action":"complete","summary":"notes.md written","artifacts":["notes.md"],"success":true}',
        '{"action":"review","task_id":"subtask-1","accepted":true,"reason":"Read notes.md; content present."}',
    ]

    class Client:
        def __init__(self):
            self.stats = {}
            self.n = 0

        def complete(self, messages, *, json_mode=True):
            if self.n >= len(script):
                raise ProviderUnavailable("Model API HTTP 402: account balance or credit exhausted")
            self.n += 1
            return script[self.n - 1]

    engine = SessionEngine.create(
        tmp_path / "s",
        [AgentSpec(id="lead", name="Lead", role="Coordinate"),
         AgentSpec(id="w", name="W", role="Write", allowed_tools=["write_file", "read_file"])],
        Client(), max_steps=20)
    engine.start_task("Produce notes.md and have it reviewed.")
    engine.run()

    state = engine.status()
    assert state["status"] == "waiting_human", state["status"]
    assert state["metrics"]["subtasks_accepted"] == 1
    assert state["metrics"]["fatal_errors"] == 0
    assert (tmp_path / "s" / "agents" / "w" / "workspace" / "notes.md").exists()
    pending = engine.state["pending"]
    assert pending["provider_retry"] is True
    assert "top up" in pending["question"]


def test_a_paused_balance_stop_resumes_after_the_human_replies(tmp_path):
    class Client:
        def __init__(self):
            self.stats = {}
            self.broke = True

        def complete(self, messages, *, json_mode=True):
            if self.broke:
                self.broke = False
                raise ProviderUnavailable("Model API HTTP 402: account balance or credit exhausted")
            return '{"action":"message","recipient":"group","content":"resumed after top-up"}'

    engine = SessionEngine.create(
        tmp_path / "s",
        [AgentSpec(id="lead", name="Lead", role="Coordinate"), AgentSpec(id="w", name="W", role="Write")],
        Client(), max_steps=4)
    engine.start_task("Say hello once service is restored.")
    engine.run()
    assert engine.state["status"] == "waiting_human"
    engine.respond("Topped up the account; please continue.")
    assert engine.state["metrics"]["fatal_errors"] == 0
    assert any("resumed after top-up" in (m.get("content") or "") for m in engine.state["messages"])
