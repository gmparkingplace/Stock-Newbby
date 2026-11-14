"""대시보드 서버 모드: 정적 파일 + 임의 종목 조회 API (표준 라이브러리만).

실행: .venv/bin/python scripts/serve_dashboard.py [포트, 기본 8734]
- http://localhost:8734/ (대시보드)
- GET /api/lookup?code=TSLA → 캔들+지표+신호 (최근 3년 일봉, 자동 시장 매핑)
- GET /api/intraday?code=TSLA&tf=H4 → 분봉 지표+신호 (tf=M5/M15/M30/H1/H2/H4, 토스 1분봉 우선, 미설정 시 yfinance)
- GET /api/backtest?code=TSLA → 즉석 백테스트 (동일 규칙·t+1 시가·비용 0, 참고용)
- GET /api/related?code=TSLA → 관련 종목 (동일 시장 유니버스 + 벤치마크)
시장 매핑: .KS→KR(069500.KS/091160.KS), 코인(BTC 등)→COIN(UTC), 그 외→US(SPY/XLK). 비용 0 베이스라인.
"""
import json
import os
import sys
import urllib.parse
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from time import time as _now

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_snapshot import to_adjusted  # noqa: E402
from indicators import cross_down, cross_up, wilder_rsi  # noqa: E402
from kr_p5 import atr_wilder  # noqa: E402
from time_contract import _fresh, _utcnow_iso, judgment_metadata, market_session, ttl_cache  # noqa: E402
from universe import COIN_ALIAS, COINS, NAMES, UNIVERSE, is_coin, is_kr, market_of, norm_code  # noqa: E402
from signals import frame, to_intraday, to_monthly, to_weekly  # noqa: E402
from intraday_timeframes import (aggregation as intraday_aggregation,  # noqa: E402
                                 label as intraday_label, minutes as intraday_minutes,
                                 tail_bars as intraday_tail_bars)
from yahoo_quality import latest_valid_segment  # noqa: E402
from request_metrics import RequestMetrics  # noqa: E402
import market_cache  # noqa: E402
import perf_probe  # noqa: E402
from request_scheduler import QueueBusy  # noqa: E402

API_METRICS = RequestMetrics()

def _app_version() -> str:
    """단일 버전 기준: package.json. 실패 시 unknown."""
    try:
        import json as _json
        return _json.loads((ROOT / "package.json").read_text())["version"]
    except Exception:
        return "unknown"


@ttl_cache(ttl=5)
def lookup(code: str) -> dict:
    code = norm_code(code)
    if not code:
        raise ValueError("종목 코드 없음")
    tz, _, _ = market_of(code)
    try:
        df = yf.Ticker(code).history(period="3y", auto_adjust=False, timeout=20)
    except Exception as e:
        raise TimeoutError(f"공급처 조회 시간초과: {code} ({e})")
    if df is None or len(df) == 0:
        raise ValueError(f"조회 결과 없음: {code}")
    if len(df) < 80:
        raise ValueError(f"데이터 부족: {code} ({len(df)}행)")
    fetched = _utcnow_iso()  # 공급처 자료를 실제로 받은 시각
    df = df.tz_convert(tz) if df.index.tz is not None else df.tz_localize(tz)
    d = to_adjusted(df).reset_index(names="timestamp")
    d["t"] = pd.to_datetime(d["timestamp"]).dt.date.astype(str)
    d, warnings = latest_valid_segment(d)
    out = frame(d, True)
    out.update({"symbol": code, "name": NAMES.get(code, code), "live": True,
                "strats": ["A", "B", "C", "F"], "trades": {},
                "weekly": frame(to_weekly(d), True), "fetchedAt": fetched,
                "dataWarnings": warnings})
    out["weekly"].update(fetchedAt=fetched, sourceDate=d["t"].iloc[-1])
    out["weekly"]["dataWarnings"] = warnings
    out["weekly"] = _fresh(out["weekly"], code, tz, out["weekly"]["candles"][-1]["time"], "W", {})
    m, mmeta = to_monthly(d)
    out["monthly"] = frame(m, True)
    out["monthly"].update(fetchedAt=fetched, sourceDate=d["t"].iloc[-1],
                          dataWarnings=warnings,
                          monthlyBars=mmeta["monthlyBars"], dailyBars=mmeta["dailyBars"],
                          droppedIncompleteFirst=mmeta["droppedIncompleteFirst"])
    mlast = out["monthly"]["candles"][-1]["time"] if out["monthly"]["candles"] else None
    out["monthly"] = _fresh(out["monthly"], code, tz, mlast, "M", {})
    return _fresh(out, code, tz, d["t"].iloc[-1], "D", {})


