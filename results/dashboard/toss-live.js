/* Browser-neutral SSE consumer. All Toss credentials stay in the Python server. */
"use strict";
(() => {
  let capability = false, source = null, activeSymbol = null, state = "idle";
  let quote = null, nextChartAt = 0;
  const forcedTransitions=new Map();
  window.__tossQuote = () => activeSymbol === S.symbol && quote ? {...quote, symbol:activeSymbol, connection:state, enabled:S.autoRef && !document.hidden} : null;
  const supported = (s) => !!s && !s.startsWith("^") && !s.endsWith("-USD");
  function paint() {
    const el = document.getElementById("realtimeLine");
    if (!el) return;
    if (!capability) { el.hidden = true; return; }
    el.hidden = false;
    if (S.selectedAsOf) {
      el.textContent = "과거 시점 보기 · 실시간 가격 표시 없음"; return;
    }
    const labels = {idle:"실시간 수신 대기", connecting:"실시간 연결 중", subscribed:"실시간 구독 연결됨",
      reconnecting:"연결 끊김 · 재연결 중", rejected:"구독 거절", "quote-unavailable":"최근 가격 조회 실패"};
    if (!supported(S.symbol)) { el.textContent = "이 종목은 yfinance 조회를 사용해요 · 토스 실시간 체결 대상 아님"; return; }
    if (!S.autoRef) { el.textContent = "실시간 수신 일시정지 · 자동갱신 OFF"; return; }
    let text = "토스증권 · " + (labels[state] || "실시간 연결 확인 중");
    if (quote && activeSymbol === S.symbol) {
      const stamp = new Date(quote.timestamp);
      const age = (Date.now() - stamp.getTime()) / 1000;
      const fresh = quote.kind === "trade" && !quote.cached && age >= 0 && age < 15 && state === "subscribed";
      text += " · " + (fresh ? "시세 수신 시각" : "마지막 시세 시각");
      text += " · " + stamp.toLocaleString("ko-KR", {hour12:false});
      if (!fresh) text += " (새 체결 대기)";
    } else text += " · 새 체결 대기";
    if (S.tf === "H4") {
      const frame = frameOf(curSym());
      text += frame?.source === "toss" ? " · 4시간봉: 토스 1분봉 집계" :
        frame?.source === "yfinance" ? " · 4시간봉: yfinance 집계" : " · 4시간봉 공급처 확인 중";
    } else text += " · 장중 캔들 스냅샷은 체결 유무와 무관하게 30초 간격 조회";
    el.textContent = text;
  }
  function close() {
    if (source) source.close();
    source = null; activeSymbol = null; quote = null; state = "idle";
  }
  function sync() {
    const wanted = capability && serverMode && S.autoRef && !document.hidden && supported(S.symbol) ? S.symbol : null;
    if (wanted === activeSymbol) { paint(); return; }
    close();
    if (!wanted) { paint(); return; }
    const symbol = wanted;
    activeSymbol = symbol; state = "connecting";
    source = new EventSource(API + "api/toss/stream?code=" + encodeURIComponent(symbol));
    const mine = source;
    mine.onmessage = event => {
      if (source !== mine || S.symbol !== symbol) return;
      let data;
      try { data = JSON.parse(event.data); } catch (_) { return; }
      if (data.kind === "status") {
        state = data.state;
      } else if ((data.kind === "quote" || data.kind === "trade") &&
                 Number.isFinite(data.price) && data.price > 0 && Number.isFinite(Date.parse(data.timestamp))) {
        if (!quote || Date.parse(data.timestamp) >= Date.parse(quote.timestamp)) quote = data;
        if (data.kind === "trade") state = "subscribed";
      }
      paint();
    };
    mine.onerror = () => { if (source === mine) { state = "reconnecting"; paint(); } };
    paint();
  }
  document.addEventListener("DOMContentLoaded", async () => {
    if (location.protocol !== "http:" && location.protocol !== "https:") return;
    async function discover() {
      try {
        const response = await fetch("api/market-provider");
        if (!response.ok) return;
        const data = await response.json(); capability = data.provider === "toss" && data.realtime === true;
      } catch (_) { capability = false; }
      sync();
    }
    await discover();
    setInterval(() => {
      sync();
      if (typeof renderSummary === "function") renderSummary();
      const frame=frameOf(curSym()),now=Date.now();
      const active=['open','break'].includes(frame?.marketSession?.state);
      const interval=active?30000:60000;
      const key=S.symbol+'#'+S.tf;
      const transitions=[frame?.marketSession?.nextTransitionAt,frame?.nextConfirmationAt]
        .map(Date.parse).filter(t=>Number.isFinite(t)&&t<=now&&t>Date.parse(frame?.fetchedAt));
      const transition=transitions.length?Math.max(...transitions):null;
      const force=transition!==null&&forcedTransitions.get(key)!==transition;
      if (serverMode && S.autoRef && !document.hidden && !S.refreshing &&
          now >= S.nextAutoAt && now >= nextChartAt &&
          (force || now-(S.lastRefreshAttemptAt||0)>=interval)) {
        if(force)forcedTransitions.set(key,transition);
        nextChartAt = now+5000;
        refreshLive({force,reason:"auto"});
      }
      if (typeof Watchlist !== "undefined" && Watchlist) Watchlist.tick(now);
    }, 1000);
    document.addEventListener("visibilitychange", sync);
    window.addEventListener("pagehide", close);
    window.addEventListener("pageshow", sync);
    document.getElementById("btnRefresh").addEventListener("click", discover);
    document.getElementById("btnAuto").addEventListener("click", sync);
    document.getElementById("sym").addEventListener("change", sync);
  });
})();
