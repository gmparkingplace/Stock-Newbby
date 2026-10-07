"""Bull/Bear Flag v1. Confirmed 2+2 pivots; no network, DOM or wall-clock."""
from copy import deepcopy
from market_store import revision
from pattern_math import validated, analyze_contiguous, atr14, fit, line, pivots, channel_coverage

from pattern_profiles import parameters, rule_version

RULE=rule_version('flag')


def shape(pattern, rows, end):
    # Geometry is encoded in real bar dates/prices, never pixels or viewport width.
    s=pattern['startIndex'];u,l=pattern['upper'],pattern['lower']
    return dict(kind='channel',points=[dict(time=rows[s]['time'],price=line(u,s)),
        dict(time=rows[end]['time'],price=line(u,end)),dict(time=rows[end]['time'],price=line(l,end)),
        dict(time=rows[s]['time'],price=line(l,s))],
        pole=[dict(time=rows[pattern['poleIndex']]['time'],price=pattern['poleStartPrice']),
              dict(time=rows[s-1]['time'],price=pattern['poleEndPrice'])])


def retracement(p, rows, end):
    extreme=min(r['low'] for r in rows[p['startIndex']:end+1]) if p['direction']=='up' else max(r['high'] for r in rows[p['startIndex']:end+1])
    return max(0,(p['poleEndPrice']-extreme if p['direction']=='up' else extreme-p['poleEndPrice'])/p['poleMove'])


def candidate(rows, atr, s, end, highs, lows, symbol, timeframe='D',profile='balanced'):
    cfg=parameters(profile);rule=rule_version('flag',timeframe,profile)
    choices=[]
    for n in range(3,11):
        pole=s-n
        if pole<14:continue
        delta=rows[s-1]['close']-rows[pole]['close']
        if atr[pole-1] and abs(delta)>=cfg['pole_atr']*atr[pole-1]:choices.append((abs(delta),n,pole,delta))
    if not choices:return None
    move,n,pole,delta=sorted(choices,key=lambda x:(-x[0],x[1]))[0]
    direction='up' if delta>0 else 'down'
    if (1 if delta>0 else -1)*(rows[s]['close']-rows[s-1]['close'])>.5*atr[s-1]:return None
    hp=[(i,v) for i,v in highs if s<=i<=end-2];lp=[(i,v) for i,v in lows if s<=i<=end-2]
    if len(hp)<2 or len(lp)<2:return None
    a=atr[end-1]
    if not a or a<=0:return None
    upper,lower=fit(hp),fit(lp)
    sign=1 if direction=='up' else -1
    if any(sign*m['slope']>cfg['flag_slope']*a for m in (upper,lower)):return None
    if abs(upper['slope']-lower['slope'])>cfg['parallel_atr']*a:return None
    if any(abs(v-line(model,i))>cfg['fit_atr']*a for points,model in ((hp,upper),(lp,lower)) for i,v in points):return None
    if any(line(upper,i)<=line(lower,i) for i in range(s,end+1)):return None
    contained,run=channel_coverage(rows,s,end,upper,lower,cfg['fit_atr']*a)
    if contained<cfg['containment'] or cfg['max_outside_run'] and run>cfg['max_outside_run']:return None
    ident=revision([symbol,timeframe,'bull-flag' if sign==1 else 'bear-flag',rule,rows[pole]['time'],rows[s]['time'],
                    [rows[i]['time'] for i,_ in hp],[rows[i]['time'] for i,_ in lp]])
    pole_volume=sum(r['volume'] for r in rows[pole:s])/n
    adj_volume=sum(r['volume'] for r in rows[s:end+1])/(end-s+1)
    p=dict(patternId=ident,type='bull-flag' if sign==1 else 'bear-flag',direction=direction,ruleVersion=rule,
        startIndex=s,poleIndex=pole,poleStartTime=rows[pole]['time'],poleStartPrice=rows[pole]['close'],
        poleEndTime=rows[s-1]['time'],poleEndPrice=rows[s-1]['close'],poleMove=move,poleAtr=atr[pole-1],
        adjustmentStartTime=rows[s]['time'],discoveredTime=rows[end]['time'],upper=upper,lower=lower,
        atr14Previous=a,anchorTime=rows[s]['time'],fitToleranceAtr=cfg['fit_atr'],minimumContainment=cfg['containment'],maxOutsideRun=cfg['max_outside_run'],maxRetracement=cfg['retracement'],maxAdjustmentBars=cfg['flag_max'],pivotHighTimes=[rows[i]['time'] for i,_ in hp],
        pivotLowTimes=[rows[i]['time'] for i,_ in lp],containment=contained,
        adjustmentVolumeRatio=adj_volume/pole_volume if pole_volume else None,status='forming',confirmedIndex=None,
        retested=False,failed=False)
    if retracement(p,rows,end)>cfg['retracement']:return None
    return p


def present(p, rows, end, status=None):
    display_end=p['confirmedIndex'] if p['confirmedIndex'] is not None else end
    u,l=line(p['upper'],display_end),line(p['lower'],display_end)
    sign=1 if p['direction']=='up' else -1
    bound=u if sign==1 else l
    other=l if sign==1 else u
    vol=sum(r['volume'] for r in rows[max(0,end-20):end])/20 if end>=20 else 0
    rv=rows[end]['volume']/vol if vol>0 else None
    clean={k:v for k,v in p.items() if k not in ('startIndex','poleIndex','confirmedIndex','retested','failed')}
    return dict(clean,status=status or p['status'],barTime=rows[end]['time'],close=rows[end]['close'],
        boundary=bound,triggerPrice=bound+sign*.1*p['atr14Previous'],
        invalidationPrice=other-sign*.1*p['atr14Previous'],upperPrice=u,lowerPrice=l,
        geometry=shape(p,rows,display_end),adjustmentBars=display_end-p['startIndex']+1,
        rvol20Previous=rv,volumeEvidence='volume-confirmed' if rv is not None and rv>=1.2 else 'volume-insufficient',
        retracementRatio=retracement(p,rows,display_end))


