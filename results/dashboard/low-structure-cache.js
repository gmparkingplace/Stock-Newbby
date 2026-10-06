(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory(require('./low-structure-rules'));else root.LowStructureCache=factory(root.LowStructureRules);})(typeof self!=='undefined'?self:this,function(Rules){
 'use strict';
 function create(limit=20){
  const frames=new Map(),previous=new Map();let hits=0,calculations=0;
  const serialize=v=>JSON.stringify(v,(_,x)=>x===undefined?{missing:true}:typeof x==='number'&&!Number.isFinite(x)?{nonfinite:String(x)}:typeof x==='bigint'?{bigint:String(x)}:x);
  const freeze=o=>{if(o&&typeof o==='object'&&!Object.isFrozen(o)){Object.freeze(o);Object.values(o).forEach(freeze);}return o;};
  function analyze(input){
   // Exact OHLCV, first bar, version and settings identity; never key only on bar count.
   const key=serialize([input.symbol,input.timeframe,input.version??Rules.version,input.params??{},input.sourceRevision??null,input.candles]);
   let item=frames.get(key);
   if(!item){item={prefixes:new Map()};frames.set(key,item);while(frames.size>limit)frames.delete(frames.keys().next().value);}
   else{frames.delete(key);frames.set(key,item);}
   const prefix=serialize([input.observedThrough,input.confirmedThrough]);
   const provenanceKey=serialize([input.symbol,input.timeframe,input.version??Rules.version,input.params??{},input.observedThrough,input.confirmedThrough]);
   const end=input.candles?.findIndex(b=>b.time===input.observedThrough),rows=end>=0?input.candles.slice(0,end+1):[];
   const prior=previous.get(provenanceKey),signature=serialize(rows);
   if(item.prefixes.has(prefix)&&(!prior||prior.signature===signature)){hits++;return item.prefixes.get(prefix);}
   let computed={...Rules.analyze(input),sourceRevision:input.sourceRevision??null};
   computed.confirmedIndex=computed.series.findLastIndex(b=>b.confirmed);delete computed.series;delete computed.pivots;
   if(prior&&prior.signature!==signature){
    const ids=new Set(computed.structures.map(s=>s.id));
    computed={...computed,revision:{kind:'source-correction',firstBarChanged:prior.first!==rows[0]?.time,
     changedIds:computed.structures.filter(s=>prior.structures.some(p=>p.id===s.id&&JSON.stringify(p)!==JSON.stringify(s))).map(s=>s.id),
     superseded:prior.structures.filter(s=>!ids.has(s.id)).map(s=>({id:s.id,phase:'superseded',reason:'원천 정정',replacedBy:computed.current?.[s.family]?.id||null})),notify:false}};
   }
   previous.delete(provenanceKey);previous.set(provenanceKey,{signature,first:rows[0]?.time,structures:computed.structures});
   while(previous.size>640)previous.delete(previous.keys().next().value);
   const out=freeze(computed);calculations++;
   item.prefixes.set(prefix,out);if(item.prefixes.size>32)item.prefixes.delete(item.prefixes.keys().next().value);
   return out;
  }
  return {analyze,clear(){frames.clear();previous.clear();},stats:()=>({frames:frames.size,hits,calculations,prefixes:[...frames.values()].reduce((n,f)=>n+f.prefixes.size,0)})};
 }
 return {create};
});
