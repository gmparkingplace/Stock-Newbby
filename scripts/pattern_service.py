"""Opt-in P2 cached analysis, immutable event basis and local read/settings API."""
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import logging
import os
import re
import sqlite3
import traceback
from secrets import compare_digest
from threading import Lock
from urllib.parse import urlparse, parse_qs
from weakref import WeakKeyDictionary
import market_cache
import perf_probe
from market_store import revision, epoch
from horizontal_patterns import analyze, settings, RULE, rule_version as horizontal_rule
from pattern_window import project, within
from pattern_profiles import rule_version

LOGGER = logging.getLogger(__name__)

# Repeated identical inputs (cache hits, retries, several tabs) must not rerun a
# pure engine or re-publish an unchanged basis. Entries are per store instance so
# separate caches/tests never share results.
_COMPUTE_CACHE = WeakKeyDictionary()
_COMPUTE_LOCK = Lock()
_COMPUTE_LIMIT = 8


def _compute_cache(store):
    with _COMPUTE_LOCK:
        cache = _COMPUTE_CACHE.get(store)
        if cache is None:
            cache = _COMPUTE_CACHE[store] = OrderedDict()
        return cache


def _signature(key, payload, cutoff, provisional, eligible, previous, input_hash):
    """Everything a pure computation depends on. Source times are re-applied per response."""
    return (key, payload.get('dataRevision'), input_hash, cutoff, bool(provisional), bool(eligible),
            payload.get('nextConfirmationAt'), payload.get('confirmedPolicy'),
            (previous or {}).get('dataRevision'))


def _remember(cache, signature, result, copy=None):
    if copy is None:
        copy = deepcopy(result)
    with _COMPUTE_LOCK:
        cache[signature] = copy
        cache.move_to_end(signature)
        while len(cache) > _COMPUTE_LIMIT:
            cache.popitem(last=False)
    return copy


def analysis_failure(error, symbol, family):
    """Record code locations, never provider payloads or exception messages."""
    invalid = isinstance(error, ValueError) and str(error) in (
        'invalid-bar-order', 'invalid-ohlcv', 'invalid-confirmed-cutoff')
    code = 'invalid-data' if invalid else 'storage-error' if isinstance(error, sqlite3.Error) else 'calculation-error'
    safe_symbol = re.sub(r'[^A-Za-z0-9_.^=-]', '_', str(symbol))[:80]
    frames = ' > '.join(f'{os.path.basename(f.filename)}:{f.lineno}:{f.name}'
                        for f in traceback.extract_tb(error.__traceback__))
    LOGGER.error('pattern-analysis-failed family=%s symbol=%s code=%s exception=%s frames=%s',
                 family, safe_symbol, code, type(error).__name__, frames)
    return dict(enabled=True, sourceStatus='error', errorCode=code)


def enabled():
    value = os.environ.get('CHART_HORIZONTAL_PATTERNS')
    if value is not None:
        return value == '1'
    try:
        return json.loads((market_cache.ROOT/'.local.json').read_text()).get('horizontalPatterns') is True
    except (OSError, ValueError):
        return False


def flags_enabled():
    value=os.environ.get('CHART_FLAG_PATTERNS')
    if value is not None:return value=='1'
    try:return json.loads((market_cache.ROOT/'.local.json').read_text()).get('flagPatterns') is True
    except (OSError,ValueError):return False



def triangles_enabled():
    value=os.environ.get('CHART_TRIANGLE_PATTERNS')
    if value is not None:return value=='1'
    try:return json.loads((market_cache.ROOT/'.local.json').read_text()).get('trianglePatterns') is True
    except (OSError,ValueError):return False


def structures_enabled():
    value=os.environ.get('CHART_STRUCTURE_PATTERNS')
    if value is not None:return value=='1'
    try:return json.loads((market_cache.ROOT/'.local.json').read_text()).get('structurePatterns') is True
    except (OSError,ValueError):return False


