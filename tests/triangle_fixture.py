from datetime import date,timedelta


def triangle_rows(kind='ascending',direction='up',length=None,breakout=True,step=None,width=10):
    length=length or (27 if kind=='symmetrical' else 36)
    rows=[dict(time=str(date(2026,1,1)+timedelta(days=i)),open=100,high=101,low=99,close=100,volume=100) for i in range(30)]
    for j in range(length):
        u=114-(step or .16)*j if kind=='symmetrical' else 114
        l=114-width+(step or (.16 if kind=='symmetrical' else .2))*j
        c=(u+l)/2;margin=min(.5,max(.05,(u-l)/4))
        h=u if j%6==2 else c+margin;low=l if j%6==5 else c-margin
        rows.append(dict(time=str(date(2026,1,1)+timedelta(days=len(rows))),open=c,high=max(h,c),low=min(low,c),close=c,volume=100))
    if kind=='descending':
        for r in rows:r.update(open=220-r['open'],high=220-r['low'],low=220-r['high'],close=220-r['close'])
    if breakout:
        j=length;u=114-(step or .16)*j if kind=='symmetrical' else 114;l=114-width+(step or (.16 if kind=='symmetrical' else .2))*j
        if kind=='descending':u,l=220-l,220-u
        c=u+3 if direction=='up' else l-3
        rows.append(dict(time=str(date(2026,1,1)+timedelta(days=len(rows))),open=(u+l)/2,high=c+1 if direction=='up' else (u+l)/2+.2,low=(u+l)/2-.2 if direction=='up' else c-1,close=c,volume=400))
    return rows
