'use strict';
const assert=require('node:assert/strict');
const M=require('../results/dashboard/technical-indicators'),P=require('../results/dashboard/price-indicators');
const near=(a,b)=>assert(Math.abs(a-b)<1e-8,`${a} != ${b}`),periods=[20,60,120,200];
assert.deepEqual(M.sma([1,2,null,4,5,6],3),[null,null,null,null,null,5]);assert.throws(()=>M.sma([],0));
const frame={candles:Array.from({length:260},(_,i)=>({time:1700000000+i*14400,close:i+1,high:i+2,low:i,volume:i+1})),lines:{},state:[{sigA:'entry'}]};
for(const n of [20,60])frame.lines['sma'+n]=frame.candles.slice(n-1).map(b=>({time:b.time,value:b.close-(n-1)/2}));
const untouched=JSON.stringify(frame),computed=M.calculate(frame);
for(const n of periods){
 assert(computed['sma'+n].slice(0,n-1).every(v=>v===null));assert(computed['ema'+n].slice(0,n-1).every(v=>v===null));assert(computed['wma'+n].slice(0,n-1).every(v=>v===null));
 near(computed['sma'+n][199],200-(n-1)/2);near(computed['ema'+n][199],200-(n-1)/2);near(computed['wma'+n][199],200-(n-1)/3);
 for(const length of [19,20,59,60,119,120,199,200,260]){
  const part=M.calculate({...frame,candles:frame.candles.slice(0,length)});
  for(const kind of ['sma','ema','wma'])assert.deepEqual(part[kind+n],computed[kind+n].slice(0,length),'lookahead in warmup');
 }
}
for(const kind of ['sma','ema','wma']){
 const full=P.build(frame,kind,199);assert.equal(full.status,'ready');assert.equal(full.values.length,4);assert.deepEqual(full.parameters.periods,periods);assert.equal(full.periodBars,200);
 for(const index of [19,59,119,198])assert.equal(P.build(frame,kind,index).status,'partial-data');
 const past=P.build(frame,kind,130),future=structuredClone(frame);future.candles.slice(131).forEach(b=>{b.close=9999;});
 assert.deepEqual(P.build(future,kind,130),past);assert(past.series.every(s=>s.slice(131).every(p=>!('value' in p))));
 const gap=structuredClone(frame);gap.candles[100].close=null;
 const data=M.calculate(gap);assert.equal(data[kind+'120'][219],null);assert(Number.isFinite(data[kind+'120'][220]));assert.equal(data[kind+'200'][259],null);
}
const source=structuredClone(frame);source.lines.sma20.find(p=>p.time===source.candles[199].time).value=777;source.lines.sma60.find(p=>p.time===source.candles[199].time).value=888;
assert.deepEqual(P.build(source,'sma',199).values,[777,888,140.5,100.5],'replaced original strategy averages');
const noSource=structuredClone(frame);noSource.lines={};assert.equal(P.build(noSource,'sma',59).status,'insufficient-data');assert.equal(P.build(noSource,'sma',199).status,'partial-data');
assert.deepEqual(P.build(noSource,'sma',199).values,[null,null,140.5,100.5]);
for(const kind of ['bollinger','donchian'])assert.equal(P.build(frame,kind,199).values.length,3);
assert.equal(JSON.stringify(frame),untouched);assert.equal(M.version,'technical-v3');
console.log('Four MAs: independent 20/60/120/200 values, warmup, gaps, source SMA preservation, historical isolation and immutable raw data passed');
