"""Opt-in, persistent daily pattern monitoring; no browser, orders or messaging."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from secrets import compare_digest
from threading import Event, Lock, RLock, Thread
from time import time
from urllib.parse import parse_qs, urlparse
from market_store import epoch, revision

ROOT = Path(__file__).resolve().parents[1]
KEY = 'monitor|settings-v1'
_INSTANCE = None
_INSTANCE_LOCK = Lock()


def enabled():
    value = os.environ.get('CHART_SERVER_MONITOR')
    if value is not None:
        return value == '1'
    try:
        return json.loads((ROOT / '.local.json').read_text()).get('serverMonitor') is True
    except (OSError, ValueError):
        return False


def stamp(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def stock(raw):
    if not isinstance(raw, str) or not raw.isascii():
        raise ValueError('stock-symbol-required')
    from universe import norm_code, is_coin
    code = norm_code(raw)
    if not code or is_coin(code) or not re.fullmatch(r'(?:\d{6}\.(?:KS|KQ)|[A-Z][A-Z0-9.\-]{0,14})', code):
        raise ValueError('stock-symbol-required')
    return code


def watch_items(items):
    if not isinstance(items, list) or len(items) > 100:
        raise ValueError('invalid-watchlist')
    rows = {}
    skipped = []
    for raw in items:
        if not isinstance(raw, dict):
            raise ValueError('invalid-watchlist')
        try:
            code = stock(raw.get('symbol'))
        except ValueError:
            skipped.append(str(raw.get('symbol', ''))[:40]);continue
        profile = raw.get('profile', 'normal')
        active = raw.get('enabled', True)
        from pattern_service import triangles_enabled
        rules = raw.get('rules', ['horizontal', 'flag'] + (['triangle'] if triangles_enabled() else []))
        name = raw.get('name', code)
        note = raw.get('note', '')
        groups = raw.get('groups', [])
        if profile not in ('normal', 'focus') or not isinstance(active, bool) or not isinstance(rules, list) or not rules or any(x not in ('horizontal', 'flag', 'triangle') for x in rules):
            raise ValueError('invalid-watchlist')
        if not isinstance(name, str) or len(name) > 80 or not isinstance(note, str) or len(note) > 500 or not isinstance(groups, list) or len(groups) > 50 or any(not isinstance(g,str) or len(g)>80 for g in groups):
            raise ValueError('invalid-watchlist')
        if code not in rows:
            rows[code] = dict(symbol=code, name=name, enabled=active, profile=profile, rules=sorted(set(rules)), note=note, groups=sorted(set(groups)))
        else:
            rows[code]['groups'] = sorted(set(rows[code]['groups'] + groups))
    return list(rows.values()), skipped


class MonitorService:
    def __init__(self, store, collect, session, clock=time):
        self.store, self.collect, self.session, self.clock = store, collect, session, clock
        self.lock = RLock();self.step_lock = Lock();self.wake = Event();self.stop_event = Event();self.thread = None
        self.generation = 0
        self.state = store.get(KEY) or dict(version=1, configRevision=0, enabled=False, items=[], runtime={}, migrations=[], lastHeartbeatAt=None, stoppedAt=None, interruption=None)
        self.state.pop('dataRevision', None)
        from pattern_service import triangles_enabled
        upgraded=False
        if triangles_enabled() and 'triangle-rules-v1' not in self.state['migrations']:
            self.state['migrations'].append('triangle-rules-v1')
            for item in self.state['items']:
                if set(item['rules'])=={'horizontal','flag'}:
                    item['rules'].append('triangle');upgraded=True
        if upgraded:self.state['configRevision']+=1
        previous = self.state.get('stoppedAt') or self.state.get('lastHeartbeatAt')
        if self.state['enabled'] and previous:
            self.state['interruption'] = dict(fromAt=previous, resumedAt=stamp(clock()), reason='server-restarted')
            for r in self.state['runtime'].values():r['nextDueAt'] = stamp(clock())
        self.state['stoppedAt'] = None
        self._save()

    def _save(self):
        self.store.put(KEY, {**self.state, 'dataRevision':revision(self.state)})

    def configure(self, items, expected=None, mode='replace', migration=None):
        rows, skipped = watch_items(items)
        if mode not in ('replace', 'preview', 'import') or migration not in (None, 'local-watchlists-v1'):
            raise ValueError('invalid-watchlist')
        if mode == 'replace' and skipped:raise ValueError('unsupported-symbol')
        with self.lock:
            if mode == 'import' and migration in self.state['migrations']:
                return {**self.status(), 'alreadyImported':True}
            existing = {r['symbol']:r for r in self.state['items']}
            merged = dict(existing) if mode in ('preview', 'import') else {}
            for row in rows:
                if mode in ('preview', 'import') and row['symbol'] in existing:
                    row = {**existing[row['symbol']], 'groups':sorted(set(existing[row['symbol']]['groups'] + row['groups']))}
                merged[row['symbol']] = row
            if len(merged) > 20 or sum(r['enabled'] and r['profile']=='focus' for r in merged.values()) > 3:
                raise ValueError('monitor-limit-exceeded')
            if mode == 'preview':
                return dict(items=list(merged.values()), added=sum(r['symbol'] not in existing for r in rows), duplicates=len(items)-len(rows)-len(skipped)+sum(r['symbol'] in existing for r in rows), skipped=skipped, configRevision=self.state['configRevision'], alreadyImported=migration in self.state['migrations'])
            if expected != self.state['configRevision']:
                raise RuntimeError('configuration-changed')
            self.state['items'] = list(merged.values())
            self.state['runtime'] = {k:v for k,v in self.state['runtime'].items() if k in merged}
            now = stamp(self.clock())
            for row in merged.values():
                r = self.state['runtime'].setdefault(row['symbol'], {})
                r['nextDueAt'] = now
            if mode == 'import' and migration and migration not in self.state['migrations']:
                self.state['migrations'].append(migration)
            self.state['configRevision'] += 1;self.generation += 1;self._save();self.wake.set()
            return {**self.status(), 'skipped':skipped}

    def control(self, action):
        if action not in ('start', 'pause'):
            raise ValueError('invalid-control')
        with self.lock:
            self.state['enabled'] = action == 'start'
            self.state['configRevision'] += 1;self.generation += 1
            if action == 'start':
                for r in self.state['runtime'].values():
                    r['nextDueAt'] = stamp(self.clock());r['failStreak'] = 0
            self._save();self.wake.set()
            return self.status()

    def status(self):
        with self.lock:
            out = deepcopy(self.state)
        running = bool(out['enabled'] and self.thread and self.thread.is_alive() and not self.stop_event.is_set())
        rows = []
        for item in out.pop('items'):
            r = out['runtime'].get(item['symbol'], {})
            age=self.clock()-epoch(r['lastSuccessAt']) if r.get('lastSuccessAt') else None
            rows.append({**item, **r, 'sourceAge':round(age,1) if age is not None else None, 'provisionalEligible':bool(out['enabled'] and item['enabled'] and r.get('snapshotEligible') and r.get('status')=='watching' and age is not None and 0<=age<=90), 'status':r.get('status','waiting') if out['enabled'] and item['enabled'] else 'paused'})
        out.pop('runtime')
        out.update(featureEnabled=True, workerState='running' if running else 'waiting-worker' if out['enabled'] else 'paused', items=rows,
                   limits=dict(symbols=20, focus=3), policy='official-all-sessions-plus-30m', errorCount=sum(r.get('status')=='error' for r in rows),
                   lastSuccessAt=max((r['lastSuccessAt'] for r in rows if r.get('lastSuccessAt')), default=None),
                   nextDueAt=min((r['nextDueAt'] for r in rows if out['enabled'] and r['enabled'] and r.get('nextDueAt')), default=None))
        return out

    def events(self, cursor=0):
        with self.lock:
            items = {x['symbol']:x for x in self.state['items']}
        rows = self.store.pattern_events(cursor=cursor, limit=100, with_symbol=True)
        events = [e for e in rows if e.get('timeframe','D') == 'D' and e['symbol'] in items and ('triangle' if e.get('ruleVersion','').startswith('triangle-') else 'flag' if e.get('ruleVersion','').startswith('flag-') else 'horizontal') in items[e['symbol']]['rules']]
        from pattern_service import visible_events
        windows={};events=visible_events(self.store,events,windows,current_only=True)
        return dict(events=events,windowEnds=windows,nextCursor=rows[-1]['cursor'] if rows else cursor)

    def step(self):
        """Process at most one due symbol. Clock/calendar/source are injectable."""
        if not self.step_lock.acquire(blocking=False):return False
        try:
            return self._step()
        finally:
            self.step_lock.release()

    def _step(self):
        now = self.clock()
        with self.lock:
            if not self.state['enabled'] or self.stop_event.is_set():return False
            self.state['lastHeartbeatAt'] = stamp(now)
            due = [x for x in self.state['items'] if x['enabled'] and epoch(self.state['runtime'].get(x['symbol'],{}).get('nextDueAt',stamp(now))) <= now]
            if not due:
                # Persist heartbeat only each minute, not every worker poll.
                if now - getattr(self, '_heartbeat_saved', 0) >= 60:
                    self._heartbeat_saved=now;self._save()
                return False
            # Earliest deadline, then focus, prevents normal-symbol starvation.
            item = min(due, key=lambda x:(epoch(self.state['runtime'].get(x['symbol'],{}).get('nextDueAt',stamp(now))), x['profile']!='focus'))
            code = item['symbol'];generation=self.generation
            runtime = deepcopy(self.state['runtime'].get(code, {}))
        try:
            from pattern_service import triangles_enabled
            session = self.session(code, datetime.fromtimestamp(now, timezone.utc))
            state = session['state'];transition = session.get('nextTransitionAt')
            next_check = min(now+21600, epoch(transition)) if transition and epoch(transition)>now else now+60
            runtime.update(marketState=state, sessionDate=session.get('sessionDate'))
            force = False
            threshold = epoch(session['lastSessionEnd'])+1800 if session.get('lastSessionEnd') else None
            if state == 'unknown':
                runtime.update(status='calendar-unknown', nextDueAt=stamp(now+60))
            elif item['rules']==['triangle'] and not triangles_enabled():
                runtime.update(status='rules-disabled',nextDueAt=stamp(now+60))
            elif state == 'closed' and (threshold is None or now < threshold or runtime.get('closedSlot') == session.get('lastSessionEnd')):
                runtime.update(status='waiting-session', nextDueAt=stamp(min(next_check, threshold) if threshold and threshold>now else next_check))
            else:
                force = state == 'closed'
                with self.lock:
                    if generation != self.generation:return True
                    self.state['runtime'][code]={**runtime,'status':'collecting'};self._save()
                payload = self.collect(code, force=force, background=True)
                if payload.get('lastError') or payload.get('stale'):
                    raise ValueError('source-ineligible')
                fetched = payload.get('fetchedAt')
                if not fetched or epoch(fetched)>self.clock():raise ValueError('source-time-invalid')
                for family,key in (('horizontal','patternAnalysis'),('flag','flagAnalysis'),('triangle','triangleAnalysis')):
                    if family=='triangle' and not triangles_enabled():continue
                    if family in item['rules'] and (not payload.get(key,{}).get('enabled') or payload[key].get('sourceStatus') in ('error','paused','unsupported')):
                        raise ValueError('pattern-ineligible')
                runtime.update(lastSuccessAt=fetched, failStreak=0, errorKind=None, upstreamStatus=None, retryAt=None,
                               sourceDate=payload['candles'][-1]['time'] if payload.get('candles') else None, dataRevision=payload.get('dataRevision'),
                               confirmedThrough=payload.get('lastConfirmedTime'), snapshotEligible=bool(payload.get('snapshotEligible')), patterns=[{k:p.get(k) for k in ('type','status','barTime','triggerPrice','invalidationPrice')} for family,key in (('horizontal','patternAnalysis'),('flag','flagAnalysis'),('triangle','triangleAnalysis')) if family in item['rules'] for p in (payload.get(key,{}).get('timeline') or [{}])[-1].get('patterns',[])], status='confirmed-history' if force else 'watching')
                if force:
                    if epoch(fetched)>=threshold and payload.get('lastConfirmedTime')==session.get('sessionDate') and runtime['sourceDate']==session.get('sessionDate'):
                        runtime['closedSlot'] = session['lastSessionEnd'];runtime['nextDueAt']=stamp(next_check)
                    else:
                        runtime.update(status='waiting-confirmation', nextDueAt=stamp(now+60))
                else:
                    interval=30 if item['profile']=='focus' else 300
                    runtime['nextDueAt']=stamp(min(now+interval,epoch(transition)) if transition and epoch(transition)>now else now+interval)
        except Exception as error:
            streak=runtime.get('failStreak',0)+1
            raw_retry=getattr(error,'retry_at',None)
            try:retry=epoch(raw_retry) if raw_retry else 0
            except (ValueError,TypeError):retry=0
            runtime.update(status='error',failStreak=streak,errorKind=getattr(error,'code',None) or 'collection-failed',
                           upstreamStatus=getattr(error,'status',None),retryAt=raw_retry,nextDueAt=stamp(max(self.clock()+min(30*2**min(streak-1,4),480),retry)))
        with self.lock:
            if generation==self.generation:
                self.state['runtime'][code]=runtime;self._save()
        return True

    def start_worker(self):
        with self.lock:
            if self.thread and self.thread.is_alive():return
            self.stop_event.clear();self.thread=Thread(target=self._run,daemon=True,name='chart-monitor');self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            self.wake.clear()
            try:busy=self.step()
            except Exception:busy=False  # Storage failure must not spin or leak raw exception details.
            self.wake.wait(0.2 if busy else 5)

    def close(self):
        self.stop_event.set();self.wake.set()
        if self.thread:self.thread.join(timeout=2)
        with self.lock:
            self.state['stoppedAt']=stamp(self.clock());self._save()


def services():
    global _INSTANCE
    import market_cache
    from time_contract import market_session
    from serve_dashboard import market_lookup
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            _INSTANCE=MonitorService(market_cache.services().store,market_lookup,market_session)
        return _INSTANCE


def start_runtime():
    import market_cache, pattern_service
    if enabled() and market_cache.enabled() and (pattern_service.enabled() or pattern_service.flags_enabled() or pattern_service.triangles_enabled()):
        services().start_worker()


def handle(handler):
    path=urlparse(handler.path).path
    if not path.startswith('/api/monitor/'):
        return False
    from analysis_jobs import _local, _reply, SESSION_TOKEN
    if not _local(handler):return _reply(handler,403,{'kind':'same-origin-required'})
    import market_cache
    if not enabled() or not market_cache.enabled():return _reply(handler,503,{'kind':'server-monitor-disabled'})
    method=handler.command
    svc=services()
    try:
        if method=='GET' and path=='/api/monitor/status':return _reply(handler,200,svc.status())
        if method=='GET' and path=='/api/monitor/events':
            cursor=int(parse_qs(urlparse(handler.path).query).get('cursor',['0'])[0])
            if cursor<0:raise ValueError('invalid-cursor')
            return _reply(handler,200,svc.events(cursor))
        supplied=handler.headers.get('X-Chart-Session','')
        if len(supplied)>128 or not supplied.isascii() or not compare_digest(supplied,SESSION_TOKEN):
            return _reply(handler,403,{'kind':'session-required'})
        if method not in ('POST','PUT'):return _reply(handler,405,{'kind':'method-not-allowed'})
        length=int(handler.headers.get('Content-Length','0'))
        if not 0<length<=32768 or handler.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('invalid-request')
        body=json.loads(handler.rfile.read(length))
        if path=='/api/monitor/watchlist':
            return _reply(handler,200,svc.configure(body.get('items'),body.get('configRevision'),body.get('mode','replace'),body.get('migration')))
        if path=='/api/monitor/control':return _reply(handler,200,svc.control(body.get('action')))
        return _reply(handler,404,{'kind':'monitor-endpoint-not-found'})
    except RuntimeError:
        return _reply(handler,409,{'kind':'configuration-changed'})
    except (ValueError,TypeError,AttributeError,KeyError,OverflowError):
        return _reply(handler,400,{'kind':'invalid-request-or-limit'})