_YF_INTRADAY_CACHE: dict = {}


# 시장 변동성 맥락. 판단을 대신하지 않고, 위험 국면에서만 보수적 하향에 쓰인다.
VIX_HIGH = 30.0
VIX_ELEVATED = 20.0
VIX_SPIKE_PERCENT = 20.0


def _market_of_code(code: str) -> str:
    if code.endswith('-USD'):
        return 'CRYPTO'
    if code.endswith(('.KS', '.KQ')) or code in ('^KS11', '^KQ11'):
        return 'KR'
    return 'US'


@ttl_cache(ttl=600, maxsize=8)
def _market_context_cached(code: str = '') -> dict:
    """VIX 기반 시장 맥락. 실패해도 예외를 올리지 않고 available=False만 돌려준다."""
    market = _market_of_code(code or '')
    base = {'source': 'yfinance', 'symbol': '^VIX', 'market': market}
    if market != 'US':
        return {**base, 'available': False, 'applicable': False, 'reason': 'not-applicable'}
    try:
        df = yf.Ticker('^VIX').history(period='1y', interval='1d', auto_adjust=False, timeout=15)
    except Exception:
        return {**base, 'available': False, 'applicable': True, 'reason': 'provider-error'}
    if df is None or len(df) < 2:
        return {**base, 'available': False, 'applicable': True, 'reason': 'no-data'}
    fetched = _utcnow_iso()
    closes = [float(v) for v in df['Close'].tolist() if pd.notna(v)]
    if len(closes) < 2:
        return {**base, 'available': False, 'applicable': True, 'reason': 'no-data'}
    value, previous = closes[-1], closes[-2]
    as_of = pd.Timestamp(df.index[-1]).date().isoformat()
    change = ((value - previous) / previous * 100) if previous else None
    level = 'high' if value >= VIX_HIGH else 'elevated' if value >= VIX_ELEVATED else 'normal'
    if change is not None and change >= VIX_SPIKE_PERCENT:
        level = 'high'
    try:
        age_days = (pd.Timestamp(fetched).date() - pd.Timestamp(as_of).date()).days
    except Exception:
        age_days = None
    stale = age_days is not None and age_days > 5
    return {**base, 'available': True, 'applicable': True, 'value': round(value, 2),
            'previousClose': round(previous, 2),
            'changePercent': round(change, 2) if change is not None else None,
            'level': level, 'asOf': as_of, 'fetchedAt': fetched, 'stale': stale}


def market_context(code: str = '', force: bool = False) -> dict:
    """캐시 껍데기(ttl_cache의 (값, 메타) 튜플)를 벗겨 실제 dict만 돌려준다."""
    value, _meta = _market_context_cached(code, force)
    return value


def _yahoo_intraday_spec(tf: str) -> tuple[str, str]:
    """Yahoo interval/period per chart timeframe. 2h and 4h aggregate 60m."""
    if tf == 'M5':
        return '5m', '60d'
    if tf == 'M15':
        return '15m', '60d'
    if tf == 'M30':
        return '30m', '60d'
    if tf in ('H1', 'H2', 'H4'):
        return '60m', '6mo'
    raise ValueError('unsupported-intraday-timeframe')


