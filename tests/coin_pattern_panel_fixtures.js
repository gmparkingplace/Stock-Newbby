'use strict';
// Execute the real panel lifecycle without starting another browser or fetching prices.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const W=require('../results/dashboard/pattern-window.js'),O=require('../results/dashboard/pattern-overlay.js');
class Element{
  constructor(){this.children=[];this.hidden=false;this.textContent='';this.dataset={};}
  replaceChildren(...items){this.children=items;}append(...items){this.children.push(...items);}
  setAttribute(k,v){this[k]=v;}
}
function frame(tf){
  const times=tf==='D'?['2026-01-01','2026-01-02','2026-01-03']:[1767225600,1767240000,1767254400];
  const bars=times.map(time=>({time,open:100,high:105,low:95,close:101,volume:100}));
  const flag={patternId:tf+'-flag',type:'bull-flag',direction:'up',status:'confirmed',adjustmentStartTime:times[0],discoveredTime:times[1],barTime:times[2],
    geometry:{kind:'channel',points:[{time:times[0],price:104},{time:times[2],price:103},{time:times[2],price:96},{time:times[0],price:97}]}};
  const triangle={patternId:tf+'-triangle',type:'ascending-triangle',direction:'neutral',status:'forming',structureStartTime:times[0],discoveredTime:times[1],barTime:times[2],
    geometry:{kind:'triangle',points:[{time:times[0],price:104},{anchorTime:times[0],logicalOffset:4.5,price:104},{time:times[0],price:97}]}};
  const analysis=p=>({enabled:true,timeframe:tf,sourceStatus:'ready',sourceFetchedAt:new Date().toISOString(),provisionalEligible:true,
    timeline:[{barTime:times[2],confirmed:true,status:'ready',patterns:[p]}],recentEvents:[]});
  return {symbol:'BTC-USD',candles:bars,confirmed:true,flagAnalysis:analysis(flag),triangleAnalysis:analysis(triangle)};
}
const daily=frame('D'),h4=frame('H4'),elements=new Map(),listeners={},drawn=[];let range,activeDaily=daily,activeH4=h4;
const ctx={console,Date,Number,String,Boolean,JSON,ChartTiming:require('../results/dashboard/chart-timing'),PatternWindow:W,S:{symbol:'BTC-USD',tf:'D',selectedAsOf:null,autoRef:true,lastErr:null},
  curSym:()=>activeDaily,frameOf:()=>ctx.S.tf==='H4'?activeH4:activeDaily,
  document:{hidden:false,getElementById:id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);},
    createElement:()=>new Element(),addEventListener:(event,f)=>(listeners[event]||=[]).push(f)},
  chart:{timeScale:()=>({setVisibleLogicalRange:r=>{range=r;},getVisibleLogicalRange:()=>range})},candles:{applyOptions:o=>{ctx.priceOptions=o;},priceScale:()=>({applyOptions:o=>{ctx.scaleOptions=o;}})},PatternPanel:{openEvent:()=>{}},
  PatternOverlay:{...O,create:()=>({set:p=>{drawn.push(p);if(p)assert(O.project(p.geometry,ctx.frameOf().candles,i=>i*20,p=>200-p),'unprojectable panel geometry');}})}};