def structure_evidence_v2_enabled():
    """Parallel evidence engine. Off by default; never feeds the existing judgment."""
    value=os.environ.get('CHART_STRUCTURE_EVIDENCE_V2')
    if value is not None:return value=='1'
    try:return json.loads((market_cache.ROOT/'.local.json').read_text()).get('structureEvidenceV2') is True
    except (OSError,ValueError):return False


def structure_evidence_supported(symbol,timeframe):
    from universe import is_coin
    if timeframe!='D' or symbol.startswith('^') or is_coin(symbol):return False
    return True


def evaluate_structure_evidence(payload,now=None):
    """Stock daily only. Recomputes from confirmed candles; stores nothing."""
    from structure_lifecycle_v2 import analyze as evidence_engine
    now=now or datetime.now(timezone.utc)
    symbol=payload['symbol'];tf=payload.get('tf','D')
    if not structure_evidence_supported(symbol,tf):
        return dict(enabled=True,symbol=symbol,timeframe=tf,sourceStatus='unsupported',
                    reason='stock-daily-only')
    session=payload.get('marketSession',{}) or {}
    eligible=(session.get('state') not in (None,'unknown') and not payload.get('stale')
              and not payload.get('lastError')
              and bool(payload.get('lastConfirmedTime') or payload.get('snapshotEligible')))
    # Even when the feed is not eligible, keep evaluating to the last confirmed
    # bar of the stored snapshot: history stays visible, new judgment is paused.
    cutoff=payload.get('lastConfirmedTime') or None
    result=evidence_engine(payload['candles'],symbol,cutoff,timeframe='D',
                           data_revision=payload.get('dataRevision'),
                           adjustment_policy=payload.get('adjustmentPolicy','provider-adjusted'))
    result.update(sourceFetchedAt=payload.get('fetchedAt'),evaluatedAt=now.isoformat(),
                  provisionalEligible=False)
    if not eligible:
        result['sourceStatus']='paused'
        result['reason']='data-paused'
        for pattern in result.get('patterns') or []:
            pattern['dataEligibility']=dict(pattern.get('dataEligibility') or {},
                                           state='paused',reason='data-paused')
    return result

def settings_key(symbol, timeframe='D'):
    return 'pattern-levels|'+symbol+('' if timeframe == 'D' else '|'+timeframe)


def get_settings(store, symbol, timeframe='D'):
    value = store.get(settings_key(symbol, timeframe))
    return settings(value.get('levels') if value else None)


def supported(symbol, timeframe, family):
    from universe import is_coin
    from intraday_timeframes import is_intraday
    if symbol.startswith('^'):return False
    intraday = is_intraday(timeframe)
    if is_coin(symbol):return (timeframe == 'D' or intraday) and family in ('flag','triangle','structure')
    return timeframe == 'D' or intraday


def valid_timeframe(timeframe):
    from intraday_timeframes import is_intraday
    return timeframe == 'D' or is_intraday(timeframe)


def result_key(symbol, levels, family='horizontal', timeframe='D'):
    if family=='triangle':
        from triangle_patterns import RULE as triangle_rule
        return '|'.join(('triangle',symbol,timeframe,rule_version('triangle',timeframe)))
    if family=='flag':
        from flag_patterns import RULE as flag_rule
        return '|'.join(('flag',symbol,timeframe,rule_version('flag',timeframe)))
    if family=='structure':
        from structure_patterns import RULE as structure_rule
        return '|'.join(('structure',symbol,timeframe,rule_version('structure',timeframe)))
    return '|'.join(('horizontal', symbol, timeframe, horizontal_rule(timeframe), revision(settings(levels))[:16]))


def semantic(event):
    return {k:v for k,v in event.items() if k not in ('basisSnapshotId','dataRevision','sourceFetchedAt','evaluatedAt','detectedAt','origin','confirmedAt','barEndAt')}


