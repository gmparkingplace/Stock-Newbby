'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),{sample,day}=require('./low_entry_sample');
class El{
 constructor(id=''){this.id=id;this.value='';this.checked=false;this.dataset={};this.children=[];this.listeners={};this.attrs={};this.parentLabel={hidden:false};this.classList={add:()=>{}};this.clientWidth=1000;this.clientHeight=500;}
 addEventListener(k,f){(this.listeners[k]||=[]).push(f);}setAttribute(k,v){this.attrs[k]=v;}replaceChildren(...x){this.children=x;}append(...x){this.children.push(...x);}appendChild(x){this.append(x);}closest(){return this.parentLabel;}querySelector(q){return this.children.find(x=>x.className===q.slice(1))||null;}
}
const html=fs.readFileSync(require.resolve('../results/dashboard/chart-first.html'),'utf8'),els=new Map([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new El(m[1])])),get=id=>{assert(els.has(id),'real HTML element '+id);return els.get(id);};
get('entryFamily').value='legacy';get('entryBreakoutKind').value='F';get('lowOverlayEnabled').checked=true;
get('entryMode').parentLabel=get('entryModeControl');
const make=(value,checked)=>Object.assign(new El(),{value,checked}),legacy=[make('A',true),make('B',false),get('entryBreakoutEnabled')],low=[make('R',true),make('H',true)];legacy[2].value='F';legacy[2].checked=true;
const init=[],tasks=new Map(),rangeCallbacks=[];let serial=0,index=26,markerOutput=[],networkCalls=0;
const frame={symbol:'TEST',tf:'D',candles:sample('H').slice(0,27),state:[],source:'toss',fetchedAt:new Date().toISOString(),marketSession:{state:'closed'},lastConfirmedTime:day(26),confirmed:true,lines:{},marks:{}};
const timeScale={timeToCoordinate:t=>frame.candles.findIndex(b=>b.time===t)*20,height:()=>30,subscribeVisibleLogicalRangeChange:f=>rangeCallbacks.push(f),subscribeVisibleTimeRangeChange:f=>rangeCallbacks.push(f)};
const ctx={console,Date,Intl,S:{symbol:'TEST',tf:'D',entryFamily:'legacy',entryStrategies:['A','F'],lowStrategies:['R','H'],autoRef:true,selectedAsOf:null},
 document:{hidden:false,getElementById:get,createElement:()=>new El(),createElementNS:()=>new El(),addEventListener:(k,f)=>{if(k==='DOMContentLoaded')init.push(f);},querySelectorAll:q=>{const list=q.includes('lowStrategy')?low:legacy;return q.includes(':checked')?list.filter(e=>e.checked):list;}},
 currentObs:()=>({f:frame,oi:index,model:{observationAsOf:frame.candles[index]?.time},st:{sigF:'exit'}}),frameOf:()=>frame,curSym:()=>frame,asOfIdx:()=>index,latestTime:f=>f.candles.at(-1)?.time,
 fmtT:String,fmtP:n=>'$'+n.toFixed(2),fmtClock:String,chart:{timeScale:()=>timeScale,priceScale:()=>({width:()=>60})},candles:{priceToCoordinate:p=>p==null?null:500-p*3},
 requestAnimationFrame:f=>{tasks.set(++serial,f);return serial;},ResizeObserver:class{observe(){}},fetch:()=>{networkCalls++;throw new Error('new API request');}};
