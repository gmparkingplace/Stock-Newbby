'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const M=require('../results/dashboard/low-structure-model');
let count=0;
function test(name,fn){try{fn();count++;}catch(error){error.message=name+': '+error.message;throw error;}}
const day=i=>new Date(Date.UTC(2026,0,1+i)).toISOString().slice(0,10);
const bars=closes=>closes.map((close,i)=>({time:day(i),open:close-.5,high:close+1,low:close-1,close,volume:100+i}));
const lowBars=lows=>lows.map((low,i)=>({time:day(i),open:low+1,high:low+3,low,close:low+2,volume:100}));
const run=(candles,extra={})=>M.analyze({symbol:'TEST',timeframe:'D',candles,
  observedThrough:Object.hasOwn(extra,'observedThrough')?extra.observedThrough:candles.at(-1)?.time??null,
  confirmedThrough:Object.hasOwn(extra,'confirmedThrough')?extra.confirmedThrough:candles.at(-1)?.time??null,...extra});
const constant=bars(Array(50).fill(100));
const near=(actual,expected)=>assert(Math.abs(actual-expected)<=1e-12*Math.max(1,Math.abs(expected)),`${actual} != ${expected}`);
function freeze(x){if(x&&typeof x==='object'){Object.values(x).forEach(freeze);Object.freeze(x);}return x;}

