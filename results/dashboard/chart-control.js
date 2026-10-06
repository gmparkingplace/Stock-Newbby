/* Local chat control: apply through the same chart functions, return the actual model. */
(() => {
  'use strict';
  if (!/^https?:$/.test(location.protocol)) return;
  const tab = crypto.randomUUID();
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  let running = false;
  async function post(path, body) {
    const r = await fetch('/api/control/'+path, {method:'POST',headers:{'Content-Type':'application/json','X-Chart-Control':'1'},body:JSON.stringify(body),signal:AbortSignal.timeout(6000)});
    if (!r.ok) throw new Error('control-unavailable');
    return r.json();
  }
  function snapshot() {
    const f=frameOf(curSym()),obs=currentObs();
    return {symbol:S.symbol,name:curSym()?.name,timeframe:S.tf,period:S.preset,selectedAsOf:S.selectedAsOf,
      visibleRange:window.__CF.visible(),autoRefresh:S.autoRef,refreshing:S.refreshing,
      source:f?.source || (S.sourceKind==='live'?'server':'stored'),sourceKind:S.sourceKind,
      marketAsOf:f?.marketAsOf || latestTime(f || {}),fetchedAt:f?.fetchedAt || null,
      delayStatus:f?.delayStatus || 'unknown',lastError:S.lastErr?.kind || null,
      entry:typeof entryEvaluation === "function" ? entryEvaluation(obs) : null, quote:window.__tossQuote?.() || null, observation:obs?.model || null,basisText:$('basisLine').textContent,
      realtimeText:$('realtimeLine').textContent,capturedAt:new Date().toISOString(),
      patterns: window.PatternPanel?.current() || null, flags: window.FlagPanel?.current() || null, triangles: window.TrianglePanel?.current() || null,
      lowStructures: window.LowStructurePanel?.current() || null,
      indicator: window.IndicatorPanel?.current() || null,
      priceIndicators: window.PriceIndicators?.current() || null,
      volumeProfile: f?.candles?.length ? VolumeProfile.build(f.candles, asOfIdx()) : null};
  }
  async function idle(deadline) {
    while (S.refreshing) {
      if (Date.now()>deadline*1000-1500) throw new Error('data-load-timeout');
      await sleep(100);
    }
  }
  async function execute(c) {
    if (Date.now()>c.deadline*1000) throw new Error('expired');
    const a=c.args;
    await idle(c.deadline);
    if (c.action==='view') {
      let target=a.symbol?.toUpperCase();
      if (target && /^\d{6}$/.test(target)) target += '.KS';
      if (target && !LIVE_D[target] && !EXP.symbols[target]) {
        if (!serverMode) throw new Error('symbol-not-in-offline-data');
        const j=await apiGet(API+'api/lookup?code='+encodeURIComponent(target));
        if (!validFrame(j)) throw new Error('symbol-data-unavailable');
        LIVE_D[j.symbol]=j; target=j.symbol;buildSymList('');
      }
      if (Date.now()>c.deadline*1000-1500) throw new Error('expired');
      if (target && target!==S.symbol) {
        if (a.tf) S.tf=a.tf;
        onSymbolChange(target);
      } else if (a.tf) setTF(a.tf);
      await idle(c.deadline);
      if (target && S.symbol!==target) throw new Error('selection-changed-during-command');
      if (a.tf && S.tf!==a.tf) throw new Error('timeframe-changed-during-command');
      const f=frameOf(curSym());
      if (!f?.candles?.length) throw new Error('timeframe-data-unavailable');
      if (Object.hasOwn(a,'asOf')) {
        if (a.asOf!==null && !f.candles.some(x=>x.time===a.asOf)) throw new Error(S.tf==='M' ? 'date-not-in-data-use-a-month-end-label-YYYY-MM-DD' : 'date-not-in-data-use-an-exact-bar-date');
        window.__CF.select(a.asOf);
      }
      if (a.period) {S.preset=a.period;window.__CF.render(true);}
      // Lightweight Charts commits its visible range on the next paint.
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    } else if (c.action==='auto') {
      if (S.autoRef!==a.enabled) $('btnAuto').click();
      await idle(c.deadline);
    } else if (c.action!=='inspect') throw new Error('unsupported-action');
    return snapshot();
  }
  async function poll() {
    if (!window.__CF || running) return;
    running=true;
    try {
      const {command:c}=await post('poll',{tab,snapshot:snapshot()});
      if (c) {
        let error=null;
        try {await execute(c);} catch (e) {error=e.message==='control-unavailable'?'control-unavailable':String(e.message).slice(0,100);}
        const result={tab,id:c.id,error,snapshot:snapshot()};
        // Repeat only the acknowledgement; never replay a chart command.
        for (let i=0;i<3;i++) {try {await post('result',result);break;} catch (_) {await sleep(500);}}
      }
    } catch (_) { /* Older/offline servers may not have control endpoints. */ }
    finally {running=false;}
  }
  document.addEventListener('DOMContentLoaded',()=>{poll();setInterval(poll,1000);});
})();
