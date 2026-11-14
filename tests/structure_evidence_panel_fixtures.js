'use strict';
// Structure evidence panel: server evidence replay, no recalculation, no fetch.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const P=require('../results/dashboard/structure-evidence-panel.js');
const ChartTiming=require('../results/dashboard/chart-timing.js'),W=require('../results/dashboard/pattern-window.js');

const pattern={patternId:'p1',type:'double-top',direction:'down',lifecycleState:'failed',
  structureBars:9,discoveredAt:'2026-01-24',confirmedAt:'2026-01-27',evaluatedAt:'2026-02-05',
  structureStartTime:'2026-01-22',structureEndTime:'2026-01-28',barTime:'2026-02-05',confirmedBarTime:'2026-01-27',atr14Previous:3,close:108,
  neckline:{points:[{time:'2026-01-22',price:95},{time:'2026-01-28',price:95}],atEvaluation:95,flat:true,anchorTimes:['2026-01-25','2026-01-25'],anchorPrices:[95,95]},
  triggerPriceAtEvaluation:94.7,triggerPriceAtEvent:94.7,invalidationPrice:95.3,
  evidence:{structureBars:9,depth:{pct:10.4},priorTrend:{direction:'up',reversalContext:true},
    breakoutVolume:{ratio:1,status:'weak'},latestVolume:{ratio:1.5,status:'supported'}},
  reasons:[{code:'breakout-failed',text:'종가가 무효 기준을 넘어 구조가 무효화됐습니다.'}],
  events:[
    {eventId:'e1',patternId:'p1',eventType:'candidate-detected',effectiveBarTime:'2026-01-24',
      snapshot:{phaseAfter:'candidate',close:104,neckline:95,triggerPrice:94.7,invalidationPrice:95.3,volumeRatio:null,reasons:[{code:'candidate-detected',text:'후보'}]}},
    {eventId:'e2',patternId:'p1',eventType:'breakout-confirmed',effectiveBarTime:'2026-01-27',
      snapshot:{phaseAfter:'confirmed',close:94,neckline:95,triggerPrice:94.7,invalidationPrice:95.3,volumeRatio:1,reasons:[{code:'close-beyond-trigger',text:'종가 확인'}]}},
    {eventId:'e3',patternId:'p1',eventType:'breakout-failed',effectiveBarTime:'2026-02-05',
      snapshot:{phaseAfter:'failed',close:109,neckline:95,triggerPrice:94.7,invalidationPrice:95.3,volumeRatio:2,reasons:[{code:'breakout-failed',text:'무효'}]}}]};
const ready=()=>({enabled:true,sourceStatus:'ready',timeframe:'D',evaluatedThrough:'2026-02-05',ruleVersion:'structure-evidence-d-v1',configId:'c',patterns:[pattern],events:pattern.events});

