#!/usr/bin/env python3
"""Loopback fixture transport; control requests use the production mailbox unchanged."""
import argparse
import copy
import datetime as dt
import json
import mimetypes
from pathlib import Path
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

ROOT = Path(__file__).resolve().parents[2]
DASH = ROOT / 'results/dashboard'
sys.path.insert(0, str(ROOT / 'scripts'))
import chart_control
import serve_dashboard as production
import time_contract
import toss_market
import toss_catalog
import market_cache
import pattern_service
import monitor_service
from types import SimpleNamespace
from market_store import MarketStore, revision
PATTERN_STORE = MarketStore(':memory:')
market_cache.enabled = lambda: CONFIG.get("monitor",False)

EPOCH = dt.datetime(2026, 9, 7, 6, tzinfo=dt.timezone.utc)
START = time.monotonic()

def clock():
    base = dt.datetime.fromisoformat(CONFIG['now']) if CONFIG.get('now') else EPOCH
    return (base + dt.timedelta(seconds=time.monotonic()-START)).isoformat()
LOCK = threading.RLock()
GATE = threading.Event()
GATE.set()
DEFAULTS = {'blockDelivery': False, 'holdSymbol': None, 'futureVolumeAfter': None,
            'futureVolumeFactor': 1, 'disableStaleGuard': False, 'now': None,
            'sourceThrough':'2026-09-07','priceMode':'candidate','restError':False,
            'calendarError':False,'keepSource':False,'perSymbol':{},'patterns':False,'flags':False,'monitor':False,'triangles':False,'triangleKind':'ascending','triangleDirection':'up','triangleBreakout':True}
CONFIG = dict(DEFAULTS)
EVENTS = []

SOURCE = {}