def intraday(code: str, tf: str = 'H4') -> dict:
    code = norm_code(code)
    if not code:
        raise ValueError("종목 코드 없음")
    minutes = intraday_minutes(tf)
    interval, period = _yahoo_intraday_spec(tf)
    cache_key = (code, tf)
    now = _now()
    hit = _YF_INTRADAY_CACHE.get(cache_key)
    if hit and now - hit[0] < 5:
        return hit[1]
    tz, _, _ = market_of(code)
    try:
        df = yf.Ticker(code).history(period=period, interval=interval,
                                     auto_adjust=False, timeout=20)
    except Exception as e:
        raise TimeoutError(f"공급처 조회 시간초과: {code} ({e})")
    if df is None or len(df) == 0:
        raise ValueError(f"조회 결과 없음: {code}")
    if len(df) < 80:
        raise ValueError(f"{intraday_label(tf)} 데이터 부족: {code} ({len(df)}행)")
    fetched = _utcnow_iso()
    if df.index.tz is None:
        df = df.tz_localize(tz)
    from h4_sessions import annotate, trim_first_session
    df, partial_warnings = trim_first_session(df, code)
    d, warnings = latest_valid_segment(to_intraday(df, tz, minutes))
    d = d.tail(intraday_tail_bars(tf))
    if d.empty:
        raise ValueError(f"{intraday_label(tf)} 데이터 부족: {code}")
    out = frame(d, True)
    annotate(out['candles'], code, minutes=minutes)
    out.update({"symbol": code, "name": NAMES.get(code, code), "live": True, "tf": tf,
                "strats": ["A", "B", "C", "F"], "trades": {}, "fetchedAt": fetched,
                "sourceInterval": interval, "aggregation": intraday_aggregation(tf),
                "dataWarnings": partial_warnings + warnings})
    out = _fresh(out, code, tz, out["candles"][-1]["time"] if out["candles"] else 0, tf, {})
    if len(_YF_INTRADAY_CACHE) >= 32:
        _YF_INTRADAY_CACHE.pop(next(iter(_YF_INTRADAY_CACHE)))
    _YF_INTRADAY_CACHE[cache_key] = (now, out)
    return out


def backtest(code: str) -> dict:
    """즉석 백테스트: 동일 신호 규칙·t+1 시가·1%리스크·2ATR트레일·비용 0 (참고용, 실험 아님)."""
    import trades_p3

    d = market_lookup(code)
    import pandas as pd

    trades_p3.INITIAL_CAPITAL = 1.0
    by_time = {}
    for s in ("A", "B", "C", "F"):
        by_time[s] = {}
        for m in d["marks"][s]:
            by_time[s].setdefault(m["time"], []).append(m["side"])
    df = pd.DataFrame({"date_s": [c["time"] for c in d["candles"]],
                       "open": [c["open"] for c in d["candles"]],
                       "close": [c["close"] for c in d["candles"]],
                       "atr14": [s.get("atr14") for s in d["state"]]})
    for s in ("A", "B", "C", "F"):
        df["sig" + s] = [by_time[s].get(t, ["none"])[0] for t in df["date_s"]]
    per, trades = {}, {}
    for s in ("A", "B", "C", "F"):
        tr, st, eq, held = trades_p3.build_sized(
            df, "sig" + s, "atr14", 0.0, 0.0, 0.0, include_fees=False, risk=0.01, k=2.0)
        eqs = pd.Series(eq)
        peak = eqs.cummax()
        mdd = float(((eqs - peak) / peak).min() * 100) if len(eqs) else 0.0
        done = [t for t in tr if t.get("status") == "completed"]
        wins = sum(1 for t in done if (t.get("ret_pct") or 0) > 0)
        n = len(done)
        per[s] = {"ret": round((eq[-1] - 1) * 100, 2) if eq else 0.0,
                  "mdd": round(mdd, 2),
                  "exposure": round(sum(held) / len(held) * 100, 1) if held else 0.0,
                  "completed": n, "winrate": round(wins / n * 100, 1) if n else 0.0}
        trades[s] = tr
    bh = round((float(df["close"].iloc[-1]) / float(df["open"].iloc[1]) - 1) * 100, 2)
    return {"symbol": d["symbol"], "name": d["name"], "per": per, "trades": trades,
            "bh": bh, "note": "즉석 계산·일봉·t+1 시가·1%리스크·2ATR·비용 0 (참고용)"}


