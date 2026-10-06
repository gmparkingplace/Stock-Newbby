"""Session-protected asynchronous adapter; no sockets or live providers."""
from copy import deepcopy
import io
import json
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import analysis_jobs as api
import market_cache
from request_scheduler import RequestScheduler


def handler(path='/api/analysis-session',method='GET',headers=None,body=None):
    h=SimpleNamespace(path=path,command=method,server=SimpleNamespace(server_port=9444),
        headers={'Host':'127.0.0.1:9444',**(headers or {})},headers_written={},wfile=io.BytesIO())
    raw=json.dumps(body or {}).encode();h.rfile=io.BytesIO(raw)
    if method=='POST':h.headers.update({'Content-Length':str(len(raw)),'Content-Type':'application/json'})
    h.send_response=lambda status:setattr(h,'status',status)
    h.send_header=lambda key,value:h.headers_written.update({key:value})
    h.end_headers=lambda:None
    return h


def result(h):
    assert api.handle(h);return h.status,json.loads(h.wfile.getvalue())


@pytest.mark.parametrize('headers',[
    {'Host':'attacker.example:9444'}, {'Origin':'https://attacker.example'},
    {'Sec-Fetch-Site':'cross-site'}, {'Origin':'http://localhost:9444'},
])
def test_foreign_origin_rejected_before_any_lookup(monkeypatch,headers):
    monkeypatch.setattr(market_cache,'enabled',lambda:True)
    status,body=result(handler(headers=headers))
    assert status==403 and body['kind']=='same-origin-required'


def test_session_token_and_no_wildcard_cors(monkeypatch):
    monkeypatch.setattr(market_cache,'enabled',lambda:True)
    h=handler();status,body=result(h)
    assert status==200 and body['sessionToken']==api.SESSION_TOKEN
    assert 'Access-Control-Allow-Origin' not in h.headers_written
    assert h.headers_written['Cache-Control']=='no-store'
    for token in ('','wrong','한글'):
        assert result(handler('/api/analysis-jobs','POST',{'X-Chart-Session':token},body={'symbol':'AAPL'}))[0]==403


def test_async_job_immediate_id_and_same_running_job_reused(monkeypatch):
    import serve_dashboard
    monkeypatch.setattr(market_cache,'enabled',lambda:True)
    registry=api.AnalysisJobs();monkeypatch.setattr(api,'JOBS',registry)
    entered,release=Event(),Event();calls=[]
    def collect(symbol,force=False,background=False):
        assert background;calls.append(symbol);entered.set();assert release.wait(1)
        return {'symbol':symbol,'fetchedAt':'2026-09-01T20:00:00+00:00','candles':[]}
    monkeypatch.setattr(serve_dashboard,'market_lookup',collect)
    token={'X-Chart-Session':api.SESSION_TOKEN}
    try:
        status,one=result(handler('/api/analysis-jobs','POST',token,{'symbol':'AAPL'}))
        assert status==202 and one['status']=='queued' and entered.wait(1)
        status,two=result(handler('/api/analysis-jobs','POST',token,{'symbol':'aapl','force':True}))
        assert status==202 and two['jobId']==one['jobId'] and calls==['AAPL']
        release.set()
        until=monotonic()+1
        while registry.get(one['jobId'])['status']!='done' and monotonic()<until:sleep(.005)
        status,done=result(handler('/api/analysis-jobs/'+one['jobId'],'GET',token))
        assert status==200 and done['status']=='done' and done['result']['symbol']=='AAPL'
        done['result']['symbol']='mutated';assert registry.get(one['jobId'])['result']['symbol']=='AAPL'
    finally:release.set()


def test_disabled_invalid_request_and_missing_job(monkeypatch):
    monkeypatch.setattr(market_cache,'enabled',lambda:False)
    assert result(handler())[0]==503
    monkeypatch.setattr(market_cache,'enabled',lambda:True)
    token={'X-Chart-Session':api.SESSION_TOKEN}
    assert result(handler('/api/analysis-jobs/missing','GET',token))[0]==404
    for body in ({'symbol':'AAPL','timeframe':'X'},{'symbol':''},{'symbol':'AAPL','force':1}):
        assert result(handler('/api/analysis-jobs','POST',token,body))[0]==400


def test_background_collector_waits_beyond_http_limit_and_finishes():
    scheduler=RequestScheduler(wait_seconds=.03)
    entered,release,finished=Event(),Event(),Event();values=[]
    def source():entered.set();assert release.wait(1);return 42
    from threading import Thread
    def work():values.append(scheduler.execute('one','toss',source,background=True));finished.set()
    thread=Thread(target=work);thread.start()
    try:
        assert entered.wait(1)
        assert not finished.wait(.05)
        release.set();assert finished.wait(1);assert values==[42]
    finally:release.set();thread.join(timeout=1);scheduler.close()


def test_expired_terminal_job_unavailable():
    now=[1000];registry=api.AnalysisJobs(clock=lambda:now[0])
    registry.jobs['example']={'jobId':'example','status':'done','updatedAt':1000,'result':{}}
    assert registry.get('example')['status']=='done'
    now[0]+=301
    assert registry.get('example') is None and 'example' not in registry.jobs
