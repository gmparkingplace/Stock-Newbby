"""Shared validation and full-precision causal ATR for versioned pattern engines."""
from copy import deepcopy
from datetime import date, datetime, timezone
import math


def validated(candles, confirmed_through, timeframe='D', symbol=None):
    from universe import is_coin
    stock_h4 = timeframe == 'H4' and symbol is not None and not is_coin(symbol)
    rows = deepcopy(candles)
    previous = None
    for row in rows:
        stamp = row['time']
        if timeframe=='H4':
            valid_time=type(stamp) is int and stamp>0 and stamp%(60 if stock_h4 else 14400)==0
            if stock_h4:
                missing = row.get('missingBarsBefore')
                valid_time = valid_time and type(missing) is int and missing >= 0
            if valid_time:
                try:datetime.fromtimestamp(stamp,timezone.utc)
                except (ValueError,OverflowError,OSError):valid_time=False
        else:
            valid_time=isinstance(stamp,str) and date.fromisoformat(stamp).isoformat()==stamp
        if not valid_time or (previous is not None and stamp<=previous):
            raise ValueError('invalid-bar-order')
        nums=[row[k] for k in ('open','high','low','close','volume')]
        if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in nums):
            raise ValueError('invalid-ohlcv')
        o,h,l,c,v=nums
        if min(o,h,l,c)<=0 or v<0 or h<max(o,l,c) or l>min(o,h,c):
            raise ValueError('invalid-ohlcv')
        previous=stamp
    if confirmed_through is not None and confirmed_through not in [x['time'] for x in rows]:
        raise ValueError('invalid-confirmed-cutoff')
    return rows


def analyze_contiguous(analyzer, rows, symbol, confirmed_through, provisional, levels, timeframe, profile):
    """Restart H4 preparation and structures after missing bars; retain earlier history.

    Each segment uses local indexes for ATR/pivots/geometry. Event identity and
    projected geometry use timestamps, so segment offsets need no translation.
    Legacy remains available only for the existing read-only profile comparison.
    """
    if timeframe != 'H4' or profile == 'legacy':
        return None
    from universe import is_coin
    coin = is_coin(symbol)
    starts = [0] + [i for i in range(1, len(rows)) if
                   (rows[i]['time']-rows[i-1]['time'] != 14400 if coin else rows[i]['missingBarsBefore'] > 0)]
    if len(starts) == 1:
        return None
    timeline, events, warnings = [], [], []
    result = None
    for n, start in enumerate(starts):
        end = starts[n+1] if n+1 < len(starts) else len(rows)
        segment = rows[start:end]
        cutoff = next((r['time'] for r in reversed(segment)
                       if confirmed_through is not None and r['time'] <= confirmed_through), None)
        result = analyzer(segment, symbol, cutoff, provisional and end == len(rows), levels,
                          timeframe=timeframe, profile=profile)
        timeline.extend(result['timeline'])
        events.extend(result['events'])
        if start:
            warnings.append(dict(code='missing-h4-bars', previous=rows[start-1]['time'],
                                 next=rows[start]['time'], missingBars=(rows[start]['time']-rows[start-1]['time'])//14400-1 if coin else rows[start]['missingBarsBefore']))
    return dict(result, confirmedThrough=confirmed_through, timeline=timeline, events=events,
                segmentCount=len(starts), dataWarnings=warnings)


def atr14(rows):
    tr,values=[],[]
    for i,row in enumerate(rows):
        pc=rows[i-1]['close'] if i else row['close']
        tr.append(max(row['high']-row['low'],abs(row['high']-pc),abs(row['low']-pc)))
        values.append(None if i<13 else sum(tr[:14])/14 if i==13 else (values[-1]*13+tr[-1])/14)
    return values


def fit(points):
    x=sum(i for i,_ in points)/len(points);y=sum(v for _,v in points)/len(points)
    denominator=sum((i-x)**2 for i,_ in points)
    slope=sum((i-x)*(v-y) for i,v in points)/denominator
    return dict(slope=slope,intercept=y-slope*x)


def line(model, index):
    return model['intercept']+model['slope']*index


def channel_coverage(rows, start, end, upper, lower, tolerance):
    """Whole-wick containment and consecutive departures, using only the shown prefix."""
    inside=run=longest=0
    for i in range(start,end+1):
        good=rows[i]['high']<=line(upper,i)+tolerance and rows[i]['low']>=line(lower,i)-tolerance
        if good:inside+=1;run=0
        else:run+=1;longest=max(longest,run)
    return (inside/(end-start+1),longest) if end>=start else (0,0)


def pivots(rows, through):
    hi,lo=[],[]
    for j in range(2,through-1):
        h,l=rows[j]['high'],rows[j]['low']
        if all(h>=rows[k]['high'] for k in (j-2,j-1)) and all(h>rows[k]['high'] for k in (j+1,j+2)):
            hi.append((j,h))
        if all(l<=rows[k]['low'] for k in (j-2,j-1)) and all(l<rows[k]['low'] for k in (j+1,j+2)):
            lo.append((j,l))
    return hi,lo