def visible_events(store, events, references=None, current_only=False):
    references={} if references is None else references;visible=[];versions={}
    for event in events:
        symbol=event['symbol']
        tf=event.get('timeframe','D');key=symbol if tf=='D' else symbol+'#'+tf
        if current_only:
            family='triangle' if event.get('ruleVersion','').startswith('triangle-') else 'flag' if event.get('ruleVersion','').startswith('flag-') else None
            if family:
                ident=(symbol,tf,family)
                if ident not in versions:
                    result=store.pattern_result(result_key(symbol,{},family,tf))
                    versions[ident]=result.get('ruleVersion') if result else None
                if versions[ident] and event.get('ruleVersion')!=versions[ident]:continue
        if key not in references:references[key]=store.pattern_latest_date(symbol,tf)
        if within(event,references[key]):visible.append(event)
    return visible


def evaluate(payload, store, now=None, family='horizontal', levels_override=None):
    """No provider access. Session/confirmation must already be validated by caller."""
    now = now or datetime.now(timezone.utc)
    symbol = payload['symbol']
    tf=payload.get('tf','D')
    if not supported(symbol,tf,family):return dict(enabled=True,symbol=symbol,timeframe=tf,sourceStatus='unsupported')
    from universe import is_coin
    from intraday_timeframes import is_intraday
    if is_intraday(tf) and not is_coin(symbol) and any('missingBarsBefore' not in r for r in payload['candles']):
        return dict(enabled=True, symbol=symbol, timeframe=tf, sourceStatus='unsupported',
                    reason='session-continuity-required')
    engine,rule=analyze,horizontal_rule(tf)
    if family=='flag':
        from flag_patterns import analyze as engine, RULE as rule
    elif family=='triangle':
        from triangle_patterns import analyze as engine, RULE as rule
    elif family=='structure':
        from structure_patterns import analyze as engine, RULE as rule
    if family in ('flag','triangle','structure'):rule=rule_version(family,tf)
    # Read the published basis only; the calculation itself must not hold the
    # store lock while other requests read or publish.
    with store.lock:
        levels = (deepcopy(levels_override) if levels_override is not None else get_settings(store, symbol, tf)) if family=='horizontal' else {}
        key = result_key(symbol, levels,family,tf)
        previous = store.pattern_result(key)
    session = payload.get('marketSession', {})
    eligible = session.get('state') not in (None, 'unknown') and not payload.get('stale') and not payload.get('lastError')
    eligible = bool(eligible and (payload.get('lastConfirmedTime') or payload.get('snapshotEligible')))
    if previous and epoch(previous['sourceFetchedAt']) > epoch(payload['fetchedAt']):
        eligible = False
    age = now.timestamp()-epoch(payload['fetchedAt'])
    provisional = eligible and payload.get('snapshotEligible') and 0 <= age <= 90
    cutoff = payload.get('lastConfirmedTime') if eligible else None
    cache = _compute_cache(store)
    input_hash = revision(payload.get('candles') or [])
    signature = _signature(key, payload, cutoff, provisional, eligible, previous, input_hash)
    with _COMPUTE_LOCK:
        cached = cache.get(signature)
    if cached is not None:
        with perf_probe.span('patterns', family+'.reuse'):
            result = deepcopy(cached)
            result.update(enabled=True, dataRevision=payload['dataRevision'], sourceFetchedAt=payload['fetchedAt'],
                          evaluatedAt=now.isoformat(), sourceStatus='ready' if eligible else 'paused',
                          provisionalEligible=bool(provisional), sessionPolicy=payload.get('confirmedPolicy', 'market-calendar'))
            result['recentEvents'] = store.pattern_recent(symbol,rule=rule,
                reference=(result.get('timeline') or [{}])[-1].get('barTime'))
            return project(result)
    with perf_probe.span('patterns', family+'.compute'):
        result = engine(payload['candles'], symbol, cutoff, bool(provisional), levels, timeframe=tf)
    result.update(enabled=True, dataRevision=payload['dataRevision'], sourceFetchedAt=payload['fetchedAt'],
                  evaluatedAt=now.isoformat(), sourceStatus='ready' if eligible else 'paused',
                  provisionalEligible=bool(provisional), sessionPolicy=payload.get('confirmedPolicy', 'market-calendar'))
    if eligible:
        with store.lock:
            # Another request may have published newer input while this one was
            # calculating. Never overwrite it with an older computation.
            current = store.pattern_result(key)
            if ((current or {}).get('dataRevision') != (previous or {}).get('dataRevision')
                    or (current and epoch(current['sourceFetchedAt']) > epoch(payload['fetchedAt']))):
                current = False
            else:
                current = True
            if current:
                with perf_probe.span('patterns', family+'.publish'):
                    pairs = []
                    now_events = {e['eventId']:e for e in result['events']}
                    tracked = deepcopy(previous.get('trackedEvents', {})) if previous else {}
                    hashes = {str(x['time']):revision(x) for x in payload['candles']}
                    prior_hashes = previous.get('barHashes',{}) if previous else {}
                    # Only genuine overlap corrections revise old events; an advancing history window alone cannot.
                    corrected = any(prior_hashes[t] != h for t,h in hashes.items() if t in prior_hashes)
                    if hashes:
                        corrected = corrected or any(min(hashes)<=t<=max(hashes) and t not in hashes for t in prior_hashes)
                    result['barHashes'] = hashes
                    changes = []
                    # Never retract events solely because the oldest history rolled out.
                    same_start=bool(prior_hashes and min(prior_hashes)==str(payload['candles'][0]['time']))
                    warmup=(14 if same_start else 74) if family=='triangle' else (17 if same_start else 54) if family=='flag' else (18 if same_start else 60) if family=='structure' else 21
                    comparable_from = payload['candles'][warmup]['time'] if len(payload['candles']) > warmup else None
                    if previous and previous['dataRevision'] != result['dataRevision'] and corrected:
                        for ident, record in tracked.items():
                            old = record['basis']
                            if comparable_from is not None and cutoff is not None and comparable_from <= old['anchorTime'] and old['confirmedBarTime'] <= cutoff:
                                new = now_events.get(ident)
                                after = semantic(new) if new else None
                                if record['last'] != after:
                                    basis_row = next((r for r in payload['candles'] if r['time']==old['confirmedBarTime']),None)
                                    changes.append(dict({**old,**(new or {})}, eventType='revised', status='revised',
                                        close=basis_row['close'] if basis_row else None,
                                        eventId=revision([ident,'revised',result['dataRevision'],after]),
                                        revisesEventId=ident, before=record['last'], after=after,
                                        revisionReason='source-correction'))
                                    record['last'] = after
                    for ident, event in now_events.items():
                        tracked[ident] = dict(basis=semantic(event),last=semantic(event))
                    result['trackedEvents'] = tracked
                    for event in result['events']+changes:
                        bar_end = None
                        if event['confirmedBarTime'] == payload['candles'][-1]['time'] and payload.get('nextConfirmationAt'):
                            try:
                                stamp = datetime.fromisoformat(payload['nextConfirmationAt'].replace('Z','+00:00'))
                                if stamp.tzinfo is not None:
                                    bar_end = (stamp-timedelta(minutes=30)).isoformat()
                            except (TypeError,ValueError):
                                pass
                        event.update(barEndAt=bar_end,dataRevision=result['dataRevision'], sourceFetchedAt=payload['fetchedAt'],
                                     detectedAt=now.isoformat(), confirmedAt=payload['fetchedAt'],
                                     origin='initial-history' if previous is None else 'source-update')
                        # Conservative received-source confirmation time. Not a guessed historical session close.
                        snap_id = revision([event['eventId'],result['dataRevision'],payload['fetchedAt']])
                        event['basisSnapshotId'] = snap_id
                        frozen = [x for x in payload['candles'] if x['time'] <= event['confirmedBarTime']]
                        snapshot = dict(snapshotId=snap_id, symbol=symbol, name=payload.get('name', symbol), timeframe=tf,
                            source=payload.get('source'), fetchedAt=payload['fetchedAt'], dataRevision=result['dataRevision'],
                            adjustmentPolicy='provider-adjusted', ruleVersion=rule, confirmedThrough=cutoff,
                            sessionPolicy=result['sessionPolicy'], candles=frozen, basisBarAvailable=any(x['time']==event['confirmedBarTime'] for x in frozen), event=deepcopy(event))
                        pairs.append((event,snapshot))
                    store.pattern_publish(key, result, pairs)
                published = _remember(cache, signature, result)
                _remember(cache, _signature(key, payload, cutoff, provisional, eligible,
                                            {'dataRevision': result['dataRevision']}, input_hash), None, published)
    else:
        _remember(cache, signature, result)
    reference=(result.get('timeline') or [{}])[-1].get('barTime')
    result['recentEvents'] = store.pattern_recent(symbol,rule=rule,reference=reference)
    return project(result)


