"""일봉 Yahoo·분봉 Toss 정책과 캐시 격리를 검증한다."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from types import SimpleNamespace
import pytest
import serve_dashboard as server
import toss_market
import market_cache
import pattern_service


def test_clean_install_defaults_daily_yahoo_intraday_auto(monkeypatch, tmp_path):
    monkeypatch.setattr(server, 'ROOT', tmp_path)
    monkeypatch.delenv('CHART_MARKET_PROVIDER', raising=False)
    monkeypatch.delenv('CHART_H4_PROVIDER', raising=False)
    assert server._provider_choice('D') == 'yfinance'
    assert server._provider_choice('H4') == 'auto'
    (tmp_path/'.local.json').write_text(json.dumps({'marketProvider':'yfinance','h4Provider':'auto'}))
    assert server._provider_choice('D') == 'yfinance'
    monkeypatch.setenv('CHART_MARKET_PROVIDER', 'toss')
    assert server._provider_choice('D') == 'toss'


def test_yahoo_daily_never_resolves_or_collects_toss(monkeypatch):
    import toss_catalog
    monkeypatch.setattr(server, '_provider_choice', lambda tf: 'yfinance')
    monkeypatch.setattr(toss_market, 'enabled', lambda: True)
    def forbidden(*a, **kw):
        pytest.fail('Yahoo 일봉에서 Toss 요청 금지')
    monkeypatch.setattr(toss_market.CLIENT, 'get', forbidden)
    monkeypatch.setattr(toss_catalog, 'resolve', forbidden)
    monkeypatch.setattr(server, 'lookup', lambda code, force=False: ({'source':'yfinance','symbol':code}, {}))
    monkeypatch.setattr(server, '_with_meta', lambda payload, cache: payload)
    monkeypatch.setattr(market_cache, 'enabled', lambda: False)
    monkeypatch.setattr(pattern_service, 'attach_evidence', lambda payload: payload)
    assert server.market_lookup('005930.KS')['source'] == 'yfinance'


def test_yahoo_cache_key_cannot_reuse_toss_snapshot(monkeypatch):
    calls=[]
    def lookup(provider, symbol, tf, fn, force, **kw):
        calls.append((provider,symbol,tf))
        return {'source':provider,'cacheHit':True,'cacheAge':0,'stale':False}
    monkeypatch.setattr(market_cache,'enabled',lambda:True)
    monkeypatch.setattr(market_cache,'services',lambda:SimpleNamespace(lookup=lookup))
    monkeypatch.setattr(server,'_provider_choice',lambda tf:'yfinance')
    monkeypatch.setattr(toss_market,'enabled',lambda:True)
    monkeypatch.setattr(server,'_with_meta',lambda payload, cache:payload)
    monkeypatch.setattr(pattern_service,'attach',lambda payload:payload)
    assert server.market_lookup('AAPL')['source']=='yfinance'
    assert calls==[('yfinance','AAPL','D')]


def test_metadata_uses_explicit_source_session(monkeypatch):
    calls=[]
    monkeypatch.setattr(server,'market_session',lambda symbol, **kw:calls.append((symbol,kw)) or {'state':'closed'})
    monkeypatch.setattr(server,'judgment_metadata',lambda payload,*a,**kw:payload)
    server._with_meta({'symbol':'AAPL','source':'yfinance'}, {})
    assert calls==[('AAPL',{'source':'yfinance'})]
