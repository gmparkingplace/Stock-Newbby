"""Provider-group cooldowns; elapsed time is never spent sleeping on a 429."""
from math import ceil
from random import uniform
from threading import RLock
from time import time
from market_store import revision


def group(path):
    return {'/oauth2/token':'auth','/api/v1/candles':'chart','/api/v1/stocks':'stock',
            '/api/v1/stocks/all':'stock-all','/api/v1/prices':'quote'}.get(path,'calendar')


class ProviderBudget:
    def __init__(self, clock=time, jitter=None):
        self.clock = clock
        self.jitter = jitter or (lambda:uniform(.1,1))
        self.lock = RLock()
        self.states = {}

    def _store(self):
        import market_cache
        return market_cache.services().store if market_cache.enabled() else None

    def _state(self, category):
        if category not in self.states:
            store = self._store()
            value = store.get('budget|toss|'+category) if store else None
            self.states[category] = value or dict(until=0,failures=0,status=0,code=None)
        return self.states[category]

    def check(self, path):
        from toss_market import TossError
        with self.lock:
            state = self._state(group(path))
            remaining = state['until']-self.clock()
            if remaining>0:
                raise TossError(state['code'],state['status'],retry_after=ceil(remaining))

    def success(self, path):
        with self.lock:
            state = self._state(group(path))
            state.update(until=0,failures=0,status=0,code=None)
            self._save(group(path),state)

    def failure(self, path, error):
        with self.lock:
            category = group(path)
            state = self._state(category)
            status = getattr(error,'status',0)
            if status not in (401,403,429) and status<500 and error.code!='network-or-timeout':
                return
            failures = min(state['failures']+1,5)
            if status==429:
                delay = error.retry_after if error.retry_after is not None else min(30*2**(failures-1),480)
                delay += self.jitter()
            elif status in (401,403):
                delay = 60
            else:
                delay = min(5*2**(failures-1),60)
            state.update(until=self.clock()+delay,failures=failures,status=status,code=error.code)
            self._save(category,state)
            # The first failing response must advertise the ACTUAL enforced delay too.
            error.retry_after = ceil(delay)
            from datetime import datetime, timezone
            error.retry_at = datetime.fromtimestamp(state['until'],timezone.utc).isoformat()

    def _save(self, category, state):
        store = self._store()
        if store:
            store.put('budget|toss|'+category,{**state,'dataRevision':revision(state)})
