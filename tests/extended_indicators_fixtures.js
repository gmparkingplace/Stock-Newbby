'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const M=require('../results/dashboard/technical-indicators.js'),P=require('../results/dashboard/price-indicators.js'),A=require('../results/dashboard/indicator-panel.js');
const near=(a,b)=>assert(Math.abs(a-b)<1e-9,`${a} != ${b}`);
const w=M.wma([1,2,3,4],3);assert.deepEqual(w.slice(0,2),[null,null]);near(w[2],14/6);near(w[3],20/6);
const wg=M.wma([1,2,null,4,5,6],3);assert(wg.slice(0,5).every(v=>v===null));near(wg[5],32/6);
assert.deepEqual(M.wma([0,0],2),[null,0]);assert.throws(()=>M.wma([],0));
assert.throws(()=>M.donchian([],0));
const d=[{high:3,low:1},{high:4,low:2},{high:7,low:4},{high:5,low:3}];
assert.deepEqual(M.donchian(d,3),[null,null,{upper:7,middle:4,lower:1},{upper:7,middle:4.5,lower:2}]);
assert.equal(M.donchian([{high:1,low:2}],1)[0],null);
assert.equal(M.donchian([{high:null,low:0}],1)[0],null);
const bars=[10,11,11,9,10,9].map((close,i)=>({time:i+1,close,volume:[100,20,30,50,0,2.5][i]}));
assert.deepEqual(M.obv(bars),[0,20,20,-30,-30,-32.5]);
for(const field of ['close','volume']){
 const bad=structuredClone(bars);bad[2][field]=null;
 assert.deepEqual(M.obv(bad),[0,20,null,null,null,null],'cumulative gap was silently filled');
 const first=structuredClone(bars);first[0][field]=null;assert(M.obv(first).every(v=>v===null));
}
const negative=structuredClone(bars);negative[3].volume=-1;assert.equal(M.obv(negative)[3],null);
assert.equal(M.obv([{close:1,volume:0}])[0],0);
const huge=[{close:1,volume:1},{close:2,volume:Number.MAX_VALUE},{close:3,volume:Number.MAX_VALUE}];assert.equal(M.obv(huge)[2],null);
const frame={confirmed:false,fetchedAt:new Date().toISOString(),candles:Array.from({length:85},(_,i)=>({time:1767225600+i*14400,open:100+i,close:100+i%9+i/10,high:115+i%6,low:95-i%4,volume:100+i/10})),state:[],lines:{}};
const original=JSON.stringify(frame),computed=M.calculate(frame);
// Independent weighted totals, complete periods and exact channel extremes.
for(const n of [20,60]){
 const segment=frame.candles.slice(85-n);let numerator=0,denominator=0;
 segment.forEach((b,j)=>{numerator+=b.close*(j+1);denominator+=j+1;});near(computed['wma'+n][84],numerator/denominator);
}
assert.equal(P.build(frame,'wma',18).status,'insufficient-data');assert.equal(P.build(frame,'wma',19).status,'partial-data');assert.equal(P.build(frame,'wma',59).status,'partial-data');
assert.equal(P.build(frame,'donchian',18).status,'insufficient-data');assert.equal(P.build(frame,'donchian',19).status,'ready');
assert.deepEqual(P.build(frame,'donchian',84).values,[120,106,92]);
assert(P.build(frame,'wma',84).provisional);assert(A.build(frame,'obv',84).provisional);
assert.equal(A.build(frame,'obv',0).value,0);assert.equal(A.build(frame,'obv',0).seedTime,frame.candles[0].time);
for(let n=1;n<=85;n++){
 const part={...frame,candles:frame.candles.slice(0,n)},data=M.calculate(part);
 for(const key of ['wma20','wma60','donchian','obv'])assert.deepEqual(data[key],computed[key].slice(0,n));
}
for(const kind of ['wma','donchian','obv']){
 const builder=kind==='obv'?A:P,past=builder.build(frame,kind,40),future=structuredClone(frame);
 future.candles.slice(41).forEach(b=>{b.close=9999;b.high=10000;b.low=9998;b.volume=999999;});
 assert.deepEqual(builder.build(future,kind,40),past,'future source values leaked into historical selection');
 const series=kind==='obv'?[past.series]:past.series;assert(series.every(s=>s.slice(41).every(p=>Object.keys(p).length===1)));
}
assert.equal(M.calculate(frame),computed);
for(const field of ['close','volume','high','low']){
 const revised=structuredClone(frame),old=M.calculate(revised);revised.candles[84][field]+=field==='low'?-5:field==='high'?100:5;
 const next=M.calculate(revised);assert.notEqual(next,old,'OHLCV correction kept old cache');
 if(field==='volume')assert.notEqual(next.obv[84],old.obv[84]);
 if(field==='high')assert.notEqual(next.donchian[84].upper,old.donchian[84].upper);
 if(field==='low')assert.notEqual(next.donchian[84].lower,old.donchian[84].lower);
}
assert.equal(JSON.stringify(frame),original);
// Execute the real UI scripts with recording chart adapters. No browser, timers or provider calls.
class Element{
 constructor(){this.hidden=false;this.textContent='';this.style={};this.clientWidth=900;this.clientHeight=180;this.listeners={};}
}
let created=0;
class Series{
 constructor(options={}){created++;this.config={...options};this.data=[];this.lines=[];}
 applyOptions(o){Object.assign(this.config,o);}setData(rows){this.data=rows;}
 createPriceLine(o){this.lines.push(o);return o;}removePriceLine(o){this.lines=this.lines.filter(l=>l!==o);}
}
class Plot{
 constructor(){this.config={rightPriceScale:{minimumWidth:80}};this.range={from:40,to:84};}
 addSeries(_,o){return new Series(o);}applyOptions(o){for(const [k,v] of Object.entries(o))this.config[k]={...this.config[k],...v};}
 options(){return this.config;}priceScale(){return {width:()=>80};}
 timeScale(){return {getVisibleLogicalRange:()=>this.range,setVisibleLogicalRange:r=>{this.range=r;},subscribeVisibleLogicalRangeChange:()=>{}};}
}
const elements=new Map(),listeners={},el=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const ctx={console,Date,TechnicalIndicators:M,chart:new Plot(),sma20S:new Series(),sma60S:new Series(),S:{symbol:'BTC-USD',tf:'H4',autoRef:true,lastErr:null},LIVE_META:{},metaKey:()=>'',curSym:()=>frame,frameOf:()=>frame,asOfIdx:()=>84,fmtT:String,fmtP:n=>'$'+n,
 document:{hidden:false,getElementById:el,addEventListener:(name,fn)=>(listeners[name]||=[]).push(fn)},
 LightweightCharts:{LineSeries:'line',HistogramSeries:'histogram',createChart:()=>new Plot()},requestAnimationFrame:fn=>fn(),ResizeObserver:class{observe(){}}};