def _with_meta(payload: dict, cache: dict) -> dict:
    sym = payload.get("symbol", "")
    tz = market_of(sym)[0]
    session = market_session(sym, source=payload.get('source'))
    result = judgment_metadata({**payload, **cache}, sym, tz, payload.get("tf", "D"), session=session)
    if "weekly" in payload:
        result["weekly"] = judgment_metadata({**payload["weekly"], **cache}, sym, tz, "W", session=session)
    if "monthly" in payload:
        result["monthly"] = judgment_metadata({**payload["monthly"], **cache}, sym, tz, "M", session=session)
    return result


_FORCE_LAST: dict = {}
_AUDIT_RETRY_AT: dict = {}


def _audit_lane(svc, provider, tf):
    lane = getattr(svc, '_lane', None)
    return lane(provider, tf) if lane else provider


def _queue_audit(svc, key, lane, fn, cooldown=300):
    """Schedule a whole-history audit without repeating a failing job per request."""
    scheduler = getattr(svc, 'scheduler', None)
    if scheduler is None or not hasattr(scheduler, 'enqueue'):
        return False
    now = _now()
    if now < _AUDIT_RETRY_AT.get(key, 0):
        return False
    if len(_AUDIT_RETRY_AT) >= 512:
        _AUDIT_RETRY_AT.clear()
    try:
        scheduled = svc.scheduler.enqueue(key, lane, fn, priority=3)
    except QueueBusy:
        scheduled = False
    if scheduled:
        _AUDIT_RETRY_AT[key] = now + cooldown
    return scheduled




def _provider_choice(tf='D'):
    """Provider override from env or .local.json.

    기본 일·주·월봉은 Yahoo이며 분봉만 지원 주식에 Toss를 사용한다.
    auto     = Toss for supported stocks, Yahoo Finance otherwise
    toss     = prefer Toss for supported stocks
    yfinance = always Yahoo Finance (no Toss candle/backfill calls)
    """
    name = 'CHART_H4_PROVIDER' if tf == 'H4' else 'CHART_MARKET_PROVIDER'
    key = 'h4Provider' if tf == 'H4' else 'marketProvider'
    value = os.environ.get(name)
    if value is None:
        try:
            value = json.loads((ROOT / '.local.json').read_text()).get(key)
        except (OSError, ValueError):
            value = None
    return value if value in ('auto', 'toss', 'yfinance') else ('auto' if tf == 'H4' else 'yfinance')


def related(code: str) -> dict:
    code = norm_code(code)
    if is_coin(code):
        group = [s for s in COINS]
        if code not in group:
            group = [code] + group
        return {"symbol": code, "related": [{"symbol": s, "name": NAMES.get(s, s)} for s in group]}
    kr = is_kr(code)
    group = [s for s in UNIVERSE if is_kr(s) == kr]
    if code not in group:
        group = [code] + group
    return {"symbol": code, "related": [{"symbol": s, "name": NAMES.get(s, s)} for s in group]}


# Toss market-data adapter; frozen research results are never modified.
_TOSS_NAMES = {}


