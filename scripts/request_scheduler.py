"""Single-flight, bounded provider queues. HTTP waiters do not own collection."""
from concurrent.futures import Future, TimeoutError as FutureTimeout
from copy import deepcopy
from datetime import datetime, timezone
from threading import Condition, Thread
from time import monotonic


class QueueBusy(Exception):
    """A local wait limit, not an upstream failure. `reason` tells contention apart."""
    code = 'queue-busy'
    status = 503
    retry_after = 2
    def __init__(self, reason='busy', retry_after=None):
        self.reason = reason
        if retry_after is not None:
            self.retry_after = retry_after
        self.retry_at = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp()+self.retry_after, timezone.utc).isoformat()
        super().__init__('조회 작업 진행 중 · 잠시 후 다시 확인하세요.')


class CollectionDeferred(Exception):
    """A long collection yielded its worker at a checkpoint.

    The job keeps its flight and is re-queued behind interactive work, so a
    user-selected symbol does not wait for a whole minute history backfill.
    """


class RequestScheduler:
    def __init__(self, wait_seconds=15, max_pending=32, expire_seconds=None):
        self.wait_seconds, self.max_pending = wait_seconds, max_pending
        # An HTTP waiter timing out must not cancel cache fill work. Keep queued jobs
        # long enough to finish behind one slow provider call, but still bound them.
        self.expire_seconds = max(60.0, wait_seconds*4) if expire_seconds is None else expire_seconds
        self.cv = Condition()
        self.flights, self.pending, self.workers = {}, {}, {}
        self.stopped = False
        self.stats = dict(submitted=0, merged=0, completed=0, failed=0, expired=0,
                          queueFull=0, waitTimeout=0, deferred=0)

    def execute(self, key, provider, fn, priority=1, background=False, wait_seconds=None):
        wait = self.wait_seconds if wait_seconds is None else wait_seconds
        with self.cv:
            if self.stopped:
                raise QueueBusy('stopped')
            future = self.flights.get(key)
            if future:
                self.stats['merged'] += 1
                # Promote a still-queued job when an interactive request joins it.
                for index, item in enumerate(self.pending.get(provider, [])):
                    if item[2] == key:
                        self.pending[provider][index] = (min(item[0], priority),
                                                         *item[1:5], item[5] or background)
                        break
            else:
                queue = self.pending.setdefault(provider, [])
                if len(queue) >= self.max_pending:
                    self.stats['queueFull'] += 1
                    raise QueueBusy('queue-full')
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
            return deepcopy(future.result(timeout=None if background else wait))
        except FutureTimeout:
            if future.done():
                return deepcopy(future.result())
            with self.cv:
                self.stats['waitTimeout'] += 1
            raise QueueBusy('wait-timeout') from None

    def enqueue(self, key, provider, fn, priority=2):
        """Queue cache fill without a waiter. Returns True when a job was added.

        The caller never blocks and never receives the result; a later request
        merges into the same flight or reads the published snapshot.
        """
        with self.cv:
            if self.stopped:
                raise QueueBusy('stopped')
            if key in self.flights:
                self.stats['merged'] += 1
                return False
            queue = self.pending.setdefault(provider, [])
            if len(queue) >= self.max_pending:
                self.stats['queueFull'] += 1
                raise QueueBusy('queue-full')
            future = Future()
            # No waiter will read this result; consume failures so a provider
            # error is not reported as an unretrieved future exception.
            future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
            self.flights[key] = future
            queue.append((priority, monotonic(), key, future, fn, True))
            self.stats['submitted'] += 1
            if provider not in self.workers:
                worker = Thread(target=self._run, args=(provider,), daemon=True, name='chart-'+provider)
                self.workers[provider] = worker
                worker.start()
            self.cv.notify_all()
            return True

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
                priority, enqueued, key, future, fn, background = item
            deferred = False
            try:
                if not background and monotonic()-enqueued > self.expire_seconds:
                    with self.cv:
                        self.stats['expired'] += 1
                    raise QueueBusy('expired')
                result = fn()
                future.set_result(result)
                with self.cv:
                    self.stats['completed'] += 1
            except CollectionDeferred:
                with self.cv:
                    self.stats['deferred'] = self.stats.get('deferred', 0) + 1
                    if self.stopped:
                        future.set_exception(QueueBusy('stopped'))
                    else:
                        # Keep the flight: waiters merge, the checkpoint resumes.
                        self.pending.setdefault(provider, []).append(
                            (max(priority, 2), enqueued, key, future, fn, True))
                        deferred = True
                        self.cv.notify_all()
            except Exception as error:
                future.set_exception(error)
                with self.cv:
                    self.stats['failed'] += 1
            finally:
                if not deferred:
                    with self.cv:
                        self.flights.pop(key, None)

    def snapshot(self):
        with self.cv:
            pending = {lane: len(queue) for lane, queue in self.pending.items()}
            return {**self.stats, 'inFlight':len(self.flights),
                    'pendingCount':sum(pending.values()),
                    'lanes': {'pending': pending, 'workers': len(self.workers)}}

    def has_waiting(self, provider, below=2):
        """True when interactive work is queued ahead of this background job."""
        with self.cv:
            return any(item[0] < below for item in self.pending.get(provider, []))

    def in_flight(self, key):
        with self.cv:
            return key in self.flights

    def close(self):
        with self.cv:
            self.stopped = True
            for queue in self.pending.values():
                for _, _, key, future, _, _ in queue:
                    future.set_exception(QueueBusy('stopped'))
                    self.flights.pop(key, None)
                queue.clear()
            self.cv.notify_all()
        for worker in self.workers.values():
            worker.join(timeout=2)
