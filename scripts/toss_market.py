"""Read-only Toss market-data client. Credentials never enter browser responses."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from request_metrics import RequestMetrics

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://openapi.tossinvest.com'
WS_URL = 'wss://openapi-ws.tossinvest.com/ws/v1'
ALLOWED = {'/api/v1/prices', '/api/v1/candles', '/api/v1/stocks', '/api/v1/stocks/all',
           '/api/v1/market-calendar/KR', '/api/v1/market-calendar/US'}


class TossError(Exception):
    def __init__(self, code, status=0, retry_after=None):
        self.code, self.status = code, status
        self.retry_after = retry_after
        self.retry_at = ((datetime.now(timezone.utc) + timedelta(seconds=retry_after)).isoformat(timespec='seconds')
                         if retry_after is not None else None)
        super().__init__(f'토스증권 연결 오류: {code}' + (f' (HTTP {status})' if status else ''))


def credentials_path():
    value = os.environ.get('TOSS_CREDENTIALS_FILE')
    if not value:
        config = ROOT / '.local.json'
        if config.is_file():
            value = json.loads(config.read_text()).get('tossCredentialsFile')
    return Path(value).expanduser() if value else None


def read_credentials():
    p = credentials_path()
    if p is None or not p.is_file():
        raise TossError('credentials-file-missing')
    found = {}
    for line in p.read_text(encoding='utf-8-sig').splitlines():
        match = re.match(r'^\s*Client\s+(Id|Secret)\s*[:=]?\s*(\S+)\s*$', line, re.I)
        if match:
            found[match.group(1).lower()] = match.group(2)
    if set(found) != {'id', 'secret'}:
        raise TossError('credentials-format')
    return found


def toss_symbol(code):
    code = code.strip().upper()
    if re.fullmatch(r'\d{6}\.(KS|KQ)', code):
        return code[:6]
    if code.startswith('^') or code.endswith('-USD'):
        raise TossError('unsupported-market')
    if not re.fullmatch(r'[A-Z0-9.\-]{1,20}', code):
        raise TossError('invalid-symbol')
    return code


class TossClient:
    def __init__(self, budget=None):
        from provider_budget import ProviderBudget
        self.budget = budget or ProviderBudget()
        self._references = {}
        self._lock = threading.RLock()
        self._token = None
        self._expires = 0
        self._next_call = 0
        self.metrics = RequestMetrics()

    def _request(self, path, body=None, params=None, token=None):
        url = BASE + path
        if params:
            url += '?' + urllib.parse.urlencode(params)
        headers = {'Accept': 'application/json'}
        data = None
        if body is not None:
            data = urllib.parse.urlencode(body).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        if token:
            headers['Authorization'] = 'Bearer ' + token
        request = urllib.request.Request(url, data=data, headers=headers)
        started = self.metrics.start(path)
        status, error_kind = None, None
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                status = response.status
                return json.load(response)
        except urllib.error.HTTPError as exc:
            # Upstream bodies can contain sensitive information. Never relay them.
            codes = {400: 'invalid-request', 401: 'authentication-failed',
                     403: 'permission-or-ip-denied', 429: 'rate-limited'}
            status, error_kind = exc.code, codes.get(exc.code, 'upstream-error')
            retry_after = None
            try:
                value = int(exc.headers.get('Retry-After', ''))
                if 0 <= value <= 86400:
                    retry_after = value
            except (TypeError, ValueError, AttributeError):
                pass
            raise TossError(error_kind, status, retry_after=retry_after) from None
        except (urllib.error.URLError, TimeoutError):
            error_kind = 'network-or-timeout'
            raise TossError('network-or-timeout') from None
        except (ValueError, TypeError):
            error_kind = 'market-response-invalid'
            raise TossError(error_kind) from None
        finally:
            self.metrics.finish(path, started, status, error_kind)

    def token(self):
        with self._lock:
            if self._token and time.monotonic() < self._expires:
                return self._token
            self.budget.check('/oauth2/token')
            credentials = read_credentials()
            try:
                reply = self._request('/oauth2/token', body={
                    'grant_type': 'client_credentials',
                    'client_id': credentials['id'], 'client_secret': credentials['secret']})
            except TossError as error:
                self.budget.failure('/oauth2/token',error)
                raise
            self.budget.success('/oauth2/token')
            if not reply.get('access_token'):
                raise TossError('token-response-invalid')
            self._token = reply['access_token']
            self._expires = time.monotonic() + max(1, float(reply.get('expires_in', 60)) - 30)
            return self._token

    def get(self, path, **params):
        if path not in ALLOWED:
            raise TossError('endpoint-not-enabled')
        with self._lock:
            import copy
            ref_ttl = (21600 if path in ('/api/v1/stocks','/api/v1/stocks/all') else 60 if 'market-calendar' in path else 0)
            ref_key = (path,tuple(sorted(params.items())))
            hit = self._references.get(ref_key)
            if hit and 0<=time.monotonic()-hit[0]<ref_ttl:
                return copy.deepcopy(hit[1])
            self.budget.check(path)
            token = self.token()
            delay = self._next_call - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._next_call = time.monotonic() + (1.1 if path == "/api/v1/stocks/all" else .25)
            try:
                reply = self._request(path, params=params, token=token)
            except TossError as error:
                self.budget.failure(path,error)
                if error.status == 401:
                    self._expires = 0
                    self.budget.failure('/oauth2/token',error)
                raise
            self.budget.success(path)
            if 'result' not in reply:
                raise TossError('market-response-invalid')
            if ref_ttl:
                if len(self._references)>=512:
                    self._references.pop(next(iter(self._references)))
                self._references[ref_key]=(time.monotonic(),copy.deepcopy(reply['result']))
            return reply['result']


CLIENT = TossClient()


def enabled():
    return credentials_path() is not None


def supports(code):
    try:
        toss_symbol(code)
        return True
    except TossError:
        return False


def normalize_candles(rows, timezone):
    """Validate complete OHLCV rows and deduplicate inclusive page boundaries."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from math import isfinite
    result = {}
    for row in rows:
        try:
            stamp = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError('naive')
            values = [float(row[name]) for name in
                      ('openPrice', 'highPrice', 'lowPrice', 'closePrice', 'volume')]
            o, h, lo, c, v = values
            if not all(isfinite(x) for x in values) or min(o,h,lo,c) <= 0 or v < 0:
                raise ValueError('invalid')
            if not lo <= min(o,c) <= max(o,c) <= h:
                raise ValueError('ohlc')
            day = stamp.astimezone(ZoneInfo(timezone)).date().isoformat()
            result[day] = {'t':day, 'open':o, 'high':h, 'low':lo, 'close':c, 'volume':v}
        except (KeyError, TypeError, ValueError):
            raise TossError('invalid-candle') from None
    return [result[key] for key in sorted(result)]