def _market_lookup(code, force=False):
    from toss_market import enabled, supports, CLIENT, CANDLES, toss_symbol
    code = norm_code(code)
    if is_coin(code):
        return _with_meta(*lookup(code, force=force))
    # An explicit Yahoo choice must not fall through to a Toss collection: the
    # cache key would label Toss rows as yfinance and slow the requested path.
    if _provider_choice('D') == 'yfinance':
        return _with_meta(*lookup(code, force=force))
    if enabled() and not code.startswith("^") and not is_coin(code):
        from toss_catalog import resolve
        code = resolve(code)
    if not enabled() or not supports(code):
        return _with_meta(*lookup(code, force=force))
    code = norm_code(code)
    symbol = toss_symbol(code)
    tz = 'Asia/Seoul' if symbol.isdigit() else 'America/New_York'
    data_revision = None
    if market_cache.enabled():
        from candle_collection import CandleCollection
        from market_store import epoch
        svc = market_cache.services()
        if not hasattr(svc, 'candles'):
            svc.candles = CandleCollection(CLIENT,svc.store,clock=svc.clock)
        session = market_session(code, source='toss')
        last_end = session.get('lastSessionEnd')
        reconcile_after = epoch(last_end)+30*60 if last_end else None
        rows, cached, source_fetched, data_revision = svc.candles.daily(code,tz,force=force)
        # Whole-history reconciliation runs as a lowest-priority background job.
        audit_due = getattr(svc.candles, 'needs_audit', None)
        if audit_due and audit_due(code,tz,reconcile_after):
            _queue_audit(svc,'|'.join(('audit',symbol)),_audit_lane(svc,'toss','D'),
                         lambda:svc.candles.daily(code,tz,audit=True))
    else:
        rows, cached, source_fetched = CANDLES.daily(code, tz, force=force)
    if symbol not in _TOSS_NAMES:
        info = CLIENT.get('/api/v1/stocks', symbols=symbol)
        if info:
            _TOSS_NAMES[symbol] = info[0].get('name') or symbol
    with perf_probe.span('market','transform-daily'):
        d = pd.DataFrame(rows)
        out = frame(d, True)
        weekly = frame(to_weekly(d), True)
        # fetchedAt은 원천 수집 시각(캐시 적중 시 원래 값). servedAt은 H.api가 응답 시점에 기록.
        # A source fetch is not a trade watermark; synchronization remains unverified.
        m, mmeta = to_monthly(d)
        monthly = frame(m, True)
    for target, tf in ((out, "D"), (weekly, "W"), (monthly, "M")):
        last = target['candles'][-1]['time'] if target['candles'] else None
        target.update({'source':'toss','delayStatus':'unknown','marketAsOf':last,
                       'fetchedAt':source_fetched, 'sourceDate':rows[-1]['t'],
                       'barAsOf':None,
                       'cacheHit':cached,'cacheAge':None,
                       'confirmedPolicy':'market-calendar'})
    monthly.update({'monthlyBars':mmeta["monthlyBars"], 'dailyBars':mmeta["dailyBars"],
                    'droppedIncompleteFirst':mmeta["droppedIncompleteFirst"]})
    out.update({'symbol':code,'name':_TOSS_NAMES.get(symbol, NAMES.get(code,code)),
                'live':True,'strats':['A','B','C','F'],'trades':{},'weekly':weekly,'monthly':monthly})
    if data_revision:
        out['dataRevision'] = data_revision
    return _with_meta(out, {})


def market_lookup(code, force=False, background=False, prefer_stale=False, defer_patterns=False):
    if not market_cache.enabled():
        # The parallel evidence field is pure calculation and must not disappear
        # just because the shared market cache is disabled.
        if defer_patterns:
            from pattern_async import attach
            return attach(_market_lookup(code,force=force))
        from pattern_service import attach_evidence
        return attach_evidence(_market_lookup(code,force=force))
    from toss_market import enabled, supports
    code = norm_code(code)
    if not code:
        raise ValueError('종목 코드 없음')
    provider = 'yfinance'
    if _provider_choice('D') != 'yfinance' and enabled() and not code.startswith('^') and not is_coin(code):
        from toss_catalog import resolve
        code = resolve(code)
        if supports(code):
            provider = 'toss'
    # Keep the default call shape: only UI loads opt into the non-blocking path.
    extra = {'prefer_stale': True} if prefer_stale else {}
    payload = market_cache.services().lookup(provider,code,'D',lambda force:_market_lookup(code,force),force,background=background,**extra)
    # Sessions/confirmation are evaluated at response time, using ORIGINAL source time.
    if defer_patterns:
        from pattern_async import attach
    else:
        from pattern_service import attach
    return attach(_with_meta(payload,{k:payload[k] for k in ('cacheHit','cacheAge','stale')}))


