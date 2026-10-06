import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import toss_catalog as c

def test_resolve_market_and_name(monkeypatch):
    def get(path,**kw):
        if path.endswith('/all'):
            return [{'symbol':'126340','name':'비나텍'}] if kw['market']=='KOSDAQ' else []
        return [{'symbol':'126340','name':'비나텍','market':'KOSDAQ'}]
    monkeypatch.setattr(c.CLIENT,'get',get);monkeypatch.setattr(c,'_rows',[])
    assert c.resolve('126340')=='126340.KQ'
    assert c.resolve('126340.KS')=='126340.KQ'
    assert c.resolve('비나텍')=='126340.KQ'
    assert c.search('비나')[0]['market']=='KOSDAQ'
    assert c.search('없는종목')==[]
    assert c.resolve('AAPL')=='AAPL'
