"""Browser-independent daily monitoring, durable settings and safe local API."""
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
from threading import Event, Thread
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from market_store import MarketStore, epoch, revision
from monitor_service import MonitorService, stock
import monitor_service as module
from flag_fixture import flag_rows
import pattern_service
from test_horizontal_patterns import payload

T=epoch('2026-09-07T01:00:00+00:00')


class Rig:
    def __init__(self, tmp_path):
        self.now=T;self.calls=[];self.calendar_calls=[];self.store=MarketStore(tmp_path/'cache.sqlite3')
        self.calendar=dict(state='open',sessionDate='2026-09-07',lastSessionEnd='2026-09-04T11:00:00+00:00',nextTransitionAt='2026-09-07T11:00:00+00:00')
        self.error=None;self.stale=False
        self.svc=MonitorService(self.store,self.collect,self.session,lambda:self.now)
    def session(self, code, now):
        self.calendar_calls.append(code);return dict(self.calendar)
    def collect(self, code, **kwargs):
        self.calls.append((code,kwargs))
        if self.error:raise self.error
        return dict(symbol=code,fetchedAt=datetime.fromtimestamp(self.now,timezone.utc).isoformat(),lastConfirmedTime=self.calendar['sessionDate'],
                    candles=[dict(time=self.calendar['sessionDate'])],dataRevision='r',stale=self.stale,
                    patternAnalysis=dict(enabled=True,sourceStatus='ready',timeline=[]),flagAnalysis=dict(enabled=True,sourceStatus='ready',timeline=[]))
    def config(self, items):return self.svc.configure(items,self.svc.state['configRevision'])


@pytest.fixture
def rig(tmp_path):
    r=Rig(tmp_path);yield r;r.svc.close();r.store.close()


def test_paused_default_has_no_browser_or_collection(rig):
    rig.config([dict(symbol='AAPL')]);assert not rig.svc.step() and not rig.calls
    assert rig.svc.status()['workerState']=='paused'
    assert rig.svc.status()['items'][0]['status']=='paused'


def test_normal_focus_intervals_and_fair_due_order(rig):
    rig.config([dict(symbol='AAPL',profile='normal'),dict(symbol='MSFT',profile='focus')]);rig.svc.control('start')
    assert rig.svc.step() and rig.svc.step() and not rig.svc.step()
    rows={r['symbol']:r for r in rig.svc.status()['items']}
    assert epoch(rows['AAPL']['nextDueAt'])==T+300
    assert epoch(rows['MSFT']['nextDueAt'])==T+30
    rig.now+=30;rig.svc.step();assert len(rig.calls)==3
    rig.now=T+300;rig.svc.step();assert rig.calls[-1][0]=='MSFT'
    rig.svc.step();assert rig.calls[-1][0]=='AAPL'


def test_closed_waits_for_buffer_then_collects_once_and_restart_keeps_slot(rig):
    rig.config([dict(symbol='AAPL')]);rig.svc.control('start')
    rig.calendar.update(state='closed',lastSessionEnd='2026-09-07T01:00:00+00:00',nextTransitionAt='2026-09-08T00:00:00+00:00')
    rig.svc.step();assert not rig.calls
    assert epoch(rig.svc.status()['nextDueAt'])==T+1800
    rig.now+=1799;assert not rig.svc.step()
    rig.now+=1;rig.svc.step();assert len(rig.calls)==1 and rig.calls[-1][1]['force']
    assert rig.svc.status()['items'][0]['status']=='confirmed-history'
    rig.svc.close();rig.svc=MonitorService(rig.store,rig.collect,rig.session,lambda:rig.now+20)
    rig.svc.step();assert len(rig.calls)==1
    assert rig.svc.status()['interruption']['reason']=='server-restarted'


def test_unknown_calendar_never_collects_or_confirms(rig):
    rig.config([dict(symbol='AAPL')]);rig.svc.control('start');rig.calendar['state']='unknown'
    rig.svc.step();assert not rig.calls and rig.svc.status()['items'][0]['status']=='calendar-unknown'
    assert epoch(rig.svc.status()['nextDueAt'])==T+60


def test_old_source_cannot_complete_close_job(rig):
    rig.config([dict(symbol='AAPL')]);rig.svc.control('start')
    rig.calendar.update(state='closed',lastSessionEnd='2026-09-06T11:00:00+00:00',sessionDate='2026-09-06')
    original=rig.svc.collect
    def lagging(*a,**k):
        data=original(*a,**k);data['lastConfirmedTime']='2026-09-04';return data
    rig.svc.collect=lagging;rig.svc.step()
    row=rig.svc.status()['items'][0];assert row['status']=='waiting-confirmation' and not row.get('closedSlot')
    assert epoch(row['nextDueAt'])==T+60