def _toss_intraday(code, tf='H4', force=False, yield_check=None):
    from toss_market import CLIENT, CANDLES, toss_symbol
    from minute_collection import MinuteCollection
    minutes = intraday_minutes(tf)
    symbol = toss_symbol(code)
    tz = 'Asia/Seoul' if symbol.isdigit() else 'America/New_York'
    if market_cache.enabled():
        svc = market_cache.services()
        with svc.lock:
            if not hasattr(svc, 'minutes'):
                svc.minutes = MinuteCollection(CLIENT, svc.store, clock=svc.clock)
        extra = {'yield_check': yield_check} if yield_check is not None else {}
        rows, cached, fetched, data_revision, history = svc.minutes.minute(
            code, tz, force=force, **extra)
        minutes_audit = getattr(svc.minutes, 'needs_audit', None)
        if minutes_audit and minutes_audit(code,tz):
            _queue_audit(svc,'|'.join(('audit','1m',symbol)),_audit_lane(svc,'toss',tf),
                         lambda:svc.minutes.minute(code,tz,audit=True))
    else:
        rows, cached, fetched, data_revision, history = CANDLES.minute(code, tz, force=force)
    with perf_probe.span('market','transform-intraday'):
        d = pd.DataFrame(rows)
        d.index = pd.to_datetime(d.pop('t'), unit='s', utc=True)
        candles = to_intraday(d, tz, minutes).tail(intraday_tail_bars(tf))
        out = frame(candles, True)
    if not out['candles']:
        raise ValueError(f'{intraday_label(tf)} 데이터 부족')
    from h4_sessions import annotate
    annotate(out['candles'], code, source='toss', minutes=minutes)
    out.update(symbol=code, name=NAMES.get(code, code), tf=tf, live=True,
               strats=['A','B','C','F'], trades={}, source='toss',
               sourceInterval='1m', aggregation=intraday_aggregation(tf),
               fetchedAt=fetched, delayStatus='unknown', barAsOf=None,
               marketAsOf=out['candles'][-1]['time'], dataRevision=data_revision,
               cacheHit=cached, cacheAge=None, history=history)
    return _with_meta(out, {})


def market_intraday(code, tf='H4', force=False, background=False, prefer_stale=False, defer_patterns=False):
    from toss_market import enabled, supports
    code = norm_code(code)
    if not code:
        raise ValueError('종목 코드 없음')
    intraday_minutes(tf)  # validate before touching the provider path
    provider = 'yfinance'
    if _provider_choice('H4') != 'yfinance' and enabled() and not code.startswith('^') and not is_coin(code):
        from toss_catalog import resolve
        code = resolve(code)
        if supports(code):
            provider = 'toss'
    def collect(force):
        if provider != 'toss':
            value = intraday(code, tf)
            # The pure lookup returns a payload; older callers/tests stub it as
            # a (payload, cache) pair. Keep both shapes.
            return _with_meta(*value) if isinstance(value, tuple) else _with_meta(value, {})
        if not market_cache.enabled():
            return _toss_intraday(code, tf, force=force)
        # Background minute paging yields its worker when another symbol waits.
        svc = market_cache.services()
        scheduler = getattr(svc, 'scheduler', None)
        lane = getattr(svc, '_lane', None)
        waiting = getattr(scheduler, 'has_waiting', None)
        if lane is None or waiting is None:
            return _toss_intraday(code, tf, force=force)
        lane = lane(provider, tf)
        return _toss_intraday(code, tf, force=force, yield_check=lambda: waiting(lane, 2))
    if not market_cache.enabled():
        if defer_patterns:
            from pattern_async import attach
            return attach(collect(force))
        from pattern_service import attach_evidence
        return attach_evidence(collect(force))
    extra = {'prefer_stale': True} if prefer_stale else {}
    payload = market_cache.services().lookup(provider,code,tf,collect,force,background=background,**extra)
    if defer_patterns:
        from pattern_async import attach
    else:
        from pattern_service import attach
    return attach(_with_meta(payload,{k:payload[k] for k in ('cacheHit','cacheAge','stale')}))