test('independent Wilder Decimal golden, not rounded source ATR',()=>{
 const prices=[100,102,101,106,104,105,110,108,111,113,109,114,112,118,117,120,116,121,119,125];
 // 50-place Decimal reference from explicit TRs: 2,3,2,6,3,2,6,3,4,3,5,6,3,7,2,4,5,6,3,7.
 const golden=['3.9285714285714285714285714285714285714285714285714','3.7908163265306122448979591836734693877551020408163',
  '3.8057580174927113702623906705539358600583090379009','3.8910610162432319866722199083715118700541441066223',
  '4.0416995150830011304813470577735467364788480990064','3.9672924068627867640183936965040076838732160919345',
  '4.1839143778011591380170798610394357064537006567963'];
 const out=run(bars(prices));assert.equal(out.status,'ready');
 assert(out.series.slice(0,13).every(b=>b.atr===null));
 golden.forEach((v,i)=>near(out.series[i+13].atr,Number(v)));
 assert.equal(out.series[0].tr,2);assert.equal(out.series[3].tr,6);assert.equal(out.basis,day(19));
 assert.equal('decision' in out,false);assert.deepEqual(out.structures,[]);
});
test('manual low/high positions with two-bar confirmation',()=>{
 const f=lowBars([12,11,9,10,12,13,12,10,11,13]);
 const out=run(f);
 assert.deepEqual(out.pivots.map(p=>[p.kind,p.index,p.knownIndex,p.price]),[['low',2,4,9],['high',5,7,16],['low',7,9,10]]);
 for(const p of out.pivots){assert.equal(p.occurredAt,day(p.index));assert.equal(p.knownAt,day(p.index+2));}
 assert.equal(out.status,'insufficient-data','raw pivots must not imply entry readiness');
});
test('observed right bar is insufficient until confirmed',()=>{
 const f=lowBars([12,11,9,10,12]);
 assert.equal(run(f,{confirmedThrough:day(3)}).pivots.length,0);
 assert.equal(run(f).pivots.length,1);
 assert.equal(run(f,{observedThrough:day(3),confirmedThrough:day(3)}).pivots.length,0);
 assert.equal(run(f,{confirmedThrough:null}).status,'unconfirmed');
 assert.equal(run(f,{confirmedThrough:null}).pivots.length,0);
});
test('equal-low and equal-high plateaus confirm last extremum',()=>{
 const lows=run(lowBars([13,12,10,10,11,12,13])).pivots.filter(p=>p.kind==='low');
 assert.deepEqual(lows.map(p=>p.index),[3]);assert.equal(lows[0].knownIndex,5);
 const f=[10,12,15,15,14,13,10].map((high,i)=>({time:day(i),open:high-1,close:high-1,high,low:1,volume:10}));
 assert.deepEqual(run(f).pivots.filter(p=>p.kind==='high').map(p=>p.index),[3]);
});
test('flat prices have no extrema and zero ATR cannot normalize risk',()=>{
 const flat=constant.map(b=>({...b,open:100,high:100,low:100,close:100}));
 const out=run(flat);assert.equal(out.status,'insufficient-data');assert.equal(out.reason,'atr-zero');
 assert.deepEqual(out.pivots,[]);assert.equal(out.series[13].atr,0);
});
test('ATR remains local, fractional full precision and scale invariant',()=>{
 const f=bars(Array.from({length:32},(_,i)=>100+i+(i%3)/7));
 const scaled=f.map(b=>({...b,...Object.fromEntries(['open','high','low','close'].map(k=>[k,b[k]/10000]))}));
 const a=run(f),b=run(scaled);a.series.slice(13).forEach((p,i)=>near(p.atr/10000,b.series[i+13].atr));
 assert.deepEqual(a.pivots.map(p=>[p.kind,p.index,p.knownIndex]),b.pivots.map(p=>[p.kind,p.index,p.knownIndex]));
});
test('ATR anchor excludes pivot and right-hand confirmation prices',()=>{
 const f=lowBars(Array.from({length:22},()=>10));f[16]=lowBars([5])[0];f[16].time=day(16);
 const out=run(f),p=out.pivots.find(p=>p.kind==='low'&&p.index===16);
 assert(p);assert.equal(p.atrBefore,out.series[15].atr);assert.notEqual(p.atrBefore,out.series[16].atr);
});
test('all historical prefixes match replay and future data is never read',()=>{
 const f=lowBars(Array.from({length:60},(_,i)=>20+Math.sin(i/2)*3));
 for(let i=0;i<f.length;i++){
  const opts={observedThrough:day(i),confirmedThrough:day(i)};
  const out=run(f,opts),part=run(f.slice(0,i+1),opts);
  assert.deepEqual(out,part);assert.equal(out.series.length,i+1);
  assert(out.pivots.every(p=>p.knownIndex<=i));
  const future=f.slice(0,i+1);future.push(new Proxy({}, {get(){throw new Error('future read');}}));
  assert.deepEqual(run(future,opts),out);
 }
 const changed=structuredClone(f);changed[50]={time:'invalid',close:NaN,volume:-1};
 assert.deepEqual(run(changed,{observedThrough:day(40),confirmedThrough:day(40),fetchedAt:'future',lastConfirmedTime:day(59)}),run(f,{observedThrough:day(40),confirmedThrough:day(40)}));
});
test('confirmation masks ATR and cannot confirm right bars prematurely',()=>{
 const out=run(constant,{confirmedThrough:day(20)});
 assert(out.series.slice(21).every(b=>b.atr===null&&b.tr===null&&!b.confirmed));
 assert(out.series.slice(21).every(b=>b.previewAtr===2));assert.equal(out.basis,day(20));
});
test('price gap resets Wilder warm-up and first TR skips missing previous close',()=>{
 const f=structuredClone(constant);f[20].close=null;for(let i=21;i<f.length;i++)for(const k of ['open','high','low','close'])f[i][k]+=100;
 const out=run(f);assert.equal(out.series[20].segment,null);assert.equal(out.series[20].atr,null);
 assert.equal(out.series[21].tr,2);assert.equal(out.series[21].segment,1);
 assert(out.series.slice(21,34).every(b=>b.atr===null));assert.equal(out.series[34].atr,2);
 assert.equal(run(f,{observedThrough:day(20),confirmedThrough:day(20)}).reason,'price-gap');
});
test('missing price prevents pivot windows connecting across segments',()=>{
 const f=lowBars([12,11,9,10,12,13,12,10,11,13]);f[3].open=null;
 const out=run(f);assert(!out.pivots.some(p=>p.index===2||p.index===5));assert(out.pivots.some(p=>p.index===7));
});
test('missing volume is unknown; zero remains zero and price data stays usable',()=>{
 const f=structuredClone(constant);f[20].volume=0;f[21].volume=null;delete f[22].volume;
 const out=run(f);assert.equal(out.status,'ready');assert.equal(out.series[20].volumeStatus,'zero');
 assert.equal(out.series[21].volumeStatus,'missing');assert.equal(out.series[22].volumeStatus,'missing');
 assert.equal(out.dataWarnings.filter(w=>w.code==='volume-missing').length,2);assert.equal(out.series[22].segment,0);
});
test('H4 numeric UTC stamps and missing interval reset',()=>{
 const start=Date.UTC(2026,0,1)/1000;
 const f=constant.map((b,i)=>({...b,time:start+i*14400}));f.splice(20,1);
 const out=run(f,{symbol:'BTC-USD',timeframe:'H4'});
 assert.equal(out.series[20].segment,1);assert.equal(out.series[20].tr,2);
 assert(out.series.slice(20,33).every(b=>b.atr===null));assert.equal(out.series[33].atr,2);
 assert.equal(out.dataWarnings.filter(w=>w.code==='bar-gap').length,1);
 const g=lowBars([12,11,9,10,12]).map((b,i)=>({...b,time:start+i*14400}));
 assert.equal(run(g,{symbol:'ETH-USD',timeframe:'H4'}).pivots[0].knownAt,start+4*14400);
 g[4].time+=14400;assert.equal(run(g,{symbol:'ETH-USD',timeframe:'H4'}).pivots.length,0);
});
test('daily weekends and holidays are not missing-bar gaps',()=>{
 const f=constant.map((b,i)=>({...b,time:day(i*3)}));const out=run(f);
 assert.equal(out.status,'ready');assert(out.series.every(b=>b.segment===0));assert.deepEqual(out.dataWarnings,[]);
});
test('invalid OHLC is rejected, never repaired or treated as missing',()=>{
 for(const [field,value,code] of [['close',NaN,'invalid-price'],['low',0,'invalid-price'],['high',Infinity,'invalid-price'],['open','100','invalid-price'],['low',102,'invalid-ohlc-range'],['close',200,'invalid-ohlc-range']]){
  const f=structuredClone(constant);f[20][field]=value;const out=run(f);
  assert.equal(out.status,'invalid-data');assert.equal(out.error.code,code);assert.equal(out.error.index,20);assert.deepEqual(out.pivots,[]);
 }
 for(const v of [-1,NaN,Infinity,true,'10']){const f=structuredClone(constant);f[20].volume=v;assert.equal(run(f).error.code,'invalid-volume');}
});
test('invalid dates, ordering, duplicates and numeric H4 alignment rejected',()=>{
 for(const time of ['2026-02-29','2026-13-01','2026-01-01T00:00:00Z','0000-01-01',1700000000]){
  const f=structuredClone(constant);f[10].time=time;assert.equal(run(f).error.code,'invalid-bar-time');
 }
 for(const time of [day(9),day(8)]){const f=structuredClone(constant);f[10].time=time;assert.equal(run(f).error.code,'invalid-bar-order');}
 const start=Date.UTC(2026,0,1)/1000,f=constant.map((b,i)=>({...b,time:start+i*14400}));
 for(const time of [start+1,Infinity,0,String(start),start+.5]){const bad=structuredClone(f);bad[10].time=time;assert.equal(run(bad,{symbol:'BTC-USD',timeframe:'H4'}).error.code,'invalid-bar-time');}
});
test('cutoffs are explicit, existing and ordered',()=>{
 assert.equal(run(constant,{observedThrough:day(99)}).error.code,'observed-cutoff-not-found');
 assert.equal(run(constant,{observedThrough:day(20),confirmedThrough:day(21)}).error.code,'confirmation-after-observation');
 assert.equal(run(constant,{confirmedThrough:'2025-01-01'}).error.code,'confirmed-cutoff-not-found');
 assert.equal(run(constant,{confirmedThrough:undefined}).error.code,'invalid-confirmed-cutoff');
 assert.equal(M.analyze({symbol:'TEST',timeframe:'D',candles:constant}).error.code,'cutoff-required');
});
test('unsupported timeframe/symbol and empty input have distinct states',()=>{
 assert.equal(run(constant,{timeframe:'M'}).status,'unsupported');assert.equal(run(constant,{timeframe:'W'}).status,'unsupported');
 assert.equal(run(constant,{timeframe:'H4',symbol:'005930.KS'}).error.code,'invalid-observed-cutoff');
 assert.equal(run([],{}).status,'unavailable');assert.equal(run([],{}).reason,'no-candles');
 assert.equal(run([],{confirmedThrough:day(0)}).error.code,'invalid-cutoff');
 assert.equal(M.analyze(null).error.code,'invalid-input');assert.equal(run(constant,{symbol:''}).error.code,'invalid-symbol');
});
test('fixed ATR14 and configurable confirmation values cannot be silently changed',()=>{
 for(const params of [{atrPeriod:13},{rightBars:0},{leftBars:6},{rightBars:1.5},{constructor:2},{unknown:1},null,[]])assert.equal(run(constant,{params}).error.code,'invalid-parameters');
 const f=lowBars([12,11,9,10,12]);assert.equal(run(f,{params:{leftBars:1,rightBars:1}}).pivots[0].knownIndex,3);
 assert.equal(run(constant,{version:'future-version'}).error.code,'unsupported-version');
 assert(Object.isFrozen(M.defaults));
});
test('corrections recompute; same-object input and outputs are independent',()=>{
 const f=structuredClone(constant),original=structuredClone(f),before=run(f);
 assert.deepEqual(f,original);before.series[13].atr=999;before.parameters.rightBars=5;
 assert.equal(run(f).series[13].atr,2);assert.equal(run(f).parameters.rightBars,2);
 f[15].high=110;assert.notEqual(run(f).series[15].atr,2);
 f[10].volume=null;assert(run(f).dataWarnings.some(w=>w.index===10));
 assert.equal(run(f.slice(10)).series[3].atr,null,'different first bar must seed anew');
 const frozen=freeze(structuredClone(original));assert.doesNotThrow(()=>run(frozen));
});
test('browser UMD and Node use identical pure engine',()=>{
 const ctx={};ctx.self=ctx;vm.createContext(ctx);
 vm.runInContext(fs.readFileSync(require.resolve('../results/dashboard/low-structure-model'),'utf8'),ctx);
 assert.equal(ctx.LowStructureModel.version,M.version);
 const data=lowBars([12,11,9,10,12,13,12,10,11,13]);
 const input={symbol:'TEST',timeframe:'D',candles:data,observedThrough:day(9),confirmedThrough:day(9)};
 assert.deepEqual(JSON.parse(JSON.stringify(ctx.LowStructureModel.analyze(input))),M.analyze(input));
});
test('stock H4 preserves ATR across closures and resets on missing market bars',()=>{
 const start=Date.UTC(2026,0,5,14,30)/1000;
 const f=constant.map((b,i)=>({...b,time:start+Math.floor(i/2)*86400+(i%2)*14400,missingBarsBefore:0}));
 const out=run(f,{symbol:'VOYG',timeframe:'H4'});
 assert.equal(out.status,'ready');assert.equal(out.series.at(-1).segment,0);
 assert.equal(out.dataWarnings.length,0);assert.equal(out.series[13].atr,2);
 const missing=structuredClone(f);missing[40].missingBarsBefore=1;
 const gap=run(missing,{symbol:'VOYG',timeframe:'H4'});
 assert.equal(gap.series[40].segment,1);assert.equal(gap.series[40].atr,null);
 assert.equal(gap.status,'insufficient-data');
 const absent=structuredClone(f);delete absent[10].missingBarsBefore;
 assert.equal(run(absent,{symbol:'VOYG',timeframe:'H4'}).error.code,'session-continuity-required');
});
console.log(`Low structure P0: ${count} cases passed (Wilder golden, confirmed pivots, prefix causality, gaps, validation and browser/Node parity)`);
