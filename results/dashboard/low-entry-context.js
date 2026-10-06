(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory(require('./low-structure-cache'),require('./low-entry-model'),require('./chart-timing'));else root.LowEntryContext=factory(root.LowStructureCache,root.LowEntryModel,root.ChartTiming);})(typeof self!=='undefined'?self:this,function(Cache,Entry,Timing){
 'use strict';
 const cache=Cache.create(20);
 function evaluate({frame,index=frame?.candles?.length-1,symbol,tf,historical=false,selected=['R','H'],maxAtr=.5,quote=null,lastError=null,enabled=true,now}={}){
  if(!frame?.candles?.length)return null;
  const bars=frame.candles;let idx=index,confirmedIndex=bars.findIndex(c=>c.time===frame.lastConfirmedTime);
  if(!historical&&frame.marketSession?.state==='closed')idx=confirmedIndex;
  // An explicit cutoff is mandatory for live data. Historical selection may only
  // use past bars below it; archived frames lacking metadata are historical-only.
  if(historical&&confirmedIndex<0&&frame.source!=='toss'&&frame.source!=='yfinance')confirmedIndex=frame.confirmed===false?bars.length-2:bars.length-1;
  confirmedIndex=Math.min(idx,confirmedIndex);
  const basis=bars[idx]?.time??null,confirmedThrough=bars[confirmedIndex]?.time??null;
  const analysis=cache.analyze({symbol:symbol||frame.symbol,timeframe:tf||frame.tf||'D',candles:bars,
   observedThrough:basis,confirmedThrough,sourceRevision:frame.sourceRevision??frame.priceBasis??null,params:{maxAtr}});
  const timing=Timing.assess({symbol,tf,historical,basis,quote,source:frame.source,barAsOf:frame.barAsOf||null,now,
   marketSession:frame.marketSession,fetchedAt:frame.fetchedAt,snapshotEligible:frame.snapshotEligible,
   confirmed:idx>=0&&idx===confirmedIndex,lastError,enabled});
  const decision=Entry.evaluate({analysis,selected,timing,historical,provisional:idx!==confirmedIndex});
  // Current OHLC of a forming bar cannot be used as a confirmed entry price.
  return {analysis,decision:{...decision,index:idx,observationBasis:basis,fetchedAt:frame.fetchedAt,source:frame.source},timing};
 }
 return {evaluate,cache};
});
