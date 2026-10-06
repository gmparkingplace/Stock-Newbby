'use strict';
const assert=require('node:assert/strict');
const M=require('../results/dashboard/technical-indicators');
const {build:price}=require('../results/dashboard/price-indicators');
const {build:aux}=require('../results/dashboard/indicator-panel');
const near=(a,b)=>assert(Math.abs(a-b)<1e-9,`${a} != ${b}`);
const closes=Array.from({length:80},(_,i)=>100+(i%7)*1.5+i*.3);
const frame={confirmed:false,candles:closes.map((close,i)=>({time:1000+i,close,open:close,volume:10})),lines:{}};
const original=JSON.stringify(frame),data=M.calculate(frame);
// Golden values calculated independently using Python Decimal (50-digit precision).
for(const [i,e20,e60,macd,signal,histogram] of [
 [25,108.81353409844663,null,2.198081766404882,null,null],
 [33,111.63367487639194,null,2.3969394061108545,2.2375114823922474,.159427923718607],
 [40,113.78448663947225,null,2.3613233707316004,2.1702738254203693,.1910495453112311],
 [79,125.03788426845917,119.22187942106698,1.817523841287085,2.066632088938937,-.24910824765185188],
])for(const [key,expected] of Object.entries({ema20:e20,ema60:e60,macd,signal,histogram}))expected==null?assert.equal(data[key][i],null):near(data[key][i],expected);
assert(data.ema20.slice(0,19).every(v=>v==null));assert(data.ema60.slice(0,59).every(v=>v==null));
assert(data.macd.slice(0,25).every(v=>v==null));assert(data.signal.slice(0,33).every(v=>v==null));
const band=M.bollinger(Array.from({length:20},(_,i)=>i+1)).at(-1);
near(band.middle,10.5);near(band.upper,10.5+2*Math.sqrt(33.25));near(band.lower,10.5-2*Math.sqrt(33.25));
assert.deepEqual(M.ema([1,2,null,4,5,6],3),[null,null,null,null,null,5]);
assert.equal(M.bollinger([1,2,3,NaN,5],3).at(-1),null);
assert.equal(M.bollinger([1,2,NaN,4,5,6],3).at(-1).middle,5);
assert(M.ema(Array(60).fill(0),20).slice(19).every(v=>v===0));
assert.equal(M.bollinger(Array(20).fill(0)).at(-1).upper,0);
assert.throws(()=>M.ema([],0));assert.throws(()=>M.bollinger([],2,-1));
assert.equal(JSON.stringify(frame),original,'calculation modified OHLCV or original strategy data');
assert.equal(M.calculate(frame),data,'unchanged closes should reuse calculations');
const altered=structuredClone(frame);altered.candles[79].close+=30;
assert.notEqual(M.calculate(altered).ema20[79],data.ema20[79]);
const old=M.calculate(altered);altered.candles[79].close+=30;
assert.notEqual(M.calculate(altered),old,'in-place source correction reused old values');
for(const kind of ['ema','bollinger']){
 const current=price(frame,kind,79);assert.equal(current.status,kind==='ema'?'partial-data':'ready');assert(current.provisional);
 const past=price(frame,kind,40),changed=structuredClone(frame);
 for(const bar of changed.candles.slice(41))bar.close=9999;
 assert.deepEqual(price(changed,kind,40),past,'future close leaked into historical overlay');
 assert(past.series.every(s=>s.slice(41).every(p=>Object.keys(p).length===1)));
}
const partial=price(frame,'ema',30);assert.equal(partial.status,'partial-data');assert.equal(partial.values[1],null);
assert.equal(price(frame,'bollinger',18).status,'insufficient-data');assert.equal(price(frame,'bollinger',19).status,'ready');
const macd=aux(frame,'macd',79);near(macd.histogramValue,-.24910824765185188);assert.equal(macd.status,'ready');
assert.equal(aux(frame,'macd',32).status,'insufficient-data');assert.equal(aux(frame,'macd',33).status,'ready');
const past=aux(frame,'macd',40);assert.deepEqual(aux(altered,'macd',40),past);
for(const field of ['series','signalSeries','histogramSeries'])assert(past[field].slice(41).every(p=>Object.keys(p).length===1));
assert.equal(macd.histogramSeries[79].color,'rgba(24,89,201,.65)');
// Prefix invariance includes warm-up and every timeframe's actual bar count.
for(let n=1;n<=80;n++){
 const part={...frame,candles:frame.candles.slice(0,n)},computed=M.calculate(part);
 for(const key of ['ema20','ema60','bollinger','macd','signal','histogram'])assert.deepEqual(computed[key],data[key].slice(0,n));
}
assert.equal(price(frame,'none',79).status,'hidden');
console.log('EMA/MACD Decimal golden, population bands, warm-up/gap, cache correction and historical isolation passed');
