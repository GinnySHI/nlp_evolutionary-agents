import httpx
import pytest

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
