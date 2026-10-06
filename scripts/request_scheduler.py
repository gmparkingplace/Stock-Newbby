"""Single-flight, bounded provider queues. HTTP waiters do not own collection."""
from concurrent.futures import Future, TimeoutError as FutureTimeout
from copy import deepcopy
from datetime import datetime, timezone
from threading import Condition, Thread
from time import monotonic


class QueueBusy(Exception):
    code = 'queue-busy'
    status = 503
    retry_after = 2
    def __init__(self):
        self.retry_at = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp()+2, timezone.utc).isoformat()
        super().__init__('조회 작업 진행 중 · 잠시 후 다시 확인하세요.')


class RequestScheduler:
    def __init__(self, wait_seconds=15, max_pending=32):
        self.wait_seconds, self.max_pending = wait_seconds, max_pending
        self.cv = Condition()
        self.flights, self.pending, self.workers = {}, {}, {}
        self.stopped = False
        self.stats = dict(submitted=0, merged=0, completed=0, failed=0, expired=0)

    def execute(self, key, provider, fn, priority=1, background=False):
        with self.cv:
            if self.stopped:
                raise QueueBusy()
            future = self.flights.get(key)
            if future:
                self.stats['merged'] += 1
                if background:
                    queue = self.pending.get(provider,[])
                    for index, item in enumerate(queue):
                        if item[2]==key:
                            queue[index]=(*item[:5],True)
                            break
            else:
                queue = self.pending.setdefault(provider, [])
                if len(queue) >= self.max_pending:
                    raise QueueBusy()
                future = Future()
                self.flights[key] = future
                queue.append((priority, monotonic(), key, future, fn, background))
                self.stats['submitted'] += 1
                if provider not in self.workers:
                    worker = Thread(target=self._run, args=(provider,), daemon=True, name='chart-'+provider)
                    self.workers[provider] = worker
                    worker.start()
                self.cv.notify_all()
        try:
            return deepcopy(future.result(timeout=None if background else self.wait_seconds))
        except FutureTimeout:
            if future.done():
                return deepcopy(future.result())
            raise QueueBusy() from None

    def _run(self, provider):
        while True:
            with self.cv:
                self.cv.wait_for(lambda: self.stopped or self.pending[provider])
                if self.stopped:
                    return
                queue = self.pending[provider]
                # One priority step per 5s of waiting prevents starvation.
                now = monotonic()
                item = min(queue, key=lambda j: (j[0]-(now-j[1])/5, j[1]))
                queue.remove(item)
                _, enqueued, key, future, fn, background = item
            try:
                if not background and monotonic()-enqueued > self.wait_seconds:
                    with self.cv:
                        self.stats['expired'] += 1
                    raise QueueBusy()
                result = fn()
                future.set_result(result)
                with self.cv:
                    self.stats['completed'] += 1
            except Exception as error:
                future.set_exception(error)
                with self.cv:
                    self.stats['failed'] += 1
            finally:
                with self.cv:
                    self.flights.pop(key, None)

    def snapshot(self):
        with self.cv:
            return {**self.stats, 'inFlight':len(self.flights), 'pendingCount':sum(map(len,self.pending.values()))}

    def close(self):
        with self.cv:
            self.stopped = True
            for queue in self.pending.values():
                for _, _, key, future, _, _ in queue:
                    future.set_exception(QueueBusy())
                    self.flights.pop(key, None)
                queue.clear()
            self.cv.notify_all()
        for worker in self.workers.values():
            worker.join(timeout=2)
