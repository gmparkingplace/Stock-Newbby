"""대시보드 서버 모드: 정적 파일 + 임의 종목 조회 API (표준 라이브러리만).

실행: .venv/bin/python scripts/serve_dashboard.py [포트, 기본 8734]
- http://localhost:8734/ (대시보드)
- GET /api/lookup?code=TSLA → 캔들+지표+신호 (최근 3년 일봉, 자동 시장 매핑)
- GET /api/intraday?code=TSLA → 4시간봉 지표+신호 (토스 1분봉 우선, 미설정 시 yfinance)
- GET /api/backtest?code=TSLA → 즉석 백테스트 (동일 규칙·t+1 시가·비용 0, 참고용)
- GET /api/related?code=TSLA → 관련 종목 (동일 시장 유니버스 + 벤치마크)
시장 매핑: .KS→KR(069500.KS/091160.KS), 코인(BTC 등)→COIN(UTC), 그 외→US(SPY/XLK). 비용 0 베이스라인.
"""
import json
import sys
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
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
from signals import frame, to_4h, to_monthly, to_weekly  # noqa: E402
from yahoo_quality import latest_valid_segment  # noqa: E402
from request_metrics import RequestMetrics  # noqa: E402
import market_cache  # noqa: E402

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


@ttl_cache(ttl=5)
def intraday(code: str) -> dict:
    code = norm_code(code)
    if not code:
        raise ValueError("종목 코드 없음")
    tz, _, _ = market_of(code)
    try:
        df = yf.Ticker(code).history(period="6mo", interval="60m", auto_adjust=False, timeout=20)
    except Exception as e:
        raise TimeoutError(f"공급처 조회 시간초과: {code} ({e})")
    if df is None or len(df) == 0:
        raise ValueError(f"조회 결과 없음: {code}")
    if len(df) < 80:
        raise ValueError(f"분봉 데이터 부족: {code} ({len(df)}행)")
    fetched = _utcnow_iso()
    if df.index.tz is None:
        df = df.tz_localize(tz)
    d, warnings = latest_valid_segment(to_4h(df, tz))
    out = frame(d, True)
    out.update({"symbol": code, "name": NAMES.get(code, code), "live": True, "tf": "H4",
                "strats": ["A", "B", "C", "F"], "trades": {}, "fetchedAt": fetched,
                "dataWarnings": warnings})
    return _fresh(out, code, tz, out["candles"][-1]["time"] if out["candles"] else 0, "H4", {})


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
    session = market_session(sym)
    result = judgment_metadata({**payload, **cache}, sym, tz, payload.get("tf", "D"), session=session)
    if "weekly" in payload:
        result["weekly"] = judgment_metadata({**payload["weekly"], **cache}, sym, tz, "W", session=session)
    if "monthly" in payload:
        result["monthly"] = judgment_metadata({**payload["monthly"], **cache}, sym, tz, "M", session=session)
    return result


_FORCE_LAST: dict = {}




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
        session = market_session(code)
        last_end = session.get('lastSessionEnd')
        reconcile_after = epoch(last_end)+30*60 if last_end else None
        rows, cached, source_fetched, data_revision = svc.candles.daily(code,tz,force=force,reconcile_after=reconcile_after)
    else:
        rows, cached, source_fetched = CANDLES.daily(code, tz, force=force)
    if symbol not in _TOSS_NAMES:
        info = CLIENT.get('/api/v1/stocks', symbols=symbol)
        if info:
            _TOSS_NAMES[symbol] = info[0].get('name') or symbol
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


def market_lookup(code, force=False, background=False):
    if not market_cache.enabled():
        return _market_lookup(code,force=force)
    from toss_market import enabled, supports
    code = norm_code(code)
    if not code:
        raise ValueError('종목 코드 없음')
    provider = 'yfinance'
    if enabled() and not code.startswith('^') and not is_coin(code):
        from toss_catalog import resolve
        code = resolve(code)
        if supports(code):
            provider = 'toss'
    payload = market_cache.services().lookup(provider,code,'D',lambda force:_market_lookup(code,force),force,background=background)
    # Sessions/confirmation are evaluated at response time, using ORIGINAL source time.
    from pattern_service import attach
    return attach(_with_meta(payload,{k:payload[k] for k in ('cacheHit','cacheAge','stale')}))