ctx.window=ctx;vm.createContext(ctx);
for(const file of ['flag-panel.js','triangle-panel.js'])vm.runInContext(fs.readFileSync(require.resolve('../results/dashboard/'+file),'utf8'),ctx);
for(const fn of listeners.DOMContentLoaded)fn();
elements.get('flagOverlayToggle').onclick();assert.equal(drawn.at(-1),null);
assert(ctx.TrianglePanel.fit());assert.equal(elements.get('flagOverlayToggle')['aria-pressed'],'true');assert.equal(drawn.at(-1).patternId,'D-triangle');
assert.equal(ctx.S.selectedAsOf,null,'fit changed observation date');ctx.FlagPanel.selectArea('auto');
for(const tf of ['D','H4','D','H4']){
  ctx.S.tf=tf;ctx.FlagPanel.render();ctx.TrianglePanel.render();
  assert.equal(ctx.FlagPanel.current().patterns[0].patternId,tf+'-flag');
  assert.equal(ctx.TrianglePanel.current().patterns[0].patternId,tf+'-triangle');
  assert.equal(drawn.at(-1).patternId,tf+'-flag');
  ctx.FlagPanel.selectArea('triangle');elements.get('triangleFit').onclick();
  assert.equal(range.from,-3);assert.equal(range.to,7.5,'H4 numeric anchor must fit the triangle');
  assert.equal(ctx.S.preset,'custom','refresh may overwrite the fit range');assert(ctx.scaleOptions.autoScale);
  const scaled=ctx.priceOptions.autoscaleInfoProvider(()=>({priceRange:{minValue:98,maxValue:102}}));assert(scaled.priceRange.minValue<97&&scaled.priceRange.maxValue>104);
  const saved=range;range={from:1,to:2};assert.equal(ctx.priceOptions.autoscaleInfoProvider(()=>42),42,'fit geometry scale survived manual zoom');range=saved;
  assert.equal(elements.get('flagOverlayToggle')['aria-pressed'],'true');
  assert.equal(drawn.at(-1).patternId,tf+'-triangle');ctx.FlagPanel.selectArea('auto');
}
// Missing H4 results must never display daily patterns.
const a=h4.flagAnalysis;delete h4.flagAnalysis;
assert.equal(ctx.FlagPanel.current().status,'disabled');assert.equal(ctx.FlagPanel.selected(),null);
h4.flagAnalysis=a;h4.confirmed=false;a.timeline[0].confirmed=false;ctx.S.autoRef=false;
assert.equal(ctx.FlagPanel.current().patterns[0].status,'paused');
assert.equal(ctx.FlagPanel.selected(),null);
ctx.TrianglePanel.render();assert(elements.get('triangleFit').disabled);const priorRange=range;assert.equal(ctx.TrianglePanel.fit(),false);assert.equal(range,priorRange,'empty fit changed the range');
if(process.env.COIN_REPLAY){
  const frames=JSON.parse(fs.readFileSync(process.env.COIN_REPLAY,'utf8')),checks=[];
  for(const symbol of ['BTC-USD','ETH-USD']){
    activeDaily=frames.find(p=>p.symbol===symbol&&(p.tf||'D')==='D');activeH4=frames.find(p=>p.symbol===symbol&&p.tf==='H4');
    assert(activeDaily&&activeH4);ctx.S.symbol=symbol;ctx.S.autoRef=true;
    for(const tf of ['D','H4'])for(const [family,panel] of [['flag',ctx.FlagPanel],['triangle',ctx.TrianglePanel]]){
      ctx.S.tf=tf;const f=ctx.frameOf(),a=f[family+'Analysis'];
      const row=a.timeline.findLast(r=>r.confirmed&&r.patterns.some(p=>!['paused','failed','expired'].includes(p.status)));
      if(!row)continue;
      ctx.S.selectedAsOf=row.barTime;ctx.FlagPanel.render();ctx.TrianglePanel.render();ctx.FlagPanel.selectArea(family);
      const p=panel.selected();assert(p&&drawn.at(-1)?.patternId===p.patternId);
      assert(!elements.get(family+'State').textContent.includes('unsupported'));
      if(family==='triangle'){elements.get('triangleFit').onclick();assert(Number.isFinite(range.from)&&Number.isFinite(range.to));}
      checks.push({symbol,tf,family,barTime:row.barTime,patternId:p.patternId,type:p.type,status:p.status});
    }
  }
  assert(checks.length>=6,'cached real examples were not exercised');
  fs.writeFileSync(process.env.COIN_REPLAY.replace('replay-frames.json','panel-replay.json'),JSON.stringify(checks,null,2));
  console.log('Cached BTC/ETH panel/geometry replays:',checks.length);
}
console.log('Coin D/H4 panel lifecycle, separate frame evidence, opaque geometry, numeric fit and pause passed');
