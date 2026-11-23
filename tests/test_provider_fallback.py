import json
import httpx
import pytest
from evoagents.config import Settings
from evoagents.provider import HKGAIClient,ProviderError


def test_config_selects_separate_deepseek_credential(tmp_path,monkeypatch):
    monkeypatch.setenv('EVO_PROVIDER','deepseek')
    p=tmp_path/'.env';p.write_text('HKGAI_API_KEY=primary\nDEEPSEEK_API_KEY=backup\nDEEPSEEK_MODEL=deepseek-chat\n')
    s=Settings.from_env(p)
    assert s.api_key=='backup' and s.base_url=='https://api.deepseek.com'
    assert s.model=='deepseek-chat'
    assert 'backup' not in repr(s)


def test_unavailability_switches_once_and_aggregates_usage(monkeypatch):
    monkeypatch.setattr('evoagents.provider.time.sleep',lambda _:None)
    calls=[]
    def handler(request):
        calls.append(request.url.host)
        if request.url.host=='api1.hkgai.net':return httpx.Response(503)
        assert request.headers['authorization']=='Bearer backup'
        assert json.loads(request.content)['model']=='deepseek-chat'
        return httpx.Response(200,json={'choices':[{'message':{'content':'{}'}}],'usage':{'total_tokens':7}})
    c=HKGAIClient(Settings(api_key='primary',deepseek_api_key='backup',fallback_enabled=True),transport=httpx.MockTransport(handler))
    try:
        assert c.complete([])=='{}';assert c.complete([])=='{}'
        assert calls==['api1.hkgai.net']*3+['api.deepseek.com']*2
        assert c.stats['requests']==5 and c.stats['total_tokens']==14
        assert c.stats['provider_switches']==1 and c.active_provider=='deepseek'
    finally:c.close()


@pytest.mark.parametrize('response',[httpx.Response(401),httpx.Response(403),httpx.Response(200,json={'choices':[{'message':{'refusal':'no','content':''}}]}),httpx.Response(200,json={'choices':[{'finish_reason':'content_filter','message':{'content':''}}]})])
def test_rejections_never_switch_provider(response):
    calls=[]
    def handler(request):calls.append(request.url.host);return response
    c=HKGAIClient(Settings(api_key='primary',deepseek_api_key='backup',fallback_enabled=True),transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError):c.complete([])
        assert calls==['api1.hkgai.net'] and c.active_provider=='hkgai'
    finally:c.close()


def test_unconfigured_backup_never_receives_primary_key(monkeypatch):
    monkeypatch.setattr('evoagents.provider.time.sleep',lambda _:None)
    calls=[]
    def handler(request):calls.append(request.url.host);raise httpx.ConnectError('offline',request=request)
    c=HKGAIClient(Settings(api_key='primary',fallback_enabled=True),transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError):c.complete([])
        assert calls==['api1.hkgai.net']*3
    finally:c.close()