def test_provider_error_respects_retry_after_and_does_not_block_other_symbol(rig):
    class Throttled(Exception):
        code='rate-limit';status=429;retry_at='2026-09-07T01:10:00+00:00'
    rig.config([dict(symbol='AAPL'),dict(symbol='MSFT')]);rig.svc.control('start');rig.error=Throttled()
    rig.svc.step();row=rig.svc.status()['items'][0];assert row['upstreamStatus']==429 and epoch(row['nextDueAt'])==T+600
    rig.error=None;rig.svc.step();assert rig.svc.status()['items'][1]['status']=='watching'
    rig.now+=30;assert not rig.svc.step()


def test_source_failure_does_not_turn_into_pattern_failure_or_last_success(rig):
    rig.config([dict(symbol='AAPL')]);rig.svc.control('start');rig.svc.step();old=rig.svc.status()['lastSuccessAt']
    rig.now+=300;rig.stale=True;rig.svc.step()
    assert rig.svc.status()['lastSuccessAt']==old and rig.svc.status()['items'][0]['status']=='error'
    assert not rig.store.pattern_events()


def test_import_preview_merge_one_time_and_version_conflict(rig):
    rig.config([dict(symbol='AAPL',note='keep',profile='focus',groups=['old'])]);rev=rig.svc.state['configRevision']
    rows=[dict(symbol='AAPL',groups=['new']),dict(symbol='AAPL',groups=['another']),dict(symbol='005930',name='삼성전자'),dict(symbol='BTC')]
    preview=rig.svc.configure(rows,mode='preview',migration='local-watchlists-v1')
    assert preview['added']==1 and preview['duplicates']==2 and preview['skipped']==['BTC']
    assert len(rig.svc.status()['items'])==1
    result=rig.svc.configure(rows,rev,'import','local-watchlists-v1')
    assert len(result['items'])==2 and result['items'][0]['profile']=='focus' and result['items'][0]['note']=='keep'
    assert result['items'][0]['groups']==['another','new','old']
    assert rig.svc.configure(rows,rev,'import','local-watchlists-v1')['alreadyImported']
    with pytest.raises(RuntimeError):rig.svc.configure([],rev)


@pytest.mark.parametrize('rows',[[dict(symbol=f'T{i}') for i in range(21)],[dict(symbol=f'T{i}',profile='focus') for i in range(4)],[dict(symbol='BTC')]])
def test_limits_reject_without_mutation(rig, rows):
    with pytest.raises(ValueError):rig.config(rows)
    assert rig.svc.state['items']==[]


def test_simultaneous_step_and_pause_never_resurrect_settings(rig):
    rig.config([dict(symbol='AAPL')]);rig.svc.control('start')
    entered=Event();release=Event();original=rig.svc.collect
    def held(*a,**k):entered.set();assert release.wait(2);return original(*a,**k)
    rig.svc.collect=held;thread=Thread(target=rig.svc.step);thread.start();assert entered.wait(1)
    assert not rig.svc.step()
    rig.svc.control('pause');release.set();thread.join(2)
    assert not thread.is_alive() and not rig.svc.step()
    assert not rig.svc.status()['enabled'] and rig.svc.status()['items'][0]['status']=='paused'


def test_headless_flag_event_at_close_and_restart_dedup(rig):
    rows=flag_rows();data=payload(rows);data.update(confirmed=False,snapshotEligible=True,lastConfirmedTime=rows[-2]['time'],fetchedAt=rows[-1]['time']+'T19:00:00+00:00')
    data['symbol']='AAPL';data['marketSession'].update(state='open',sessionDate=rows[-1]['time'])
    rig.now=epoch(data['fetchedAt'])
    rig.calendar=dict(state='open',sessionDate=rows[-1]['time'],lastSessionEnd=None,nextTransitionAt=None)
    def collect(*a,**k):
        data['fetchedAt']=datetime.fromtimestamp(rig.now,timezone.utc).isoformat()
        data['flagAnalysis']=pattern_service.evaluate(data,rig.store,datetime.fromtimestamp(rig.now,timezone.utc),family='flag')
        return deepcopy(data)
    rig.svc.collect=collect;rig.config([dict(symbol='AAPL',rules=['flag'])]);rig.svc.control('start');rig.svc.step()
    assert not rig.svc.events()['events']
    rig.now+=1800
    rig.calendar.update(state='closed',lastSessionEnd=datetime.fromtimestamp(rig.now-1800,timezone.utc).isoformat())
    data.update(confirmed=True,lastConfirmedTime=rows[-1]['time']);data['marketSession']['state']='closed'
    rig.svc.step();events=rig.svc.events()['events'];assert len([e for e in events if e['eventType']=='confirmed'])==1
    snapshot=rig.store.pattern_snapshot(events[0]['basisSnapshotId']);assert snapshot['event']['geometry']['kind']=='channel'
    rig.svc.close();rig.svc=MonitorService(rig.store,collect,rig.session,lambda:rig.now)
    rig.svc.step();assert rig.svc.events()['events']==events