ctx.window=ctx;vm.createContext(ctx);
for(const file of ['price-indicators.js','indicator-panel.js'])vm.runInContext(fs.readFileSync(require.resolve('../results/dashboard/'+file),'utf8'),ctx);
for(const fn of listeners.DOMContentLoaded)fn();const initialSeries=created;
const choosePrice=kind=>el('priceIndicatorChoice').onchange({target:{value:kind}}),chooseAux=kind=>el('indicatorChoice').onchange({target:{value:kind}});
for(const tf of ['H4','D','W','M']){
 ctx.S.tf=tf;
 for(const kind of ['wma','donchian','bollinger','ema','sma','none']){
  choosePrice(kind);assert.equal(ctx.PriceIndicators.current().kind,kind);
  if(['donchian','bollinger'].includes(kind)){assert.equal(ctx.PriceIndicators.series().length,3);assert(ctx.PriceIndicators.series().every(s=>s.config.visible));assert.equal(ctx.sma20S.config.visible,false);assert(el('priceIndicatorCell3').hidden);}
  else if(kind!=='none'){assert(ctx.sma20S.config.visible);assert.equal(ctx.PriceIndicators.series().length,4);assert(!el('priceIndicatorCell3').hidden);if(kind!=='sma')assert(ctx.PriceIndicators.series()[0].data.some(p=>p.value!=null));else assert.equal(ctx.PriceIndicators.current().status,'insufficient-data');}
 }
 choosePrice('wma');
 for(const kind of ['rsi','obv','macd','obv','volume','atr','none']){
  chooseAux(kind);assert.equal(ctx.IndicatorPanel.kind(),kind);
  if(kind==='obv'){
   const s=ctx.IndicatorPanel.series();assert(s.line.config.visible);assert(!s.histogram.config.visible);assert(!s.signal.config.visible);assert.equal(s.line.config.priceFormat.type,'volume');
   assert.equal(s.line.config.autoscaleInfoProvider(()=>42),42,'RSI fixed scale survived OBV switch');
   assert(el('indicatorHelp').textContent.includes('첫 봉을 0'));
   assert.equal(ctx.IndicatorPanel.current().basisTime,ctx.PriceIndicators.current().basisTime);
  }
 }
}
assert.equal(created,initialSeries,'changing indicators accumulated chart series');
choosePrice('donchian');chooseAux('obv');ctx.S.autoRef=false;
assert.equal(ctx.PriceIndicators.current().status,'paused');assert.equal(ctx.IndicatorPanel.current().status,'paused');
assert.equal(el('indicatorStatus').textContent,'진행 중 · 잠정');ctx.IndicatorPanel.tick();ctx.PriceIndicators.tick();assert.equal(el('indicatorStatus').textContent,'자료 보류');
const html=fs.readFileSync(require.resolve('../results/dashboard/chart-first.html'),'utf8');
for(const kind of ['wma','donchian','obv'])assert(html.includes(`value="${kind}"`));
console.log('WMA/Donchian/OBV: independent values, gaps, corrections, historical isolation, real panel lifecycle and fixed series passed');
