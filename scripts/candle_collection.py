"""Adjusted Toss daily history: recent-bar merge and atomic full reconciliation."""
from copy import deepcopy
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from threading import RLock
from time import time
from market_store import epoch, revision


class CandleCollection:
    def __init__(self, client, store, clock=time):
        self.client, self.store, self.clock = client, store, clock
        self.lock = RLock()

    def _full(self, symbol, timezone_name):
        from toss_market import normalize_candles, TossError
        collected, before, seen, normalized_pages = [], None, set(), {}
        for page in range(4):
            params = dict(symbol=symbol,interval='1d',count=200,adjusted='true')
            if before:
                params['before'] = before
            reply = self.client.get('/api/v1/candles',**params)
            rows = reply.get('candles',[])
            for row in normalize_candles(rows,timezone_name):
                previous = normalized_pages.get(row['t'])
                if previous is not None and row!=previous:
                    raise TossError('adjusted-history-conflict')
                normalized_pages[row['t']] = row
            collected.extend(rows)
            cursor = reply.get('nextBefore')
            if not rows or not cursor:
                break
            if cursor in seen:
                raise TossError('history-cursor-repeated')
            seen.add(cursor)
            before = cursor
        data = normalize_candles(collected,timezone_name)[-800:]
        if not data:
            raise TossError('no-candles')
        return data

    def daily(self, code, timezone_name, force=False, reconcile_after=None):
        from toss_market import normalize_candles, toss_symbol, TossError
        symbol = toss_symbol(code)
        key = '|'.join(('candles',symbol,'D','adjusted',timezone_name,'v1'))
        with self.lock:
            old = self.store.get(key)
            now = self.clock()
            age = now-epoch(old['fetchedAt']) if old else None
            full = not old or now-old['fullRefreshAt']>=86400
            if old and reconcile_after is not None:
                full = full or (now>=reconcile_after and old['fullRefreshAt']<reconcile_after)
            if old and not full and 0<=age<(10 if force else 30):
                return deepcopy(old['rows']), True, old['fetchedAt'], old['dataRevision']
            if full:
                data = self._full(symbol,timezone_name)
            else:
                reply = self.client.get('/api/v1/candles',symbol=symbol,interval='1d',count=30,adjusted='true')
                recent = normalize_candles(reply.get('candles',[]),timezone_name)
                if not recent:
                    raise TossError('no-candles')
                indexed = {r['t']:r for r in old['rows']}
                overlap = [r for r in recent if r['t'] in indexed]
                today = datetime.fromtimestamp(now,ZoneInfo(timezone_name)).date().isoformat()
                changed_history = any(r!=indexed[r['t']] and (r['t']<old['rows'][-1]['t'] or r['t']<today) for r in overlap)
                # No common date means the fetch may have skipped a gap >30 bars.
                full = not overlap or changed_history or recent[-1]['t']<old['rows'][-1]['t']
                if full:
                    data = self._full(symbol,timezone_name)
                else:
                    indexed.update({r['t']:r for r in recent})
                    data = [indexed[t] for t in sorted(indexed)][-800:]
            fetched = datetime.fromtimestamp(self.clock(),timezone.utc).isoformat(timespec='seconds')
            value = dict(rows=data,fetchedAt=fetched,dataRevision=revision(data),
                         fullRefreshAt=self.clock() if full else old['fullRefreshAt'])
            self.store.put(key,value)
            return deepcopy(data), False, fetched, value['dataRevision']
