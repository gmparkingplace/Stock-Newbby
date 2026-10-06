(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.TechnicalIndicators=factory();})(typeof self!=='undefined'?self:this,function(){
  'use strict';
  const known=v=>typeof v==='number'&&Number.isFinite(v);
  const version='technical-v3',cache=new WeakMap();
  // Seed from a complete consecutive window. A missing value starts warm-up anew.
  function sma(values,period){
    if(!Number.isInteger(period)||period<1)throw new Error('invalid-period');
    return values.map((_,i)=>{
      const window=values.slice(Math.max(0,i-period+1),i+1);
      if(window.length!==period||!window.every(known))return null;
      const value=window.reduce((sum,v)=>sum+v/period,0);return known(value)?value:null;
    });
  }
  function ema(values,period){
    if(!Number.isInteger(period)||period<1)throw new Error('invalid-period');
    const out=values.map(()=>null),alpha=2/(period+1);let window=[],previous=null;
    for(let i=0;i<values.length;i++){
      const value=values[i];
      if(!known(value)){window=[];previous=null;continue;}
      if(previous==null){
        window.push(value);if(window.length<period)continue;
        previous=window.reduce((s,v)=>s+v/period,0);window=[];
      }else previous=previous+alpha*(value-previous);
      if(known(previous))out[i]=previous;else{previous=null;window=[];}
    }
    return out;
  }
  function bollinger(values,period=20,multiplier=2){
    if(!Number.isInteger(period)||period<1||!known(multiplier)||multiplier<0)throw new Error('invalid-period');
    return values.map((_,i)=>{
      const window=values.slice(Math.max(0,i-period+1),i+1);
      if(window.length!==period||!window.every(known))return null;
      const middle=window.reduce((s,v)=>s+v/period,0);
      const deviation=Math.sqrt(window.reduce((s,v)=>s+(v-middle)**2/period,0));
      const upper=middle+multiplier*deviation,lower=middle-multiplier*deviation;
      return [middle,upper,lower].every(known)?{middle,upper,lower}:null;
    });
  }
  function wma(values,period){
    if(!Number.isInteger(period)||period<1)throw new Error('invalid-period');
    const denominator=period*(period+1)/2;
    return values.map((_,i)=>{
      const window=values.slice(Math.max(0,i-period+1),i+1);
      if(window.length!==period||!window.every(known))return null;
      const value=window.reduce((sum,v,j)=>sum+v*((j+1)/denominator),0);
      return known(value)?value:null;
    });
  }
  function donchian(bars,period=20){
    if(!Number.isInteger(period)||period<1)throw new Error('invalid-period');
    return bars.map((_,i)=>{
      const window=bars.slice(Math.max(0,i-period+1),i+1);
      if(window.length!==period||!window.every(b=>known(b.high)&&known(b.low)&&b.high>=b.low))return null;
      const upper=Math.max(...window.map(b=>b.high)),lower=Math.min(...window.map(b=>b.low)),middle=upper/2+lower/2;
      return {upper,middle,lower};
    });
  }
  function obv(bars){
    const out=bars.map(()=>null);let value=0;
    for(let i=0;i<bars.length;i++){
      const b=bars[i];
      // A missing cumulative step cannot be reconstructed from later bars. No reset across gaps.
      if(!known(b.close)||!known(b.volume)||b.volume<0)break;
      if(i)value+=Math.sign(b.close-bars[i-1].close)*b.volume;
      if(!known(value))break;
      out[i]=value;
    }
    return out;
  }
  function calculate(frame){
    const bars=frame?.candles||[],closes=bars.map(b=>known(b.close)?b.close:null);
    // OBV depends on volume and Donchian on high/low: source corrections invalidate their cache too.
    const signature=JSON.stringify(bars.map(b=>[b.close,b.high,b.low,b.volume].map(v=>known(v)?v:null)));
    const saved=frame&&cache.get(frame);if(saved?.signature===signature)return saved.value;
    const fast=ema(closes,12),slow=ema(closes,26);
    const macd=closes.map((_,i)=>known(fast[i])&&known(slow[i])?fast[i]-slow[i]:null),signal=ema(macd,9);
    const value={version,seedPolicy:'sma-period',bollinger:bollinger(closes),
      ...Object.fromEntries([20,60,120,200].flatMap(n=>[['sma'+n,sma(closes,n)],['ema'+n,ema(closes,n)],['wma'+n,wma(closes,n)]])),donchian:donchian(bars),obv:obv(bars),
      macd,signal,histogram:macd.map((v,i)=>known(v)&&known(signal[i])?v-signal[i]:null)};
    if(frame)cache.set(frame,{signature,value});return value;
  }
  // Keep all timestamps for logical-axis alignment while masking future values.
  function series(bars,values,index){return bars.map((b,i)=>i<=index&&known(values[i])?{time:b.time,value:values[i]}:{time:b.time});}
  return {known,version,sma,ema,bollinger,wma,donchian,obv,calculate,series};
});
