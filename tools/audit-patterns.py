"""Audit cached public patterns offline; active SQLite is opened read-only.

Replay, concurrent publication and restarts modify only a disposable backup.
No provider calls, browser, monitor setting changes or trading operations.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from market_store import MarketStore, revision
from pattern_service import evaluate, get_settings, result_key
from pattern_window import within
import horizontal_patterns
import flag_patterns
import triangle_patterns
from pattern_profiles import parameters

ENGINES = dict(horizontal=horizontal_patterns, flag=flag_patterns, triangle=triangle_patterns)


def event_checks(event, snapshot):
    """Check recorded price evidence separately from engine replay."""
    errors = []
    rows = snapshot['candles']
    indices = {r['time']:i for i,r in enumerate(rows)}
    t = event['confirmedBarTime']
    if not rows or t not in indices or rows[-1]['time'] != t:
        return ['snapshot-basis-bar']
    i = indices[t]; row = rows[i]
    if snapshot['event'] != {k:v for k,v in event.items() if k!='cursor'}:
        errors.append('snapshot-event-mismatch')
    if not snapshot.get('confirmedThrough') or t > snapshot['confirmedThrough']:
        errors.append('unconfirmed-event')
    if event['eventType'] == 'revised':
        return errors
    sign = 1 if event['direction'] == 'up' else -1
    a = event['atr14Previous']
    kind = event['eventType']
    trigger = event['triggerPrice']; boundary = event['boundary']
    if kind == 'confirmed' and sign * (row['close'] - trigger) <= 0:
        errors.append('close-not-beyond-trigger')
    if kind == 'failed' and sign * (row['close'] - event['invalidationPrice']) >= 0:
        errors.append('close-not-beyond-invalidation')
    if kind == 'retested' and not (row['low'] <= boundary + .1*a and row['high'] >= boundary - .1*a
                                 and sign*(row['close']-trigger) > 0):
        errors.append('retest-price-evidence')
    if kind != 'confirmed':
        return errors
    prior_volume = sum(r['volume'] for r in rows[i-20:i])/20 if i>=20 else 0
    expected_rvol = row['volume']/prior_volume if prior_volume else None
    recorded_rvol = event.get('rvol20Previous')
    if (expected_rvol is None) != (recorded_rvol is None) or (expected_rvol is not None and abs(recorded_rvol-expected_rvol)>1e-8*max(1,abs(expected_rvol))):
        errors.append('volume-evidence')
    if event['ruleVersion'].startswith('horizontal-'):
        if event['type'].startswith('prior-'):
            expected = max(r['high'] for r in rows[i-20:i]) if sign == 1 else min(r['low'] for r in rows[i-10:i])
            if not abs(boundary-expected) <= 1e-8*max(1,abs(expected)):
                errors.append('rolling-boundary')
        if i == 0 or sign*(rows[i-1]['close']-trigger) > 0:
            errors.append('no-price-crossing')
    else:
        d = indices.get(event['discoveredTime'])
        if d is None or d > i:
            errors.append('discovery-date')
        else:
            for field,price,greater in [('pivotHighTimes','high',True),('pivotLowTimes','low',False)]:
                for stamp in event[field]:
                    j = indices.get(stamp)
                    if j is None or j < 2 or j+2 > d:
                        errors.append('unconfirmed-pivot'); continue
                    v = rows[j][price]
                    left = [rows[k][price] for k in (j-2,j-1)]
                    right = [rows[k][price] for k in (j+1,j+2)]
                    good = (all(v>=x for x in left) and all(v>x for x in right)) if greater else (all(v<=x for x in left) and all(v<x for x in right))
                    if not good:
                        errors.append('non-pivot-contact')
        cfg=parameters('legacy' if event['ruleVersion'].endswith('-v1') else 'balanced')
        if event['containment'] < cfg['containment']:
            errors.append('insufficient-containment')
        if event['upperPrice'] <= event['lowerPrice']:
            errors.append('crossed-boundaries')
        if event['ruleVersion'].startswith('triangle-'):
            if event['contactCount'] < cfg['triangle_contacts'] or not cfg['triangle_min'] <= event['structureBars'] <= 60 or event['convergenceRatio'] > cfg['convergence'] or event['apexRemainingBars'] <= 0:
                errors.append('triangle-shape')
            if row['high'] > event['upTrigger'] and row['low'] < event['downTrigger']:
                errors.append('triangle-two-sided-bar')
        else:
            if not 1 <= event['adjustmentBars'] <= cfg['flag_max'] or event['retracementRatio'] > cfg['retracement'] or event['poleMove'] < cfg['pole_atr']*event['poleAtr']:
                errors.append('flag-shape')
    return errors


def run(cache):
    report = dict(auditedAt=datetime.now(timezone.utc).isoformat(), cache=str(cache),
                  sourceAccess='read-only SQLite backup; no network', symbols=[], issues=[], samples=[])
    with TemporaryDirectory(prefix='chart-pattern-audit-') as temp:
        backup = Path(temp) / 'audit.sqlite3'
        # SQLite backup takes a coherent WAL-inclusive snapshot, without changing the source.
        source = sqlite3.connect(cache.resolve().as_uri()+'?mode=ro', uri=True)
        dest = sqlite3.connect(backup)
        try:
            source.backup(dest)
        finally:
            dest.close(); source.close()
        store = MarketStore(backup)
        try:
            entries = list(store.db.execute("SELECT key,value FROM entries WHERE key LIKE 'toss|%|D|%'").fetchall())
            sources = {}
            for key, body in entries:
                p = json.loads(body)
                if p.get('candles') and p.get('tf', 'D') == 'D':
                    old = sources.get(p['symbol'])
                    if not old or p['fetchedAt'] > old['fetchedAt']:
                        sources[p['symbol']] = p
            report['symbols'] = sorted(sources)
            originals = [(seq,symbol,json.loads(body)) for seq,symbol,body in store.db.execute('SELECT seq,symbol,value FROM pattern_events')]
            ids_before = {e['eventId'] for _,_,e in originals}
            counts = Counter((symbol,e['ruleVersion'],e['patternId'],e['eventType'],e['confirmedBarTime']) for _,symbol,e in originals)
            report['storedEvents'] = len(originals)
            report['duplicateSemanticEvents'] = sum(n-1 for n in counts.values() if n>1)
            price_keys = Counter((symbol,e['ruleVersion'],e['type'],e['direction'],e['eventType'],e['confirmedBarTime'],e.get('boundary')) for _,symbol,e in originals)
            report['sameKindBarPriceCollisions'] = sum(n-1 for n in price_keys.values() if n>1)
            frozen = {}; evidence_checked = 0
            for _,symbol,event in originals:
                snapshot = store.pattern_snapshot(event['basisSnapshotId'])
                if not snapshot:
                    report['issues'].append(dict(symbol=symbol,eventId=event['eventId'],checks=['missing-snapshot'])); continue
                frozen[snapshot['snapshotId']] = revision(snapshot)
                errors = event_checks(event,snapshot); evidence_checked += 1
                if errors:
                    report['issues'].append(dict(symbol=symbol,eventId=event['eventId'],date=event['confirmedBarTime'],checks=sorted(set(errors))))
            report['evidenceChecked'] = evidence_checked
            jobs = []; candidates = defaultdict(list)
            for symbol,payload in sorted(sources.items()):
                print(f'audit {symbol}', flush=True)
                fetched = datetime.fromisoformat(payload['fetchedAt'].replace('Z','+00:00'))
                for family,engine in ENGINES.items():
                    key = result_key(symbol, get_settings(store,symbol) if family=='horizontal' else None, family)
                    old = store.pattern_result(key)
                    if not old: continue
                    levels = old.get('levels',{})
                    raw = engine.analyze(payload['candles'],symbol,payload.get('lastConfirmedTime'),False,levels)
                    old_ids = {e['eventId'] for e in old.get('events',[])}
                    new_ids = {e['eventId'] for e in raw['events']}
                    if old_ids != new_ids:
                        report['issues'].append(dict(symbol=symbol,family=family,checks=['cached-replay-event-mismatch'],missing=len(old_ids-new_ids),added=len(new_ids-old_ids)))
                    recent = [e for e in raw['events'] if within(e,payload['candles'][-1]['time'])]
                    confirms = [e for e in recent if e['eventType']=='confirmed']
                    failed_ids = {e['patternId'] for e in recent if e['eventType']=='failed'}
                    confirmed_rows = [r for r in payload['candles'] if r['time'] <= payload['lastConfirmedTime']]
                    positions = {r['time']:i for i,r in enumerate(confirmed_rows)}
                    completed = [e for e in confirms if len(confirmed_rows)-1-positions[e['confirmedBarTime']] >= 10]
                    report['samples'].append(dict(symbol=symbol,family=family,bars=len(payload['candles']),sourceDate=payload['candles'][-1]['time'],
                        confirmedThrough=payload.get('lastConfirmedTime'),fetchedAt=payload['fetchedAt'],recentEvents=len(recent),confirmations=len(confirms),
                        laterFailures=sum(e['patternId'] in failed_ids for e in confirms),
                        completedTenBarWindows=len(completed),completedWindowFailures=sum(e['patternId'] in failed_ids for e in completed),
                        lowVolumeConfirmations=sum(e['volumeEvidence']=='volume-insufficient' for e in confirms),
                        events=[{k:e.get(k) for k in ('eventId','patternId','type','eventType','confirmedBarTime','direction','boundary','triggerPrice','invalidationPrice','volumeEvidence')} for e in recent]))
                    # Prove that future prices do not change sampled historical decisions.
                    chosen = confirms[-2:] or raw['events'][-1:]
                    prefix_count = 0
                    for e in chosen:
                        n = next(i+1 for i,r in enumerate(payload['candles']) if r['time']==e['confirmedBarTime'])
                        part = engine.analyze(payload['candles'][:n],symbol,e['confirmedBarTime'],False,levels)
                        if raw['timeline'][:n] != part['timeline'] or [x for x in raw['events'] if x['confirmedBarTime']<=e['confirmedBarTime']] != part['events']:
                            report['issues'].append(dict(symbol=symbol,family=family,checks=['future-influence'],date=e['confirmedBarTime']))
                        prefix_count += 1
                    report.setdefault('prefixChecks',0); report['prefixChecks'] += prefix_count
                    # Replay against existing ledger, then again after a common restart below.
                    for _ in range(2):
                        evaluate(payload,store,fetched+timedelta(seconds=1),family)
                    jobs.append((payload,family,fetched))
                    candidates[family].append(payload)
                    for mode in ('lastError','stale','unknown-calendar'):
                        blocked = deepcopy(payload)
                        if mode=='unknown-calendar':blocked['marketSession']={'state':'unknown'}
                        else:blocked[mode] = 'audit-failure' if mode=='lastError' else True
                        result = evaluate(blocked,store,fetched+timedelta(seconds=1),family)
                        if result['sourceStatus']!='paused' or result['events'] or result['provisionalEligible']:
                            report['issues'].append(dict(symbol=symbol,family=family,checks=['blocked-source-emitted'],mode=mode))
                        if store.pattern_result(key)['sourceFetchedAt'] != payload['fetchedAt']:
                            report['issues'].append(dict(symbol=symbol,family=family,checks=['blocked-overwrote-result']))
                    aged = evaluate(payload,store,fetched+timedelta(seconds=91),family)
                    if aged['provisionalEligible']:
                        report['issues'].append(dict(symbol=symbol,family=family,checks=['expired-provisional']))
            store.close(); store = MarketStore(backup)
            for payload,family,fetched in jobs:
                evaluate(payload,store,fetched+timedelta(seconds=1),family)
            # Shared store concurrency mirrors server monitor/browser publication.
            for family,payloads in candidates.items():
                payload = next((p for p in payloads if p['symbol']=='VELO'),payloads[0])
                fetched = datetime.fromisoformat(payload['fetchedAt'].replace('Z','+00:00'))
                with ThreadPoolExecutor(max_workers=4) as pool:
                    list(pool.map(lambda _:evaluate(payload,store,fetched+timedelta(seconds=1),family),range(4)))
            ids_after = {e['eventId'] for e in store.pattern_events(limit=100000)}
            report['replayJobs'] = len(jobs)
            report['newEventsAfterRepeatsRestartConcurrency'] = len(ids_after-ids_before)
            report['removedEventsAfterReplay'] = len(ids_before-ids_after)
            report['changedOriginalSnapshots'] = sum(revision(store.pattern_snapshot(ident))!=digest for ident,digest in frozen.items())
            report['passed'] = bool(jobs) and not report['issues'] and not any(report[k] for k in (
                'duplicateSemanticEvents','sameKindBarPriceCollisions','newEventsAfterRepeatsRestartConcurrency','removedEventsAfterReplay','changedOriginalSnapshots'))
        finally:
            store.close()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',type=Path,default=ROOT/'logs/market-cache.sqlite3')
    parser.add_argument('--output',type=Path,default=ROOT/'logs/pattern-audit.json')
    args = parser.parse_args()
    result = run(args.cache)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('samples','issues')},ensure_ascii=False))
    print('issues',len(result['issues']), 'output',args.output)
    sys.exit(0 if result['passed'] else 1)
