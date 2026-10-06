'use strict';
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const html = fs.readFileSync(require('path').join(__dirname, '../results/dashboard/chart-first.html'), 'utf8');
const source = html.split('/* 관찰/신호 마커 합성 렌더:')[1].split('/* 강조선:')[0];
const candles = Array.from({length:80}, (_, i) => ({time:1000+i, close:100, volume:10}));
const frame = {candles, marks:{F:[10,12,14,16,22,30,40,50,60,70,75].map(i=>({time:1000+i,side:'entry'}))}};
const observations = candles.map((c,i)=>({statusId:i%5===0?'watch':'flat',label:'상태',observationAsOf:c.time}));
let range={from:1000,to:1079}, rendered, width=8000;
const elements={};
const ctx={ChartLegend:require('../results/dashboard/chart-legend.js'),S:{showSig:true,showObs:true,selectedAsOf:null}, window:{matchMedia:()=>({matches:false})},
 chart:{timeScale:()=>({getVisibleRange:()=>range,width:()=>width,timeToCoordinate:t=>10+(t-range.from)/(range.to-range.from)*(width-20)})},
 document:{createElement:()=>({getContext:()=>({measureText:t=>({width:t.length*12})})})}, ChartLayout:require("../results/dashboard/chart-layout"), asOfIdx:()=>79, curSym:()=>'',frameOf:()=>frame,
 $:id=>elements[id]||(elements[id]={}), candles:{},markersPlugin:null,UP:'red',DOWN:'blue',
 LightweightCharts:{createSeriesMarkers:(_,m)=>{rendered=m;return{setMarkers:m=>rendered=m}}},
 latestTime:f=>f.candles.at(-1).time,obsIdx:()=>79,fmtT:String,tfWord:()=> '일봉'};
const ChartUtil = require('../results/dashboard/chart-util.js');
// 마커 구간의 pickObsLabels/obsTransitions는 브라우저에서 ChartUtil이 제공한다. 픽스처도 같은 모듈을 쓴다.
ctx.pickObsLabels = ChartUtil.pickObsLabels; ctx.obsTransitions = ChartUtil.obsTransitions;
vm.createContext(ctx);
vm.runInContext('/*'+source, ctx);
ctx.observations=observations;
vm.runInContext('buildObservationSeries = () => observations;',ctx);
vm.runInContext('renderMarkers()',ctx);
assert(rendered.filter(m=>m.shape==='circle').length<=8,'dense transitions sampled independently of viewport');
const firstMarkers=JSON.stringify(rendered);
for(let n=0;n<50;n++)vm.runInContext('renderMarkers()',ctx);
assert.equal(JSON.stringify(rendered),firstMarkers,'repainting must replace markers without accumulating circles');
const baseline=JSON.stringify(frame);const colors=new Map(rendered.filter(m=>m.shape==='arrowUp').map(m=>[m.time,m.color]));
assert.equal(rendered.find(m=>m.time===1016&&m.shape==='arrowUp').color,'#e65100');
for (const r of [{from:1015,to:1045},{from:1030,to:1040},{from:1000,to:1079}]) {
 range=r;width=500;vm.runInContext('renderMarkers()',ctx);
 assert.equal(JSON.stringify(frame),baseline,'Viewport must not change raw signal data');
 for(const m of rendered.filter(m=>m.shape==='arrowUp'))assert.equal(m.color,colors.get(m.time),'full-history signal color preserved');
}
assert.equal(ctx.S.selectedAsOf,null);
const hover=html.split('chart.subscribeCrosshairMove((p) => {')[1].split('let gestureStart')[0];
assert(!hover.includes('showObsPreview('),'Hover must not replace judgment');
console.log('Chart viewport regression: unchanged raw signals with collision-aware displays across 3 ranges, full-history signal color and fixed judgment passed');
