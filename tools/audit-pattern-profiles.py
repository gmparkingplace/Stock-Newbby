"""Compare v1/v2 on cached public candles. Never collect or write the source cache."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import flag_patterns,triangle_patterns
from pattern_window import start,within
from pattern_profiles import PROFILES
from pattern_service import supported


def compare(path):
    conn=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    try:
        conn.execute('BEGIN')
        rows=conn.execute("SELECT key,value FROM entries WHERE key LIKE 'toss|%|D|%' OR key LIKE 'yfinance|%|D|%' OR key LIKE 'yfinance|%|H4|%'").fetchall()
    finally:conn.close()
    frames={}
    for key,raw in rows:
        frame=json.loads(raw);symbol=frame.get('symbol');tf=frame.get('tf','D')
        if not symbol or not supported(symbol,tf,'triangle') or not frame.get('candles'):continue
        ident=(symbol,tf)
        if ident not in frames or (frame.get('fetchedAt') or '')>(frames[ident].get('fetchedAt') or ''):frames[ident]=frame
    samples=[];totals={}
    for (symbol,tf),frame in sorted(frames.items()):
        cutoff=frame.get('lastConfirmedTime')
        if cutoff is None:continue
        bars=[b for b in frame['candles'] if b['time']<=cutoff];begin=start(cutoff)
        first=next((i for i,b in enumerate(bars) if b['time']>=begin),len(bars));bars=bars[max(0,first-74):]
        for family,engine in [('flag',flag_patterns),('triangle',triangle_patterns)]:
            sample=dict(symbol=symbol,timeframe=tf,family=family,sourceFetchedAt=frame.get('fetchedAt'),reference=cutoff,loadedBars=len(bars))
            for profile in PROFILES:
                result=engine.analyze(bars,symbol,cutoff,timeframe=tf,profile=profile)
                visible=[t for t in result['timeline'] if t['barTime']>=begin]
                patterns={p['patternId'] for t in visible for p in t['patterns'] if within({**p,'barTime':t['barTime']},cutoff)}
                events=[e for e in result['events'] if within(e,cutoff)]
                ids=[e['eventId'] for e in events]
                if len(ids)!=len(set(ids)):raise AssertionError('duplicate-event-id')
                counts=Counter(e['eventType'] for e in events)
                current=[p for p in result['timeline'][-1]['patterns'] if within(p,cutoff) and p['status'] not in ('failed','expired','paused')]
                summary=dict(ruleVersion=result['ruleVersion'],structures=len(patterns),confirmed=counts['confirmed'],retested=counts['retested'],failed=counts['failed'],current=len(current))
                sample[profile]=summary
                group=('coin' if symbol.endswith('-USD') else 'stock')+'-'+tf+'-'+family
                totals.setdefault(group,{name:Counter() for name in PROFILES})[profile].update({k:v for k,v in summary.items() if k!='ruleVersion'})
            samples.append(sample)
    return dict(auditedAt=datetime.now(timezone.utc).isoformat(),scope='cached confirmed bars; latest three calendar months plus 74-bar warmup; no provider or active DB writes; counts are not accuracy or profitability',parameters={k:dict(v) for k,v in PROFILES.items()},groups=totals,samples=samples)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cache',type=Path,default=ROOT/'logs/market-cache.sqlite3');parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.cache.resolve()==args.out.resolve():parser.error('output-must-not-overwrite-cache')
    result=compare(args.cache);args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(dict(groups=result['groups'],samples=len(result['samples'])),ensure_ascii=False))


if __name__=='__main__':main()