class CandleStore:
    def __init__(self, client):
        self.client = client
        self.lock = threading.RLock()
        self.rows = {}
        self.updated = {}
        self.fetched_at = {}  # 원천 수집 시각(UTC ISO). 캐시 적중 시 원래 값 유지.
    def daily(self, code, timezone, force=False):
        """(rows, cached, source_fetched_at) 반환. cached여도 fetched_at은 수집 시각."""
        import copy
        from datetime import datetime, timezone as _tz
        with self.lock:
            symbol = toss_symbol(code)
            now = time.monotonic()
            if symbol in self.rows and not force and now-self.updated[symbol] < 30:
                return copy.deepcopy(self.rows[symbol]), True, self.fetched_at[symbol]
            # Reconcile up to 800 bars, including historical adjustment corrections.
            pages = 4
            collected, before, seen = [], None, set()
            for _ in range(pages):
                params = {'symbol':symbol,'interval':'1d','count':200,'adjusted':'true'}
                if before:
                    params['before'] = before
                reply = self.client.get('/api/v1/candles', **params)
                rows = reply.get('candles', [])
                collected.extend(rows)
                cursor = reply.get('nextBefore')
                if not rows or not cursor or cursor in seen:
                    break
                seen.add(cursor)
                before = cursor
            new = normalize_candles(collected, timezone)
            if not new:
                raise TossError('no-candles')
            # Inclusive pagination duplicates are expected. New rows win.
            data = new[-800:]
            self.rows[symbol] = data
            self.updated[symbol] = time.monotonic()
            self.fetched_at[symbol] = datetime.now(_tz.utc).isoformat(timespec="seconds")
            return copy.deepcopy(data), False, self.fetched_at[symbol]


CANDLES = CandleStore(CLIENT)
