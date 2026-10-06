/* Current UI only: desktop only; one Firefox session, one real Python mailbox, sequential scenarios. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const zlib = require('node:zlib');
const {sameProfile,sameSnapshot,sameComputedModel,samePatternSnapshot} = require('./snapshot-check');
const {spawn, spawnSync} = require('node:child_process');
const ROOT = path.resolve(__dirname, '../..');
const LOGS = path.join(__dirname, 'logs');
const SHOTS = path.join(__dirname, 'shots');
const PY = process.env.PYTHON || path.join(ROOT,'.venv/bin/python');
const PORT = Number(process.env.MOCK_PORT || 9444);
const WDPORT = Number(process.env.WD_PORT || 4449);
const URL = `http://127.0.0.1:${PORT}`;
const DRIVER = process.env.GECKODRIVER || 'geckodriver';
const FIREFOX = process.env.FIREFOX || 'firefox';
const deadline = Date.now() + Number(process.env.RUN_TIMEOUT_MS || 300000);
const owned = [];
let session, driver, server, stopping = false, cleanupDeadline;
const evidence = [];
fs.mkdirSync(LOGS, {recursive:true});
fs.mkdirSync(SHOTS, {recursive:true});
const pause = ms => new Promise(r => setTimeout(r, ms));
function remaining() { if(cleanupDeadline) {const n=cleanupDeadline-Date.now();assert(n>0,'cleanup timeout');return n;} assert(!stopping, 'run cancelled'); const n=deadline-Date.now(); assert(n>0, 'run timeout'); return n; }
function scrub(text) { return String(text).replace(/((?:authorization|api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*)[^\s,]+/gi, '$1[redacted]').replace(/Bearer\s+\S+/gi, 'Bearer [redacted]'); }
async function request(base, route, method='GET', body, timeout=15000) {
  const response = await fetch(base+route, {method, headers:{'Content-Type':'application/json'}, body:body===undefined?undefined:JSON.stringify(body), signal:AbortSignal.timeout(Math.min(timeout, remaining()))});
  const data = await response.json();
  assert(response.ok, `${method} ${route}: ${response.status} ${JSON.stringify(data).slice(0,300)}`);
  return data;
}
const wd = (route, method='GET', body) => request(`http://127.0.0.1:${WDPORT}`, route, method, body, 35000);
const cmd = (route, method='GET', body) => wd(`/session/${session}${route}`, method, body);
async function ev(expression) {
  return (await cmd('/execute/sync', 'POST', {script:'return window.eval(arguments[0]);', args:[expression]})).value;
}
async function until(fn, description, ms=15000) {
  const end = Date.now()+Math.min(ms, remaining());
  let last;
  do { remaining(); last=await fn(); if(last) return last; await pause(100); } while(Date.now()<end);
  throw new Error(`timeout: ${description}; last=${JSON.stringify(last)}`);
}
async function portOpen(port) {
  return new Promise(resolve => { const s=net.connect(port,'127.0.0.1'); s.setTimeout(500); s.once('connect',()=>{s.destroy();resolve(true);}); s.once('error',()=>resolve(false)); s.once('timeout',()=>{s.destroy();resolve(true);}); });
}
function launch(exe, args, name) {
  const p=spawn(exe,args,{cwd:ROOT,stdio:['ignore','pipe','pipe']}); owned.push(p);
  const log=path.join(LOGS,name+'.log'); fs.writeFileSync(log,'');
  // Only fixed fixture logs and sanitized Firefox diagnostics are retained.
  for(const stream of [p.stdout,p.stderr]) stream.on('data',d=>fs.appendFileSync(log,scrub(d)));
  p.on('error',e=>{p.launchError=e;}); return p;
}
async function cli(args, timeout=55000) {
  const target = ['tabs','patterns','events','monitor','vp'].includes(args[0]) ? [] : ['--tab', await ev('window.__controlTab')];
  const p=spawn(PY,[path.join(ROOT,'skills/chart-assistant/scripts/chartctl.py'),'--url',URL,...target,...args], {cwd:ROOT,timeout:Math.min(timeout,remaining())});
  owned.push(p); let out='',err='';
  p.stdout.on('data',d=>out+=d); p.stderr.on('data',d=>err+=d);
  return await new Promise((resolve,reject)=>{p.on('error',reject);p.on('close',(code,signal)=>{let data;try{data=JSON.parse(out);}catch{} resolve({code,signal,data,error:scrub(err)});});});
}
function done(r) { assert.equal(r.code,0,r.error || JSON.stringify(r.data)); assert.equal(r.data.status,'done'); assert(r.data.result); return r.data.result; }
async function inspect() { return done(await cli(['inspect'])); }
async function view(symbol='005930.KS', period='3M', asof='2026-08-20', tf='D') {
  return done(await cli(['view','--symbol',symbol,'--tf',tf,'--period',period,'--as-of',asof]));
}
const config = body => request(URL,'/api/test/config','POST',body);
const trace = () => request(URL,'/api/test/state');
async function checkErrors() {
  assert.deepEqual(await ev('[window.__jsErrors,window.__jsRejections]'),[[],[]]);
}
async function navigate() {
  if(await ev('Boolean(window.__CF)').catch(()=>false)) await checkErrors();
  await ev('if(window.__CF) S.autoRef=false;void 0');
  const handles = (await cmd('/window/handles')).value;
  const opened = (await cmd('/execute/sync','POST',{
    script:'const [url]=arguments;const win=window.open(url,"_blank","width=1280,height=900");return Boolean(win);',
    args:[URL + '/chart-first.html']
  })).value;
  assert.equal(opened, true, 'popup chart window failed');
  await until(async () => {
    const now = (await cmd('/window/handles')).value;
    return now.length === handles.length + 1;
  }, 'chart popup handles');
  const after = (await cmd('/window/handles')).value;
  const next = after.find(h => !handles.includes(h));
  assert(next, 'missing popup handle');
  // Dispose earlier pages so their timers/mailboxes cannot issue background requests.
  for(const handle of handles) {
    await cmd('/window','POST',{handle});
    await cmd('/window','DELETE');
  }
  await cmd('/window','POST', {handle: next});
  assert.equal((await cmd('/window/handles')).value.length,1,'one chart window');
  await cmd('/window/rect','POST',{width:1280,height:900});
  await until(()=>ev('Boolean(window.__CF && serverMode && !S.refreshing && S.sourceKind === "live")'),'chart fixture loaded',30000);
  await until(async()=>{const r=await cli(['tabs']);return r.code===0 && r.data.tabs.some(t=>t.snapshot?.sourceKind==='live');},'mailbox registration');
}

function stable(s) { return {symbol:s.symbol,timeframe:s.timeframe,selectedAsOf:s.selectedAsOf,observation:s.observation,volumeProfile:s.volumeProfile}; }
async function screen() {
  return ev('({symbol:S.symbol,timeframe:S.tf,period:S.preset,selectedAsOf:S.selectedAsOf,observation:currentObs()?.model,basisText:document.getElementById("basisLine").textContent,volumeProfile:VolumeProfile.build(frameOf(curSym()).candles,asOfIdx()),visibleRange:__CF.visible(),entry:entryEvaluation(currentObs())})');
}
function validProfile(s) { const v=s.volumeProfile; assert(v && v.count>=10 && v.total>0 && v.bins.length===12); assert(v.bins.every(b=>Number.isFinite(b.low)&&Number.isFinite(b.high)&&Number.isFinite(b.volume)&&Number.isFinite(b.share))); }
function invertedFinal(s, expected) { assert.equal(s.symbol,'AAPL'); assert.deepEqual(s.candles,expected.candles); assert.equal(s.observation.observationAsOf,'2026-09-07'); assert(s.evidence.some(e=>e.observedRaw===expected.candles.at(-1).close), 'second ticker close absent from observation evidence'); }
async function inversion(expected, mutant=false) {
  await config({holdSymbol:'005930.KS'});
  await ev('window.__firstDone=false;window.__first=requestNewTicker("005930.KS").finally(()=>window.__firstDone=true);void 0');
  await until(async()=> (await trace()).events.some(e=>e.kind==='received'&&e.symbol==='005930.KS'),'first request received');
  assert.equal(await ev('window.__firstDone'),false);
  await ev('window.__secondDone=false;window.__second=requestNewTicker("AAPL").finally(()=>window.__secondDone=true);void 0');
  await until(()=>ev('window.__secondDone && S.symbol === "AAPL" && !S.refreshing'),'second response applied');
  const beforeRelease=await trace();
  assert(beforeRelease.events.some(e=>e.kind==='delivered'&&e.symbol==='AAPL'));
  assert(!beforeRelease.events.some(e=>e.kind==='delivered'&&e.symbol==='005930.KS'));
  await config({release:true});
  await until(()=>ev('window.__firstDone && !S.refreshing'),'late first response complete');
  const state=await ev('({symbol:S.symbol,candles:__CF.frameNow().candles,observation:currentObs().model,evidence:currentObs().model.evidence})');
  if(mutant) assert.throws(()=>invertedFinal(state,expected), 'checker must reject removed stale guard');
  else invertedFinal(state,expected);
  evidence.push({scenario:mutant?'stale guard negative control':'response inversion',events:(await trace()).events});
}
async function pointer(actions) {
  await cmd('/actions','POST',{actions:[{type:'pointer',id:'mouse',parameters:{pointerType:'mouse'},actions}]});
  await cmd('/actions','DELETE');
}
async function tableMatches(snapshot) {
  validProfile(snapshot);
  const actual=await ev('Array.from(document.querySelectorAll("#volumeProfileRows tr"),tr=>Array.from(tr.cells,c=>c.textContent.trim()))');
  const kr=/\.(KS|KQ)$/.test(snapshot.symbol);
  const price=n=>(kr?'':'$')+Number(n).toLocaleString('ko-KR',{maximumFractionDigits:kr?0:2})+(kr?'원':'');
  const expected=snapshot.volumeProfile.bins.slice().reverse().map(b=>[price(b.low)+' ~ '+price(b.high)+(b.peak?' · 거래 집중':''),(b.share*100).toFixed(1)+'%',b.volume.toLocaleString('ko-KR')]);
  assert.equal(actual.length,expected.length);
  assert.deepEqual(actual,expected);
}
async function scenarios() {
  let fixtures=await request(URL,'/api/test/fixtures');
  await config({reset:true}); await inversion(fixtures.AAPL);
  await config({reset:true,disableStaleGuard:true}); await navigate(); await config({reset:true,disableStaleGuard:true});
  await inversion(fixtures.AAPL,true);
  await config({reset:true}); await navigate();
  console.log('PASS response inversion and removed-guard negative control');
  await config({reset:true,holdSymbol:'005930.KS'});
  await ev('window.__lateDaily=false;refreshLive({reason:"manual"}).finally(()=>window.__lateDaily=true);void 0');
  await until(async()=> (await trace()).events.some(e=>e.kind==='received'&&e.symbol==='005930.KS'),'held daily request');
  await config({holdSymbol:null});
  await ev('setTF("W");refreshLive({reason:"manual"});void 0');
  await until(()=>ev('S.tf==="W"&&!S.refreshing'),'weekly response before daily');
  const weeklyBefore=await screen();
  await config({release:true});await until(()=>ev('__lateDaily'),'late daily released');
  assert.equal((await screen()).timeframe,'W');
  sameSnapshot(stable(await screen()),stable(weeklyBefore));
  evidence.push({scenario:'timeframe response inversion',timeframe:'W',entry:(await screen()).entry});

  const tabs=await cli(['tabs']); assert.equal(tabs.code,0); assert.equal(tabs.data.tabs.filter(t=>t.snapshot?.sourceKind==='live').length>=1,true);
  for(const [period,from] of [['1M','2026-08-07'],['3M','2026-06-08']]) {
    const result=await view('005930.KS',period);
    assert.equal(result.symbol,'005930.KS');assert.equal(result.timeframe,'D');assert.equal(result.period,period);
    assert.equal(result.selectedAsOf,'2026-08-20'); assert.equal(result.observation.observationAsOf,'2026-08-20');
    assert.deepEqual(result.visibleRange,{from,to:'2026-09-07'});
    const actual=await screen(); sameSnapshot(stable(result),stable(actual));assert.deepEqual(result.visibleRange,actual.visibleRange);
  }
  const prior=await inspect();
  const bad=await cli(['view','--as-of','2026-08-22']);
  assert.equal(bad.code,2);assert.equal(bad.data.status,'failed'); assert.match(bad.data.error,/date-not-in-data/);
  sameSnapshot(stable(bad.data.result),stable(prior)); sameSnapshot(stable(await screen()),stable(prior));
  // This is a real queued CLI request: no delivered command may produce a done result.
  await config({blockDelivery:true});
  const blocked=await cli(['view','--period','1M'],2500);
  assert.throws(()=>done(blocked));assert.equal((await screen()).period,'3M');
  await config({blockDelivery:false}); await until(()=>ev('S.preset === "1M"'),'released mailbox command');
  await view(); console.log('PASS CLI round trip, exact ranges, failed actual state, blocked delivery');

  const before=await inspect();validProfile(before);await tableMatches(before);
  await ev('document.getElementById("chart").scrollIntoView();void 0');
  const box=await ev('(()=>{const r=document.getElementById("chart").getBoundingClientRect();return {x:Math.round(r.left+r.width*.5),y:Math.round(r.top+r.height*.4)}})()');
  await ev('window.__hoverCount=0;chart.subscribeCrosshairMove(p=>{if(p.time)window.__hoverCount++});void 0');
  await cmd('/actions','POST',{actions:[{type:'wheel',id:'wheel',actions:[{type:'scroll',origin:'viewport',x:box.x,y:box.y,deltaX:0,deltaY:-300,duration:300}]}]});
  await pause(400); const zoom=await screen(); assert.notDeepEqual(zoom.visibleRange,before.visibleRange);sameSnapshot(stable(zoom),stable(before));
  await pointer([{type:'pointerMove',origin:'viewport',x:box.x,y:box.y},{type:'pointerDown',button:0},{type:'pointerMove',origin:'viewport',x:box.x+150,y:box.y,duration:600},{type:'pointerUp',button:0}]);
  await pause(400);const pan=await screen();assert.notDeepEqual(pan.visibleRange,zoom.visibleRange);sameSnapshot(stable(pan),stable(before));
  await pointer([{type:'pointerMove',origin:'viewport',x:box.x-80,y:box.y+25,duration:200}]);
  await until(()=>ev('__hoverCount > 0'),'real crosshair hover');sameSnapshot(stable(await screen()),stable(before));await tableMatches(await inspect());
  const future=fixtures['005930.KS'].candles.filter(c=>c.time>'2026-08-20');assert(future.length>0);
  await config({futureVolumeAfter:'2026-08-20',futureVolumeFactor:999});
  await ev('window.__reloadDone=false;refreshLive({force:true}).finally(()=>window.__reloadDone=true);void 0');
  await until(()=>ev('__reloadDone && !S.refreshing'),'future volume reload');
  const changed=await ev('__CF.frameNow().candles.filter(c=>c.time>"2026-08-20")');
  assert.deepEqual(changed.map(c=>c.volume),future.map(c=>c.volume*999));
  sameProfile((await inspect()).volumeProfile,before.volumeProfile);
  await view('AAPL','3M','latest'); await tableMatches(await inspect());
  console.log('PASS real zoom/pan/hover, complete profile, KR/US table precision, future volume isolation');
  // 9. Monthly timeframe: UI select, CLI round trip, month-end labels,
  // in-progress provisional + prior confirmed basis, VP agreement, zoom keep.
  await ev('document.getElementById("tM").click();void 0');
  await until(()=>ev('S.tf==="M" && !S.refreshing'),'monthly UI select');
  assert.equal(await ev('document.getElementById("tM").getAttribute("aria-pressed")'),'true');
  assert.equal((await screen()).period,'ALL');
  const mlabels=await ev('__CF.frameNow().candles.map(c=>c.time)');
  assert(mlabels.length>0);
  assert(mlabels.every(t=>{const d=new Date(t+"T00:00:00");return d.getMonth()===new Date(d.getFullYear(),d.getMonth()+1,0).getMonth()&&d.getDate()===new Date(d.getFullYear(),d.getMonth()+1,0).getDate();}),'all monthly labels are month-end');
  const mview=await view('005930.KS','ALL','latest','M');
  assert.equal(mview.symbol,'005930.KS');assert.equal(mview.timeframe,'M');assert.equal(mview.period,'ALL');
  assert.equal(mview.selectedAsOf,null);
  sameSnapshot(stable(await screen()),stable(mview));
  const mframe=await ev("({confirmed:__CF.frameNow().confirmed,lastConfirmed:__CF.frameNow().lastConfirmedTime,entry:entryEvaluation(currentObs()),obs:currentObs().model})");
  assert.equal(mframe.confirmed,false);
  assert.equal(mframe.lastConfirmed,mlabels[mlabels.length-2]);
  assert.equal(mframe.obs.observationAsOf,mlabels[mlabels.length-1]);
  assert.equal(mframe.entry.basis,mlabels[mlabels.length-1]);
  assert.match((await screen()).basisText,/월봉 \d+개 확보/);
  await tableMatches(await inspect());
  assert.deepEqual(mview.entry,(await screen()).entry);
  assert.equal((await screen()).visibleRange.from,mlabels[0]);
  await ev('document.getElementById("chart").scrollIntoView();void 0');
  await until(()=>ev('Date.now() >= progUntil'),'program range settled');
  const mbox=await ev('(()=>{const r=document.getElementById("chart").getBoundingClientRect();return {x:Math.round(r.left+r.width*.5),y:Math.round(r.top+r.height*.4)}})()');
  await cmd('/actions','POST',{actions:[{type:'wheel',id:'wheel',actions:[{type:'scroll',origin:'viewport',x:mbox.x,y:mbox.y,deltaX:0,deltaY:-300,duration:300}]}]});
  await pause(400);
  const zoomed=(await screen()).visibleRange;
  assert.notDeepEqual(zoomed,{from:mlabels[0],to:mlabels[mlabels.length-1]});
  await ev('window.__reloadDone=false;refreshLive({force:true}).finally(()=>window.__reloadDone=true);void 0');
  await until(()=>ev('__reloadDone && !S.refreshing'),'monthly refresh');
  assert.deepEqual((await screen()).visibleRange,zoomed);
  const badMonth=await cli(['view','--symbol','005930.KS','--tf','M','--as-of','2026-08-20']);
  assert.equal(badMonth.code,2);assert.equal(badMonth.data.status,'failed');assert.match(badMonth.data.error,/month-end-label/);
  await view('005930.KS','3M','latest');
  assert.equal((await screen()).timeframe,'D');
  console.log('PASS monthly selection, month-end labels, provisional/confirmed basis, VP agreement, zoom keep, label rejection');

  await config({reset:true}); await view('005930.KS','3M','latest');
  async function reload() {
    await ev('window.__reloadDone=false;refreshLive({force:true}).finally(()=>window.__reloadDone=true);void 0');
    await until(()=>ev('__reloadDone && !S.refreshing'),'source refreshed');
    return inspect();
  }
  async function setClock(iso) {
    await config({now:iso});
    const fixture=await request(URL,'/api/test/state');
    await ev(`__setClock(${JSON.stringify(fixture.clock)});void 0`);
  }
  let state=await reload();
  assert.equal(state.entry.judgmentMode,'live-snapshot');
  assert.equal(state.entry.label,'봉 확정 대기');
  assert.equal(state.observation.timeliness.realtimeReady,false);
  assert.equal(await ev('__CF.frameNow().barAsOf'),null);
  // No SSE and no direct EntryModel/quote injection: mutate source OHLCV, wait for polling.
  const firstClose=await ev('__CF.frameNow().candles.at(-1).close');
  await config({priceMode:'wait'});
  await setClock('2026-09-07T06:00:31+00:00'); // production interval is 30s; advance the fixture clock
  await until(()=>ev('entryEvaluation().code==="wait"&&!entryEvaluation().matched'),'automatic OHLCV wait transition',16000);
  assert.notEqual(await ev('__CF.frameNow().candles.at(-1).close'),firstClose);
  for(const mode of ['avoid','chase','candidate']){
    await config({priceMode:mode});state=await reload();
    assert.equal(state.entry.code,mode==='candidate'?'wait':mode);
    assert.equal(state.entry.judgmentMode,'live-snapshot');
    assert.deepEqual(state.entry,(await screen()).entry);
    evidence.push({scenario:'production source '+mode,entry:state.entry});
  }
  await config({restError:true});state=await reload();
  assert.equal(state.entry.code,'blocked');assert.equal(state.entry.judgmentMode,'blocked');
  assert.equal(await ev('__CF.frameNow().candles.at(-1).close'),firstClose);
  await config({restError:false});await reload();
  await ev('document.getElementById("btnAuto").click();void 0');
  assert.equal((await inspect()).entry.code,'blocked');
  await ev('document.getElementById("btnAuto").click();void 0');await until(()=>ev('!S.refreshing'),'auto resume');
  await config({keepSource:true,holdSymbol:'005930.KS'});await setClock('2026-09-07T06:02:00+00:00');
  await until(()=>ev('document.getElementById("entryPanel").dataset.state==="blocked"&&currentObs().model.timeliness.reason==="snapshot-expired"'),'one-second expiry without completed lookup');
  await config({release:true});state=await reload();
  assert.equal(state.entry.code,'blocked');assert.equal(state.observation.timeliness.reason,'snapshot-expired');
  await config({keepSource:false});await reload();
  await config({calendarError:true});state=await reload();
  assert.equal(state.entry.code,'blocked');assert.equal(state.observation.timeliness.reason,'session-unknown');
  await config({calendarError:false});await reload();
  // Closing the clock without collecting a post-buffer source must not finalize today's bar.
  await config({keepSource:true});await setClock('2026-09-07T11:31:00+00:00');state=await reload();
  assert.equal(state.entry.basis,'2026-09-04');
  assert.equal(state.entry.judgmentMode,'closed-confirmed');
  await config({restError:true});state=await reload();assert.equal(state.entry.code,'blocked');
  await config({restError:false,keepSource:false});state=await reload();
  assert.equal(state.entry.basis,'2026-09-07');assert.equal(state.entry.code,'candidate');
  assert.equal(state.entry.judgmentMode,'closed-confirmed');
  assert.match(await ev('document.getElementById("entryDataDetails").textContent'),/확정봉 기준 · 다음 거래 시점 가격 미반영/);
  evidence.push({scenario:'post-close fresh source',entry:state.entry});
  await config({sourceThrough:'2026-09-09'});await setClock('2026-09-09T12:00:00+00:00');
  await view('005930.KS','3M','latest','W');state=await reload();
  assert.equal(state.entry.basis,'2026-09-04');assert.equal(state.entry.observationBasis,'2026-09-11');
  assert.equal(state.entry.judgmentMode,'closed-confirmed');
  assert.equal(state.observation.currentBarProvisional,true);
  assert.equal(state.observation.timeliness.judgmentReady,false,'latest chart week is not the confirmed entry week');
  assert.deepEqual(state.entry,(await screen()).entry);
  assert.match(await ev('document.getElementById("entrySetup").textContent'),/2026-09-04.*2026-09-11/);
  evidence.push({scenario:'Wednesday closed weekly CLI and panel',entry:state.entry});
  await ev('document.getElementById("entryPanel").scrollIntoView();void 0');
  await screenshot('firefox-weekly-confirmed');
  await config({reset:true});await setClock('2026-09-07T06:00:00+00:00');await view('005930.KS','3M','latest');await reload();
  for(const k of 'ABCF') {
    const element=(await cmd('/element','POST',{using:'css selector',value:'#signalStrategy'})).value;
    const id=element['element-6066-11e4-a52e-4f735466cecf'];assert(id,JSON.stringify(element));
    await cmd(`/element/${id}/click`,'POST',{});
    await cmd(`/element/${id}/value`,'POST',{text:k,value:[k]});
    await cmd(`/element/${id}/value`,'POST',{text:'\uE007',value:['\uE007']});
    const actual=await ev('({selected:document.getElementById("signalStrategy").value,state:S.signalStrategy,rule:document.getElementById("activeExitRule").textContent,markers:markersPlugin.markers().filter(m=>m.shape!=="circle"),raw:__CF.frameNow().marks[S.signalStrategy]})');
    assert.equal(actual.selected,k);assert.equal(actual.state,k);
    for(const m of actual.markers){
      const raw=actual.raw.find(r=>r.time===m.time && (r.side==='entry'?'arrowUp':'arrowDown')===m.shape);
      assert(raw,'displayed marker has original signal');
      if(m.text)assert.equal(m.text,(m.time==='2026-09-07'?'잠정 ':'')+k+(raw.side==='entry'?' 진입 조건':' 이탈 조건'));
    }
    assert.match(await ev('document.getElementById("readSignalKey").textContent'),new RegExp(k));
  }
  console.log('PASS production OHLCV transitions, freshness/failure gates, closed daily and weekly CLI agreement');

  // Watchlist scenarios
  await config({reset:true});
  await setClock('2026-09-07T06:00:00+00:00');
  await view('005930.KS','3M','latest');
  await reload();

  async function wlRows() {
    return ev('(() => { const rows = document.getElementById("wlRows"); return [...rows.children].map(r => ({symbol: r.dataset.symbol, name: r.querySelector(".wl-row-name").textContent, state: r.querySelector(".wl-row-state").textContent, title: r.title, tone: r.querySelector(".wl-tone").dataset.tone})); })()');
  }
  async function wlGroups() {
    return ev('(() => { const strip = document.getElementById("wlGroupStrip"); return [...strip.children].map(b => ({name: b.textContent, pressed: b.getAttribute("aria-pressed")})); })()');
  }

  // 1. Group creation
  await ev('Watchlist.addGroup("반도체");void 0');
  await ev('Watchlist.addGroup("미국 관심");void 0');
  let groups = await wlGroups();
  assert.equal(groups.length, 3);
  assert.equal(groups[1].name, '반도체');
  assert.equal(groups[2].name, '미국 관심');
  assert.equal(groups[2].pressed, 'true');

  // 2. Symbol registration
  await ev('Watchlist.addSymbol("005930.KS", "삼성전자");void 0');
  await ev('Watchlist.addSymbol("AAPL", "Apple");void 0');
  let rows = await wlRows();
  assert.equal(rows.length, 2);
  assert.equal(rows[0].symbol, '005930.KS');
  assert.equal(rows[1].symbol, 'AAPL');

  // 3. Duplicate registration
  await ev('Watchlist.addSymbol("005930.KS", "삼성전자");void 0');
  assert.equal(await ev('document.getElementById("wlSymbolErr").hidden'), false);
  assert.match(await ev('document.getElementById("wlSymbolErr").textContent'), /이미 등록된 종목/);

  // 4. Multiple symbol entry states (perSymbol priceMode)
  await config({perSymbol: {'005930.KS': {priceMode: 'candidate'}, 'AAPL': {priceMode: 'wait'}}});
  await until(async () => {
    const rows = await wlRows();
    return rows.length === 2 && rows[0].state !== '조회 대기' && rows[1].state !== '조회 대기';
  }, 'background lookup complete', 30000);
  rows = await wlRows();
  assert.match(rows[0].state, /진입 검토|봉 확정 대기/);
  assert.match(rows[1].state, /조건 대기|관망/);
  assert(rows.every(r => ['entry','exit','neutral'].includes(r.tone)),'tone box per row');
  assert.equal(rows[0].tone,rows[0].state.startsWith('진입 검토')?'entry':'neutral');
  assert.equal(rows[1].tone,'neutral');

  // 5. Row click and detail agreement
  await ev('document.querySelector(\'.wl-row[data-symbol="AAPL"]\').click();void 0');
  await until(() => ev('S.symbol === "AAPL"'), 'row click switches chart');
  const aaplEntry = await ev('entryEvaluation(currentObs())');
  const aaplRow = (await wlRows()).find(r => r.symbol === 'AAPL');
  assert.equal(aaplEntry.label, aaplRow.state.replace(' (잠정)', ''));
  assert.deepEqual(aaplEntry, (await screen()).entry);

  // 6. Chart context isolation
  await ev('S.selectedAsOf = "2026-08-20";void 0');
  await config({perSymbol: {'005930.KS': {priceMode: 'chase'}, 'AAPL': {priceMode: 'wait'}}});
  await ev('Watchlist.refresh();void 0');
  await until(async () => {
    const rows = await wlRows();
    return /추격/.test(rows.find(r => r.symbol === '005930.KS').state);
  }, 'background lookup after source change', 30000);
  assert.equal(await ev('S.selectedAsOf'), '2026-08-20');
  rows = await wlRows();
  assert.match(rows.find(r => r.symbol === '005930.KS').state, /추격/);
  assert.equal(rows.find(r => r.symbol === '005930.KS').tone,'exit');

  // 7. Error handling
  await config({perSymbol: {'005930.KS': {restError: true}, 'AAPL': {priceMode: 'wait'}}});
  await ev('Watchlist.refresh();void 0');
  await until(async () => {
    const rows = await wlRows();
    return rows.find(r => r.symbol === '005930.KS').state === '조회 실패 · 판단 보류';
  }, 'error row', 30000);
  rows = await wlRows();
  assert.equal(rows.find(r => r.symbol === '005930.KS').state, '조회 실패 · 판단 보류');
  assert.match(rows.find(r => r.symbol === 'AAPL').state, /조건 대기|관망/);

  // 8. Responsive viewport
  // W/M list rows must use the same frame and confirmed basis as the chart.
  await config({perSymbol:{},sourceThrough:'2026-09-11',priceMode:'candidate'});
  await setClock('2026-09-12T01:00:00+00:00');
  for(const tf of ['W','M']) {
    await ev(`setTF(${JSON.stringify(tf)});void 0`);
    await until(()=>ev('!S.refreshing'),'selected frame refreshed');
    await ev('Watchlist.refresh();void 0');
    const expected=await request(URL,'/api/lookup?code=005930.KS');
    const frame=tf==='W'?expected.weekly:expected.monthly;
    const basis=frame.lastConfirmedTime;
    assert(basis,'fixture must have a confirmed '+tf+' bar');
    await until(()=>ev(`document.querySelector('.wl-row[data-symbol="005930.KS"]').dataset.basis === ${JSON.stringify(String(basis))}`),'watchlist '+tf+' basis',30000);
    const row=await ev('({basis:document.querySelector(\'.wl-row[data-symbol="005930.KS"]\').dataset.basis, state:document.querySelector(\'.wl-row[data-symbol="005930.KS"] .wl-row-state\').textContent})');
    await ev('document.querySelector(\'.wl-row[data-symbol="005930.KS"]\').click();void 0');
    await until(()=>ev('S.symbol === "005930.KS" && !S.refreshing'),'row-selected chart');
    const entry=await ev('entryEvaluation(currentObs())');
    assert.equal(String(entry.basis),row.basis);
    assert.equal(entry.label,row.state.replace(' (잠정)',''));
    const field=tf==='W'?'weekly':'monthly';
    await ev(`window.__savedPeriod=LIVE_D[S.symbol][${JSON.stringify(field)}];delete LIVE_D[S.symbol][${JSON.stringify(field)}];renderAll(false);void 0`);
    assert.equal(await ev('candles.data().length'),0,'missing period must clear old candles');
    assert.equal(await ev('document.getElementById("entryPanel").dataset.state'),'blocked','missing period must clear old entry status');
    await ev(`LIVE_D[S.symbol][${JSON.stringify(field)}]=window.__savedPeriod;renderAll(false);void 0`);
    await ev('document.querySelector(\'.wl-row[data-symbol="AAPL"]\').click();void 0');
    await until(()=>ev('S.symbol === "AAPL" && !S.refreshing'),'restore non-selected row');
    evidence.push({scenario:'watchlist timeframe agreement',tf,basis:row.basis,label:entry.label});
  }
  await ev('setTF("D");void 0');
  await until(()=>ev('!S.refreshing'),'restore daily');
  console.log('PASS watchlist weekly/monthly frame and selected-chart agreement');

  // Main pane must contain chart pixels, not merely axes/canvas elements.
  await cmd('/window/rect','POST',{width:1280,height:900});
  await ev('document.getElementById("chart").scrollIntoView();void 0');
  await until(()=>ev(`Array.from(document.querySelectorAll('#chart canvas')).some(c=>c.clientWidth>document.getElementById('chart').clientWidth*.8)`),'chart resize settled');
  await until(()=>ev(`(() => {
    let red=0,blue=0;
    for(const c of document.querySelectorAll('#chart canvas')) {
      if(c.clientWidth<200||c.clientHeight<100)continue;
      const p=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
      for(let i=0;i<p.length;i+=4){if(p[i+3]<100)continue;
        if(p[i]>160&&p[i+1]<100&&p[i+2]<100)red++;
        if(p[i]<70&&p[i+1]>50&&p[i+1]<140&&p[i+2]>150)blue++;
      }
    }return red>50&&blue>50;
  })()`),'rendered main-pane pixels');
  await screenshot('firefox-chart-p0');
  await cmd('/window/rect','POST',{width:1280,height:900});
  assert.equal(await ev('window.innerWidth'), 1280);
  await ev('document.getElementById("watchlistPanel").scrollIntoView();void 0');
  await screenshot('watchlist-1280');
  await cmd('/window/rect','POST',{width:1280,height:900});
  assert.equal(await ev('window.innerWidth'), 1280);
  await until(() => ev(`(() => {
    const fits=document.documentElement.scrollWidth<=window.innerWidth&&document.body.scrollWidth<=window.innerWidth;
    if(!fits)window.__pageOverflow=Array.from(document.querySelectorAll('body *')).filter(el=>{
      const r=el.getBoundingClientRect();return r.width&&r.right>innerWidth+1;
    }).map(el=>({tag:el.tagName,id:el.id,classes:el.className,right:el.getBoundingClientRect().right,width:el.getBoundingClientRect().width})).slice(0,30);
    return fits;
  })()`), 'watchlist page fits viewport', 10000);
  assert.equal(await ev('document.documentElement.scrollWidth <= window.innerWidth && document.body.scrollWidth <= window.innerWidth'),true,'watchlist page fits viewport');
  await screenshot('watchlist-desktop');

  console.log('PASS watchlist groups, multi-symbol states, row click, context isolation, errors, desktop layout');

  for(const width of [1280]) {
    await cmd('/window/rect','POST',{width,height:900});
    await until(()=>ev('Math.abs(document.querySelector("#chart > div").getBoundingClientRect().height-document.getElementById("chart").clientHeight)<2'),'chart follows aspect ratio');
    await ev('paintSelLine();document.getElementById("selline").scrollIntoView();void 0');
    const getGeometry=()=>ev(`Array.from(document.querySelectorAll('.readout,.chartTools button'),el=>{const r=el.getBoundingClientRect();return [r.x,r.y,r.width,r.height]})`);
    const geometry=await getGeometry();
    const state=await ev('({observation:document.getElementById("readObservation").textContent,signal:document.getElementById("readSignal").textContent,asOf:S.selectedAsOf})');
    await ev('paintCandleReadout({time:"2026-09-01",open:999999999,high:9999999999,low:1,close:99999999,volume:9999999999999},"미리보기");void 0');
    assert.deepEqual(await getGeometry(),geometry,'text length cannot move price cells or controls');
    assert.deepEqual(await ev('({observation:document.getElementById("readObservation").textContent,signal:document.getElementById("readSignal").textContent,asOf:S.selectedAsOf})'),state,'hover preserves fixed observation and signal');
    await ev('paintSelLine();zoom(1.8);void 0');await pause(200);
    const layout=await ev('({boxes:markerLayout.boxes,icons:markerLayout.icons,width:chart.timeScale().width(),ratio:document.getElementById("chart").clientWidth/document.getElementById("chart").clientHeight,signal:document.getElementById("readSignal").textContent,asOf:S.selectedAsOf})');
    assert(Math.abs(layout.ratio-1.5)<.02,'stable chart aspect ratio');
    assert.equal(layout.signal,state.signal);assert.equal(layout.asOf,state.asOf);
    for(const b of layout.boxes){
      assert(b.left>=4 && b.right<=layout.width-4);
      assert(!layout.boxes.some(o=>o!==b && o.lane===b.lane && b.left<o.right+8 && b.right>o.left-8),'text boxes do not overlap');
    }
    assert.equal(await ev('document.documentElement.scrollWidth<=window.innerWidth'),true,'desktop page fits');
    await screenshot('chart-readout-'+width);
  }
  evidence.push({scenario:'fixed readout and proportional chart',widths:[1280],aspectRatio:1.5});
  console.log('PASS fixed readout geometry, preview isolation, zoom collision spacing, desktop viewport');

  // Use WebDriver window rect as the source of truth, then verify DOM overflow.
  await cmd('/window/rect','POST',{width:1280,height:900});
  let rect = (await cmd('/window/rect')).value;
  assert.equal(rect.width, 1280);
  assert.equal(await ev('document.documentElement.scrollWidth <= window.innerWidth && document.body.scrollWidth <= window.innerWidth'),true,'unmodified page fits viewport');
  assert.equal(await ev('window.innerWidth'), 1280, 'actual desktop viewport');
  await checkErrors();
  await ev('document.getElementById("entryPanel").scrollIntoView();void 0');
  await screenshot('firefox-final');
  console.log('PASS initial-script errors, actual desktop viewport, decoded PNG');
}
async function screenshot(name) {
  const value=(await cmd('/screenshot')).value;
  assert.equal(typeof value,'string');const png=Buffer.from(value,'base64');
  assert(png.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])));
  fs.writeFileSync(path.join(SHOTS,name+'.png'),png);
  const chunks=[];let width,height,bpp,ended=false;
  for(let p=8;p<png.length;) {
    const n=png.readUInt32BE(p),type=png.toString('ascii',p+4,p+8);assert(p+12+n<=png.length);
    const data=png.subarray(p+8,p+8+n);
    if(type==='IHDR'){width=data.readUInt32BE(0);height=data.readUInt32BE(4);assert.equal(data[8],8);assert([2,6].includes(data[9]));bpp=data[9]===6?4:3;assert.equal(data[12],0);}
    if(type==='IDAT')chunks.push(data);
    if(type==='IEND'){ended=true;assert.equal(p+n+12,png.length);}
    p+=n+12;
  }
  assert(ended&&width>0&&height>0);const raw=zlib.inflateSync(Buffer.concat(chunks));const stride=width*bpp;
  assert.equal(raw.length,(stride+1)*height);let previous=Buffer.alloc(stride);
  for(let y=0;y<height;y++){const filter=raw[y*(stride+1)];assert(filter<=4);const row=Buffer.from(raw.subarray(y*(stride+1)+1,(y+1)*(stride+1)));
    for(let x=0;x<stride;x++){const a=x>=bpp?row[x-bpp]:0,b=previous[x],c=x>=bpp?previous[x-bpp]:0;let predictor=0;
      if(filter===1)predictor=a;if(filter===2)predictor=b;if(filter===3)predictor=Math.floor((a+b)/2);
      if(filter===4){const p=a+b-c,pa=Math.abs(p-a),pb=Math.abs(p-b),pc=Math.abs(p-c);predictor=pa<=pb&&pa<=pc?a:pb<=pc?b:c;}
      row[x]=(row[x]+predictor)&255;
    }previous=row;
  }
  evidence.push({scenario:'PNG decode',width,height,decodedBytes:stride*height});
}
async function stopChild(p) {
  if(!p || p.exitCode!==null || p.signalCode!==null)return;
  try {process.kill(p.pid,'SIGTERM');} catch(e) {
    if(!['EPERM','EACCES'].includes(e.code))throw e;
    // Snap confinement permits signaling only from the same verified driver snap.
    assert.equal(p,driver);assert(fs.readFileSync(`/proc/${p.pid}/cmdline`,'utf8').includes('geckodriver'));
    const r=spawnSync('snap',['run','--shell','firefox.geckodriver','-c',`kill -TERM ${p.pid}`],{timeout:5000});assert.equal(r.status,0,'owned Snap driver cleanup');
  }
  const end=Date.now()+7000;while(p.exitCode===null&&p.signalCode===null&&Date.now()<end)await pause(100);
  if(p.exitCode===null&&p.signalCode===null){p.kill('SIGKILL');await pause(500);}
  assert(p.exitCode!==null||p.signalCode!==null,'owned child still running');
}
async function patternScenario() {
  await config({reset:true,patterns:true,priceMode:'chase',now:'2026-09-07T06:00:00+00:00'});
  await navigate();
  await ev('S.symbol="005930.KS";S.tf="D";S.selectedAsOf=null;S.autoRef=true;void __CF.refreshLive({reason:"manual"})');
  await until(()=>ev('!S.refreshing && Boolean(__CF.frameNow()?.patternAnalysis)'), 'pattern fixture loaded');
  let pending=await ev('PatternPanel.current()');
  assert(pending.levels.some(x=>x.status==='breakout-pending'));
  assert(!pending.events.some(x=>x.confirmedBarTime==='2026-09-07'&&x.eventType==='confirmed'));
  await config({now:'2026-09-07T12:00:00+00:00'});
  await ev('__setClock("2026-09-07T12:00:00+00:00");void __CF.refreshLive({reason:"manual"})');
  await until(()=>ev('!S.refreshing && PatternPanel.current().levels.some(x=>x.status==="confirmed")'), 'confirmed P2 crossing');
  let state=await ev('PatternPanel.current()');
  const event=state.events.find(x=>x.eventType==='confirmed'&&x.confirmedBarTime==='2026-09-07');assert(event);
  await ev('void __CF.refreshLive({reason:"manual"})');
  await until(()=>ev('!S.refreshing'), 'repeat P2 source read');
  state=await ev('PatternPanel.current()');
  assert.equal(state.events.filter(x=>x.eventId===event.eventId).length,1,'duplicate event after source re-read');
  const captured=done(await cli(['inspect']));assert.deepEqual(captured.patterns,state);
  const sourceCalls=(await trace()).events.filter(e=>e.kind==='received').length;
  const shown=await cli(['events','show','--id',event.eventId]);assert.equal(shown.code,0,shown.error);
  assert.equal(shown.data.event.eventId,event.eventId);
  assert.equal((await trace()).events.filter(e=>e.kind==='received').length,sourceCalls,'event CLI fetched source');
  await ev(`void PatternPanel.openEvent(${JSON.stringify(event)})`);
  await until(()=>ev('document.getElementById("patternDialog").open && Boolean(PatternPanel.snapshot())'), 'frozen basis dialog');
  samePatternSnapshot(await ev('PatternPanel.snapshot()'),shown.data);
  assert.equal(await ev('PatternPanel.snapshot().candles.at(-1).time'),'2026-09-07');
  await until(()=>ev(`Array.from(document.querySelectorAll('#patternSnapshotChart canvas')).some(canvas=>{
    if(!canvas.width||!canvas.height)return false;
    const data=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;let colored=0;
    for(let i=0;i<data.length;i+=4)if((data[i]>150&&data[i+1]<100)||(data[i+1]>100&&data[i]<80))colored++;
    return colored>20;
  })`), 'frozen snapshot candle pixels');
  await screenshot('pattern-confirmed-basis');
  await ev('document.getElementById("patternClose").click();__CF.setRange("2026-08-03","2026-09-07");void 0');
  assert.deepEqual(await ev('PatternPanel.current()'),state,'zoom changed pattern basis');
  await ev('__CF.setTF("W");void 0');
  assert.equal(await ev('PatternPanel.current().status'),'unsupported');
  await ev('__CF.setTF("D");S.lastErr={kind:"provider"};PatternPanel.render();void 0');
  assert.equal(await ev('PatternPanel.current().status'),'paused');
  await ev('S.lastErr=null;__CF.select("2026-09-04");void 0');
  assert(!(await ev('PatternPanel.current()')).events.some(e=>e.confirmedBarTime==='2026-09-07'),'historical view leaked event');
  await ev('__CF.select(null);void 0');
  for(const width of [1280]){
    await cmd('/window/rect','POST',{width,height:1000});
    await ev('PatternPanel.render();void 0');
    assert.equal(await ev('document.documentElement.scrollWidth<=window.innerWidth'),true,'P2 page overflow');
    await ev('document.getElementById("patternPanel").scrollIntoView({block:"start"});void 0');
    await pause(200);
    await screenshot('pattern-panel-'+width);
  }
  await checkErrors();
  evidence.push({scenario:'P2 provisional/confirmed UI, CLI frozen snapshot, zoom and historical guards',eventId:event.eventId});
}

async function flagScenario(){
  await config({reset:true,flags:true,now:'2026-09-07T06:00:00+00:00'});
  await navigate();await view('005930.KS','3M','latest','D');
  await ev('S.autoRef=true;void __CF.refreshLive({reason:"manual"})');
  await until(()=>ev('!S.refreshing && Boolean(curSym()?.flagAnalysis)'), 'flag fixture loaded');
  assert((await ev('FlagPanel.current()')).patterns.some(p=>p.status==='breakout-pending'));
  await ev('document.getElementById("btnAuto").click();void 0');
  assert.equal(await ev('FlagPanel.current().status'),'paused');
  assert((await ev('document.getElementById("flagState").textContent')).includes('자료 보류'));
  await ev('document.getElementById("btnAuto").click();void 0');
  await until(()=>ev('!S.refreshing'),'Flag auto resume');
  await config({holdSymbol:'005930.KS'});
  await ev('__setClock(new Date(Date.parse(curSym().flagAnalysis.sourceFetchedAt)+91000).toISOString());renderSummary();void 0');
  assert.equal(await ev('FlagPanel.current().status'),'paused','expired intraday Flag remained live');
  assert((await ev('document.getElementById("flagState").textContent')).includes('자료 보류'));
  const actualClock=(await trace()).clock;
  await ev(`__setClock(${JSON.stringify(actualClock)});renderSummary();void 0`);
  await config({release:true});await until(()=>ev('!S.refreshing'),'release expired source request');
  await config({now:'2026-09-07T12:00:00+00:00'});
  await ev('__setClock("2026-09-07T12:00:00+00:00");void __CF.refreshLive({reason:"manual"})');
  await until(()=>ev('!S.refreshing && FlagPanel.current().patterns.some(p=>p.status==="confirmed")'),'Flag confirmed');
  const model=await ev('FlagPanel.current()');assert.equal(model.patterns[0].type,'bull-flag');
  sameComputedModel(done(await cli(['inspect'])).flags,model);
  await until(()=>ev('document.querySelector("#chart .patternUnderlay polygon[data-pattern]")?.getAttribute("fill")==="#dbeafe"'),'opaque flag area');
  assert.equal(await ev('getComputedStyle(document.querySelector("#chart .patternUnderlay")).pointerEvents'),'none');
  const before=await ev('FlagPanel.overlay().element.querySelector("polygon[data-pattern]").getAttribute("points")');
  await ev('__CF.setRange("2026-08-17","2026-09-07");void 0');
  await until(()=>ev(`FlagPanel.overlay().element.querySelector('polygon[data-pattern]')?.getAttribute('points')!==${JSON.stringify(before)}`),'flag zoom coordinates');
  assert.deepEqual(await ev('FlagPanel.current()'),model,'zoom changed flag evidence');
  await ev('document.getElementById("chart").scrollIntoView({block:"start"});void 0');await pause(300);
  await screenshot('flag-channel-overlay');
  await ev('document.getElementById("flagOverlayToggle").click();void 0');
  await until(()=>ev('!document.querySelector("#chart .patternUnderlay polygon[data-pattern]")'),'overlay off');
  assert.deepEqual(await ev('FlagPanel.current()'),model,'hide changed model');
  await ev('document.getElementById("flagOverlayToggle").click();void 0');
  const event=model.events.find(e=>e.eventType==='confirmed');assert(event);
  const shown=await cli(['events','show','--id',event.eventId]);assert.equal(shown.code,0,shown.error);
  await ev(`void PatternPanel.openEvent(${JSON.stringify(event)})`);
  await until(()=>ev('document.querySelector("#patternSnapshotChart .patternUnderlay polygon[data-pattern]")'),'frozen flag polygon');
  samePatternSnapshot(await ev('PatternPanel.snapshot()'),shown.data);
  await pause(300);await screenshot('flag-snapshot-overlay');
  await ev('document.getElementById("patternClose").click();void 0');
  // Renderer-only triangle contract. Triangle detection remains the planned later engine.
  await ev(`window.__triangleModel={patternId:'fixture-triangle',direction:'up',status:'forming',geometry:{kind:'triangle',points:[{time:'2026-08-17',price:114},{time:'2026-08-17',price:110},{time:'2026-09-07',price:112}]}};FlagPanel.overlay().set(__triangleModel);void 0`);
  await until(()=>ev('document.querySelector("#chart polygon[data-pattern=fixture-triangle]")?.getAttribute("points").split(" ").length===3'),'filled triangle renderer');
  await pause(200);await screenshot('triangle-overlay-renderer');
  await ev('FlagPanel.update();__CF.setTF("W");void 0');
  await until(()=>ev('!document.querySelector("#chart .patternUnderlay polygon[data-pattern]")'),'clear on timeframe');
  await ev('__CF.setTF("D");__CF.select("2026-08-03");void 0');
  assert.equal((await ev('FlagPanel.current()')).patterns.length,0,'past selection leaked future flag');
  await config({now:'2026-09-08T01:00:00+00:00'});
  await ev('__setClock("2026-09-08T01:00:00+00:00");void 0');
  await view('AAPL','3M','latest','D');await ev('void __CF.refreshLive({reason:"manual"})');
  await until(()=>ev('!S.refreshing && FlagPanel.current().patterns.some(p=>p.type==="bear-flag")'),'bear flag');
  await until(()=>ev('document.querySelector("#chart polygon[data-pattern]")?.getAttribute("fill")=="#fee2e2"'),'bear area rendered');
  for(const width of [1280]){
    await cmd('/window/rect','POST',{width,height:1000});
    await ev('FlagPanel.render();document.getElementById("flagPanel").scrollIntoView({block:"start"});void 0');await pause(200);
    assert.equal(await ev('document.documentElement.scrollWidth<=innerWidth'),true,'Flag overflow');
    await screenshot('flag-panel-'+width);
  }
  await checkErrors();evidence.push({scenario:'Bull/Bear causal Flag with opaque channel, triangle renderer, zoom/TF/as-of guards and frozen snapshot'});
}

async function monitorScenario(){
  await config({reset:true,monitor:true,patterns:true,flags:true,now:'2026-09-07T06:00:00+00:00'});
  await cmd('/window/rect','POST',{width:1280,height:1000});await navigate();
  await until(()=>ev('MonitorPanel.state()?.workerState==="paused"'),'monitor initially paused');
  assert.equal(await ev('Array.from(document.querySelector("#flagPanel h2").childNodes).filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent).join("").trim()'),'플래그');
  await ev(`Watchlist.reset();Watchlist.addSymbol('005930.KS','삼성전자');Watchlist.addGroup('다른 그룹');Watchlist.addSymbol('005930.KS','삼성전자');Watchlist.addSymbol('AAPL','애플');Watchlist.addSymbol('BTC-USD','비트코인');window.__originalWatch=localStorage.getItem('cf_watchlists_v1');document.getElementById('monitorImport').click();void 0`);
  await until(()=>ev('!document.getElementById("monitorPreview").hidden'),'import preview');
  assert.match(await ev('document.getElementById("monitorPreviewText").textContent'),/저장 후 2종목.*중복 1.*BTC-USD/);
  assert.equal((await request(URL,'/api/monitor/status')).items.length,0,'preview wrote settings');
  await ev('document.getElementById("monitorImportSave").click();void 0');
  await until(()=>ev('MonitorPanel.state()?.items.length===2'),'persist imported list');
  assert.equal(await ev('localStorage.getItem("cf_watchlists_v1")===__originalWatch'),true,'import destroyed local list');
  assert.equal(await ev('document.getElementById("monitorImport").disabled'),true,'one time import');
  await ev('document.querySelector("#monitorRows select").value="focus";document.querySelector("#monitorRows select").dispatchEvent(new Event("change"));void 0');
  await until(()=>ev('MonitorPanel.state()?.items[0].profile==="focus"'),'focus profile');
  const paused=await cli(['monitor','status']);assert.equal(paused.code,0,paused.error);assert.equal(paused.data.enabled,false);
  await ev('document.getElementById("monitorToggle").click();void 0');
  await until(async()=>{const s=await request(URL,'/api/monitor/status');return s.enabled&&s.items.every(r=>r.lastSuccessAt);},'server collection');
  await ev('void MonitorPanel.poll();if(S.autoRef)document.getElementById("btnAuto").click();void 0');
  assert.equal((await request(URL,'/api/monitor/status')).enabled,true,'screen auto disabled server monitoring');
  for(const width of [1280]){
    await cmd('/window/rect','POST',{width,height:1000});await ev('document.getElementById("monitorPanel").scrollIntoView({block:"start"});void 0');await pause(200);
    assert.equal(await ev('document.documentElement.scrollWidth<=innerWidth'),true,'monitor overflow');await screenshot('monitor-panel-'+width);
  }
  // Navigate away: server still receives a close job and stores an event.
  await cmd('/url','POST',{url:URL+'/api/health'});
  await config({now:'2026-09-07T12:00:00+00:00'});
  await until(async()=>{const s=await request(URL,'/api/monitor/status');return s.items.find(r=>r.symbol==='005930.KS')?.status==='confirmed-history';},'headless close confirmation');
  const events=await request(URL,'/api/monitor/events');assert(events.events.some(e=>e.symbol==='005930.KS'&&e.eventType==='confirmed'));
  const one=events.events.find(e=>e.symbol==='005930.KS'&&e.type==='bull-flag'&&e.eventType==='confirmed');assert(one);
  const shown=await cli(['events','show','--id',one.eventId]);assert.equal(shown.code,0,shown.error);assert.equal(shown.data.event.geometry.kind,'channel');
  const p=await cli(['monitor','pause']);assert.equal(p.code,0,p.error);assert.equal(p.data.enabled,false);
  await cmd('/url','POST',{url:'about:blank'});await navigate();await ev('void MonitorPanel.poll();void 0');
  await until(()=>ev('MonitorPanel.state()?.enabled===false'),'paused view restoration');
  await until(()=>ev('document.querySelectorAll("#monitorEvents button").length>0'),'stored events shown');
  await checkErrors();evidence.push({scenario:'Grouped Flag category; server monitor preview/merge, separate controls, headless close event, cached CLI and desktop layout'});
}

async function triangleScenario(){
  await config({reset:true,triangles:true,triangleBreakout:false,now:'2026-09-07T06:00:00+00:00'});await navigate();await ev('if(!S.autoRef)document.getElementById("btnAuto").click();void 0');
  // Earlier watchlist scenarios persist AAPL, whose session is closed at this
  // fixture time. Select the KR session explicitly for provisional assertions.
  await view('005930.KS','3M','latest','D');
  await until(()=>ev('TrianglePanel.current().patterns.some(p=>p.status==="forming")'),'neutral forming triangle');
  await until(()=>ev('document.querySelector("#chart polygon[data-pattern]")?.getAttribute("fill")=="#e2e8f0"'),'neutral triangle fill');
  await config({reset:true,triangles:true,now:'2026-09-07T06:00:00+00:00'});await ev('void __CF.refreshLive({reason:"manual"})');
  await until(()=>ev('TrianglePanel.current().patterns.some(p=>p.status==="breakout-pending")'),'provisional triangle');
  assert.equal(await ev('TrianglePanel.current().events.length'),0,'provisional event');
  await ev('document.getElementById("btnAuto").click();renderSummary();void 0');
  assert.equal((await ev('TrianglePanel.current()')).status,'paused');
  await ev('document.getElementById("btnAuto").click();void 0');await until(()=>ev('!S.refreshing'),'resume triangle');
  await config({now:'2026-09-07T12:00:00+00:00'});await ev('__setClock("2026-09-07T12:00:00+00:00");void __CF.refreshLive({reason:"manual"})');
  await until(()=>ev('!S.refreshing&&TrianglePanel.current().patterns.some(p=>p.status==="confirmed")'),'triangle confirmed');
  let model=await ev('TrianglePanel.current()');assert.equal(model.patterns[0].type,'ascending-triangle');assert.equal(model.patterns[0].direction,'up');
  sameComputedModel(done(await cli(['inspect'])).triangles,model);
  const cached=await cli(['patterns','--symbol','005930.KS','--kind','triangle']);assert.equal(cached.code,0,cached.error);assert.equal(cached.data.ruleVersion,'triangle-d-v2');
  await ev('document.getElementById("triangleFit").click();document.getElementById("chart").scrollIntoView({block:"start"});void 0');
  await until(()=>ev('document.querySelector("#chart polygon[data-pattern]")?.getAttribute("points").split(" ").length===3'),'three projected vertices');
  assert.equal(await ev('document.querySelectorAll("#chart .patternUnderlay").length'),1,'multiple chart overlays');
  const before=await ev('document.querySelector("#chart polygon[data-pattern]").getAttribute("points")');
  await ev('__CF.setRange("2026-08-10","2026-09-07");void 0');
  await until(()=>ev(`document.querySelector('#chart polygon[data-pattern]')?.getAttribute('points')!==${JSON.stringify(before)}`),'triangle zoom coordinates');
  assert.deepEqual(await ev('TrianglePanel.current()'),model,'zoom changed triangle evidence');
  await ev('document.getElementById("triangleFit").click();void 0');await pause(250);
  const diag=await ev('({model:TrianglePanel.selected(),range:chart.timeScale().getVisibleLogicalRange(),bars:frameOf(curSym()).candles.length,points:document.querySelector("#chart polygon[data-pattern]").getAttribute("points")})');
  fs.writeFileSync(path.join(LOGS,'triangle-coordinates.json'),JSON.stringify(diag,null,2));
  const vertices=diag.points.split(' ').map(p=>p.split(',').map(Number));
  const plotWidth=await ev('document.getElementById("chart").clientWidth-chart.priceScale("right").width()');
  assert(vertices[1][0]-vertices[0][0]>plotWidth*.7,'future apex collapsed at chart edge');
  await screenshot('triangle-auto-overlay');
  // The apex can move inside the available history after several new bars.
  // v5 then returns 0 for a fractional index; interpolate integer neighbors.
  const interior=await ev(`(()=>{
    const p=structuredClone(TrianglePanel.selected()),rows=frameOf(curSym()).candles;
    const base=rows.findIndex(r=>r.time===p.geometry.points[1].anchorTime),idx=rows.length-1.5;
    p.patternId='interior-apex-regression';p.geometry.points[1].logicalOffset=idx-base;
    FlagPanel.overlay().set(p);
    const x=chart.timeScale().logicalToCoordinate(Math.floor(idx)),next=chart.timeScale().logicalToCoordinate(Math.ceil(idx));
    return {raw:chart.timeScale().logicalToCoordinate(idx),expected:x+.5*(next-x)};
  })()`);
  assert.equal(interior.raw,0,'regression must reproduce integer-only library coordinates');
  await until(()=>ev('Boolean(document.querySelector("#chart polygon[data-pattern=interior-apex-regression]"))'),'interior fractional apex');
  const interiorX=await ev('Number(document.querySelector("#chart polygon[data-pattern=interior-apex-regression]").getAttribute("points").split(" ")[1].split(",")[0])');
  assert(Math.abs(interiorX-interior.expected)<.001,'interior apex collapsed to screen left');
  await screenshot('triangle-interior-apex');await ev('FlagPanel.update();void 0');
  await ev('document.getElementById("patternAreaFamily").value="flag";document.getElementById("patternAreaFamily").dispatchEvent(new Event("change"));void 0');
  await until(()=>ev('!document.querySelector("#chart polygon[data-pattern]")'),'category flag clears triangle');
  await ev('FlagPanel.selectArea("triangle");void 0');
  const event=model.events.find(e=>e.eventType==='confirmed');assert(event);
  const shown=await cli(['events','show','--id',event.eventId]);assert.equal(shown.code,0,shown.error);
  await ev(`void PatternPanel.openEvent(${JSON.stringify(event)})`);await until(()=>ev('document.querySelector("#patternSnapshotChart polygon[data-pattern]")'),'frozen triangle');
  samePatternSnapshot(await ev('PatternPanel.snapshot()'),shown.data);await pause(200);await screenshot('triangle-snapshot');await ev('document.getElementById("patternClose").click();__CF.select("2026-07-20");void 0');
  assert.equal((await ev('TrianglePanel.current()')).patterns.length,0,'historical triangle leak');
  await ev('__CF.setTF("W");void 0');assert.equal((await ev('TrianglePanel.current()')).status,'unsupported');
  await ev('__CF.setTF("D");__CF.select(null);void 0');
  for(const kind of ['descending','symmetrical']){
    await config({reset:true,triangles:true,triangleKind:kind,triangleDirection:'down',now:'2026-09-07T12:00:00+00:00'});
    await ev('void __CF.refreshLive({reason:"manual"})');
    await until(()=>ev(`!S.refreshing&&TrianglePanel.current().patterns.some(p=>p.type==='${kind}-triangle'&&p.direction==='down')`),'actual '+kind);
  }
  for(const width of [1280]){
    await cmd('/window/rect','POST',{width,height:1000});await ev('document.getElementById("trianglePanel").scrollIntoView({block:"start"});void 0');await pause(200);
    assert.equal(await ev('document.documentElement.scrollWidth<=innerWidth'),true,'triangle overflow');await screenshot('triangle-panel-'+width);
  }
  await checkErrors();evidence.push({scenario:'Actual ascending/descending/symmetrical triangle, both directions, fractional apex, one overlay, historical/TF/freshness guards and immutable UI/CLI basis'});
}

async function indicatorScenario(){
  await config({reset:true,triangles:true,now:'2026-09-07T12:00:00+00:00'});await navigate();await view('005930.KS','3M','latest','D');
  await ev('Watchlist.reset();if(S.autoRef)document.getElementById("btnAuto").click();void 0');
  await cmd('/window/rect','POST',{width:1280,height:1100});
  assert.equal(await ev('document.querySelectorAll("#chartLegend [data-status]").length'),7);
  assert(await ev('document.getElementById("chartLegend").getBoundingClientRect().bottom<document.getElementById("chart").getBoundingClientRect().top'),'legend above chart');
  assert.match(await ev('document.getElementById("chartLegend").textContent'),/상승 흐름.*최근 10봉 저점 아래.*고점 접근/);
  let baseline=await ev('IndicatorPanel.current()');assert.equal(baseline.kind,'rsi');
  assert.equal(baseline.value,await ev('frameOf(curSym()).state[asOfIdx()].rsi14'));assert.equal(baseline.status,'ready');
  sameComputedModel(done(await cli(['inspect'])).indicator,baseline);
  const count=(await trace()).events.filter(e=>e.kind==='received').length;
  for(const kind of ['atr','volume','rsi']){
    await ev(`document.getElementById('indicatorChoice').value='${kind}';document.getElementById('indicatorChoice').dispatchEvent(new Event('change'));void 0`);
    const data=await ev('IndicatorPanel.current()');assert.equal(data.kind,kind);
    assert.equal(data.value,await ev(kind==='volume'?'frameOf(curSym()).candles[asOfIdx()].volume':`frameOf(curSym()).state[asOfIdx()].${kind}14`));
    await until(()=>ev('Math.abs(IndicatorPanel.chart().timeScale().getVisibleLogicalRange().from-chart.timeScale().getVisibleLogicalRange().from)<.001'),'range alignment');
  }
  assert.equal((await trace()).events.filter(e=>e.kind==='received').length,count,'indicator selection fetched candles');
  await pause(200); // Let the final series replacement complete its layout frame.
  const before=await ev('IndicatorPanel.current()');await ev('__CF.setRange("2026-08-10","2026-09-07");void 0');
  await until(()=>ev('Math.abs(IndicatorPanel.chart().timeScale().getVisibleLogicalRange().from-chart.timeScale().getVisibleLogicalRange().from)<.001'),'main to indicator zoom');
  assert.deepEqual(await ev('IndicatorPanel.current()'),before,'zoom altered indicator basis');
  await ev('chart.timeScale().setVisibleLogicalRange({from:34,to:59});void 0');
  await until(()=>ev('Math.abs(IndicatorPanel.chart().timeScale().getVisibleLogicalRange().from-34)<.001'),'indicator follows main pan');
  const historic=await ev('frameOf(curSym()).candles[45].time');await ev(`__CF.select(${JSON.stringify(historic)});void 0`);
  assert.equal((await ev('IndicatorPanel.current()')).basisTime,historic);assert.equal((await ev('IndicatorPanel.current()')).value,await ev('frameOf(curSym()).state[45].rsi14'));
  await ev('__CF.select(null);void 0');
  const window=await ev('TrianglePanel.current().window');assert.deepEqual(window,{months:3,start:'2026-06-07',end:'2026-09-07'});
  // Old structure must not reappear on a six-month chart, even from an older server.
  await ev('window.__triSaved=structuredClone(curSym().triangleAnalysis);curSym().triangleAnalysis.timeline.at(-1).patterns[0].structureStartTime="2026-06-06";TrianglePanel.render();void 0');
  assert.equal(await ev('TrianglePanel.current().patterns.length'),0);await until(()=>ev('!document.querySelector("#chart polygon[data-pattern]")'),'old geometry cleared');
  await ev('curSym().triangleAnalysis=__triSaved;TrianglePanel.render();document.getElementById("triangleFit").click();void 0');
  for(const width of [1280]){
    await cmd('/window/rect','POST',{width,height:1100});await ev('document.getElementById("chartLegend").scrollIntoView({block:"start"});void 0');await pause(300);
    await until(()=>ev('Math.abs(IndicatorPanel.chart().timeScale().getVisibleLogicalRange().from-chart.timeScale().getVisibleLogicalRange().from)<.001'),'responsive indicator period');
    fs.writeFileSync(path.join(LOGS,'indicator-range-'+width+'.json'),JSON.stringify(await ev('({main:chart.timeScale().getVisibleLogicalRange(),indicator:IndicatorPanel.chart().timeScale().getVisibleLogicalRange(),mainX:chart.timeScale().logicalToCoordinate(66),indicatorX:IndicatorPanel.chart().timeScale().logicalToCoordinate(66)})'),null,2));
    assert(await ev('document.documentElement.scrollWidth<=innerWidth'),'indicator/legend overflow');
    const ratio=await ev('document.getElementById("chart").clientWidth/document.getElementById("chart").clientHeight');assert(Math.abs(ratio-1.5)<.03);
    await screenshot('indicator-legend-'+width);
    await ev('document.getElementById("indicatorPanel").scrollIntoView({block:"start"});void 0');await screenshot('indicator-panel-'+width);
  }
  await ev('document.getElementById("indicatorChoice").value="none";document.getElementById("indicatorChoice").dispatchEvent(new Event("change"));void 0');
  assert.equal(await ev('IndicatorPanel.current().status'),'hidden');assert(await ev('document.getElementById("indicatorBody").hidden'));
  await ev('document.getElementById("indicatorChoice").value="rsi";document.getElementById("indicatorChoice").dispatchEvent(new Event("change"));__CF.setTF("W");void 0');
  assert.equal((await ev('IndicatorPanel.current()')).basisTime,await ev('frameOf(curSym()).candles.at(-1).time'));
  await ev('__CF.setTF("M");void 0');assert.equal((await ev('IndicatorPanel.current()')).status,'insufficient-data');assert.equal((await ev('IndicatorPanel.current()')).value,null);
  await checkErrors();evidence.push({scenario:'Three-month pattern window and circle legend; RSI/ATR/volume, cached values, fixed basis, shared viewport, TF guards and desktop layout'});
}

async function technicalScenario(){
  await config({reset:true,triangles:true,now:'2026-09-07T12:00:00+00:00'});await navigate();await view('005930.KS','3M','latest','D');
  await ev('S.autoRef=false;void 0');
  await until(()=>ev('!S.refreshing'),'initial indicator requests settled');
  const original=await ev('JSON.stringify([frameOf(curSym()).candles,frameOf(curSym()).marks,currentObs().model,TrianglePanel.current()])');
  const count=(await trace()).events.filter(e=>e.kind==='received').length;
  const choosePrice=kind=>ev(`document.getElementById('priceIndicatorChoice').value='${kind}';document.getElementById('priceIndicatorChoice').dispatchEvent(new Event('change'));void 0`);
  const chooseAux=kind=>ev(`document.getElementById('indicatorChoice').value='${kind}';document.getElementById('indicatorChoice').dispatchEvent(new Event('change'));void 0`);
  for(const kind of ['ema','bollinger','sma','none','ema','bollinger']){
    await choosePrice(kind);const s=await ev('PriceIndicators.current()');assert.equal(s.kind,kind);assert.equal(s.status,kind==='none'?'hidden':kind==='bollinger'?'ready':'partial-data');
    sameComputedModel(done(await cli(['inspect'])).priceIndicators,s);
    if(kind!=='none')assert.equal(await ev('PriceIndicators.series().filter(s=>s.options().visible).length'),kind==='bollinger'?3:4);
  }
  await chooseAux('macd');const macd=await ev('IndicatorPanel.current()');assert.equal(macd.status,'ready');
  sameComputedModel(done(await cli(['inspect'])).indicator,macd);
  assert.equal(await ev('IndicatorPanel.series().signal.options().visible'),true);assert.equal(await ev('IndicatorPanel.series().histogram.options().visible'),true);
  await until(()=>ev('Math.abs(IndicatorPanel.series().line.priceToCoordinate(IndicatorPanel.current().value)-IndicatorPanel.series().line.priceToCoordinate(0))>20'),'MACD must release RSI fixed 0–100 scale');
  assert.equal(await ev('document.getElementById("indicatorSignal").textContent'),macd.signalValue.toLocaleString('ko-KR',{maximumFractionDigits:4}));
  assert.equal((await trace()).events.filter(e=>e.kind==='received').length,count,'indicator selection requested candles');
  assert.equal(await ev('JSON.stringify([frameOf(curSym()).candles,frameOf(curSym()).marks,currentObs().model,TrianglePanel.current()])'),original,'display changed original strategy or pattern judgment');
  await pause(200);
  const basis=await ev('[PriceIndicators.current(),IndicatorPanel.current()]');
  await ev('chart.timeScale().setVisibleLogicalRange({from:40,to:66});void 0');
  await until(()=>ev('Math.abs(IndicatorPanel.chart().timeScale().getVisibleLogicalRange().from-40)<.001'),'MACD range follows main');
  assert.deepEqual(await ev('[PriceIndicators.current(),IndicatorPanel.current()]'),basis,'zoom changed indicator basis');
  await ev('__CF.select(frameOf(curSym()).candles[40].time);void 0');
  assert.equal(await ev('PriceIndicators.current().basisTime'),await ev('IndicatorPanel.current().basisTime'));
  assert(await ev('PriceIndicators.series().every(s=>s.data().slice(41).every(p=>p.value===undefined))'),'future price overlay values');
  assert(await ev('Object.values(IndicatorPanel.series()).every(s=>s.data().slice(41).every(p=>p.value===undefined))'),'future MACD values');
  await choosePrice('ema');assert.equal(await ev('PriceIndicators.current().status'),'partial-data');
  await ev('__CF.select(null);window.__savedConfirmed=frameOf(curSym()).confirmed;frameOf(curSym()).confirmed=false;__CF.render(false);void 0');
  assert.equal(await ev('PriceIndicators.current().status'),'paused');assert.equal(await ev('IndicatorPanel.current().status'),'paused');
  await ev('frameOf(curSym()).confirmed=__savedConfirmed;S.lastErr={kind:"fixture"};__CF.render(false);void 0');
  assert.equal(await ev('PriceIndicators.current().status'),'paused');assert.equal(await ev('IndicatorPanel.current().status'),'paused');
  await ev('S.lastErr=null;__CF.render(false);void 0');
  const geometry=[];
  for(const width of [1280]){
    await cmd('/window/rect','POST',{width,height:1100});
    for(const kind of ['ema','bollinger']){
      await choosePrice(kind);await ev('document.getElementById("priceIndicatorPanel").scrollIntoView({block:"start"});void 0');await pause(250);
      assert(await ev('document.documentElement.scrollWidth<=innerWidth'),'price indicator overflow');await screenshot('technical-'+kind+'-'+width);
    }
    await ev('document.getElementById("indicatorPanel").scrollIntoView({block:"start"});void 0');await pause(200);
    await until(()=>ev('Math.abs(IndicatorPanel.chart().timeScale().getVisibleLogicalRange().from-chart.timeScale().getVisibleLogicalRange().from)<.001'),'MACD responsive range');
    assert(await ev('document.documentElement.scrollWidth<=innerWidth'),'MACD overflow');
    const g=await ev('({main:chart.timeScale().getVisibleLogicalRange(),aux:IndicatorPanel.chart().timeScale().getVisibleLogicalRange(),mainX:chart.timeScale().logicalToCoordinate(50),auxX:IndicatorPanel.chart().timeScale().logicalToCoordinate(50),ratio:document.getElementById("chart").clientWidth/document.getElementById("chart").clientHeight})');
    assert(Math.abs(g.mainX-g.auxX)<.1,'MACD candle alignment: '+JSON.stringify(g));assert(Math.abs(g.ratio-1.5)<.03);geometry.push({width,...g});await screenshot('technical-macd-'+width);
  }
  fs.writeFileSync(path.join(LOGS,'technical-ranges.json'),JSON.stringify(geometry,null,2));
  for(const kind of ['rsi','volume','atr','macd']){await chooseAux(kind);assert.equal(await ev('IndicatorPanel.series().signal.options().visible'),kind==='macd');}
  await choosePrice('none');assert.equal(await ev('getComputedStyle(document.getElementById("priceIndicatorReadout")).display'),'none');
  await choosePrice('ema');await ev('__CF.setTF("M");void 0');await until(()=>ev('!S.refreshing'),'monthly indicators');
  assert.equal(await ev('PriceIndicators.current().status'),'insufficient-data');assert.equal(await ev('IndicatorPanel.current().status'),'insufficient-data');
  await checkErrors();evidence.push({scenario:'EMA/MACD/Bollinger selection, fixed basis and future masks, no collection or strategy mutation, pause states, one auxiliary chart and desktop alignment'});
}

async function cachedTriangleReplay(){
  const payload=JSON.parse(fs.readFileSync(process.env.CACHED_TRIANGLE_REPLAY,'utf8'));
  assert(payload.symbol&&payload.triangleAnalysis&&payload.candles.length>30);
  await cmd('/window/rect','POST',{width:1280,height:1100});
  await ev(`S.autoRef=false;LIVE_D[${JSON.stringify(payload.symbol)}]=${JSON.stringify(payload)};S.symbol=${JSON.stringify(payload.symbol)};S.tf='D';S.selectedAsOf=null;S.preset='3M';S.lastErr=null;buildSymList('');__CF.render(true);FlagPanel.selectArea('triangle');document.getElementById('chart').scrollIntoView({block:'start'});void 0`);
  await until(()=>ev('Boolean(document.querySelector("#chart polygon[data-pattern]"))'),'cached triangle replay');
  const result=await ev(`(()=>{
    const f=frameOf(curSym()),p=TrianglePanel.selected(),point=p.geometry.points[1],i=f.candles.findIndex(r=>r.time===point.anchorTime)+point.logicalOffset;
    const x=chart.timeScale().logicalToCoordinate(Math.floor(i)),next=chart.timeScale().logicalToCoordinate(Math.ceil(i));
    return {symbol:S.symbol,bars:f.candles.length,apex:i,lastIndex:f.candles.length-1,raw:chart.timeScale().logicalToCoordinate(i),
      expected:x+(i-Math.floor(i))*(next-x),actual:Number(document.querySelector('#chart polygon[data-pattern]').getAttribute('points').split(' ')[1].split(',')[0]),
      circles:markerLayout.markers.filter(m=>m.shape==='circle').length,
      originalTransitions:obsTransitions(buildObservationSeries(f)).filter(({i})=>f.candles[i].time>=visibleTimes().from).length,
      markers:JSON.stringify(markerLayout.markers)};
  })()`);
  assert(result.apex<result.lastIndex&&!Number.isInteger(result.apex));assert.equal(result.raw,0);
  assert(Math.abs(result.actual-result.expected)<.001);assert(result.circles<result.originalTransitions);
  await ev('for(let i=0;i<50;i++)renderMarkers();void 0');
  assert.equal(await ev('JSON.stringify(markerLayout.markers)'),result.markers,'cached replay accumulated markers');
  await screenshot('cached-triangle-replay');await checkErrors();
  delete result.markers;fs.writeFileSync(path.join(LOGS,'cached-triangle-replay.json'),JSON.stringify(result,null,2));
  evidence.push({scenario:'Cached real bars: interior fractional apex and bounded stable observation dots',...result});
}

async function topbarStability(){
  await config({reset:true});await navigate();
  await ev('if(S.autoRef)document.getElementById("btnAuto").click();void 0');
  const geometry=()=>ev(`(()=>{
    const ids=['q','sym','btnLookup','btnRefresh','btnAuto','btnHelp','tD','tW','tH','tM','netState','symTitle','basisLine'];
    const rect=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};};
    return {items:Object.fromEntries(ids.map(id=>[id,rect(document.getElementById(id))])),
      header:rect(document.querySelector('.topbar')),title:rect(document.querySelector('.titleline')),
      overflow:document.querySelector('.topbar').scrollWidth>document.querySelector('.topbar').clientWidth};
  })()`);
  for(const width of [1440,1280,1024]){
    await cmd('/window/rect','POST',{width,height:1000});
    await ev('setBusy(false);S.lastErr=null;paintBasis();void 0');
    const before=await geometry();assert.equal(before.overflow,false);
    await config({holdSymbol:'AAPL'});
    await ev('window.__headerDone=false;requestNewTicker("AAPL").finally(()=>window.__headerDone=true);void 0');
    await until(()=>ev('S.refreshing'),'held lookup busy');
    assert.deepEqual(await geometry(),before,`header moved during lookup at ${width}px`);
    assert.equal(await ev('document.getElementById("btnRefresh").textContent'),'조회 중…');
    await config({release:true});await until(()=>ev('window.__headerDone && !S.refreshing'),'header lookup completed');
    assert.deepEqual(await geometry(),before,`header moved after lookup at ${width}px`);
    await config({restError:true});
    await ev('window.__headerDone=false;requestNewTicker("AAPL").then(r=>window.__headerResult=r).finally(()=>window.__headerDone=true);void 0');
    await until(()=>ev('window.__headerDone && !S.refreshing && window.__headerResult?.ok===false'),'header failed lookup');
    assert.deepEqual(await geometry(),before,`header moved after failure at ${width}px`);
    await ev(`paintNet('공급처 조회 실패 · '.repeat(60));LIVE_D.AAPL.name='아주 긴 종목명 '.repeat(30);S.lastErr={kind:'provider'};paintBasis();void 0`);
    assert.deepEqual(await geometry(),before,`long status or symbol changed header at ${width}px`);
    assert.equal(await ev('document.getElementById("netState").title===document.getElementById("netState").textContent'),true);
    assert.equal(await ev('document.getElementById("symTitle").title===document.getElementById("symTitle").textContent'),true);
    assert.equal(await ev('document.getElementById("basisLine").title===document.getElementById("basisLine").textContent'),true);
    await config({restError:false});
  }
  await cmd('/window/rect','POST',{width:1280,height:900});
  await ev('S.lastErr=null;void 0');
  await ev('__CF.setTF("H4");void 0');
  await until(()=>ev('!S.refreshing && frameOf(curSym())?.source==="toss"'),'Toss H4 loaded');
  assert.equal(await ev('frameOf(curSym()).sourceInterval'),'1m');
  assert.equal(await ev('frameOf(curSym()).candles.length'),260);
  await checkErrors();
  evidence.push({scenario:'Desktop lookup header: identical geometry pending/success/failure/long status at 1440/1280/1024px; configured stock H4 uses Toss minute aggregation'});
}

async function main() {
  for(const exe of [PY,DRIVER,FIREFOX]) {const r=spawnSync(exe,['--version'],{timeout:10000});assert(!r.error&&r.status===0,`required executable unavailable: ${exe}`);}
  assert(!await portOpen(PORT),'fixture port already owned by another process');assert(!await portOpen(WDPORT),'WebDriver port already owned by another process');
  let failed;
  try {
    server=launch(PY,[path.join(__dirname,'mock-server.py'),'--port',String(PORT)],'server');
    await until(async()=>{if(server.launchError)throw server.launchError;return request(URL,'/api/health').catch(()=>false);},'fixture server');
    driver=launch(DRIVER,['--port',String(WDPORT),'--allow-system-access'],'geckodriver');
    await until(async()=>{if(driver.launchError)throw driver.launchError;return wd('/status').catch(()=>false);},'geckodriver');
    const value=(await wd('/session','POST',{capabilities:{alwaysMatch:{browserName:'firefox','moz:firefoxOptions':{args:['-headless']}}}})).value;
    session=value.sessionId;assert(session);evidence.push({scenario:'session',browser:value.capabilities.browserName,version:value.capabilities.browserVersion,driverPid:driver.pid,browserPid:value.capabilities['moz:processID'],serverPid:server.pid});
    await cmd('/timeouts','POST',{script:20000,pageLoad:30000,implicit:0});
      if(process.env.TECHNICAL_ONLY==='1')await technicalScenario();
      else if(process.env.INDICATOR_ONLY==='1')await indicatorScenario();
      else if(process.env.TRIANGLE_ONLY==='1')await triangleScenario();
      else if(process.env.MONITOR_ONLY==='1')await monitorScenario();
      else if(process.env.FLAG_ONLY==='1')await flagScenario();
      else if(process.env.PATTERN_ONLY==='1')await patternScenario();
      else {await topbarStability(); await config({reset:true}); await navigate(); await scenarios(); await patternScenario(); await flagScenario(); await monitorScenario(); await triangleScenario(); await indicatorScenario(); await technicalScenario();}
      if(process.env.CACHED_TRIANGLE_REPLAY)await cachedTriangleReplay();
  } catch(error) {
    cleanupDeadline=Date.now()+45000;
    failed=error;console.error(scrub(error.stack));
    if(session)console.error('Layout diagnostics: '+scrub(JSON.stringify(await ev('window.__pageOverflow||null').catch(()=>null))));
    if(session)await screenshot('firefox-failure').catch(e=>console.error('failure capture: '+scrub(e.message)));
  } finally {
    cleanupDeadline=Date.now()+45000;
    if(session)try{await cmd('','DELETE');}catch(e){failed ||= e;}
    for(const p of owned.slice().reverse())try{await stopChild(p);}catch(e){console.error('cleanup: '+scrub(e.stack));failed ||= e;}
    if(await portOpen(PORT)||await portOpen(WDPORT))failed ||= new Error('owned test port remains open');
    evidence.push({scenario:'cleanup',portsClosed:!await portOpen(PORT)&&!await portOpen(WDPORT),children:owned.map(p=>({pid:p.pid,exitCode:p.exitCode,signal:p.signalCode}))});
    fs.writeFileSync(path.join(LOGS,'evidence.json'),JSON.stringify(evidence,null,2));
  }
  if(failed)throw failed;
  console.log('PASS Firefox single-session suite; owned children exited and ports closed');
}
main().catch(error=>{console.error(scrub(error.stack));process.exitCode=1;});
