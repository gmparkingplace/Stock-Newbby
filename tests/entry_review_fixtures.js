'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const E=require('../results/dashboard/entry-model.js');
const timing={judgmentReady:true,judgmentMode:'closed-confirmed',message:'확정봉'};
function sample(entries=['A']){
 const candles=Array.from({length:65},(_,i)=>({time:i+1,close:101}));
 const state=candles.map((_,i)=>({sigA:'none',sigB:'none',sigC:'none',sigF:'none',rsi14:i<60?29:35,don_hi:100,don_lo:90,atr14:10,vol_ratio:1.2}));
 for(const k of entries)state[60]['sig'+k]='entry';
 const lines={sma20:candles.map((b,i)=>({time:b.time,value:i<60?99:101})),sma60:candles.map(b=>({time:b.time,value:100}))};
 return {candles,state,lines,marks:{},confirmed:true};
}
const run=(frame,index,selected=['A'],extra={})=>E.evaluate({frame,index,selected,timing,...extra});
for(const k of ['A','B']){
 const f=sample([k]),original=JSON.stringify(f);
 for(let age=0;age<=3;age++){
  const s=run(f,60+age,[k]);assert.equal(s.code,'candidate');assert.equal(s.matched,age===0);assert.equal(s.continuation,age>0);
  assert.equal(s.anchorTime,61);assert.equal(s.signalAge,age);assert.equal(s.chaseLimit,106);
  assert.equal(s.rows.find(r=>r.id===k).phase,age?'tracking':'new');
 }
 assert.equal(run(f,64,[k]).code,'wait');
 assert.equal(run(f,62,[k],{timing:{judgmentReady:false,message:'조회 실패'}}).code,'blocked');
 assert.equal(run(f,62,[k],{timing:{judgmentReady:false,message:'자료 지연'}}).code,'blocked');
 assert.equal(run(f,62,[k],{timing:{judgmentReady:true,judgmentMode:'live-snapshot'}}).label,'봉 확정 대기');
 const future=structuredClone(f),past=run(f,62,[k],{historical:true});future.candles[64].close=9999;future.state[64]['sig'+k]='exit';
 assert.deepEqual(run(future,62,[k],{historical:true}),past,'future changed past continuation');
 const chase=structuredClone(f);chase.candles[62].close=106.01;assert.equal(run(chase,62,[k]).code,'chase');
 const boundary=structuredClone(f);boundary.candles[63].close=106;assert.equal(run(boundary,63,[k]).code,'candidate');
 const exited=structuredClone(f);exited.state[61]['sig'+k]='exit';assert.equal(run(exited,62,[k]).code,'wait');assert.equal(run(exited,61,[k]).code,'avoid');
 const low=structuredClone(f);low.candles[61].close=89;assert.equal(run(low,61,[k]).code,'avoid');assert.equal(run(low,62,[k]).code,'wait','invalidated review resumed after rebound');
 const lost=structuredClone(f);if(k==='A')lost.lines.sma20[61].value=99;else lost.state[61].rsi14=30;
 assert.equal(run(lost,62,[k]).code,'wait','maintenance break resumed old review');
 const missing=structuredClone(f);missing.lines.sma60.splice(62,1);assert.equal(run(missing,62,[k]).code,'blocked');
 const atr=structuredClone(f);atr.state[60].atr14=null;assert.equal(run(atr,62,[k]).code,'blocked');
 assert.equal(JSON.stringify(f),original,'review mutated raw producer signals');
}
const ab=sample(['A','B']);assert.equal(run(ab,63,['A','B']).code,'candidate');
const separate=sample(['A']);separate.state[61].sigB='entry';
assert.equal(run(separate,62,['A','B']).code,'wait','AND joined crossings on different bars');
assert.equal(run(separate,62,['A','B'],{mode:'any'}).code,'candidate');
const mixed=sample(['A','F']);mixed.state[62].sigF='entry';
assert.equal(run(mixed,62,['A','F']).code,'candidate');assert.equal(run(mixed,61,['A','F']).code,'wait');
const noEvent=sample(['F']);assert.equal(run(noEvent,62,['A','F'],{mode:'any'}).code,'wait','OR extended F-only event as A');
const newCross=sample([]);for(let i=45;i<65;i++)newCross.state[i].sigC='entry';newCross.state[63].sigA='entry';
const freshCross=run(newCross,63,['A','C'],{mode:'any'});assert.equal(freshCross.code,'candidate');assert.equal(freshCross.anchorTime,64);assert.equal(freshCross.signalAge,0,'old OR breakout swallowed new A crossing');
assert.equal(run(newCross,64,['A','C'],{mode:'any'}).signalAge,1);
const continuous=sample(['C','F']);continuous.state[61].sigC='entry';continuous.state[61].sigF='entry';
assert.equal(run(continuous,61,['F']).rows.find(r=>r.id==='F').phase,'maintained');
assert.equal(run(continuous,62,['F']).code,'wait');assert(run(continuous,61,['C','F']).combinationNote);
const monthly=sample([]);monthly.lines={sma20:[],sma60:[]};
const unavailable=run(monthly,62,['B']);assert.equal(unavailable.code,'blocked');assert.match(unavailable.reason,/SMA 60/);
assert.equal(unavailable.rows.find(r=>r.id==='B').signal,'none');assert.equal(unavailable.rows.find(r=>r.id==='B').phase,'unavailable');

