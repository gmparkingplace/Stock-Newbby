'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const R=require('../results/dashboard/low-structure-rules'),E=require('../results/dashboard/low-entry-model'),{sample,day}=require('./low_entry_sample');
let count=0;const test=(name,fn)=>{try{fn();count++;}catch(e){e.message=name+': '+e.message;throw e;}};
const run=(bars,i=bars.length-1,extra={})=>R.analyze({symbol:'TEST',timeframe:'D',candles:bars,observedThrough:bars[i].time,confirmedThrough:bars[i].time,...extra});
const closed={judgmentReady:true,judgmentMode:'closed-confirmed',message:'확정봉'};
const entry=(analysis,selected=['R','H'],extra={})=>E.evaluate({analysis,selected,timing:closed,...extra});
test('H higher low is confirmed at right-hand bar, not occurrence',()=>{
 const b=sample('H');assert.equal(run(b,24).current.H,null);assert.equal(run(b,25).current.H,null);
 const a=run(b,26),h=a.current.H;assert.equal(h.phase,'ready');assert.equal(h.testTime,day(24));assert.equal(h.knownAt,day(26));
 assert.equal(h.signalAt,day(26));assert(h.triggerLevel>104);assert(h.invalidationLevel<97);assert.equal(entry(a,['H']).code,'candidate');
});
test('R follows breach, reclaim, test and ready with no same-bar test',()=>{
 const b=sample('R');assert.equal(run(b,24).current.R.phase,'reclaimed');assert.equal(run(b,28).current.R.phase,'reclaimed');
 const a=run(b,30),r=a.current.R;assert.equal(r.phase,'ready');assert.equal(r.testTime,day(28));assert.equal(r.testKnownAt,day(30));
 assert.equal(r.signalAt,day(30));assert.deepEqual(a.events.filter(e=>e.family==='R').map(e=>e.phase),['breached','reclaimed','tested','ready']);
 assert.equal(new Set(a.events.map(e=>e.id)).size,a.events.length);
});
test('independent H survives R failure in OR',()=>{
 const a=run(sample('R'),30);a.current.R={...a.current.R,phase:'invalidated',reason:'회복 실패'};
 const e=entry(a);assert.equal(e.code,'candidate');assert.equal(e.structureId,a.current.H.id);
 const fail=entry({...a,current:{R:a.current.R,H:null}});assert.equal(fail.code,'avoid','empty H wait hid failed R');
});
test('representative is latest confirmed, H wins exact tie; no merged prices',()=>{
 const a=run(sample('R'),30),e=entry(a);assert.equal(e.structureId,a.current.H.id);assert.equal(e.chaseLimit,a.current.H.chaseLimit);
 assert.equal(e.rows.length,2);assert.equal(e.setupDecision.code,'candidate');
});
test('fixed reference, ATR, levels and signal age through three subsequent bars',()=>{
 for(const [family,index] of [['H',26],['R',30]]){
  const b=sample(family),first=run(b,index).current[family];
  for(let j=0;j<=3;j++){const a=run(b,index+j),s=a.current[family];for(const k of ['id','signalAt','atrAnchor','referencePrice','triggerLevel','invalidationLevel','chaseLimit'])assert.equal(s[k],first[k]);assert.equal(entry(a,[family]).signalAge,j);assert.equal(entry(a,[family]).code,'candidate');}
  assert.equal(run(b,index+4).current[family].phase,'expired');assert.equal(entry(run(b,index+4),[family]).code,'wait');
 }
});
test('H stop penetration invalidates even with recovered close; cannot revive',()=>{
 const b=sample('H'),stop=run(b,26).current.H.invalidationLevel;b[27].low=stop-1e-8;
 const a=run(b,27);assert.equal(a.current.H.phase,'invalidated');assert.equal(entry(a,['H']).code,'avoid');
 assert.equal(run(b,28).current.H.phase,'invalidated');
 b[27].low=stop;assert.equal(run(b,27).current.H.phase,'ready','strict boundary should pass');
});
test('price crossing chase cap blocks, exact boundary is accepted',()=>{
 const b=sample('H'),cap=run(b,26).current.H.chaseLimit;
 b[27].high=cap+1;b[27].close=cap+1e-8;
 assert.equal(entry(run(b,27),['H']).code,'chase');b[27].close=cap;assert.equal(entry(run(b,27),['H']).code,'candidate');
 assert.equal(run(b,27).current.H.chaseLimit,cap);
});
test('same event cannot resume after close loses trigger',()=>{
 const b=sample('H');b[27].close=104;b[27].open=104;b[27].low=103;
 assert.equal(run(b,27).current.H.phase,'invalidated');assert.equal(run(b,28).current.H.phase,'invalidated');
});
test('unrecovered breach expires and a late rebound does not revive',()=>{
 const b=sample('R');for(const i of [24,25,26]){b[i].close=94;b[i].open=94;b[i].low=Math.min(b[i].low,94);}
 assert.equal(run(b,24).current.R.phase,'breached');assert.equal(run(b,26).current.R.phase,'breached');
 assert.equal(run(b,27).current.R.phase,'expired');assert.equal(entry(run(b,27),['R']).code,'wait');
});
test('deep plunge is excluded, no instantaneous bottom buying',()=>{
 const b=sample('R');b[24].low=88;
 const a=run(b,24);assert.equal(a.current.R.phase,'invalidated');assert.match(a.current.R.reason,/깊은/);assert.equal(entry(a,['R']).code,'avoid');
});
test('retest cannot break spring low, including confirmation period',()=>{
 const b=sample('R');b[27].low=93;
 assert.equal(run(b,27).current.R.phase,'invalidated');assert.equal(run(b,30).current.R.phase,'invalidated');
});
test('higher low without prior high break remains waiting then expires',()=>{
 const b=sample('H');for(let i=26;i<=31;i++){b[i].open=102;b[i].close=102;b[i].high=103;b[i].low=99;}
 assert.equal(run(b,26).current.H.phase,'rising');assert.equal(entry(run(b,26),['H']).code,'wait');
 assert.equal(run(b,30).current.H.phase,'rising');assert.equal(run(b,31).current.H.phase,'expired');
});
test('preconfirmation price jump is not backdated or counted after pullback',()=>{
 const b=sample('H');b[25].high=107;b[25].close=106;b[26].close=102;b[26].open=102;b[26].high=103;
 assert.equal(run(b,25).current.H,null);assert.equal(run(b,26).current.H.phase,'rising');assert.equal(run(b,26).current.H.signalAt,null);
});
test('same/lower low and rolling-low drop-off are not higher-low signals',()=>{
 for(const low of [95,94]){const b=sample('H');b[24].low=low;assert.equal(run(b,26).current.H,null);}
 const b=sample('H');for(let i=19;i<b.length;i++){b[i].low=98;b[i].high=102;b[i].close=100;b[i].open=100;}
 assert.equal(run(b,35).current.H,null);
});
test('retest and breakout deadlines have distinct failure reasons',()=>{
 const b=sample('R');for(let i=25;i<=35;i++){b[i].low=98;b[i].high=102;b[i].open=100;b[i].close=100;}
 assert.equal(run(b,33).current.R.phase,'expired');assert.match(run(b,33).current.R.reason,/재시험/);
});
test('freshness, confirmation and historical color gates preserve setup decision',()=>{
 const a=run(sample('H'),26);
 assert.equal(entry(a,['H'],{timing:{judgmentReady:false,message:'조회 실패'}}).code,'blocked');
 assert.equal(entry(a,['H'],{provisional:true}).label,'봉 확정 대기');
 const past=entry(a,['H'],{historical:true,timing:{judgmentReady:false}});assert.equal(past.code,'historical');assert.equal(past.setupDecision.code,'candidate');
 assert.match(past.reason,/현재 진입 안내가 아니/);assert.equal(entry(a,[]).code,'blocked');
});
test('support is known before breach; current/future low is not retroactive support',()=>{
 const b=sample('R');const a=run(b,30),r=a.current.R;
 assert(r.supportKnownAt<r.breachTime);assert.equal(r.supportPrice,95);assert.equal(r.springTime,day(24));
});
test('price/volume evidence is causal, relative volume excludes current, missing stays unknown',()=>{
 const b=sample('R');b[30].volume=200;const a=run(b,30),s=a.current.R;
 const mean=b.slice(10,30).reduce((v,b)=>v+b.volume,0)/20;
 assert(Math.abs(s.evidence.find(e=>e.id==='relative-volume').observed-200/mean)<1e-12);
 assert(s.evidence.every(e=>e.basisTime===day(30)&&e.knownAt===day(30)));
 b[28].volume=null;const m=run(b,30).current.R.evidence;
 assert.equal(m.find(e=>e.id==='test-volume').result,'unknown');assert.equal(m.find(e=>e.id==='obv-change').result,'unknown');
 assert.equal(entry(run(b,30),['R']).code,'candidate');
});
test('zero-range and zero-reference-volume remain unknown, not fake evidence',()=>{
 const b=sample('H');for(let i=0;i<26;i++)b[i].volume=0;b[26].low=b[26].high=b[26].open=b[26].close=105;
 const e=run(b,26).current.H.evidence;assert.equal(e.find(e=>e.id==='close-position').result,'unknown');assert.equal(e.find(e=>e.id==='relative-volume').result,'unknown');
});
test('gap terminates structure, no continuity across missing price',()=>{
 const b=sample('H');b[27].close=null;assert.equal(run(b,27).status,'insufficient-data');
 assert.equal(run(b,27).current.H.phase,'invalidated');assert.equal(entry(run(b,27),['H']).code,'blocked');
});
test('all prefixes, full frame replay and mutated future agree; no source mutation',()=>{
 for(const family of ['R','H']){
  const b=sample(family),original=JSON.stringify(b);
  for(let i=0;i<b.length;i++)assert.deepEqual(run(b,i),run(b.slice(0,i+1)));
  const a=run(b,30),future=structuredClone(b);future[40].close=NaN;future[40].time='invalid';
  assert.deepEqual(run(future,30),a);assert.equal(JSON.stringify(b),original);
 }
});
test('UTC H4 and daily paths have matching states but independent identities',()=>{
 const b=sample('R'),base=Date.UTC(2026,0,1)/1000,h4=b.map((b,i)=>({...b,time:base+i*14400}));
 const a=run(b,30),h=run(h4,30,{symbol:'BTC-USD',timeframe:'H4'});
 for(const k of ['R','H']){assert.equal(h.current[k].phase,a.current[k].phase);assert.equal(h.current[k].signalIndex,a.current[k].signalIndex);assert.notEqual(h.current[k].id,a.current[k].id);}
 assert.equal(h.current.R.testKnownAt,base+30*14400);
});
test('parameter changes version event identity; repeat calls do not duplicate',()=>{
 const b=sample('H'),a=run(b,26),other=run(b,26,{params:{maxAtr:1}});
 assert.notEqual(a.current.H.id,other.current.H.id);assert.deepEqual(run(b,26),a);
 assert.equal(run(b,26,{params:{minSeparation:31,maxSeparation:30}}).status,'invalid-data');
 assert.equal(run(b,26,{params:{constructor:1}}).status,'invalid-data');assert.equal(run(b,26,{version:'future'}).status,'invalid-data');
});
test('new higher-low structure supersedes without mutating historical event',()=>{
 const b=sample('H');b[31].low=101;b[31].close=104;b[31].open=104;
 const old=run(b,26).current.H.id,a=run(b,33);assert.notEqual(a.current.H.id,old);
 assert.equal(a.structures.find(s=>s.id===old).signalAt,day(26));assert.equal(run(b,26).current.H.id,old);
});
test('same-bar higher low replaces old waiting setup before issuing a signal',()=>{
 const b=sample('H');b[25].low=100;for(const [i,low,high,close] of [[26,100,103,102],[27,99,103,101],[28,100,106,102],[29,100,108,107]])b[i]={...b[i],open:close,low,high,close};
 const old=run(b,26).current.H.id,a=run(b,29),prior=a.structures.find(s=>s.id===old);
 assert.equal(prior.phase,'superseded');assert.equal(prior.signalAt,null);
 assert.equal(a.current.H.signalAt,day(29));assert.equal(a.events.filter(e=>e.time===day(29)&&e.phase==='ready').length,1);
});
test('browser and Node structural/entry engines agree',()=>{
 const c={};c.self=c;vm.createContext(c);
 for(const f of ['low-structure-model','low-structure-rules','low-entry-model'])vm.runInContext(fs.readFileSync(require.resolve('../results/dashboard/'+f),'utf8'),c);
 const b=sample('R'),input={symbol:'TEST',timeframe:'D',candles:b,observedThrough:day(30),confirmedThrough:day(30)};
 const a=c.LowStructureRules.analyze(input);assert.deepEqual(JSON.parse(JSON.stringify(a)),R.analyze(input));
 assert.deepEqual(JSON.parse(JSON.stringify(c.LowEntryModel.evaluate({analysis:a,timing:closed}))),entry(run(b,30)));
});
test('failure explanation preserves the real stop event and fixed prices',()=>{
 const b=sample('H'),first=run(b,26).current.H;b[27].low=first.invalidationLevel-1e-8;
 const a=run(b,27),before=JSON.stringify(a),e=entry(a,['H']);
 assert.equal(a.current.H.reason,'고정 무효선 이탈');assert.equal(e.code,'avoid');assert.equal(e.label,'지지선 이탈 · 매수 대기');
 assert.match(e.reason,/확정봉의 저가.*지지 하한선.*새 저점과 반등/);assert.equal(e.structureId,first.id);assert.equal(e.chaseLimit,first.chaseLimit);
 assert.equal(e.rows[0].label,'지지 하한선 아래로 하락');assert.equal(JSON.stringify(a),before);
 const past=entry(a,['H'],{historical:true});assert.equal(past.code,'historical');assert.equal(past.setupDecision.code,'avoid');assert.equal(past.setupDecision.label,e.label);
});
test('expired review has a next step rather than repeated engine vocabulary',()=>{
 const a=run(sample('R'),34),e=entry(a,['R']);assert.equal(a.current.R.reason,'신호 후 검토 기한 초과');
 assert.equal(e.code,'wait');assert.equal(e.label,'새 매수 신호를 기다리세요');assert.match(e.reason,/발생봉과 이후 3봉/);
 assert.equal(e.rows[0].label,'이전 매수 신호 확인 기간 종료');assert(!e.reason.includes('조건 만료'));
});
test('expiry stages explain separate deadlines using the actual parameters',()=>{
 const p={...R.defaults,reclaimBars:4,retestBars:9,triggerBars:6,reviewBars:2};
 for(const [reason,count] of [['회복 기한 초과',4],['재시험 확인 기한 초과',9],['반등 돌파 대기 기한 초과',6],['신호 후 검토 기한 초과',2]]){
  const description=E.describe({phase:'expired',reason},p);assert.equal(description.label,'새 매수 신호를 기다리세요');assert(description.reason.includes(count+'봉'));
 }
 assert.equal(new Set(['회복 기한 초과','재시험 확인 기한 초과','반등 돌파 대기 기한 초과','신호 후 검토 기한 초과'].map(reason=>E.describe({phase:'expired',reason},p).rowLabel)).size,4);
});
console.log(`Low entry P1: ${count} cases passed (R/H states, fixed risk, evidence, time gates, OR and future isolation)`);