def test_event_cursor_reads_do_not_collect_and_filters_unmonitored(rig):
    from pattern_service import result_key
    rig.config([dict(symbol='AAPL',rules=['flag'])])
    pairs=[]
    for i,(symbol,rule) in enumerate([('AAPL','horizontal-d-v1'),('AAPL','flag-d-v1'),('MSFT','flag-d-v1'),('AAPL','flag-h4-v3')]):
        event=dict(eventId=str(i),symbol=symbol,timeframe='H4' if i==3 else 'D',ruleVersion=rule,basisSnapshotId='s'+str(i),anchorTime='2026-09-01',confirmedBarTime='2026-09-07')
        family='flag' if rule.startswith('flag-') else 'horizontal'
        rig.store.pattern_publish(result_key(symbol,{},family),dict(symbol=symbol,timeline=[dict(barTime='2026-09-07')]),[(event,dict(snapshotId=event['basisSnapshotId']))])
    data=rig.svc.events();assert [e['eventId'] for e in data['events']]==['1'] and data['nextCursor']==4
    assert not rig.svc.events(data['nextCursor'])['events'] and not rig.calls


def test_api_origin_session_limits_and_read_only(rig,monkeypatch):
    import market_cache, analysis_jobs
    monkeypatch.setattr(module,'enabled',lambda:True);monkeypatch.setattr(module,'services',lambda:rig.svc);monkeypatch.setattr(market_cache,'enabled',lambda:True)
    def request(path, method='GET', body=None, headers=None):
        h=SimpleNamespace(path=path,command=method,server=SimpleNamespace(server_port=8735),headers={'Host':'127.0.0.1:8735',**(headers or {})},rfile=io.BytesIO(json.dumps(body).encode() if body else b''))
        h.headers.update({'Content-Type':'application/json','Content-Length':str(len(h.rfile.getvalue()))})
        monkeypatch.setattr(analysis_jobs,'_reply',lambda handler,status,data:(status,data))
        return module.handle(h)
    assert request('/api/monitor/status')[0]==200 and not rig.calls
    assert request('/api/monitor/status',headers={'Origin':'https://external.example'})[0]==403
    assert request('/api/monitor/control','POST',{'action':'start'})[0]==403
    token={'X-Chart-Session':analysis_jobs.SESSION_TOKEN}
    assert request('/api/monitor/watchlist','PUT',{'items':[dict(symbol='AAPL')],'configRevision':0},token)[0]==200
    assert request('/api/monitor/watchlist','PUT',{'items':[],'configRevision':0},token)[0]==409
    assert request('/api/monitor/control','POST',{'action':'start'},token)[1]['enabled']
    assert request('/api/monitor/events?cursor=-1')[0]==400
    assert not rig.calls


def test_monitor_and_chart_share_one_provider_collection(rig,tmp_path):
    from market_cache import MarketCache
    cache=MarketCache(tmp_path/'shared.sqlite3',clock=lambda:rig.now)
    entered=Event();release=Event();source_calls=[];chart_results=[]
    def source(force):
        source_calls.append(force);entered.set();assert release.wait(2)
        return rig.collect('AAPL')
    def common(*args,**kwargs):
        return cache.lookup('fixture','AAPL','D',source,background=kwargs.get('background',False))
    rig.svc.collect=common;rig.config([dict(symbol='AAPL')]);rig.svc.control('start')
    chart=Thread(target=lambda:chart_results.append(common()));chart.start();assert entered.wait(1)
    monitor=Thread(target=rig.svc.step);monitor.start()
    import time
    end=time.monotonic()+1
    while cache.scheduler.snapshot()['merged']<1 and time.monotonic()<end:time.sleep(.01)
    release.set();chart.join(2);monitor.join(2)
    assert not chart.is_alive() and not monitor.is_alive()
    assert len(source_calls)==1 and cache.scheduler.snapshot()['merged']==1
    assert rig.svc.status()['items'][0]['lastSuccessAt']==chart_results[0]['fetchedAt']
    cache.close()


def test_reading_status_does_not_renew_provisional_freshness(rig):
    rig.config([dict(symbol='AAPL')]);rig.svc.control('start')
    original=rig.svc.collect
    rig.svc.collect=lambda *a,**k:{**original(*a,**k),'snapshotEligible':True}
    rig.svc.step();assert rig.svc.status()['items'][0]['provisionalEligible']
    collected=rig.svc.status()['items'][0]['lastSuccessAt'];rig.now+=91
    for _ in range(3):
        r=rig.svc.status()['items'][0]
        assert not r['provisionalEligible'] and r['lastSuccessAt']==collected
    assert len(rig.calls)==1


def test_runtime_hook_restores_worker_but_never_starts_monitoring_implicitly(rig,monkeypatch):
    import market_cache
    monkeypatch.setattr(module,'enabled',lambda:True);monkeypatch.setattr(module,'services',lambda:rig.svc)
    monkeypatch.setattr(market_cache,'enabled',lambda:True);monkeypatch.setattr(pattern_service,'enabled',lambda:True)
    module.start_runtime()
    assert rig.svc.thread.is_alive() and not rig.svc.status()['enabled'] and not rig.calls
    rig.svc.close();assert not rig.svc.thread.is_alive()