def analyze(candles,symbol,confirmed_through,provisional=False,levels=None,timeframe='D',profile='balanced'):
    if timeframe not in ('D','H4'):raise ValueError('unsupported-pattern-timeframe')
    cfg=parameters(profile);rule=rule_version('flag',timeframe,profile)
    rows=validated(candles,confirmed_through,timeframe,symbol)
    segmented=analyze_contiguous(analyze,rows,symbol,confirmed_through,provisional,levels,timeframe,profile)
    if segmented is not None:return segmented
    atr=atr14(rows)
    timeline,events,patterns=[],[],[]
    indices={r['time']:i for i,r in enumerate(rows)}
    seen=set()
    def emit(p,i,kind):
        event=present(p,rows,i,kind)
        event.update(eventType=kind,confirmedBarTime=rows[i]['time'],
                     eventId=revision([p['patternId'],kind,rows[i]['time'],rule]))
        if timeframe!='D':event['timeframe']=timeframe
        events.append(event)
    for i,row in enumerate(rows):
        confirmed=confirmed_through is not None and row['time']<=confirmed_through
        if confirmed:
            hi,lo=pivots(rows,i)
            for s in range(max(17,i-cfg['flag_max']+1),i-3):
                if s in seen:continue
                p=candidate(rows,atr,s,i,hi,lo,symbol,timeframe,profile)
                if p and not any(x['direction']==p['direction'] and (x['status']=='forming' or x['confirmedIndex'] is not None and i-x['confirmedIndex']<=10 and not x['failed']) for x in patterns):
                    seen.add(s);patterns.append(p)
            for p in patterns:
                if p['confirmedIndex'] is not None:
                    age=i-p['confirmedIndex']
                    if not 1<=age<=10 or p['failed']:continue
                    d=present(p,rows,i);sign=1 if p['direction']=='up' else -1
                    failed=sign*(row['close']-d['invalidationPrice'])<0
                    touch=row['low']<=d['boundary']+.1*p['atr14Previous'] and row['high']>=d['boundary']-.1*p['atr14Previous']
                    retest=touch and sign*(row['close']-d['triggerPrice'])>0 and not p['retested']
                    if failed or retest:
                        kind='failed' if failed else 'retested';p[kind]=True;p['status']=kind;emit(p,i,kind)
                    continue
                if p['status'] in ('failed','expired'):continue
                d=present(p,rows,i);sign=1 if p['direction']=='up' else -1
                crossing=sign*(row['close']-d['triggerPrice'])>0
                check_end=i-1 if crossing and i>p['startIndex'] else i
                contained,run=channel_coverage(rows,p['startIndex'],check_end,p['upper'],p['lower'],p['fitToleranceAtr']*p['atr14Previous'])
                if contained<p['minimumContainment'] or p['maxOutsideRun'] and run>p['maxOutsideRun'] or retracement(p,rows,i)>p['maxRetracement'] or sign*(row['close']-d['invalidationPrice'])<0 or d['upperPrice']<=d['lowerPrice']:
                    p['status']='failed';p['reason']='structure-invalidated';continue
                if i-p['startIndex']+1>p['maxAdjustmentBars']:
                    p['status']='expired';p['reason']='adjustment-over-'+str(p['maxAdjustmentBars']);continue
                if sign*(row['close']-d['triggerPrice'])>0:
                    p['status']='confirmed';p['confirmedIndex']=i;emit(p,i,'confirmed')
        displayed=[]
        for p in patterns:
            if p['confirmedIndex'] is not None and i-p['confirmedIndex']>10:continue
            if p['status'] in ('failed','expired') and i-p['startIndex']>p['maxAdjustmentBars']+2:continue
            d=present(p,rows,i)
            if not confirmed and p['confirmedIndex'] is None and p['status']=='forming':
                sign=1 if p['direction']=='up' else -1
                crossing=sign*(row['close']-d['triggerPrice'])>0
                covered,run=channel_coverage(rows,p['startIndex'],i-1 if crossing else i,p['upper'],p['lower'],p['fitToleranceAtr']*p['atr14Previous'])
                invalid=covered<p['minimumContainment'] or p['maxOutsideRun'] and run>p['maxOutsideRun'] or retracement(p,rows,i)>p['maxRetracement'] or sign*(row['close']-d['invalidationPrice'])<0 or d['upperPrice']<=d['lowerPrice'] or i-p['startIndex']+1>p['maxAdjustmentBars']
                d['status']='breakout-pending' if provisional and i==len(rows)-1 and not invalid and sign*(row['close']-d['triggerPrice'])>0 else 'forming' if provisional and not invalid else 'paused'
                d['provisionalInvalidation']=invalid
            displayed.append(d)
        # One visible structure per direction; all confirmed events remain in history.
        rank={'confirmed':0,'retested':0,'breakout-pending':1,'forming':2,'paused':3,'failed':4,'expired':5}
        displayed.sort(key=lambda p:(rank[p['status']],-indices[p['adjustmentStartTime']]))
        chosen=[]
        for p in displayed:
            if not any(x['direction']==p['direction'] for x in chosen):chosen.append(p)
        timeline.append(dict(barTime=row['time'],confirmed=confirmed,status='ready' if chosen or i>=30 else 'insufficient-data',patterns=chosen))
    return dict(symbol=symbol,timeframe=timeframe,ruleVersion=rule,levels={},configId=rule,
                confirmedThrough=confirmed_through,timeline=timeline,events=events)
