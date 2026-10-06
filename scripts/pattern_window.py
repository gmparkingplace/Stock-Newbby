"""Three calendar months of visible evidence; stored originals stay intact."""
from calendar import monthrange
from copy import deepcopy
from datetime import date, datetime, timezone


def start(reference):
    intraday=type(reference) is int
    stamp=datetime.fromtimestamp(reference,timezone.utc) if intraday else None
    d=stamp.date() if intraday else date.fromisoformat(reference)
    month=d.year*12+d.month-1-3
    year,m=divmod(month,12);m+=1
    day=min(d.day,monthrange(year,m)[1])
    return int(stamp.replace(year=year,month=m,day=day).timestamp()) if intraday else date(year,m,day).isoformat()


def structure_start(item):
    return item.get('poleStartTime') or item.get('structureStartTime') or item.get('adjustmentStartTime') or item.get('anchorTime') or item.get('confirmedBarTime') or item.get('barTime')


def within(item, reference):
    if not reference:return False
    first=structure_start(item)
    event=item.get('confirmedBarTime') or item.get('barTime') or first
    return bool(first and event and start(reference)<=first<=event<=reference)


def project(result):
    if not result or not result.get('timeline'):return result
    out=deepcopy(result);end=out['timeline'][-1]['barTime'];begin=start(end)
    out['window']=dict(months=3,start=begin,end=end,basis='latest-source-bar',structureStartRequired=True)
    out['timeline']=[r for r in out['timeline'] if begin<=r['barTime']<=end]
    for row in out['timeline']:
        for key in ('patterns','levels'):
            if key in row:row[key]=[p for p in row[key] if within({**p,'barTime':row['barTime']},end)]
    for key in ('events','recentEvents'):
        if key in out:out[key]=[e for e in out[key] if within(e,end)]
    # Internal correction bookkeeping is retained in storage, not a display list.
    out.pop('trackedEvents',None);out.pop('barHashes',None)
    return out