def serve_toss_stream(handler, code):
    import queue
    from toss_market import enabled, CLIENT, toss_symbol, TossError
    from toss_stream import HUB
    if not enabled():
        handler.send_error(503, 'Toss not configured')
        return
    origin = handler.headers.get('Origin')
    allowed = {f'http://127.0.0.1:{handler.server.server_port}', f'http://localhost:{handler.server.server_port}'}
    if origin and origin not in allowed:
        handler.send_error(403, 'Same-origin required')
        return
    try:
        symbol = toss_symbol(code)
        listener = HUB.subscribe(code)
    except TossError:
        handler.send_error(400, 'Unsupported subscription')
        return
    handler.send_response(200)
    handler.send_header('Content-Type','text/event-stream; charset=utf-8')
    handler.send_header('Cache-Control','no-cache')
    handler.send_header('X-Accel-Buffering','no')
    handler.end_headers()
    handler.connection.settimeout(15)
    def send(value):
        handler.wfile.write(('data: '+json.dumps(value,ensure_ascii=False,allow_nan=False)+'\n\n').encode())
        handler.wfile.flush()
    try:
        # REST snapshot is explicitly labelled, not a newly received realtime trade.
        try:
            rows = CLIENT.get('/api/v1/prices',symbols=symbol)
            if rows:
                quote = rows[0]
                send({'kind':'quote','price':float(quote['lastPrice']),
                      'timestamp':quote['timestamp'],'currency':quote['currency'],'source':'toss-rest'})
        except TossError:
            send({'kind':'status','state':'quote-unavailable'})
        while True:
            try:send(listener.get(timeout=5))
            except queue.Empty:
                handler.wfile.write(b': heartbeat\n\n')
                handler.wfile.flush()
    except (BrokenPipeError,ConnectionResetError,TimeoutError,OSError):
        pass
    finally:
        HUB.unsubscribe(listener)
        handler.close_connection = True


def search_assets(query):
    from toss_market import enabled
    from toss_catalog import search
    q=query.strip().upper()
    coins=[{"symbol":s,"name":NAMES[s],"market":"코인 · yfinance","source":"yfinance"} for s in COINS
           if q in ("코인","COIN","CRYPTO") or q and q in (s+NAMES[s]).upper()]
    if coins:return {"results":coins}
    if enabled():return {"results":search(query)}
    return {"results":[{"symbol":s,"name":NAMES.get(s,s)} for s in UNIVERSE if q and q in (s+NAMES.get(s,s)).upper()]}


from local_http import LocalOnlyHTTPMixin, LocalThreadingHTTPServer


