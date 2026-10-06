import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import serve_dashboard as s
import toss_catalog,toss_market

def test_coin_aliases_and_provider(monkeypatch):
    monkeypatch.setattr(toss_market,'enabled',lambda:True)
    def forbidden(*a,**kw):raise AssertionError('coin reached Toss')
    monkeypatch.setattr(toss_catalog,'resolve',forbidden)
    monkeypatch.setattr(toss_catalog,'search',forbidden)
    monkeypatch.setattr(s,'lookup',lambda code,force=False:({'symbol':code,'source':'yfinance'},{}))
    for code in ['btc','BTC-USD','비트코인']:
        result=s.market_lookup(code);assert result['symbol']=='BTC-USD' and result['source']=='yfinance'
    assert s.market_lookup('이더리움')['symbol']=='ETH-USD'
    assert s.search_assets('BTC')['results'][0]['symbol']=='BTC-USD'
    assert s.search_assets('비트코인')['results'][0]['source']=='yfinance'
    assert len(s.search_assets('코인')['results'])==len(s.COINS)