ctx.window=ctx;ctx.self=ctx;ctx.renderMarkers=()=>{markerOutput=ctx.LowStructurePanel?.markers()||[];};vm.createContext(ctx);
for(const name of ['chart-timing','entry-model','low-structure-model','low-structure-rules','low-structure-cache','low-entry-model','low-entry-context','pattern-window','entry-panel','low-structure-panel'])vm.runInContext(fs.readFileSync(require.resolve('../results/dashboard/'+name),'utf8'),ctx);
for(const f of init)f();const flush=()=>{for(const [id,f] of [...tasks]){tasks.delete(id);f();}};flush();
const baseline=JSON.stringify(ctx.entryEvaluation());assert.equal(markerOutput.length,0);
get('entryFamily').value='low';get('entryFamily').onchange({target:get('entryFamily')});flush();
assert.equal(get('legacyStrategies').hidden,true);assert.equal(get('lowStrategies').hidden,false);assert.equal(get('entryMode').disabled,true);
assert.equal(get('entryModeControl').hidden,true);assert.equal(get('entryControls').dataset.family,'low');
assert.equal(get('entrySettingsLegacy').hidden,true);assert.equal(get('entrySettingsLow').hidden,false);
assert.equal(get('entryPanel').dataset.decision,'candidate');assert.match(get('entryTitle').textContent,/저점 상승/);assert.equal(get('entryCompare').children.length,2);assert.equal(get('lowStructureFacts').children.length,4);assert.equal(markerOutput.length,3);
assert.match(get('lowStructureNote').textContent,/돌파 전략 이탈/);const overlay=get('chart').children.at(-1);assert.equal(overlay.children.at(-1).children.length,4);
const facts=JSON.stringify(get('lowStructureFacts').children.map(c=>c.children.map(e=>e.textContent))),before=ctx.LowEntryContext.cache.stats().calculations;
for(let i=0;i<100;i++){ctx.LowStructurePanel.render();ctx.renderMarkers();flush();}assert.equal(markerOutput.length,3);assert.equal(ctx.LowEntryContext.cache.stats().calculations,before);assert.equal(JSON.stringify(get('lowStructureFacts').children.map(c=>c.children.map(e=>e.textContent))),facts);
for(const cb of rangeCallbacks)cb();flush();assert.equal(overlay.children.at(-1).children.length,4);
get('lowOverlayEnabled').checked=false;get('lowOverlayEnabled').onchange();flush();assert.equal(overlay.children.length,0);assert.equal(markerOutput.length,0);
get('lowOverlayEnabled').checked=true;get('lowOverlayEnabled').onchange();flush();assert.equal(markerOutput.length,3);
index=24;ctx.S.selectedAsOf=day(24);ctx.renderEntryPanel(ctx.currentObs());ctx.renderMarkers();flush();assert.equal(get('entryPanel').dataset.state,'historical');assert.equal(get('entryPanel').dataset.decision,'wait');assert.equal(markerOutput.some(m=>m.shape==='arrowUp'),false);
index=26;ctx.S.selectedAsOf=day(26);ctx.renderEntryPanel(ctx.currentObs());flush();assert.equal(get('entryPanel').dataset.decision,'candidate');
ctx.S.lastErr={kind:'failed'};ctx.renderEntryPanel(ctx.currentObs());assert.equal(get('entryPanel').dataset.decision,'blocked');ctx.S.lastErr=null;
// Use actual terminal states: the prior signal price remains historical, not a current entry cap.
const originalCandles=frame.candles,originalConfirmed=frame.lastConfirmedTime;
const failed=sample('H');failed[27].low=ctx.LowStructurePanel.current().selected.invalidationLevel-1e-8;
frame.candles=failed.slice(0,28);frame.lastConfirmedTime=day(27);index=27;ctx.S.selectedAsOf=null;ctx.renderEntryPanel(ctx.currentObs());
assert.equal(get('entryPanel').dataset.decision,'avoid');assert.equal(get('entryTitle').textContent,'지지선 이탈 · 매수 대기');
assert.match(get('entryReason').textContent,/확정봉의 저가.*새 저점과 반등/);assert.equal(get('entrySetup').textContent,'판단 봉 '+day(27));
assert.equal(get('entryRisk').textContent,'새 신호 확인 후 매수 상한 표시');assert.match(get('entryRiskHelp').textContent,/이전 신호.*지금 매수 기준으로 쓰지/);
assert.equal(get('entryCompare').children[1].children[0].textContent,'저점 상승');assert.equal(get('lowStructureFacts').children[2].children[0].textContent,'이전 지지 하한선');
frame.candles=sample('H').slice(0,31);frame.lastConfirmedTime=day(30);index=30;ctx.renderEntryPanel(ctx.currentObs());
assert.equal(get('entryTitle').textContent,'새 매수 신호를 기다리세요');assert.match(get('entryReason').textContent,/발생봉과 이후 3봉/);
assert.equal(get('entryRisk').textContent,'새 신호 확인 후 매수 상한 표시');
frame.candles=originalCandles;frame.lastConfirmedTime=originalConfirmed;index=26;
get('entryFamily').value='legacy';get('entryFamily').onchange({target:get('entryFamily')});ctx.S.selectedAsOf=null;assert.equal(JSON.stringify(ctx.entryEvaluation()),baseline);assert.equal(JSON.stringify(ctx.S.entryStrategies),'["A","F"]');
assert.equal(get('entryModeControl').hidden,false);assert.equal(get('entryMode').disabled,false);assert.equal(get('entryControls').dataset.family,'legacy');
assert.equal(get('entrySettingsLegacy').hidden,false);assert.equal(get('entrySettingsLow').hidden,true);
assert.equal(networkCalls,0);
// Script execution order and shared-marker integration are checked against production HTML.
const order=['low-structure-model','low-structure-rules','low-structure-cache','low-entry-model','low-entry-context','entry-panel','low-structure-panel'];for(let i=1;i<order.length;i++)assert(html.indexOf('src="'+order[i-1]+'.js"')<html.indexOf('src="'+order[i]+'.js"'));
assert.match(html,/mk\.push\(\.\.\.LowStructurePanel\.markers\(\)\)/);assert.match(html,/\.lowFacts\{display:grid/);assert.match(html,/@media\(max-width:480px\)\{\.lowFacts\{grid-template-columns:1fr\}/);
// hidden must override the author display:grid rule; property-only mocks missed the visible AND control.
assert.match(html,/#entryPanel \.entryControls>label\[hidden\][^{]*\{display:none\}/);
assert.match(html,/\.entryControls\[data-family="low"\]\{grid-template-columns:minmax\(0,1fr\)\}/);
// Exercise actual watchlist rendering for selected and list-only cached symbols.
ctx.ChartUtil=require('../results/dashboard/chart-util');ctx.validFrame=ctx.ChartUtil.validFrame;ctx.serverMode=true;ctx.tfWord=()=> '일봉';ctx.LIVE_D={TEST:frame};ctx.LIVE_H4={};
vm.runInContext(fs.readFileSync(require.resolve('../results/dashboard/watchlist'),'utf8'),ctx);
ctx.Watchlist.state.groups.push({id:'test',name:'fixture',symbols:[{symbol:'TEST',name:'테스트'}]});ctx.Watchlist.state.activeGroupId='test';
frame.state=frame.candles.map(()=>({sigF:'exit'}));ctx.S.entryStrategies=['F'];
get('entryFamily').value='low';get('entryFamily').onchange({target:get('entryFamily')});flush();
const row=()=>get('wlRows').children[0],assertAgreement=()=>{
 const main=ctx.entryEvaluation();assert.equal(main.code,'candidate');assert.equal(row().querySelector('.wl-row-state').textContent,main.label);
 assert.equal(row().dataset.basis,main.observationBasis);assert.equal(row().dataset.family,'low');assert.equal(row().querySelector('.wl-tone').dataset.tone,'entry');
};
assertAgreement();assert.match(get('wlInfo').textContent,/저점 회복.*저점 상승.*OR/);
ctx.S.symbol='OTHER';ctx.Watchlist.onSymbolChangeHook('TEST');assertAgreement(); // saves TEST frame into actual list-only cache
ctx.S.symbol='TEST';index=24;ctx.S.selectedAsOf=day(24);ctx.renderEntryPanel(ctx.currentObs());ctx.Watchlist.render();
assert.equal(get('entryPanel').dataset.state,'historical');assert.equal(row().dataset.basis,day(26),'list must remain latest during historical chart review');
index=26;ctx.S.selectedAsOf=null;
low[1].checked=false;low[1].listeners.change[0]();flush();
assert.equal(ctx.LowStructurePanel.current().selected,null);assert.equal(markerOutput.length,0);assert.equal(overlay.children.length,0);
assert.match(get('lowStructureStatus').textContent,/선택한 전략의 구조 없음/);assert(!get('wlInfo').textContent.includes('저점 상승'));
// Manual history may show an unselected family, but must identify its separate purpose.
const h=ctx.LowStructurePanel.current().structures.find(s=>s.family==='H');assert(h);
get('lowStructureChoice').onchange({target:{value:h.id}});flush();assert.equal(ctx.LowStructurePanel.current().manual,true);
assert.match(get('lowStructureStatus').textContent,/과거 구조 · 현재 판단과 별도/);assert.equal(ctx.entryEvaluation().code,'wait');
get('lowStructureChoice').onchange({target:{value:'auto'}});flush();assert.equal(markerOutput.length,0);
low[1].checked=true;low[1].listeners.change[0]();flush();assertAgreement();
ctx.MonitorPanel={row:s=>s==='TEST'?{label:'돌파 대기',basis:day(26)}:null,active:()=>true,manages:()=>true};ctx.S.symbol='OTHER';ctx.S.tf='W';ctx.Watchlist.render();
assert.equal(row().dataset.family,'pattern-monitor');assert.equal(row().dataset.timeframe,'D');assert.match(row().querySelector('.wl-row-state').textContent,/일봉 패턴 감시/);
ctx.S.symbol='TEST';ctx.S.tf='W';ctx.Watchlist.render();assert.match(row().querySelector('.wl-row-state').textContent,/지원|보류|확인/);
assert.equal(networkCalls,0);
console.log('Low UI DOM: family round-trip, past colors, one overlay/markers, fixed facts, zoom reuse and zero extra API calls passed');
