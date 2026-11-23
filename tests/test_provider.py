import httpx
import pytest
from datetime import datetime, timezone

import evoagents.provider as provider_module

from evoagents.config import Settings
from evoagents.provider import HKGAIClient, ProviderError


def test_request_uses_configured_hkgai_and_counts_usage():
    def handler(request):
        assert str(request.url) == "https://api1.hkgai.net/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer unit-test-secret"
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"action":"finish"}'}}], "usage": {"total_tokens": 12}})
    client = HKGAIClient(Settings(api_key="unit-test-secret"), transport=httpx.MockTransport(handler))
    assert client.complete([{"role": "user", "content": "hello"}]).startswith("{")
    assert client.stats["calls"] == 1 and client.stats["total_tokens"] == 12
    client.close()


def test_server_error_body_cannot_expose_secret():
    client = HKGAIClient(Settings(api_key="unit-test-secret"), transport=httpx.MockTransport(lambda request: httpx.Response(401, text="unit-test-secret")))
    with pytest.raises(ProviderError) as error:
        client.complete([])
    assert "unit-test-secret" not in str(error.value)
    client.close()


def test_nullable_usage_does_not_discard_valid_response():
    client = HKGAIClient(Settings(api_key="test"), transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}], "usage": None})))
    assert client.complete([]) == "OK"
    assert client.stats["calls"] == 1
    client.close()


def test_v1_not_duplicated_and_truncation_rejected():
    def handler(request):
        assert str(request.url) == "https://api.deepseek.com/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": "{"}}]})
    client = HKGAIClient(Settings(api_key="test", base_url="https://api.deepseek.com/v1"), transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="token"):
        client.complete([])
    client.close()


def test_dotenv_no_global_mutation(tmp_path, monkeypatch):
    for key in ("HKGAI_API_KEY", "HKGAI_BASE_URL", "EVO_DATA_DIR"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text("HKGAI_API_KEY=test-secret\nEVO_DATA_DIR=data\n")
    config = Settings.from_env(env)
    assert config.data_dir == tmp_path / "data"
    assert "test-secret" not in repr(config)


@pytest.mark.parametrize("url", ["https://api.openai.com", "https://api.anthropic.com", "http://api1.hkgai.net", "https://api1.hkgai.net.evil.test", "https://api1.hkgai.net:invalid", "https://api1.hkgai.net:444"])
def test_prohibited_provider_rejected(tmp_path, monkeypatch, url):
    monkeypatch.setenv("HKGAI_BASE_URL", url)
    with pytest.raises(ValueError):
        Settings.from_env(tmp_path / ".env")


@pytest.mark.parametrize("header,expected", [("4", 4.25), ("invalid", 0.75), ("-1", 0.75), ("nan", 0.75), ("999999", 30)])
def test_rate_limit_respects_retry_after_with_bounded_jitter(monkeypatch, header, expected):
    delays = []
    monkeypatch.setattr(provider_module.time, "sleep", delays.append)
    monkeypatch.setattr(provider_module.random, "uniform", lambda *_: 0.25)
    responses = iter([
        httpx.Response(429, headers={"Retry-After": header}),
        httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]}),
    ])
    client = HKGAIClient(Settings(api_key="test"), transport=httpx.MockTransport(lambda _: next(responses)))
    try:
        assert client.complete([]) == "OK"
        assert delays == [expected]
        assert client.stats["requests"] == 2
    finally:
        client.close()


def test_retry_after_http_date(monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 20, tzinfo=timezone.utc)

    monkeypatch.setattr(provider_module, "datetime", FixedDatetime)
    monkeypatch.setattr(provider_module.random, "uniform", lambda *_: 0)
    client = HKGAIClient(Settings(api_key="test"))
    try:
        assert client._retry_delay(0, httpx.Response(503, headers={"Retry-After": "Fri, 20 Nov 2026 00:00:08 GMT"})) == 8
        assert client._retry_delay(0, httpx.Response(503, headers={"Retry-After": "Thu, 19 Nov 2026 00:00:00 GMT"})) == 0.5
    finally:
        client.close()


@pytest.mark.parametrize("network_error", [False, True])
def test_retries_are_bounded_for_server_and_network_failures(monkeypatch, network_error):
    delays = []
    monkeypatch.setattr(provider_module.time, "sleep", delays.append)
    monkeypatch.setattr(provider_module.random, "uniform", lambda *_: 0.25)

    def handler(request):
        if network_error:
            raise httpx.ConnectError("temporary", request=request)
        return httpx.Response(503)

    client = HKGAIClient(Settings(api_key="test"), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError):
            client.complete([])
        assert delays == [0.75, 1.25]
        assert client.stats["requests"] == 3
        assert client.stats["errors"] == 1
    finally:
        client.close()


def test_json_mode_requests_structured_output_and_private_chat_does_not():
    payloads = []

    def handler(request):
        import json
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    client = HKGAIClient(Settings(api_key="test"), transport=httpx.MockTransport(handler))
    try:
        client.complete([{"role": "user", "content": "Return JSON"}])
        client.complete([{"role": "user", "content": "Hello"}], json_mode=False)
        assert payloads[0]["response_format"] == {"type": "json_object"}
        assert "response_format" not in payloads[1]
    finally:
        client.close()


