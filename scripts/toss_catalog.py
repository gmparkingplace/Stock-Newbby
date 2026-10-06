"""Cached official market universe for name search and exchange resolution."""
import threading,time,re
from toss_market import CLIENT,TossError
_lock=threading.RLock();_rows=[];_at=0

def canonical(symbol,market):
    return symbol+({'KOSPI':'.KS','KOSDAQ':'.KQ'}.get(market,''))

def catalog():
    global _rows,_at
    with _lock:
        if _rows and time.monotonic()-_at<21600:return _rows
        rows=[]
        for market in ('KOSPI','KOSDAQ','NASDAQ','NYSE','AMEX'):
            for s in CLIENT.get('/api/v1/stocks/all',market=market):
                rows.append({'symbol':canonical(s['symbol'],market),'code':s['symbol'],'name':s['name'],'market':market})
        _rows=rows;_at=time.monotonic();return _rows

def search(query):
    q=query.strip().casefold()
    if not q:return []
    rows=[r for r in catalog() if q in r['name'].casefold() or q in r['symbol'].casefold()]
    return sorted(rows,key=lambda r:(q not in (r['name'].casefold(),r['code'].casefold(),r['symbol'].casefold()),r['name']))[:30]

def resolve(value):
    v=value.strip().upper()
    if re.fullmatch(r'\d{6}(?:\.(?:KS|KQ))?',v):
        rows=CLIENT.get('/api/v1/stocks',symbols=v[:6])
        if not rows:raise TossError('symbol-not-found')
        return canonical(rows[0]['symbol'],rows[0]['market'])
    if re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,19}',v):return v
    hits=[r for r in search(value) if r['name'].casefold()==value.strip().casefold()]
    if len(hits)!=1:raise TossError('symbol-name-not-unique')
    return hits[0]['symbol']