assert.equal(P.view({enabled:false},'D',null,false).status,'disabled');
assert.equal(P.view(ready(),'H4',null,false).status,'unsupported');
const paused=P.view({...ready(),sourceStatus:'paused'},'D',null,false);
assert.equal(paused.status,'paused');
assert.equal(paused.patterns.length,1,'a paused source keeps the last valid history');
assert.equal(paused.patterns[0].paused,true);
assert.equal(paused.events.length,3);
assert.equal(P.view(ready(),'D',null,true).status,'paused');
assert.equal(P.view({...ready(),ruleVersion:'structure-evidence-d-v2'},'D',null,false).status,'unsupported-version');
assert.equal(P.view({...ready(),ruleVersion:undefined},'D',null,false).status,'ready');
assert.equal(P.view({...ready(),sourceStatus:'error'},'D',null,false).status,'error');
assert.equal(P.view({...ready(),patterns:[],events:[]},'D',null,false).status,'insufficient-data');
assert.equal(P.stateAt(pattern,'2026-01-20'),null);
const early=P.stateAt(pattern,'2026-01-26');
assert.equal(early.lifecycleState,'candidate');
// Nothing from a later confirmation bar may appear in a past view.
assert.equal(early.evidence.breakoutVolume,null);
assert.equal(early.evidence.latestVolume.ratio,null);
assert.equal(early.triggerPriceAtEvent,null);
assert.equal(early.confirmedBarTime,null);
assert.equal(early.confirmedAt,null);
const held=P.stateAt(pattern,'2026-01-30');
assert.equal(held.lifecycleState,'confirmed');assert.equal(held.historical,true);
assert.equal(held.triggerPriceAtEvaluation,94.7);assert.equal(held.confirmedAt,'2026-01-27');
assert.equal(held.events.length,2);
assert.equal(held.evidence.breakoutVolume.ratio,1);
assert.equal(held.evidence.latestVolume.ratio,1);
assert.equal(held.evidence.boostedAt,undefined);
assert.equal(held.evidence.retestVolume,undefined);
const later=P.stateAt(pattern,'2026-02-06');
assert.equal(later.evidence.latestVolume.ratio,1.5);
assert.equal(P.stateAt(pattern,'2026-02-06'),pattern);
const historical=P.view(ready(),'D','2026-01-26',false);
assert.equal(historical.status,'ready');assert.equal(historical.patterns[0].lifecycleState,'candidate');
assert.equal(historical.events.length,1);
assert.equal(P.stateLabel({lifecycleState:'retesting'}),'기준선 재시험');
assert.equal(P.eventLabel({eventType:'volume-supported'}),'거래량 동반 재돌파');
assert.equal(P.volumeLabel('unknown'),'자료 부족');

class El{constructor(){this.children=[];this.hidden=false;this.textContent='';this.dataset={};}
  replaceChildren(...items){this.children=items;}append(...items){this.children.push(...items);}setAttribute(k,v){this[k]=v;}}
const elements=new Map(),listeners={},frame={symbol:'AAPL',candles:[{time:'2026-01-01'},{time:'2026-02-05'}],confirmed:true};
const analysis=ready(),ctx={console,Date,Number,String,Boolean,JSON,PatternWindow:W,
  ChartTiming:{patternContext:({analysis:a,enabled})=>({historical:Boolean(ctx.S.selectedAsOf),asOf:ctx.S.selectedAsOf,blocked:!a?.enabled||!enabled})},
  S:{symbol:'AAPL',tf:'D',selectedAsOf:null,autoRef:true,lastErr:null},
  curSym:()=>({structureEvidenceV2:analysis}),frameOf:()=>frame,
  document:{hidden:false,getElementById:id=>{if(!elements.has(id))elements.set(id,new El());return elements.get(id);},
    createElement:()=>new El(),addEventListener:(event,f)=>(listeners[event]||=[]).push(f)}};
ctx.window=ctx;vm.createContext(ctx);
vm.runInContext(fs.readFileSync(require.resolve('../results/dashboard/structure-evidence-panel.js'),'utf8'),ctx);
for(const fn of listeners.DOMContentLoaded)fn();
assert.equal(elements.get('structureEvidencePanel').hidden,false);
assert.match(elements.get('structureEvidenceState').textContent,/미반영/);
assert.equal(elements.get('structureEvidenceChoice').children.length,2);
assert.equal(elements.get('structureEvidenceCards').children.length,1);
assert.match(elements.get('structureEvidenceCards').children[0].children[0].textContent,/더블탑 · 구조 무효/);
assert.equal(elements.get('structureEvidenceEvents').children.length,3);
elements.get('structureEvidenceEvents').children[1].onclick();
assert.ok(elements.get('structureEvidenceEvents').children.some(c=>/종가 94/.test(c.textContent)));
ctx.S.selectedAsOf='2026-01-26';ctx.StructureEvidencePanel.render();
assert.match(elements.get('structureEvidenceCards').children[0].children[0].textContent,/돌파 대기 · 당시 기준/);
assert.equal(elements.get('structureEvidenceEvents').children.length,1);
console.log('structure evidence panel fixtures: ok');
