"""One upstream trade socket shared by browser SSE subscribers. No account topics."""
from __future__ import annotations
from datetime import datetime, timezone
import json
import math
import queue
import random
import threading
import time
from toss_market import CLIENT, WS_URL, TossError, toss_symbol


def topic_for(code):
    symbol = toss_symbol(code)
    market = 'kr' if symbol.isdigit() and len(symbol) == 6 else 'us'
    return f'trade:{market}:{symbol}'


def normalize_trade(message):
    if message.get('type') != 'message' or not str(message.get('topic','')).startswith(('trade:kr:', 'trade:us:')):
        return None
    try:
        data = message['data']
        price, volume = float(data['price']), float(data['volume'])
        stamp = datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))
        if stamp.tzinfo is None or not math.isfinite(price) or price <= 0 or not math.isfinite(volume) or volume < 0:
            return None
        if data['currency'] not in ('KRW', 'USD'):
            return None
        return {'kind':'trade','topic':message['topic'],'price':price,'volume':volume,
                'timestamp':data['timestamp'],'currency':data['currency'],
                'receivedAt':datetime.now(timezone.utc).isoformat(),'source':'toss-websocket'}
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


class TradeHub:
    def __init__(self, client=CLIENT):
        self.client = client
        self.lock = threading.RLock()
        self.listeners = {}
        self.thread = None
        self.changed = threading.Event()
        self.last = {}
        self.status = 'idle'
        self.accepted = set()

    def subscribe(self, code):
        topic = topic_for(code)
        listener = queue.Queue(maxsize=32)
        with self.lock:
            if len({v for v in self.listeners.values()} | {topic}) > 20:
                raise TossError('subscription-limit')
            self.listeners[listener] = topic
            listener.put({'kind':'status','state':'subscribed' if topic in self.accepted and self.status == 'connected' else 'connecting'})
            # The cached tick retains its original timestamp; never call it new.
            if topic in self.last:
                listener.put(dict(self.last[topic], cached=True))
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._run, daemon=True)
                self.thread.start()
        self.changed.set()
        return listener

    def unsubscribe(self, listener):
        with self.lock:
            self.listeners.pop(listener, None)
        self.changed.set()

    def publish(self, value, topic=None):
        with self.lock:
            for listener, target in list(self.listeners.items()):
                if topic is not None and topic != target:
                    continue
                if listener.full():
                    try:listener.get_nowait()
                    except queue.Empty:pass
                listener.put_nowait(value)

    def _topics(self):
        with self.lock:
            return set(self.listeners.values())

    def _run(self):
        from websockets.sync.client import connect
        backoff = 1
        while True:
            if not self._topics():
                self.status = 'idle'
                self.changed.wait(1)
                self.changed.clear()
                continue
            self.publish({'kind':'status','state':'connecting'})
            try:
                token = self.client.token()
                with connect(WS_URL, additional_headers={'Authorization':'Bearer '+token},
                             open_timeout=15, close_timeout=2, ping_interval=30, ping_timeout=20) as ws:
                    declared = None
                    heartbeat = time.monotonic()
                    self.status = 'connected'
                    with self.lock:self.accepted = set()
                    while self._topics():
                        topics = self._topics()
                        if topics != declared:
                            groups = {}
                            for topic in sorted(topics):
                                channel, code = topic.rsplit(':',1)
                                groups.setdefault(channel, []).append(code)
                            ws.send(json.dumps([{'type':key,'codes':value} for key,value in groups.items()]))
                            declared = topics
                        if time.monotonic()-heartbeat >= 60:
                            ws.send('PING')
                            heartbeat = time.monotonic()
                        try:raw = ws.recv(timeout=.5)
                        except TimeoutError:continue
                        message = json.loads(raw)
                        if message.get('type') == 'subscriptions':
                            backoff = 1
                            with self.lock:self.accepted = set(message.get('subscribed',[]))
                            for topic in message.get('subscribed',[]):
                                self.publish({'kind':'status','state':'subscribed'}, topic)
                            for rejected in message.get('rejected',[]):
                                self.publish({'kind':'status','state':'rejected','code':'subscription-rejected'}, rejected.get('target'))
                        elif message.get('type') == 'error':
                            raise TossError('stream-server-error')
                        else:
                            tick = normalize_trade(message)
                            if tick and tick['topic'] in topics:
                                with self.lock:
                                    previous = self.last.get(tick['topic'])
                                    # Ignore older ticks; do not sum volume (no unique trade ID).
                                    if previous and datetime.fromisoformat(tick['timestamp']) < datetime.fromisoformat(previous['timestamp']):
                                        continue
                                    self.last[tick['topic']] = tick
                                self.publish(tick, tick['topic'])
            except Exception as exc:
                # Expose controlled error categories, never upstream headers or tokens.
                code = exc.code if isinstance(exc, TossError) else 'stream-disconnected'
                status = getattr(getattr(exc,'response',None),'status_code',None)
                if status == 401:
                    with self.client._lock:self.client._token = None
                if status == 403:code = 'permission-or-ip-denied'
                self.status = 'reconnecting'
                with self.lock:self.accepted = set()
                self.publish({'kind':'status','state':'reconnecting','code':code})
                time.sleep(backoff + random.random())
                backoff = min(30, backoff*2)


HUB = TradeHub()
