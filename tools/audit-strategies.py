"""Read-only strategy frequency audit; no collection, server changes or cache writes."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from pattern_window import start

STRATEGIES = ('A', 'B', 'C', 'F')


def summarize(frame, recent=False):
    bars, state = frame.get('candles', []), frame.get('state', [])
    reference = frame.get('lastConfirmedTime')
    if reference is None:
        return {'excluded': 'no-confirmation-basis'}
    if not bars or len(bars) != len(state):
        return {'excluded': 'unaligned-bars-state'}
    stamps = [b['time'] for b in bars]
    if len(set(stamps)) != len(stamps) or stamps != sorted(stamps) or reference not in stamps:
        return {'excluded': 'invalid-confirmation-basis'}
    boundary = start(reference) if recent else None
    indices = [i for i, b in enumerate(bars) if b['time'] <= reference and (boundary is None or b['time'] >= boundary)]
    signal = lambda i, k: state[i].get('sig'+k)
    entries = {k: {i for i in indices if signal(i, k) == 'entry'} for k in STRATEGIES}
    exits = {k: {i for i in indices if signal(i, k) == 'exit'} for k in STRATEGIES}
    slow = {p['time']: p['value'] for p in frame.get('lines', {}).get('sma60', [])}
    ready = lambda i: stamps[i] in slow and all(state[i].get(k) is not None for k in ('rsi14','don_hi','don_lo'))
    first = indices[0] if indices else None
    return {
        'from': bars[first]['time'] if first is not None else None, 'through': reference,
        'windowStart': boundary, 'bars': len(indices), 'commonReadyBars': sum(ready(i) for i in indices),
        'entry': {k: len(v) for k, v in entries.items()}, 'exit': {k: len(v) for k, v in exits.items()},
        'newEntryEpisodes': {k: sum(i == 0 or signal(i-1,k) != 'entry' for i in entries[k]) for k in STRATEGIES},
        'carryInEpisodes': {k: int(first is not None and first in entries[k] and first>0 and signal(first-1,k)=='entry') for k in STRATEGIES},
        'pairEntry': {a+'+'+b: len(entries[a]&entries[b]) for a,b in combinations(STRATEGIES,2)},
        'allEntry': len(set.intersection(*entries.values())),
        'fEntryOutsideC': len(entries['F']-entries['C']), 'cExitOutsideF': len(exits['C']-exits['F']),
        'latestSignals': {k: signal(stamps.index(reference),k) for k in STRATEGIES},
    }


def total(records):
    good=[r for r in records if 'excluded' not in r]
    keys=('entry','exit','newEntryEpisodes','carryInEpisodes','pairEntry')
    out={'frames':len(good),'excludedFrames':len(records)-len(good)}
    for k in ('bars','commonReadyBars','allEntry','fEntryOutsideC','cExitOutsideF'):
        out[k]=sum(r[k] for r in good)
    for k in keys:
        counts=Counter()
        for r in good: counts.update(r[k])
        out[k]=dict(counts)
    return out


def analyze(path):
    # A transaction reads one coherent snapshot including WAL. Do not instantiate MarketStore.
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    try:
        db.execute('BEGIN')
        rows=db.execute("SELECT key,value FROM entries WHERE key LIKE 'toss|%|D|%' OR key LIKE 'yfinance|%|D|%' OR key LIKE 'yfinance|%|H4|%'").fetchall()
    finally:
        db.close()
    selected={}
    for key, body in rows:
        p=json.loads(body)
        if not p.get('candles'):continue
        tf=p.get('tf','D');symbol=p['symbol'];provider=key.split('|')[0]
        for kind, frame in [(tf,p)]+([('W',p.get('weekly')),('M',p.get('monthly'))] if tf=='D' else []):
            if not frame:continue
            ident=(symbol,kind)
            value={'symbol':symbol,'tf':kind,'provider':provider,'fetchedAt':frame.get('fetchedAt') or p.get('fetchedAt'),
                'firstBar':frame['candles'][0]['time'],'lastBar':frame['candles'][-1]['time'],'loadedBars':len(frame['candles']),
                'full':summarize(frame),'recent':summarize(frame,True)}
            if ident not in selected or value['fetchedAt']>selected[ident]['fetchedAt']:selected[ident]=value
    samples=sorted(selected.values(),key=lambda r:(r['tf'],r['symbol']))
    groups={}
    for tf in ('D','W','M','H4'):
        for kind in ('stock','coin'):
            matching=[r for r in samples if r['tf']==tf and (r['symbol'].endswith('-USD'))==(kind=='coin')]
            if matching:groups[kind+'-'+tf]={scope:total([r[scope] for r in matching]) for scope in ('full','recent')}
    return {'version':1,'auditedAt':datetime.now(timezone.utc).isoformat(),'scope':'cached confirmed bars; frequency and logical dependence only; no P&L or current entry advice',
        'cache':str(Path(path).resolve()),'groups':groups,'samples':samples}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',type=Path,default=ROOT/'logs/market-cache.sqlite3')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.cache.resolve()==args.out.resolve():parser.error('output-must-not-overwrite-cache')
    report=analyze(args.cache)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'frames':len(report['samples']),'recent':{k:v['recent'] for k,v in report['groups'].items()}},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