def attach(payload):
    if (not enabled() and not flags_enabled() and not triangles_enabled()
            and not structures_enabled() and not structure_evidence_v2_enabled()):
        return payload
    output=dict(payload)
    for feature,family,on in (('patternAnalysis','horizontal',enabled()),('flagAnalysis','flag',flags_enabled()),('triangleAnalysis','triangle',triangles_enabled()),('structureAnalysis','structure',structures_enabled())):
        if not on:continue
        if not market_cache.enabled():
            output[feature]=dict(enabled=False,sourceStatus='shared-cache-disabled');continue
        if not supported(payload['symbol'],payload.get('tf','D'),family):
            output[feature]=dict(enabled=True,timeframe=payload.get('tf','D'),sourceStatus='unsupported');continue
        try:output[feature]=evaluate(payload,market_cache.services().store,family=family)
        except Exception as error:
            output[feature]=analysis_failure(error,payload['symbol'],family)
            if payload.get('tf')!='D':output[feature]['timeframe']=payload.get('tf')
    return attach_evidence(output)


def attach_evidence(payload):
    """Add only the parallel evidence field. It needs no shared cache store."""
    if not structure_evidence_v2_enabled():
        return payload
    output=dict(payload)
    try:output['structureEvidenceV2']=evaluate_structure_evidence(payload)
    except Exception as error:
        output['structureEvidenceV2']=analysis_failure(error,payload['symbol'],'structure-evidence-v2')
        if payload.get('tf')!='D':output['structureEvidenceV2']['timeframe']=payload.get('tf')
    return output


