"""Synthetic mirrored flags; explicit wiggles provide confirmed 2+2 pivots."""
from datetime import date,timedelta


def flag_rows(direction='up', breakout=True, adjustment=13):
    rows=[]
    def add(close, high=None, low=None,volume=100):
        rows.append(dict(time=(date(2026,1,1)+timedelta(days=len(rows))).isoformat(),
                         open=close,close=close,high=high if high is not None else close+.5,
                         low=low if low is not None else close-.5,volume=volume))
    for _ in range(30):add(100)
    for price in (102,105,108,111,114):add(price,volume=300)
    for j in range(adjustment):
        middle=113.5-.1*j
        # upper pivots at 2,6,10, lower at 4,8; alternating narrow channel.
        high=115-.1*j-(0 if j%4==2 else .4)
        low=111.8-.1*j+(0 if j%4==0 else .4)
        add(middle,high,low,volume=80)
    if breakout:add(118,119,112,volume=500)
    if direction=='down':
        for row in rows:
            o,h,l,c=row['open'],row['high'],row['low'],row['close']
            row.update(open=220-o,high=220-l,low=220-h,close=220-c)
    return rows