def _toss_intraday(code, force=False):
    from toss_market import CLIENT, CANDLES, toss_symbol
    from minute_collection import MinuteCollection
    symbol = toss_symbol(code)
    tz = 'Asia/Seoul' if symbol.isdigit() else 'America/New_York'
    if market_cache.enabled():
        svc = market_cache.services()
        with svc.lock:
            if not hasattr(svc, 'minutes'):
                svc.minutes = MinuteCollection(CLIENT, svc.store, clock=svc.clock)
        rows, cached, fetched, data_revision, history = svc.minutes.minute(code, tz, force=force)
    else:
        rows, cached, fetched, data_revision, history = CANDLES.minute(code, tz, force=force)
    d = pd.DataFrame(rows)
    d.index = pd.to_datetime(d.pop('t'), unit='s', utc=True)
    candles = to_4h(d, tz).tail(MinuteCollection.TARGET_BARS)
    out = frame(candles, True)
    if not out['candles']:
        raise ValueError('4시간봉 데이터 부족')
    out.update(symbol=code, name=NAMES.get(code, code), tf='H4', live=True,
               strats=['A','B','C','F'], trades={}, source='toss',
               sourceInterval='1m', aggregation='exchange-date-first-minute-4h',
               fetchedAt=fetched, delayStatus='unknown', barAsOf=None,
               marketAsOf=out['candles'][-1]['time'], dataRevision=data_revision,
               cacheHit=cached, cacheAge=None, history=history)
    return _with_meta(out, {})


def market_intraday(code, force=False, background=False):
    from toss_market import enabled, supports
    code = norm_code(code)
    if not code:
        raise ValueError('종목 코드 없음')
    provider = 'yfinance'
    if enabled() and not code.startswith('^') and not is_coin(code):
        from toss_catalog import resolve
        code = resolve(code)
        if supports(code):
            provider = 'toss'
    def collect(force):
        return _toss_intraday(code, force=force) if provider == 'toss' else _with_meta(*intraday(code, force=force))
    if not market_cache.enabled():
        return collect(force)
    payload = market_cache.services().lookup(provider,code,'H4',collect,force,background=background)
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


from local_http import LocalOnlyHTTPMixin


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
        if not monitor(self) and not patterns(self) and not handle(self):
            self.send_error(404)

    def do_PUT(self):
        self.do_POST()

    def do_GET(self):
        from analysis_jobs import handle
        from monitor_service import handle as monitor
        from pattern_service import handle as patterns
        if monitor(self) or patterns(self) or handle(self):
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
            return self.api(lambda f: {"api": API_METRICS.snapshot(),
                                       "toss": CLIENT.metrics.snapshot(),
                                       "scope": "current-process", "collection":market_cache.diagnostics()}, "", "diagnostics", False)
        if u.path == "/api/search":
            query=q.get("q",[""])[0][:80]
            return self.api(lambda f: search_assets(query), "", "search", False)
        if u.path == "/api/market-provider":
            from toss_market import enabled
            return self.api(lambda f: {"provider":"toss" if enabled() else "yfinance", "realtime":enabled()}, "", "provider", False)
        if u.path == "/api/toss/stream":
            return serve_toss_stream(self, q.get("code", [""])[0])
        if u.path == "/api/lookup":
            return self.api(lambda f: market_lookup(q.get("code", [""])[0], force=f),
                            q.get("code", [""])[0], "lookup", force)
        if u.path == "/api/intraday":
            return self.api(lambda f: market_intraday(q.get("code", [""])[0],force=f),
                            q.get("code", [""])[0], "intraday", force)
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
            payload = fn(force)
            if isinstance(payload, dict):
                cache_hit = bool(payload.get("cacheHit"))
                payload["servedAt"] = _utcnow_iso()
                if note:
                    payload["note"] = ((payload.get("note") or "") + " · " + note).strip(" ·")
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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
            body = json.dumps({"error": msg[:200], "kind": kind,
                               "upstreamStatus": upstream_status, "retryAt": retry_at,
                               "lastSuccessAt":getattr(e,"last_success_at",None), "stale":True}).encode()
            self.send_response(status)
            retry_after = getattr(e, "retry_after", None)
            if retry_after is not None:
                self.send_header("Retry-After", str(retry_after))
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        finally:
            API_METRICS.finish(endpoint, started, status, kind, cache_hit)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8734
    from monitor_service import start_runtime, services, enabled as monitor_enabled
    server = ThreadingHTTPServer(("127.0.0.1", port), H)
    start_runtime()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if monitor_enabled() and market_cache.enabled():services().close()
        server.server_close()