class H(LocalOnlyHTTPMixin, SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT / "results" / "dashboard"), **kw)

    def end_headers(self):
        static_path = self.path.split("?")[0]
        if static_path in ("/", "/index.html", "/data.js", "/chart-first.html"):
            self.send_header("Cache-Control", "no-store")
        elif static_path.endswith(".js"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_POST(self):
        from analysis_jobs import handle
        from monitor_service import handle as monitor
        from pattern_service import handle as patterns
        from pattern_async import handle as pattern_jobs
        if not monitor(self) and not patterns(self) and not pattern_jobs(self) and not handle(self):
            self.send_error(404)

    def do_PUT(self):
        self.do_POST()

    def do_GET(self):
        from analysis_jobs import handle
        from monitor_service import handle as monitor
        from pattern_service import handle as patterns
        from pattern_async import handle as pattern_jobs
        if monitor(self) or patterns(self) or pattern_jobs(self) or handle(self):
            return
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        force = q.get("force", [""])[0] == "1"
        if u.path == "/api/health":
            from toss_market import enabled
            return self.api(lambda f: {"status": "ok", "version": _app_version(),
                                       "provider": "toss" if enabled() else "yfinance",
                                       "realtime": enabled()}, "", "health", False)
        if u.path == "/api/diagnostics":
            from toss_market import CLIENT
            import perf_probe
            return self.api(lambda f: {"api": API_METRICS.snapshot(),
                                       "toss": CLIENT.metrics.snapshot(),
                                       "perf": perf_probe.snapshot(),
                                       "scope": "current-process", "collection":market_cache.diagnostics()}, "", "diagnostics", False)
        if u.path == "/api/search":
            query=q.get("q",[""])[0][:80]
            return self.api(lambda f: search_assets(query), "", "search", False)
        if u.path == "/api/market-provider":
            from toss_market import enabled
            return self.api(lambda f: {"provider":"toss" if enabled() else "yfinance", "realtime":enabled(),
                                       "dailyProvider":_provider_choice('D'), "intradayProvider":_provider_choice('H4'),
                                       "realtimeScope":"intraday"}, "", "provider", False)
        if u.path == "/api/toss/stream":
            return serve_toss_stream(self, q.get("code", [""])[0])
        if u.path == "/api/market-context":
            return self.api(lambda f: market_context(q.get("code", [""])[0]), "", "market-context", False)
        if u.path == "/api/lookup":
            return self.api(lambda f: market_lookup(q.get("code", [""])[0], force=f, prefer_stale=not force, defer_patterns=True),
                            q.get("code", [""])[0], "lookup", force)
        if u.path == "/api/intraday":
            code = q.get("code", [""])[0]
            tf = q.get("tf", ["H4"])[0]
            return self.api(lambda f: market_intraday(code, tf, force=f, prefer_stale=not force, defer_patterns=True),
                            code, "intraday", force)
        if u.path == "/api/backtest":
            return self.api(lambda f: backtest(q.get("code", [""])[0]),
                            q.get("code", [""])[0], "backtest", False)
        if u.path == "/api/related":
            return self.api(lambda f: related(q.get("code", [""])[0]),
                            q.get("code", [""])[0], "related", False)
        if u.path == "/api/universe":
            return self.api(lambda f: {"universe": [{"symbol": s, "name": NAMES.get(s, s)}
                                                    for s in UNIVERSE]}, "", "universe", False)
        return super().do_GET()

    def _send_json(self, status, payload, headers=()):
        body = json.dumps(payload, ensure_ascii=False).encode()
        try:
            self.send_response(status)
            for key, value in headers:
                self.send_header(key, str(value))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True
        except OSError:
            # A browser cancellation must not surface as a server traceback.
            self.close_connection = True
            return False

    def api(self, fn, code="", endpoint="", force=False):
        # force 과도 요청 제한: 같은 종목 10초 이내 강제갱신은 캐시로 응답하고 표시
        note = None
        if force and endpoint in ("lookup", "intraday") and not market_cache.enabled():
            key = (endpoint, norm_code(code))
            t = _now()
            if key in _FORCE_LAST and t - _FORCE_LAST[key] < 10:
                force = False
                note = "force throttled (10s) · 캐시 재사용"
            else:
                _FORCE_LAST[key] = t
        started = API_METRICS.start(endpoint)
        status, kind, cache_hit = 200, None, False
        try:
            with perf_probe.span('request', endpoint or 'other'):
                payload = fn(force)
            if isinstance(payload, dict):
                cache_hit = bool(payload.get("cacheHit"))
                payload["servedAt"] = _utcnow_iso()
                if note:
                    payload["note"] = ((payload.get("note") or "") + " · " + note).strip(" ·")
            if not self._send_json(200, payload):
                status, kind = 499, "client-disconnected"
        except (BrokenPipeError, ConnectionResetError):
            # Browser cancellation does not mean the upstream lookup failed.
            status, kind = 499, "client-disconnected"
        except Exception as e:
            msg = str(e)
            kind = ("timeout" if isinstance(e, TimeoutError) or "시간초과" in msg
                    else "invalid" if "코드 없음" in msg
                    else "nodata" if ("없음" in msg or "부족" in msg) else "provider")
            kind = getattr(e, "code", None) or kind
            upstream_status = None if kind == "queue-busy" else getattr(e, "status", None) or None
            retry_at = getattr(e, "retry_at", None)
            status = (503 if kind == "queue-busy" else 429 if upstream_status == 429 else 504 if kind in ("timeout", "network-or-timeout")
                      else 502 if upstream_status or kind in ("upstream-error", "market-response-invalid")
                      else 400)
            headers = []
            retry_after = getattr(e, "retry_after", None)
            if retry_after is not None:
                headers.append(("Retry-After", retry_after))
            delivered = self._send_json(status, {"error": msg[:200], "kind": kind,
                                                 "upstreamStatus": upstream_status, "retryAt": retry_at,
                                                 "lastSuccessAt":getattr(e,"last_success_at",None), "stale":True}, headers)
            if not delivered:
                status, kind = 499, "client-disconnected"
        finally:
            API_METRICS.finish(endpoint, started, status, kind, cache_hit)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8734
    from monitor_service import start_runtime, services, enabled as monitor_enabled
    server = LocalThreadingHTTPServer(("127.0.0.1", port), H)
    start_runtime()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if monitor_enabled() and market_cache.enabled():services().close()
        server.server_close()
