"""Causal ascending/descending/symmetrical daily triangles. No provider or clock."""
from market_store import revision
from pattern_math import validated, analyze_contiguous, atr14, fit, line, pivots, channel_coverage

from pattern_profiles import parameters, rule_version

RULE=rule_version('triangle')


def contained(p, rows, end):
    start=p['startIndex'];a=p['atr14Previous'];tolerance=p.get('fitToleranceAtr',.25)
    return channel_coverage(rows,start,end,p['upper'],p['lower'],tolerance*a)[0]


def channel_valid(p, rows, end):
    ratio,run=channel_coverage(rows,p['startIndex'],end,p['upper'],p['lower'],p['fitToleranceAtr']*p['atr14Previous'])
    return ratio>=p['minimumContainment'] and (not p['maxOutsideRun'] or run<=p['maxOutsideRun'])


def candidate(rows, atr, start, end, highs, lows, symbol,timeframe='D',profile='balanced'):
    cfg=parameters(profile);rule=rule_version('triangle',timeframe,profile)
    hp=[(i,v) for i,v in highs if start<=i<=end-2];lp=[(i,v) for i,v in lows if start<=i<=end-2]
    if len(hp)<2 or len(lp)<2 or len(hp)+len(lp)<cfg['triangle_contacts']:return None
    start=min(hp[0][0],lp[0][0])
    if not cfg['triangle_min']<=end-start+1<=60:return None
    a=atr[end-1]
    if not a or a<=0:return None
    upper,lower=fit(hp),fit(lp);u,l=upper['slope'],lower['slope']
    if u<=-cfg['trend_slope']*a and l>=cfg['trend_slope']*a:kind='symmetrical-triangle'
    elif abs(u)<=cfg['flat_slope']*a and l>=cfg['trend_slope']*a:kind='ascending-triangle'
    elif u<=-cfg['trend_slope']*a and abs(l)<=cfg['flat_slope']*a:kind='descending-triangle'
    else:return None
    if any(abs(v-line(m,i))>cfg['fit_atr']*a for points,m in ((hp,upper),(lp,lower)) for i,v in points):return None
    width=line(upper,start)-line(lower,start);last=line(upper,end)-line(lower,end)
    if width<=0 or last<=0 or last/width>cfg['convergence']:return None
    apex=(lower['intercept']-upper['intercept'])/(u-l)
    if apex<=end:return None
    ident=revision([symbol,timeframe,kind,rule,rows[start]['time'],[rows[i]['time'] for i,_ in hp],[rows[i]['time'] for i,_ in lp]])
    p=dict(patternId=ident,type=kind,direction='neutral',ruleVersion=rule,startIndex=start,
           anchorTime=rows[start]['time'],structureStartTime=rows[start]['time'],discoveredTime=rows[end]['time'],
           upper=upper,lower=lower,apexIndex=apex,startWidth=width,atr14Previous=a,fitToleranceAtr=cfg['fit_atr'],minimumContainment=cfg['containment'],maxOutsideRun=cfg['max_outside_run'],
           pivotHighTimes=[rows[i]['time'] for i,_ in hp],pivotLowTimes=[rows[i]['time'] for i,_ in lp],
           contactCount=len(hp)+len(lp),status='forming',confirmedIndex=None,terminalIndex=None,retested=False,failed=False)
    p['containment']=contained(p,rows,end)
    if not channel_valid(p,rows,end):return None
    return p


def present(p, rows, end, status=None, direction=None):
    fixed=p['confirmedIndex'] if p['confirmedIndex'] is not None else p['terminalIndex']
    shown=end if fixed is None else fixed
    u,l=line(p['upper'],shown),line(p['lower'],shown);a=p['atr14Previous']
    direction=direction or p['direction'];sign=1 if direction=='up' else -1
    boundary=(u if sign==1 else l) if direction!='neutral' else None
    rv=sum(r['volume'] for r in rows[end-20:end])/20 if end>=20 else 0
    clean={k:v for k,v in p.items() if k not in ('startIndex','confirmedIndex','terminalIndex','apexIndex','startWidth','retested','failed')}
    geometry=dict(kind='triangle',points=[dict(time=rows[p['startIndex']]['time'],price=line(p['upper'],p['startIndex'])),
        dict(anchorTime=rows[p['startIndex']]['time'],logicalOffset=p['apexIndex']-p['startIndex'],price=line(p['upper'],p['apexIndex'])),
        dict(time=rows[p['startIndex']]['time'],price=line(p['lower'],p['startIndex']))],observedThrough=rows[shown]['time'])
    return dict(clean,status=status or p['status'],direction=direction,barTime=rows[end]['time'],close=rows[end]['close'],
                geometry=geometry,structureBars=shown-p['startIndex']+1,upperPrice=u,lowerPrice=l,
                upTrigger=u+.1*a,downTrigger=l-.1*a,boundary=boundary,
                triggerPrice=boundary+sign*.1*a if boundary is not None else None,
                invalidationPrice=(l-.1*a if sign==1 else u+.1*a) if direction!='neutral' else None,
                convergenceRatio=(u-l)/p['startWidth'],apexRemainingBars=p['apexIndex']-shown,
                rvol20Previous=rows[end]['volume']/rv if rv else None,
                volumeEvidence='volume-confirmed' if rv and rows[end]['volume']/rv>=1.2 else 'volume-insufficient')