class FixtureDateTime(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls.fromisoformat(clock())
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


time_contract.datetime = FixtureDateTime
toss_market.enabled = lambda: True
toss_catalog.resolve = lambda code: code


def provider_get(path, **params):
    if path == '/api/v1/stocks':
        return [{'name': '삼성전자' if params['symbols'].isdigit() else 'Apple'}]
    if not path.startswith('/api/v1/market-calendar/'):
        raise AssertionError('unexpected provider endpoint')
    if CONFIG['calendarError']:
        raise toss_market.TossError('calendar-fixture-error')
    market = path.rsplit('/', 1)[1]
    query = dt.date.fromisoformat(params['date'])
    before, after = query-dt.timedelta(days=1), query+dt.timedelta(days=1)
    while before.weekday()>4: before-=dt.timedelta(days=1)
    while after.weekday()>4: after+=dt.timedelta(days=1)
    def day(value):
        sessions = dict.fromkeys(['preMarket','regularMarket','afterMarket'] if market=='KR'
                                 else ['dayMarket','preMarket','regularMarket','afterMarket'])
        if value.weekday()<5:
            zone = '+09:00' if market=='KR' else '-04:00'
            sessions['regularMarket']={'startTime':f'{value}T09:00:00{zone}','endTime':f'{value}T15:30:00{zone}'}
            sessions['afterMarket']={'startTime':f'{value}T16:00:00{zone}','endTime':f'{value}T20:00:00{zone}'}
        return {'date':str(value),**({'integrated':sessions if value.weekday()<5 else None} if market=='KR' else sessions)}
    return dict(today=day(query),previousBusinessDay=day(before),nextBusinessDay=day(after))


toss_market.CLIENT.get = provider_get


def source_daily(symbol, timezone, force=False):
    with LOCK:
        config = dict(CONFIG)
        ps = config.get('perSymbol', {}).get(symbol, {})
    if 'priceMode' in ps: config['priceMode'] = ps['priceMode']
    if 'restError' in ps: config['restError'] = ps['restError']
    if config['restError']:
        raise toss_market.TossError('source-fixture-error')
    if config['keepSource'] and symbol in SOURCE:
        rows, fetched = SOURCE[symbol]
        return copy.deepcopy(rows), True, fetched
    kr = symbol == '005930.KS'
    base, step = (70000, 40) if kr else (180, .31)
    dates = []
    day = dt.date(2025, 12, 1)
    while day <= dt.date.fromisoformat(config['sourceThrough']):
        if day.weekday() < 5:
            dates.append(day.isoformat())
        day += dt.timedelta(days=1)
    if config['triangles']:
        sys.path.insert(0,str(ROOT/'tests'))
        from triangle_fixture import triangle_rows
        target=triangle_rows(config['triangleKind'],config['triangleDirection'],breakout=config['triangleBreakout'])
        days=dates[-len(target):]
        rows=[dict(t=str(day),open=r['open'],high=r['high'],low=r['low'],close=r['close'],volume=r['volume']) for r,day in zip(target,days)]
        fetched=clock();SOURCE[symbol]=(copy.deepcopy(rows),fetched)
        return rows,False,fetched
    elif config['flags']:
        sys.path.insert(0,str(ROOT/'tests'))
        from flag_fixture import flag_rows
        rows=flag_rows('up' if symbol=='005930.KS' else 'down')
        for r,t in zip(rows,dates[-len(rows):]):r['t']=t;r.pop('time')
        fetched=clock();SOURCE[symbol]=(copy.deepcopy(rows),fetched)
        return rows,False,fetched
    rows = []
    for i, day in enumerate(dates):
        price = round(base + i * step, 2)
        rows.append(dict(t=day, open=price-step, high=price+2*step,
                         low=price-2*step, close=price, volume=(1000+i*17)*(100 if kr else 1)))
    last=rows[-1]
    if config['priceMode']=='candidate':
        last['close'] += 2*step
        last['high'] = last['close']+step
        last['volume'] *= 2
    elif config['priceMode']=='chase':
        last['close'] += 20*step
        last['high'] = last['close']+step
        last['volume'] *= 2
    elif config['priceMode']=='avoid':
        last['close'] -= 30*step
        last['low'] = last['close']-step
    for row in rows:
        if config['futureVolumeAfter'] and row['t'] > config['futureVolumeAfter']:
            row['volume'] *= config['futureVolumeFactor']
    fetched=clock()
    SOURCE[symbol]=(copy.deepcopy(rows),fetched)
    return rows,False,fetched


toss_market.CANDLES.daily = source_daily


def source_minute(symbol, timezone, force=False):
    from zoneinfo import ZoneInfo
    daily, cached, fetched = source_daily(symbol, timezone, force)
    rows = []
    for row in daily:
        start = dt.datetime.fromisoformat(row['t']).replace(hour=9, minute=0 if symbol.endswith('.KS') else 30,
                                                          tzinfo=ZoneInfo(timezone))
        for offset in (0, 240):
            rows.append({**row, 't':int((start+dt.timedelta(minutes=offset)).timestamp()),
                         'volume':row['volume']/2})
    return rows, cached, fetched, revision(rows), {'stop':'fixture-history'}


toss_market.CANDLES.minute = source_minute


def fixture(symbol, force=False):
    result=production.market_lookup(symbol, force=force)
    if CONFIG['patterns']:
        result['dataRevision'] = revision(result['candles'])
        result['patternAnalysis'] = pattern_service.evaluate(result,PATTERN_STORE,FixtureDateTime.now(dt.timezone.utc))
    if CONFIG['flags']:
        result['dataRevision']=revision(result['candles'])
        result['flagAnalysis']=pattern_service.evaluate(result,PATTERN_STORE,FixtureDateTime.now(dt.timezone.utc),family='flag')
    if CONFIG['triangles']:
        result['dataRevision']=revision(result['candles'])
        result['triangleAnalysis']=pattern_service.evaluate(result,PATTERN_STORE,FixtureDateTime.now(dt.timezone.utc),family='triangle')
    return {**result,'servedAt':clock()}


class FixtureCandles:
    def daily(self,code,tz,force=False,reconcile_after=None):
        rows,cached,fetched=source_daily(code,tz,force)
        return rows,cached,fetched,revision(rows)

class FixtureCache:
    store=PATTERN_STORE
    candles=FixtureCandles()
    lock=LOCK
    minutes=SimpleNamespace(minute=source_minute)
    def lookup(self,provider,code,tf,fn,force=False,background=False):
        result=fn(force);return {**result,'stale':False,'cacheHit':False,'cacheAge':0}

market_cache.services=lambda:FixtureCache()
pattern_service.enabled=lambda:CONFIG['patterns']
pattern_service.flags_enabled=lambda:CONFIG['flags']
pattern_service.triangles_enabled=lambda:CONFIG['triangles']
monitor_service.enabled=lambda:CONFIG['monitor']

def monitor_collect(code,**kwargs):
    with LOCK:EVENTS.append({'kind':'monitor-collect','symbol':code})
    return fixture(code,force=kwargs.get('force',False))

MONITOR=monitor_service.MonitorService(PATTERN_STORE,monitor_collect,lambda code,now:time_contract.market_session(code,now.isoformat()),lambda:dt.datetime.fromisoformat(clock()).timestamp())
monitor_service.services=lambda:MONITOR

EARLY = """<script>
window.__jsErrors=[];window.__jsRejections=[];
{const original=window.fetch;window.fetch=function(url,options){if(String(url)==='/api/control/poll')window.__controlTab=JSON.parse(options.body).tab;return original.apply(this,arguments);};}
addEventListener('error',e=>window.__jsErrors.push(String(e.message)));
addEventListener('unhandledrejection',e=>window.__jsRejections.push(String(e.reason)));
{const RealDate=Date;let start=RealDate.now(),epoch=RealDate.parse('__CLOCK__');
window.__setClock=iso=>{epoch=RealDate.parse(iso);start=RealDate.now();};
window.Date=class extends RealDate {constructor(...a){super(...(a.length?a:[epoch+RealDate.now()-start]));} static now(){return epoch+RealDate.now()-start;}};}
</script>"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # No URLs, headers, local configuration or request bodies in logs.

    def send(self, status, raw, kind='application/json'):
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def reply(self, obj, status=200):
        self.send(status, json.dumps(obj, ensure_ascii=False).encode())

    def do_POST(self):
        self.route()

    def do_PUT(self):
        self.route()

    def do_GET(self):
        self.route()

    def route(self):
        u = urlparse(self.path)
        p = u.path
        if p == '/api/control/poll' and CONFIG['blockDelivery']:
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            self.reply({'command': None})
            return
        if monitor_service.handle(self):
            return
        if p=='/api/analysis-session':
            from analysis_jobs import SESSION_TOKEN
            return self.reply({'sessionToken':SESSION_TOKEN})
        if chart_control.handle(self):
            return
        if p.startswith('/api/test/'):
            if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
                return self.reply({'error':'loopback required'}, 403)
            if p == '/api/test/config' and self.command == 'POST':
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
                with LOCK:
                    if body.get('reset'):
                        MONITOR.control('pause')
                        MONITOR.configure([],MONITOR.state['configRevision'])
                        MONITOR.state['migrations']=[]
                        with PATTERN_STORE.lock, PATTERN_STORE.db:
                            for table in ('pattern_results','pattern_events','pattern_snapshots'):
                                PATTERN_STORE.db.execute('DELETE FROM '+table)
                        EVENTS.clear()
                        CONFIG.update(DEFAULTS)
                        SOURCE.clear()
                        GATE.set()
                    CONFIG.update({k:v for k,v in body.items() if k in CONFIG})
                    time_contract._CALENDAR_CACHE.clear()
                    if body.get('holdSymbol'):
                        GATE.clear()
                    if body.get('release'):
                        CONFIG['holdSymbol'] = None
                        GATE.set()
                if CONFIG['monitor']:MONITOR.start_worker()
                return self.reply(dict(CONFIG))
            if p == '/api/test/state':
                with LOCK:
                    return self.reply({'events': list(EVENTS), 'config': dict(CONFIG), 'clock':clock()})
            if p == '/api/test/fixtures':
                return self.reply({s:fixture(s) for s in ('005930.KS','AAPL')})
            return self.reply({'error':'unknown test endpoint'}, 404)
        if p.startswith('/api/snapshots/'):
            snap = PATTERN_STORE.pattern_snapshot(p.rsplit('/',1)[1])
            return self.reply(snap or {'kind':'snapshot-not-found'},200 if snap else 404)
        if p.startswith('/api/events/'):
            event = PATTERN_STORE.pattern_event(p.rsplit('/',1)[1])
            return self.reply(event or {'kind':'event-not-found'},200 if event else 404)
        if p == '/api/events':
            query = parse_qs(u.query)
            events = PATTERN_STORE.pattern_events(query.get('symbol',[None])[0],int(query.get('cursor',['0'])[0]),with_symbol=True)
            visible=pattern_service.visible_events(PATTERN_STORE,events)
            return self.reply({'events':visible,'nextCursor':events[-1]['cursor'] if events else 0})
        if p == '/api/patterns':
            symbol = parse_qs(u.query).get('symbol',['005930.KS'])[0]
            family=parse_qs(u.query).get('kind',['horizontal'])[0]
            return self.reply(pattern_service.project(PATTERN_STORE.pattern_result(pattern_service.result_key(symbol,{},family))))
        if p in ('/api/lookup','/api/intraday'):
            symbol = parse_qs(u.query).get('code', [''])[0]
            if symbol not in ('005930.KS','AAPL'):
                return self.reply({'error':'no fixture', 'kind':'nodata'}, 404)
            with LOCK:
                EVENTS.append({'kind':'received', 'symbol':symbol})
                hold = symbol == CONFIG['holdSymbol']
            if hold and not GATE.wait(18):
                return self.reply({'error':'gate timeout'}, 504)
            try:
                force = parse_qs(u.query).get('force') == ['1']
                payload = production.market_intraday(symbol, force=force) if p == '/api/intraday' else fixture(symbol, force=force)
            except toss_market.TossError:
                return self.reply({'error':'fixture source request failed','kind':'provider'},503)
            self.reply(payload)
            with LOCK:
                EVENTS.append({'kind':'delivered', 'symbol':symbol})
            return
        if p == '/api/market-provider':
            return self.reply({'provider':'yfinance', 'realtime':False})
        if p in ('/api/universe','/api/health','/api/search'):
            return self.send(200, (Path(__file__).parent/'fixtures'/f'{p.rsplit("/",1)[1]}.json').read_bytes())
        if p == '/api/related':
            return self.reply({'related':[]})
        if p.startswith('/api/'):
            return self.reply({'error':'no fixture', 'kind':'nodata'}, 404)
        target = (DASH / unquote(p).lstrip('/')).resolve() if p != '/' else DASH/'chart-first.html'
        if not target.is_relative_to(DASH) or not target.is_file():
            return self.reply({'error':'not found'}, 404)
        raw = target.read_bytes()
        if target.name == 'chart-first.html':
            text = raw.decode().replace('<head>', '<head>'+EARLY.replace('__CLOCK__', clock()), 1)
            if CONFIG['disableStaleGuard']:
                text = text.replace('if (mySeq !== reqSeq) { result = {ok:false, cancelled:true}; }', 'if (false) { result = {ok:false, cancelled:true}; }')
            raw = text.encode()
        self.send(200, raw, mimetypes.guess_type(target.name)[0] or 'application/octet-stream')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=9444)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'fixture server ready port={server.server_port}; production chart_control mailbox', flush=True)
    try:
        server.serve_forever()
    finally:
        GATE.set()
        server.server_close()