def test_explicit_unsupported_json_format_falls_back_once_and_is_remembered():
    import json
    payloads = []

    def handler(request):
        payload = json.loads(request.content)
        payloads.append(payload)
        if "response_format" in payload:
            return httpx.Response(400, json={"error": {"param": "response_format", "code": "unsupported_parameter", "message": "response_format not supported"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    client = HKGAIClient(Settings(api_key="test"), transport=httpx.MockTransport(handler))
    try:
        assert client.complete([]) == "{}"
        assert client.complete([]) == "{}"
        assert ["response_format" in p for p in payloads] == [True, False, False]
        assert client.stats["json_mode_fallbacks"] == 1
        assert client.stats["requests"] == 3
    finally:
        client.close()


@pytest.mark.parametrize("error", [
    {"param": "messages", "code": "unsupported_parameter"},
    {"param": "response_format", "message": "content moderation rejected request"},
    {"message": "model not supported"},
])
def test_json_fallback_never_retries_unrelated_rejections(error):
    client = HKGAIClient(Settings(api_key="test"), transport=httpx.MockTransport(lambda _: httpx.Response(400, json={"error": error})))
    try:
        with pytest.raises(ProviderError, match="HTTP 400"):
            client.complete([])
        assert client.stats["requests"] == 1
        assert client.stats.get("json_mode_fallbacks", 0) == 0
    finally:
        client.close()


@pytest.mark.parametrize("bad_response,expected_code", [
    ([], "root_not_object"),
    ({"choices": []}, "missing_choice"),
    ({"choices": [None]}, "missing_choice"),
    ({"choices": [{}]}, "missing_message"),
    ({"choices": [{"message": {"content": None}}]}, "nontext_content"),
    ({"choices": [{"message": {"content": " "}}]}, "empty_content"),
])
def test_malformed_successful_responses_are_retried_but_bounded(monkeypatch, bad_response, expected_code):
    monkeypatch.setattr(provider_module.time, "sleep", lambda _: None)
    client = HKGAIClient(Settings(api_key="test"), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=bad_response)))
    try:
        with pytest.raises(ProviderError, match=expected_code):
            client.complete([])
        assert client.stats["requests"] == 3
        assert client.stats["invalid_responses"] == 3
        assert client.stats["protocol_retries"] == 2
        assert client.stats["errors"] == 1
    finally:
        client.close()


def test_empty_response_recovers_and_records_usage_from_both_responses(monkeypatch):
    monkeypatch.setattr(provider_module.time, "sleep", lambda _: None)
    responses = iter([
        httpx.Response(200, json={"choices": [{"message": {"content": ""}}], "usage": {"total_tokens": 9}}),
        httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}], "usage": {"total_tokens": 12}}),
    ])
    client = HKGAIClient(Settings(api_key="test"), transport=httpx.MockTransport(lambda _: next(responses)))
    try:
        assert client.complete([]) == "{}"
        assert client.stats["requests"] == 2
        assert client.stats["calls"] == 1
        assert client.stats["total_tokens"] == 21
        assert client.stats["protocol_retries"] == 1
    finally:
        client.close()


def test_truncation_is_typed_counted_and_never_returned_or_retried():
    from evoagents.provider import OutputLimitError
    response = {"choices": [{"finish_reason": "length", "message": {"content": '{"secret":"unit-test-secret"'}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 20, "total_tokens": 31}}
    client = HKGAIClient(Settings(api_key="test", max_output_tokens=20), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)))
    try:
        with pytest.raises(OutputLimitError) as error:
            client.complete([])
        assert error.value.max_tokens == 20
        assert "unit-test-secret" not in str(error.value)
        assert client.stats["requests"] == 1
        assert client.stats["truncated_responses"] == 1
        assert client.stats["total_tokens"] == 31
        assert client.stats.get("calls", 0) == 0
    finally:
        client.close()


@pytest.mark.parametrize("choice", [
    {"finish_reason": "content_filter", "message": {"content": ""}},
    {"message": {"content": None, "refusal": "This request is declined."}},
])
def test_explicit_refusal_is_not_retried(choice):
    client = HKGAIClient(Settings(api_key="test"), transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": [choice]})))
    try:
        with pytest.raises(ProviderError, match="declined"):
            client.complete([])
        assert client.stats["requests"] == 1
    finally:
        client.close()


def test_invalid_json_error_has_safe_diagnostic_and_no_response_body(monkeypatch):
    monkeypatch.setattr(provider_module.time, "sleep", lambda _: None)
    client = HKGAIClient(Settings(api_key="test"), transport=httpx.MockTransport(lambda _: httpx.Response(200, text="unit-test-secret")))
    try:
        with pytest.raises(ProviderError, match="invalid_response_json") as error:
            client.complete([])
        assert "unit-test-secret" not in str(error.value)
        assert client.stats["requests"] == 3
    finally:
        client.close()


def test_fallback_and_transient_failures_share_three_request_budget(monkeypatch):
    monkeypatch.setattr(provider_module.time, "sleep", lambda _: None)
    responses = iter([
        httpx.Response(400, json={"error": {"param": "response_format", "code": "unsupported_parameter"}}),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(503),
    ])
    client = HKGAIClient(Settings(api_key="test"), transport=httpx.MockTransport(lambda _: next(responses)))
    try:
        with pytest.raises(ProviderError, match="HTTP 503"):
            client.complete([])
        assert client.stats["requests"] == 3
    finally:
        client.close()


def test_usage_ignores_negative_values_and_boolean_counts():
    client = HKGAIClient(Settings(api_key="test"), transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
        "choices": [{"message": {"content": "{}"}}],
        "usage": {"prompt_tokens": -1, "completion_tokens": True, "total_tokens": 3},
    })))
    try:
        client.complete([])
        assert client.stats.get("prompt_tokens", 0) == 0
        assert client.stats.get("completion_tokens", 0) == 0
        assert client.stats["total_tokens"] == 3
    finally:
        client.close()
