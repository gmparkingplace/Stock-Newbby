/* P0 foundation only. No entry decisions, DOM, provider requests or wall-clock reads. */
(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory();
  else root.LowStructureModel=factory();
})(typeof self!=='undefined'?self:this,function(){
  'use strict';
  const version='low-entry-v1-draft';
  const defaults=Object.freeze({leftBars:2,rightBars:2,atrPeriod:14});
  const finite=v=>typeof v==='number'&&Number.isFinite(v);
  const absent=v=>v===null||v===undefined;
  const fail=(code,details={})=>({code,...details});
  function validTime(time,timeframe){
    if(timeframe==='H4')return Number.isSafeInteger(time)&&time>0&&time%14400===0&&Number.isFinite(new Date(time*1000).getTime());
    if(typeof time!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(time)||time.startsWith('0000-'))return false;
    const stamp=new Date(time+'T00:00:00Z');
    return Number.isFinite(stamp.getTime())&&stamp.toISOString().slice(0,10)===time;
  }
  function parameters(value){
    if(value===undefined)value={};
    if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(k=>!Object.hasOwn(defaults,k)))return null;
    const p={...defaults,...value};
    if(![p.leftBars,p.rightBars].every(v=>Number.isInteger(v)&&v>=1&&v<=5)||p.atrPeriod!==14)return null;
    return p;
  }
  function validateBar(bar,index,timeframe,previousTime){
    if(!bar||typeof bar!=='object'||Array.isArray(bar))return fail('invalid-bar',{index});
    const {time}=bar;
    if(!validTime(time,timeframe))return fail('invalid-bar-time',{index,time});
    if(previousTime!==null&&time<=previousTime)return fail('invalid-bar-order',{index,time});
    for(const field of ['open','high','low','close']){
      if(!absent(bar[field])&&(!finite(bar[field])||bar[field]<=0))return fail('invalid-price',{index,time,field});
    }
    if((finite(bar.high)&&finite(bar.low)&&bar.high<bar.low)||
       ['open','close'].some(k=>finite(bar[k])&&((finite(bar.high)&&bar[k]>bar.high)||(finite(bar.low)&&bar[k]<bar.low))))
      return fail('invalid-ohlc-range',{index,time});
    if(!absent(bar.volume)&&(!finite(bar.volume)||bar.volume<0))return fail('invalid-volume',{index,time});
    return null;
  }
  function analyze(input={}){
    const base={version,stage:'foundation',status:'invalid-data',error:null,dataWarnings:[],
      observedThrough:null,confirmedThrough:null,basis:null,parameters:null,series:[],pivots:[],structures:[]};
    const reject=(code,details={})=>({...base,error:fail(code,details)});
    if(!input||typeof input!=='object'||Array.isArray(input))return reject('invalid-input');
    const {symbol,candles,timeframe,observedThrough,confirmedThrough}=input;
    if(!['D','H4'].includes(timeframe))return {...base,status:'unsupported',error:null,reason:'timeframe-not-supported'};
    if(typeof symbol!=='string'||!symbol.trim()||symbol.length>32)return reject('invalid-symbol');
    if(timeframe==='H4'&&!/^[A-Z0-9]+-USD$/.test(symbol.toUpperCase()))return {...base,status:'unsupported',reason:'h4-crypto-only'};
    const params=parameters(input.params);
    if(!params)return reject('invalid-parameters');
    if(input.version!==undefined&&input.version!==version)return reject('unsupported-version');
    if(!Array.isArray(candles))return reject('invalid-candles');
    if(!Object.hasOwn(input,'observedThrough')||!Object.hasOwn(input,'confirmedThrough'))return reject('cutoff-required');
    if(!candles.length){
      if(observedThrough!==null||confirmedThrough!==null)return reject('invalid-cutoff');
      return {...base,status:'unavailable',reason:'no-candles',parameters:params};
    }
    if(!validTime(observedThrough,timeframe))return reject('invalid-observed-cutoff');
    // Stop at the requested prefix. Invalid or corrected future bars do not affect this result.
    let end=-1;
    for(let i=0;i<candles.length;i++)if(candles[i]?.time===observedThrough){end=i;break;}
    if(end<0)return reject('observed-cutoff-not-found');
    let confirmed=-1,previousTime=null;
    for(let i=0;i<=end;i++){
      const error=validateBar(candles[i],i,timeframe,previousTime);
      if(error)return {...base,error};
      previousTime=candles[i].time;
      if(previousTime===confirmedThrough)confirmed=i;
    }
    if(confirmedThrough!==null){
      if(!validTime(confirmedThrough,timeframe))return reject('invalid-confirmed-cutoff');
      if(confirmedThrough>observedThrough)return reject('confirmation-after-observation');
      if(confirmed<0)return reject('confirmed-cutoff-not-found');
    }
    const series=[],warnings=[];
    let segment=-1,needsSegment=true,previousClose=null,seed=[],atr=null;
    for(let i=0;i<=end;i++){
      const b=candles[i],priceReady=['open','high','low','close'].every(k=>finite(b[k]));
      const volumeStatus=absent(b.volume)?'missing':b.volume===0?'zero':'known';
      if(volumeStatus==='missing')warnings.push({code:'volume-missing',index:i,time:b.time});
      const timeGap=timeframe==='H4'&&i>0&&b.time-candles[i-1].time!==14400;
      if(timeGap){warnings.push({code:'bar-gap',index:i,time:b.time});needsSegment=true;previousClose=null;seed=[];atr=null;}
      if(!priceReady){
        warnings.push({code:'price-missing',index:i,time:b.time});
        needsSegment=true;previousClose=null;seed=[];atr=null;
        series.push({time:b.time,segment:null,priceReady:false,volumeStatus,confirmed:i<=confirmed,tr:null,atr:null,previewAtr:null});
        continue;
      }
      if(needsSegment){segment++;needsSegment=false;}
      const tr=previousClose===null?b.high-b.low:Math.max(b.high-b.low,Math.abs(b.high-previousClose),Math.abs(b.low-previousClose));
      if(atr===null){
        seed.push(tr);
        if(seed.length===params.atrPeriod){atr=seed.reduce((mean,v,j)=>mean+(v-mean)/(j+1),0);seed=[];}
      }else atr=atr+(tr-atr)/params.atrPeriod;
      previousClose=b.close;
      series.push({time:b.time,segment,priceReady:true,volumeStatus,confirmed:i<=confirmed,
        tr:i<=confirmed?tr:null,atr:i<=confirmed?atr:null,previewAtr:i>confirmed?atr:null});
    }
    const pivots=[];
    for(let j=params.leftBars;j+params.rightBars<=confirmed;j++){
      const c=series[j];
      if(!c.priceReady)continue;
      const start=j-params.leftBars,finish=j+params.rightBars;
      if(series.slice(start,finish+1).some(b=>!b.priceReady||b.segment!==c.segment))continue;
      for(const [kind,field,direction] of [['low','low',-1],['high','high',1]]){
        const price=candles[j][field];
        const left=candles.slice(start,j).every(b=>direction*price>=direction*b[field]);
        const right=candles.slice(j+1,finish+1).every(b=>direction*price>direction*b[field]);
        if(left&&right)pivots.push({kind,price,occurredAt:c.time,knownAt:series[finish].time,
          index:j,knownIndex:finish,segment:c.segment,atrBefore:series[j-1]?.segment===c.segment?series[j-1].atr:null});
      }
    }
    const current=series[confirmed];
    const ready=!!current?.priceReady&&finite(current.atr)&&current.atr>0;
    const status=confirmed<0?'unconfirmed':ready?'ready':'insufficient-data';
    const reason=confirmed<0?'no-confirmed-bars':!current.priceReady?'price-gap':current.atr===0?'atr-zero':ready?null:'atr-warmup';
    return {...base,status,reason,error:null,symbol:symbol.toUpperCase(),timeframe,parameters:params,
      observedThrough,confirmedThrough,basis:confirmed<0?null:series[confirmed].time,
      dataWarnings:warnings,series,pivots};
  }
  return {version,defaults,analyze};
});