// Real panel handlers: one breakout choice, A/B preserved and no network/timer dependency.
class Element{constructor(){this.value='';this.checked=false;this.dataset={};this.children=[];}addEventListener(k,f){this[k]=f;}replaceChildren(){this.children=[];}appendChild(x){this.children.push(x);}}
const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const a=new Element(),b=new Element(),breakout=get('entryBreakoutEnabled');a.value='A';a.checked=true;b.value='B';breakout.value='F';breakout.checked=true;
const checkboxes=[a,b,breakout];let init;
const ctx={EntryModel:E,ChartTiming:{},S:{},Date,document:{getElementById:get,createElement:()=>new Element(),querySelectorAll:q=>q.includes(':checked')?checkboxes.filter(x=>x.checked):checkboxes,addEventListener:(_,fn)=>{init=fn;}},currentObs:()=>null,fmtT:String,fmtP:String,fmtClock:String};ctx.window=ctx;
vm.createContext(ctx);vm.runInContext(fs.readFileSync(require.resolve('../results/dashboard/entry-panel.js'),'utf8'),ctx);
ctx.entryEvaluation=()=>null;init();get('entryBreakoutKind').onchange({target:{value:'C'}});
assert.equal(JSON.stringify(ctx.S.entryStrategies),'["A","C"]');breakout.checked=false;breakout.change();assert.equal(JSON.stringify(ctx.S.entryStrategies),'["A"]');
const out=run(sample(['A']),62);ctx.entryEvaluation=()=>({...out,fetchedAt:null,observationBasis:out.basis});ctx.renderEntryPanel({});
assert.match(get('entryCompare').children[0].children[1].textContent,/추적 2\/3봉/);assert.match(get('entrySetup').textContent,/최초 신호/);
ctx.entryEvaluation=()=>({...out,basis:'2026-09-04',observationBasis:'2026-09-11'});ctx.renderEntryPanel({});
assert.match(get('entrySetup').textContent,/2026-09-04.*차트 봉 2026-09-11/);
for(const kind of ['F','C']){
 get('entryBreakoutKind').value=kind;ctx.renderEntryPanel({});
 const table=get('entryCompare').children;assert.equal(table.length,3);assert.match(table[2].children[0].textContent,/^돌파 · /);
 assert.equal(table[2].children[0].textContent.includes(kind==='F'?'고점 돌파':'추세·거래량'),false,'independent C/F row survived grouping');
}
ctx.entryEvaluation=()=>({...out,code:'chase',reason:'긴 추격 설명',modeMessage:'잠정 · 공급처 지연 미확인',fetchedAt:'2026-10-06',observationBasis:out.basis});ctx.renderEntryPanel({});
assert(!get('entryReason').textContent.includes('공급처'));assert.match(get('entryDataDetails').textContent,/마지막 조회/);

// Past presentation uses the selected bar's computed decision, without turning it into a live signal.
const historicalCases=[['candidate',sample(['A']),62],['chase',sample(['A']),62],['avoid',sample(['A']),62],['wait',sample(['A']),64],['blocked',sample(['A']),62]];
historicalCases[1][1].candles[62].close=106.01;
historicalCases[2][1].state[62].sigA='exit';
historicalCases[4][1].lines.sma60.splice(62,1);
for(const [decision,frame,index] of historicalCases){
 const past=run(frame,index,['A'],{historical:true,timing:{judgmentReady:false,message:'현재 조회 실패'}});
 assert.equal(past.code,'historical');assert.equal(past.setupDecision.code,decision);
 ctx.entryEvaluation=()=>past;ctx.renderEntryPanel({});
 assert.equal(get('entryPanel').dataset.state,'historical');assert.equal(get('entryPanel').dataset.decision,decision);
 assert.equal(get('entryTitle').textContent,`당시 · ${past.setupDecision.label}`);
 assert.match(get('entryReason').textContent,/현재 진입 안내가 아니/);assert.equal(get('entryDataStatus').textContent,'과거 봉');
}
// Live freshness and confirmation gates still override a positive underlying setup.
for(const gate of [{judgmentReady:false,message:'조회 실패'},{judgmentReady:true,judgmentMode:'live-snapshot'},timing]){
 const live=run(sample(['A']),62,['A'],{timing:gate});assert.equal(live.setupDecision.code,'candidate');
 ctx.entryEvaluation=()=>live;ctx.renderEntryPanel({});
 assert.equal(get('entryPanel').dataset.state,live.code);assert.equal(get('entryPanel').dataset.decision,live.code);
 assert.equal(get('entryTitle').textContent,live.label);
}
ctx.entryEvaluation=()=>null;ctx.renderEntryPanel(null);assert.equal(get('entryPanel').dataset.decision,'blocked');
const html=fs.readFileSync(require.resolve('../results/dashboard/chart-first.html'),'utf8');
assert.match(html,/#entryPanel\[data-decision="candidate"\]\{border-left-color:#17644C;background:#effaf5\}/);
assert.match(html,/#entryPanel\[data-decision="chase"\],#entryPanel\[data-decision="avoid"\]\{border-left-color:#b45309;background:#fff7ed\}/);
console.log('A/B review, panel grouping and historical decision colors with live gates preserved passed');
