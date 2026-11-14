"""이미 수집한 불변 자료의 패턴만 계산하는 유한 비동기 작업함."""
import atexit
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from queue import Empty, Full, Queue
import re
from secrets import token_hex
from threading import RLock, Thread
from time import time
from urllib.parse import parse_qs, urlparse

import market_cache
import pattern_service
import perf_probe

FAMILIES = (('patternAnalysis', 'horizontal', 'enabled'),
            ('flagAnalysis', 'flag', 'flags_enabled'),
            ('triangleAnalysis', 'triangle', 'triangles_enabled'),
            ('structureAnalysis', 'structure', 'structures_enabled'),
            ('structureEvidenceV2', 'evidence', 'structure_evidence_v2_enabled'))
FIELDS = tuple(row[0] for row in FAMILIES)
ID_RE = re.compile(r'^[0-9a-f]{32}$')


def _context(payload):
    """기능·수평선 설정과 저장소 참조를 제출 시점에 고정한다."""
    features = tuple((field, family) for field, family, gate in FAMILIES
                     if getattr(pattern_service, gate)())
    shared = market_cache.enabled()
    store = None
    levels = None
    if shared and any(family != 'evidence' and pattern_service.supported(
            payload['symbol'], payload.get('tf', 'D'), family) for _, family in features):
        store = market_cache.services().store
        if any(family == 'horizontal' for _, family in features):
            with store.lock:
                levels = deepcopy(pattern_service.get_settings(
                    store, payload['symbol'], payload.get('tf', 'D')))
    return dict(features=features, shared=shared, store=store, levels=levels)


def _placeholder(payload, family, shared):
    value = dict(enabled=True, sourceStatus='computing', symbol=payload['symbol'],
                 timeframe=payload.get('tf', 'D'), tf=payload.get('tf', 'D'),
                 dataRevision=payload.get('dataRevision'), sourceFetchedAt=payload.get('fetchedAt'))
    if family == 'evidence':
        if not pattern_service.structure_evidence_supported(payload['symbol'], payload.get('tf', 'D')):
            value.update(sourceStatus='unsupported', reason='stock-daily-only')
    elif not shared:
        value.update(enabled=False, sourceStatus='shared-cache-disabled')
    elif not pattern_service.supported(payload['symbol'], payload.get('tf', 'D'), family):
        value['sourceStatus'] = 'unsupported'
    return value


def _attach_frozen(payload, context):
    """공급처/달력을 호출하지 않고 기존 계산 캐시와 게시 보호를 재사용한다."""
    output = dict(payload)
    for field, family in context['features']:
        value = _placeholder(payload, family, context['shared'])
        if value['sourceStatus'] == 'computing':
            if family == 'evidence':
                value = pattern_service.evaluate_structure_evidence(payload)
            else:
                extra = {'levels_override': context['levels']} if family == 'horizontal' else {}
                value = pattern_service.evaluate(payload, context['store'], family=family, **extra)
        output[field] = value
    return output