def handle(handler):
    parsed = urlparse(handler.path)
    path = parsed.path
    if path not in ('/api/patterns','/api/events','/api/pattern-levels') and not path.startswith(('/api/events/','/api/snapshots/')):
        return False
    from analysis_jobs import _local, _reply, SESSION_TOKEN
    if not _local(handler): return _reply(handler,403,{'kind':'same-origin-required'})
    if not (enabled() or flags_enabled() or triangles_enabled() or structures_enabled()) or not market_cache.enabled(): return _reply(handler,503,{'kind':'patterns-disabled'})
    if handler.command != 'GET':
        token = handler.headers.get('X-Chart-Session','')
        if not token.isascii() or len(token)>128 or not compare_digest(token,SESSION_TOKEN):
            return _reply(handler,403,{'kind':'session-required'})
    store = market_cache.services().store
    query = parse_qs(parsed.query)
    try:
        from universe import norm_code
        raw = query.get('symbol',[''])[0]
        if len(raw)>80: raise ValueError('invalid-symbol')
        symbol = norm_code(raw) if raw else None
        if path == '/api/patterns' and handler.command == 'GET':
            if not symbol: raise ValueError('symbol-required')
            tf=query.get('tf',['D'])[0]
            family=query.get('kind',['horizontal'])[0]
            if family not in ('horizontal','flag','triangle','structure'):raise ValueError('invalid-kind')
            if not ({'horizontal':enabled,'flag':flags_enabled,'triangle':triangles_enabled,'structure':structures_enabled}[family]()):return _reply(handler,503,{'kind':'feature-disabled'})
            if not supported(symbol,tf,family):return _reply(handler,200,dict(enabled=True,symbol=symbol,sourceStatus='unsupported',timeframe=tf))
            levels=get_settings(store,symbol,tf) if family=='horizontal' else {}
            result = store.pattern_result(result_key(symbol,levels,family,tf))
            if result:
                # A read cannot renew source freshness or promote the cached unfinished bar.
                result['cachedResult'] = True
                result['readAt'] = datetime.now(timezone.utc).isoformat()
                age = datetime.now(timezone.utc).timestamp()-epoch(result['sourceFetchedAt'])
                if not 0 <= age <= 90:
                    result['provisionalEligible'] = False
                    for row in result['timeline']:
                        if not row['confirmed']:
                            for level in row.get('levels',row.get('patterns',[])): level['status'] = 'paused'
            if result:result['recentEvents']=store.pattern_recent(symbol,rule=result['ruleVersion'],reference=(result.get('timeline') or [{}])[-1].get('barTime'))
            return _reply(handler,200,project(result) or dict(symbol=symbol,timeframe=tf,sourceStatus='not-collected',levels=levels))
        if path == '/api/events' and handler.command == 'GET':
            cursor = int(query.get('cursor',['0'])[0])
            if cursor < 0: raise ValueError('invalid-cursor')
            events = store.pattern_events(symbol,cursor,with_symbol=True)
            tf=query.get('tf',[None])[0]
            if tf is not None and not valid_timeframe(tf):raise ValueError('invalid-timeframe')
            visible=visible_events(store,[e for e in events if tf is None or e.get('timeframe','D')==tf])
            return _reply(handler,200,{'events':visible,'nextCursor':events[-1]['cursor'] if events else cursor})
        if path.startswith('/api/events/') and handler.command == 'GET':
            value = store.pattern_event(path.rsplit('/',1)[1])
            return _reply(handler,200 if value else 404,value or {'kind':'event-not-found'})
        if path.startswith('/api/snapshots/') and handler.command == 'GET':
            value = store.pattern_snapshot(path.rsplit('/',1)[1])
            return _reply(handler,200 if value else 404,value or {'kind':'snapshot-not-found'})
        if path == '/api/pattern-levels' and handler.command == 'POST':
            length = int(handler.headers.get('Content-Length','0'))
            if not 0<length<=1024 or handler.headers.get('Content-Type','').split(';')[0] != 'application/json': raise ValueError('invalid-request')
            body = json.loads(handler.rfile.read(length))
            raw = body.get('symbol')
            if not isinstance(raw,str) or not 0<len(raw)<=80: raise ValueError('invalid-symbol')
            symbol = norm_code(raw)
            from universe import is_coin
            if not symbol or is_coin(symbol) or symbol.startswith('^'): raise ValueError('unsupported-symbol')
            levels = settings(body.get('levels'))
            tf = body.get('tf', 'D')
            if not valid_timeframe(tf): raise ValueError('invalid-timeframe')
            store.put(settings_key(symbol,tf),dict(levels=levels,dataRevision=revision(levels)))
            return _reply(handler,200,dict(symbol=symbol,timeframe=tf,levels=levels,requiresRefresh=True))
        return _reply(handler,405,{'kind':'method-not-allowed'})
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
        return _reply(handler,400,{'kind':'invalid-request'})
