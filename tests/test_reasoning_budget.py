"""Reasoning-token budget control on the approved reasoning backbones.

Both HKGAI-V3 and DeepSeek V4 bill thinking tokens inside max_tokens, so an
uncapped effort level can spend a whole turn's budget without emitting any
answer. These tests pin the knob, its fallback, and its accounting.
"""
from __future__ import annotations

import json

import httpx
import pytest

from evoagents.config import Settings
from evoagents.provider import HKGAIClient, OutputLimitError


def _settings(**overrides) -> Settings:
    base = {"api_key": "sk-test-key-value", "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-pro", "provider": "deepseek", "max_output_tokens": 8192}
    return Settings(**{**base, **overrides})


def _ok(content: str = '{"action":"message","recipient":"group","content":"hi"}', **usage) -> dict:
    return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            "usage": usage or {}}


def test_effort_is_sent_when_configured():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=_ok())

    client = HKGAIClient(_settings(reasoning_effort="low"), transport=httpx.MockTransport(handler))
    client.complete([{"role": "user", "content": "x"}])
    assert seen[0]["reasoning_effort"] == "low"
    assert "thinking" not in seen[0]


def test_none_disables_thinking_instead_of_setting_an_effort_level():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=_ok())

    client = HKGAIClient(_settings(reasoning_effort="none"), transport=httpx.MockTransport(handler))
    client.complete([{"role": "user", "content": "x"}])
    assert seen[0]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in seen[0]


def test_default_leaves_the_service_setting_untouched():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=_ok())

    client = HKGAIClient(_settings(), transport=httpx.MockTransport(handler))
    client.complete([{"role": "user", "content": "x"}])
    assert "reasoning_effort" not in seen[0] and "thinking" not in seen[0]


def test_explicitly_unsupported_control_is_dropped_once_and_remembered():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen.append(payload)
        if "reasoning_effort" in payload:
            return httpx.Response(400, json={"error": {"param": "reasoning_effort",
                                                       "code": "unsupported_parameter",
                                                       "message": "reasoning_effort is not supported"}})
        return httpx.Response(200, json=_ok())

    client = HKGAIClient(_settings(reasoning_effort="high"), transport=httpx.MockTransport(handler))
    assert client.complete([{"role": "user", "content": "x"}])
    client.complete([{"role": "user", "content": "y"}])
    assert client.stats["reasoning_control_fallbacks"] == 1
    # Only the first request carries the rejected parameter.
    assert sum("reasoning_effort" in item for item in seen) == 1


def test_unrelated_validation_error_does_not_drop_the_control():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"param": "messages", "code": "invalid_request_error",
                                                   "message": "messages must not be empty"}})

    client = HKGAIClient(_settings(reasoning_effort="low"), transport=httpx.MockTransport(handler))
    with pytest.raises(Exception):
        client.complete([{"role": "user", "content": "x"}])
    assert client.stats.get("reasoning_control_fallbacks", 0) == 0


def test_reasoning_tokens_are_recorded_even_when_the_turn_is_truncated():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": None}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 8192, "total_tokens": 8202,
                      "completion_tokens_details": {"reasoning_tokens": 8192}}})

    client = HKGAIClient(_settings(reasoning_effort="max"), transport=httpx.MockTransport(handler))
    with pytest.raises(OutputLimitError):
        client.complete([{"role": "user", "content": "write a large module"}])
    # The spend is real even though nothing was executed; it must stay visible.
    assert client.stats["reasoning_tokens"] == 8192
    assert client.stats["completion_tokens"] == 8192
    assert client.stats["truncated_responses"] == 1


def test_reasoning_token_accounting_accumulates_across_calls():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok(prompt_tokens=5, completion_tokens=40, total_tokens=45,
                                            completion_tokens_details={"reasoning_tokens": 30}))

    client = HKGAIClient(_settings(reasoning_effort="low"), transport=httpx.MockTransport(handler))
    client.complete([{"role": "user", "content": "x"}])
    client.complete([{"role": "user", "content": "y"}])
    assert client.stats["reasoning_tokens"] == 60


def test_malformed_usage_details_are_ignored():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok(completion_tokens=7,
                                            completion_tokens_details={"reasoning_tokens": "many"}))

    client = HKGAIClient(_settings(), transport=httpx.MockTransport(handler))
    client.complete([{"role": "user", "content": "x"}])
    assert "reasoning_tokens" not in client.stats
    assert client.stats["completion_tokens"] == 7


@pytest.mark.parametrize("value", ["", "none", "low", "high", "max"])
def test_settings_accept_supported_effort_levels(tmp_path, value):
    env = tmp_path / ".env"
    env.write_text(f"EVO_PROVIDER=deepseek\nDEEPSEEK_API_KEY=sk-x\nEVO_REASONING_EFFORT={value}\n", encoding="utf-8")
    assert Settings.from_env(env).reasoning_effort == value


def test_settings_reject_an_unknown_effort_level(tmp_path):
    env = tmp_path / ".env"
    env.write_text("EVO_PROVIDER=deepseek\nDEEPSEEK_API_KEY=sk-x\nEVO_REASONING_EFFORT=turbo\n", encoding="utf-8")
    with pytest.raises(ValueError, match="EVO_REASONING_EFFORT"):
        Settings.from_env(env)


def test_engine_metrics_expose_measured_provider_usage(tmp_path):
    """The performance report must quote measured spend, not an estimate."""
    from evoagents.engine import AgentSpec, SessionEngine

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok(prompt_tokens=100, completion_tokens=20, total_tokens=120,
                                            completion_tokens_details={"reasoning_tokens": 12}))

    client = HKGAIClient(_settings(reasoning_effort="low"), transport=httpx.MockTransport(handler))
    engine = SessionEngine.create(
        tmp_path / "s",
        [AgentSpec(id="lead", name="Lead", role="Coordinate"), AgentSpec(id="w", name="W", role="Write")],
        client, max_steps=1)
    engine.start_task("Say hello to the group.")
    engine.run()
    provider = engine.status()["metrics"]["provider"]
    assert provider["active_provider"] == "deepseek"
    assert provider["prompt_tokens"] == 100 and provider["reasoning_tokens"] == 12
    assert provider["calls"] == 1


def test_engine_metrics_tolerate_a_client_without_usage_stats(tmp_path):
    from evoagents.engine import AgentSpec, SessionEngine

    class Bare:
        def complete(self, messages, *, json_mode=True):
            return '{"action":"message","recipient":"group","content":"hi"}'

    engine = SessionEngine.create(
        tmp_path / "s",
        [AgentSpec(id="lead", name="Lead", role="Coordinate"), AgentSpec(id="w", name="W", role="Write")],
        Bare(), max_steps=1)
    engine.start_task("Say hello to the group.")
    engine.run()
    assert "provider" not in engine.status()["metrics"]