def crossing(row,d):
    return 'up' if row['close']>d['upTrigger'] else 'down' if row['close']<d['downTrigger'] else None


def whipsaw(row,d):
    return row['high']>d['upTrigger'] and row['low']<d['downTrigger']


def analyze(candles,symbol,confirmed_through,provisional=False,levels=None,timeframe='D',profile='balanced'):
    if timeframe not in ('D','H4'):raise ValueError('unsupported-pattern-timeframe')
    cfg=parameters(profile);rule=rule_version('triangle',timeframe,profile)
    rows=validated(candles,confirmed_through,timeframe,symbol)
    segmented=analyze_contiguous(analyze,rows,symbol,confirmed_through,provisional,levels,timeframe,profile)
    if segmented is not None:return segmented
    atr=atr14(rows)
    timeline,events,history=[],[],[];active=None;blocked=-1
    def emit(p,i,kind):
        event=present(p,rows,i,kind);event.update(eventType=kind,confirmedBarTime=rows[i]['time'],eventId=revision([p['patternId'],kind,rows[i]['time'],rule]))
        if timeframe!='D':event['timeframe']=timeframe
        events.append(event)
    for i,row in enumerate(rows):
        confirmed=confirmed_through is not None and row['time']<=confirmed_through
        if confirmed:
            if active and (active['terminalIndex'] is not None or active['confirmedIndex'] is not None and i-active['confirmedIndex']>10):
                blocked=max(blocked,active['terminalIndex'] if active['terminalIndex'] is not None else active['confirmedIndex']);active=None
            if active is None:
                hi,lo=pivots(rows,i)
                for start in range(max(14,blocked+1,i-59),i-cfg['triangle_min']+2):
                    p=candidate(rows,atr,start,i,hi,lo,symbol,timeframe,profile)
                    if p:active=p;history.append(p);break
            if active:
                p=active;d=present(p,rows,i)
                if p['confirmedIndex'] is not None:
                    age=i-p['confirmedIndex'];sign=1 if p['direction']=='up' else -1
                    if 1<=age<=10 and not p['failed']:
                        failure=sign*(row['close']-d['invalidationPrice'])<0
                        touch=row['low']<=d['boundary']+.1*p['atr14Previous'] and row['high']>=d['boundary']-.1*p['atr14Previous']
                        retest=touch and sign*(row['close']-d['triggerPrice'])>0 and not p['retested']
                        if failure or retest:
                            kind='failed' if failure else 'retested';p[kind]=True;p['status']=kind;emit(p,i,kind)
                else:
                    direction=crossing(row,d);prefix=i-1 if direction else i
                    if i<p['apexIndex'] and (whipsaw(row,d) or not channel_valid(p,rows,prefix)):
                        p.update(status='failed',reason='two-sided-range' if whipsaw(row,d) else 'channel-containment',terminalIndex=i)
                    elif i>=p['apexIndex'] or i-p['startIndex']+1>60:
                        p.update(status='expired',reason='apex-reached' if i>=p['apexIndex'] else 'structure-over-60',terminalIndex=max(p['startIndex'],i-1))
                    elif direction:
                        p.update(status='confirmed',direction=direction,confirmedIndex=i);emit(p,i,'confirmed')
        displayed=[]
        for p in history:
            if p['confirmedIndex'] is not None and i-p['confirmedIndex']>10:continue
            if p['terminalIndex'] is not None and i-p['terminalIndex']>2:continue
            d=present(p,rows,i)
            if not confirmed and p['confirmedIndex'] is None and p['terminalIndex'] is None:
                direction=crossing(row,d)
                invalid=i>=p['apexIndex'] or i-p['startIndex']+1>60 or whipsaw(row,d) or not channel_valid(p,rows,i-1 if direction else i)
                d['status']='breakout-pending' if provisional and i==len(rows)-1 and direction and not invalid else 'forming' if provisional and not invalid else 'paused'
                if d['status']=='breakout-pending':d=present(p,rows,i,'breakout-pending',direction)
                d['provisionalInvalidation']=invalid
            displayed.append(d)
        rank={'confirmed':0,'retested':0,'breakout-pending':1,'forming':2,'paused':3,'failed':4,'expired':5}
        displayed.sort(key=lambda p:(rank[p['status']],p['discoveredTime']),reverse=False)
        timeline.append(dict(barTime=row['time'],confirmed=confirmed,status='ready' if displayed or i>=30 else 'insufficient-data',patterns=displayed[:1]))
    return dict(symbol=symbol,timeframe=timeframe,ruleVersion=rule,levels={},configId=rule,confirmedThrough=confirmed_through,timeline=timeline,events=events)