class AsyncPatterns:
    """작업자 한 개, 중복 제출 합치기, 완료 항목만 TTL/LRU 제거."""
    def __init__(self, attach_fn=None, context_fn=None, clock=time,
                 max_jobs=64, max_queue=16, ttl=300):
        if max_jobs < 1 or max_queue < 1 or ttl <= 0:
            raise ValueError('invalid-pattern-job-limits')
        self.attach_fn = attach_fn
        self.context_fn = context_fn or _context
        self.clock, self.max_jobs, self.ttl = clock, max_jobs, ttl
        self.lock = RLock()
        self.jobs, self.keys = OrderedDict(), {}
        self.queue = Queue(maxsize=max_queue)
        self.closed = False
        self.worker = None

    def _evict(self):
        now = self.clock()
        for ident, job in list(self.jobs.items()):
            if job['state'] != 'pending' and now - job['updatedAt'] >= self.ttl:
                self._remove(ident)

    def _remove(self, ident):
        job = self.jobs.pop(ident)
        if self.keys.get(job['key']) == ident:
            self.keys.pop(job['key'], None)

    def _fingerprint(self, payload, context):
        # 응답/달력 검사 시각과 캐시 적중 표시는 계산 입력이 아니다.
        names = ('symbol', 'tf', 'source', 'candles', 'dataRevision', 'snapshotId', 'fetchedAt',
                 'lastConfirmedTime', 'snapshotEligible', 'stale', 'lastError',
                 'nextConfirmationAt', 'confirmedPolicy', 'adjustmentPolicy')
        basis = {name: payload.get(name) for name in names}
        session = payload.get('marketSession') or {}
        basis['marketSession'] = {name: session.get(name) for name in
                                 ('state', 'source', 'scope', 'sessionDate', 'lastSessionEnd')}
        try:
            fetched = datetime.fromisoformat(payload['fetchedAt'].replace('Z', '+00:00')).timestamp()
            fresh = 0 <= self.clock() - fetched <= 90
        except (KeyError, ValueError, TypeError, AttributeError):
            fresh = False
        basis.update(features=context['features'], shared=context['shared'], levels=context['levels'],
                     provisionalTimeEligible=fresh)
        return sha256(json.dumps(basis, sort_keys=True, separators=(',', ':'),
                                 ensure_ascii=False, allow_nan=False).encode()).hexdigest()

    @staticmethod
    def _public(job):
        value = dict(id=job['id'], state=job['state'], retryAfterMs=300,
                     identity=deepcopy(job['identity']))
        if job['state'] == 'ready':
            value['fields'] = deepcopy(job['fields'])
        elif job['state'] == 'error':
            value['error'] = deepcopy(job['error'])
        return value

    @staticmethod
    def _metadata(job):
        return {name: deepcopy(job[name]) for name in ('id', 'state', 'retryAfterMs', 'error') if name in job}

    def attach(self, payload):
        with perf_probe.span('pattern-async', 'submit'):
            context = self.context_fn(payload)
            if not context['features']:
                return payload
            output = dict(payload)
            placeholders = {field: _placeholder(payload, family, context['shared'])
                            for field, family in context['features']}
            output.update(placeholders)
            if not any(v['sourceStatus'] == 'computing' for v in placeholders.values()):
                return output
            fingerprint = self._fingerprint(payload, context)
            with self.lock:
                self._evict()
                ident = self.keys.get(fingerprint)
                if ident is not None:
                    self.jobs.move_to_end(ident)
                    result = self._public(self.jobs[ident])
                else:
                    # 대기 항목은 제거하지 않는다. 포화는 새 수집/동기 계산 없이 명시한다.
                    while len(self.jobs) >= self.max_jobs:
                        victim = next((i for i, j in self.jobs.items() if j['state'] != 'pending'), None)
                        if victim is None:
                            break
                        self._remove(victim)
                    ident = token_hex(16)
                    if self.closed or len(self.jobs) >= self.max_jobs or self.queue.full():
                        result = dict(id=ident, state='error', retryAfterMs=300,
                                      error={'kind': 'closed' if self.closed else 'busy'})
                    else:
                        identity = dict(symbol=payload['symbol'], timeframe=payload.get('tf', 'D'),
                                        source=payload.get('source'), dataRevision=payload.get('dataRevision'),
                                        snapshotId=payload.get('snapshotId'), fetchedAt=payload.get('fetchedAt'))
                        job = dict(id=ident, key=fingerprint, state='pending', identity=identity,
                                   updatedAt=self.clock())
                        # 원본과 공유하지 않는 깊은 복사본만 작업자에게 넘긴다.
                        frozen = deepcopy(payload)
                        self.jobs[ident] = job
                        self.keys[fingerprint] = ident
                        try:
                            self.queue.put_nowait((ident, frozen, context))
                        except Full:  # lock 안에서 제출하므로 보통 도달하지 않는다.
                            self._remove(ident)
                            result = dict(id=ident, state='error', retryAfterMs=300, error={'kind': 'busy'})
                        else:
                            result = self._public(job)
                            if self.worker is None:
                                self.worker = Thread(target=self._run, daemon=True, name='chart-patterns')
                                self.worker.start()
            if result['state'] == 'ready':
                output.update(result['fields'])
            elif result['state'] == 'error':
                for field, value in placeholders.items():
                    if value['sourceStatus'] == 'computing':
                        output[field] = dict(value, sourceStatus='error', errorCode=result['error']['kind'])
            output['patternJob'] = self._metadata(result)
            return output

    def _run(self):
        while True:
            item = self.queue.get()
            if item is None:
                self.queue.task_done()
                return
            ident, payload, context = item
            try:
                with perf_probe.span('pattern-async', 'work'):
                    result = self.attach_fn(payload) if self.attach_fn else _attach_frozen(payload, context)
                    fields = {field: deepcopy(result[field]) for field, _ in context['features']}
                    if any(value.get('sourceStatus') == 'error' for value in fields.values()):
                        raise ValueError('pattern-calculation-error')
                value = dict(state='ready', fields=fields)
            except Exception:
                # 오류에는 이전 timeline/결과나 공급처 예외 메시지를 싣지 않는다.
                value = dict(state='error', error={'kind': 'calculation-error'})
            with self.lock:
                job = self.jobs.get(ident)
                if job is not None and job['state'] == 'pending':
                    job.update(value, updatedAt=self.clock())
            self.queue.task_done()

    def get(self, ident):
        if not isinstance(ident, str) or not ID_RE.fullmatch(ident):
            raise ValueError('invalid-pattern-job-id')
        with self.lock:
            self._evict()
            job = self.jobs.get(ident)
            if job is None:
                return None
            self.jobs.move_to_end(ident)
            return self._public(job)

    def shutdown(self, wait=True, timeout=None):
        with self.lock:
            worker = self.worker
            if not self.closed:
                self.closed = True
                while True:
                    try:
                        ident, _, _ = self.queue.get_nowait()
                    except Empty:
                        break
                    if ident in self.jobs:
                        self.jobs[ident].update(state='error', error={'kind': 'closed'}, updatedAt=self.clock())
                    self.queue.task_done()
                if worker is not None:
                    self.queue.put_nowait(None)
        if wait and worker is not None:
            worker.join(timeout)


JOBS = AsyncPatterns()
atexit.register(JOBS.shutdown, wait=False)


def attach(payload):
    return JOBS.attach(payload)


def handle(handler):
    parsed = urlparse(handler.path)
    if parsed.path != '/api/pattern-jobs':
        return False
    from analysis_jobs import _local, _reply
    if not _local(handler):
        return _reply(handler, 403, {'kind': 'same-origin-required'})
    if handler.command != 'GET':
        return _reply(handler, 405, {'kind': 'method-not-allowed'})
    query = parse_qs(parsed.query, keep_blank_values=True)
    values = query.get('id', [])
    if len(values) != 1:
        return _reply(handler, 400, {'kind': 'invalid-pattern-job-id'})
    try:
        result = JOBS.get(values[0])
    except ValueError:
        return _reply(handler, 400, {'kind': 'invalid-pattern-job-id'})
    return _reply(handler, 200 if result else 404, result or {'kind': 'pattern-job-not-found'})
