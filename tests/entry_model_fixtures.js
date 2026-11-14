const assert=require('assert'),{evaluate}=require('../results/dashboard/entry-model');
const {assess}=require('../results/dashboard/chart-timing');
const now=Date.now(),live=assess({now,source:'toss',fetchedAt:new Date(now).toISOString(),marketSession:{state:'open'},snapshotEligible:true,enabled:true,barAsOf:null});
const closed=assess({now,source:'toss',fetchedAt:new Date(now).toISOString(),marketSession:{state:'closed'},confirmed:true});
const frame={candles:[{time:'2026-09-01',close:100},{time:'2026-09-02',close:102},{time:'2026-09-03',close:108}],state:[{sigA:'entry',sigB:'none',sigC:'entry',sigF:'entry',atr14:10},{sigA:'none',sigB:'entry',sigC:'entry',sigF:'none',atr14:10},{sigA:'none',sigB:'none',sigC:'entry',sigF:'entry',atr14:10}],marks:{}};
const run=x=>evaluate({frame,index:0,timing:closed,...x});
assert.equal(run({}).code,'candidate');
assert.equal(run({timing:live}).label,'봉 확정 대기');
assert.equal(run({timing:{judgmentReady:false,message:'조회 실패'}}).code,'blocked');
assert.equal(run({index:2,selected:['C']}).code,'chase');
assert.equal(run({index:1,selected:['A','B'],mode:'all'}).matched,false);
assert.equal(run({index:1,selected:['A','B'],mode:'any'}).matched,true);
assert.equal(run({selected:[]}).code,'blocked');
assert.equal(run({historical:true}).code,'historical');
assert(run({selected:['C','F']}).combinationNote);
const baseline=JSON.stringify(run({historical:true}));frame.state[2].sigF='exit';frame.candles[2].close=900;
assert.equal(JSON.stringify(run({historical:true})),baseline,'Future bars must not change historical judgment');
assert.equal(run({index:2}).setupDecision.code,'avoid');
const missing={candles:frame.candles,state:[{sigF:'entry',atr14:null}]};assert.equal(run({frame:missing}).code,'blocked');
assert.equal(live.realtimeReady,false);
for(const selected of [['A'],['C'],['F']])assert.equal(run({selected,timing:live}).label,'봉 확정 대기');
assert.equal(run({selected:['B'],index:1,timing:live}).label,'봉 확정 대기');
assert.equal(run({selected:['B'],timing:live}).code,'wait');
assert.equal(run({index:2,timing:live}).code,'avoid');
// Source exit explanations are additive: selected source bits alone decide which rules are explained.
function exitFrame(){
 const candles=[{time:'2026-11-13',close:100},{time:'2026-11-14',close:89},{time:'2026-11-15',close:999}];
 return {candles,state:[{sigA:'none',sigB:'none',sigC:'none',sigF:'none',rsi14:70,don_lo:90},
  {sigA:'exit',sigB:'exit',sigC:'exit',sigF:'exit',rsi14:69.99,don_lo:90},
  {sigA:'entry',sigB:'entry',sigC:'entry',sigF:'entry',rsi14:99,don_lo:999}],
  lines:{sma20:[{time:candles[0].time,value:100},{time:candles[1].time,value:99.9999}],
   sma60:[{time:candles[0].time,value:100},{time:candles[1].time,value:100}]},marks:{}};
}
const explain=(f,selected=['F'],extra={})=>evaluate({frame:f,index:1,selected,timing:closed,...extra});
for(const [id,condition] of [['A','sma-cross-down'],['B','rsi-cross-down-70'],['C','prior-10-low']]){
 const f=exitFrame(),before=JSON.stringify(f),e=explain(f,[id]);
 assert.equal(e.code,'avoid');assert.equal(e.setupDecision.code,'avoid');assert.equal(e.exitEvidence.length,1);
 const item=e.exitEvidence[0];assert.equal(item.strategy,id);assert.equal(item.id,condition);assert.equal(item.status,'met');assert.equal(item.met,true);
 assert.equal(item.basis,'2026-11-14');assert.equal(item.previousBasis,id==='C'?null:'2026-11-13');
 assert.match(e.reason,new RegExp(id+' 전략'));assert(!e.reason.includes('선택한 전략 중'));assert.equal(JSON.stringify(f),before);
}
const f=exitFrame();
assert.deepEqual(explain(f,['F']).exitEvidence.map(e=>e.id),['prior-10-low','sma-cross-down']);
f.lines.sma20[0].value=99;
const lowOnly=explain(f,['F']);assert.deepEqual(lowOnly.exitEvidence.map(e=>e.id),['prior-10-low']);
assert(!lowOnly.reason.includes('거래량'));assert(!lowOnly.reason.includes('교차'));
f.candles[1].close=90;f.lines.sma20[0].value=100;
assert.deepEqual(explain(f,['F']).exitEvidence.map(e=>e.id),['sma-cross-down']);
for(const [id,change] of [['A',x=>x.lines.sma20[1].value=100],['B',x=>x.state[1].rsi14=70],['C',x=>x.candles[1].close=90],['F',x=>{x.candles[1].close=90;x.lines.sma20[0].value=99;}]]){
 const rounded=exitFrame();change(rounded);const e=explain(rounded,[id]);
 assert.equal(e.code,'avoid','rounded evidence must never override source exit');assert.equal(e.exitEvidence[0].id,'raw-exit');
 assert.equal(e.exitEvidence[0].status,'unverified');assert.equal(e.exitEvidence[0].observed,null);assert.equal(e.exitEvidence[0].reference,null);
 assert.match(e.reason,/원천 이탈 신호.*세부 수치 근거/);
}
for(const id of ['A','B','C','F']){
 const x=exitFrame();x.state[1]['sig'+id]='none';
 assert.deepEqual(explain(x,[id]).exitEvidence,[],'a numeric rule alone must not create an exit');
 const legacy={candles:x.candles,marks:{[id]:[{time:x.candles[1].time,side:'exit'}]}};
 const e=explain(legacy,[id]);assert.equal(e.code,'avoid');assert.equal(e.exitEvidence[0].status,'unavailable');
 assert.equal(e.exitEvidence[0].strategy,id);assert.equal(e.exitEvidence[0].observed,null);
}
const historicalFrame=exitFrame(),past=explain(historicalFrame,['F'],{historical:true});
historicalFrame.candles[2].close=-1;historicalFrame.state[2].sigF='exit';historicalFrame.lines.sma20.push({time:'2026-11-15',value:-999});
assert.deepEqual(explain(historicalFrame,['F'],{historical:true}),past);
assert.equal(past.code,'historical');assert.equal(past.setupDecision.code,'avoid');assert.match(past.reason,/현재 진입 안내가 아니/);
const blockedExit=explain(exitFrame(),['C'],{timing:{judgmentReady:false,message:'자료 지연'}});
assert.equal(blockedExit.code,'blocked');assert.equal(blockedExit.reason,'자료 지연');assert.equal(blockedExit.setupDecision.code,'avoid');
assert.equal(blockedExit.exitEvidence[0].id,'prior-10-low');
console.log('Entry decisions and selected source exit evidence regression assertions passed');
