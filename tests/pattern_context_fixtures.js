'use strict';
// Real panel current()/tick()/DOM paths; no browser, server or provider calls.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element{
 constructor(){this.children=[];this.dataset={};this.value='';this.textContent='';}
 replaceChildren(...items){this.children=items;}append(...items){this.children.push(...items);}
 setAttribute(k,v){this[k]=v;}
 addEventListener(){}
}
const fetched=Date.parse('2026-10-06T00:00:00Z');let now=fetched;
const times=['2026-10-05','2026-10-06'];
const analysis=family=>({enabled:true,symbol:'TEST',timeframe:'D',sourceStatus:'ready',provisionalEligible:true,sourceFetchedAt:new Date(fetched).toISOString(),recentEvents:[],
 timeline:times.map((barTime,i)=>({barTime,confirmed:i===0,status:'ready',
  levels:[{type:'prior-20-high',anchorTime:barTime,barTime,status:i?'breakout-pending':'confirmed',direction:'up'}],
  patterns:[{patternId:family+i,type:family==='flag'?'bull-flag':'ascending-triangle',anchorTime:barTime,barTime,status:i?'breakout-pending':'confirmed',direction:'up'}]}))});
const frame={candles:times.map(time=>({time})),confirmed:false,patternAnalysis:analysis('horizontal'),flagAnalysis:analysis('flag'),triangleAnalysis:analysis('triangle')};
const elements=new Map(),listeners={};let network=0;
const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const ctx={Date:class extends Date{static now(){return now;}},PatternWindow:require('../results/dashboard/pattern-window'),
 S:{symbol:'TEST',tf:'D',selectedAsOf:null,autoRef:true,lastErr:null},curSym:()=>frame,frameOf:()=>frame,
 document:{hidden:false,getElementById:get,createElement:()=>new Element(),addEventListener:(k,f)=>(listeners[k]||=[]).push(f)},
 chart:{},candles:{},PatternOverlay:{create:()=>({set(){}}),choose:()=>null},fetch:()=>{network++;throw Error('unexpected lookup');}};
ctx.window=ctx;vm.createContext(ctx);
for(const name of ['chart-timing','pattern-panel','flag-panel','triangle-panel'])vm.runInContext(fs.readFileSync(require.resolve('../results/dashboard/'+name),'utf8'),ctx);
for(const f of listeners.DOMContentLoaded)f();
const panels=[ctx.PatternPanel,ctx.FlagPanel,ctx.TrianglePanel];
const statuses=()=>panels.map(p=>{const v=p.current();return (v.levels||v.patterns)[0].status;});
for(const age of [0,89000,90000,91000]){
 now=fetched+age;
 for(const selection of [null,times[1]]){
  ctx.S.selectedAsOf=selection;panels.forEach(p=>p.tick());
  const expected=age>90000?'paused':'breakout-pending';assert.deepEqual(statuses(),[expected,expected,expected]);
  assert.equal(get('patternLevels').children[0].dataset.state,expected,'horizontal card kept an expired snapshot');
  if(expected==='paused')for(const id of ['patternStatus','flagState','triangleState'])assert.match(get(id).textContent,/자료 보류/);
 }
}
now=fetched;
for(const reason of ['auto','hidden','error']){
 ctx.S.autoRef=reason!=='auto';ctx.document.hidden=reason==='hidden';ctx.S.lastErr=reason==='error'?{kind:'fixture'}:null;
 for(const selection of [null,times[1]]){ctx.S.selectedAsOf=selection;panels.forEach(p=>p.tick());assert.deepEqual(statuses(),['paused','paused','paused']);}
 // Today's error/offline state must not invalidate a confirmed historical bar.
 ctx.S.selectedAsOf=times[0];panels.forEach(p=>p.tick());assert.deepEqual(statuses(),['confirmed','confirmed','confirmed']);
}
ctx.S.autoRef=true;ctx.S.lastErr=null;ctx.document.hidden=false;ctx.S.selectedAsOf=null;
for(const age of [-1,NaN]){now=fetched+age;assert.deepEqual(statuses(),['paused','paused','paused']);}
frame.confirmed=true;now=fetched+10*86400000;ctx.S.autoRef=false;
for(const a of [frame.patternAnalysis,frame.flagAnalysis,frame.triangleAnalysis]){
 a.timeline[1].confirmed=true;for(const p of [...a.timeline[1].levels,...a.timeline[1].patterns])p.status='confirmed';
}
assert.deepEqual(statuses(),['confirmed','confirmed','confirmed'],'clock expiry must not erase confirmed source history');
assert.equal(network,0);
const html=fs.readFileSync(require.resolve('../results/dashboard/chart-first.html'),'utf8');assert.match(html,/function renderSummary\(\)\s*\{\s*if \(window\.PatternPanel\) PatternPanel\.tick\(\)/);
console.log('Pattern context: all three real panels, 89/90/91s, latest click, OFF/hidden/errors, historical retention and DOM expiry passed');
