(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.PatternWindow=factory();})(typeof self!=='undefined'?self:this,function(){
  'use strict';
  function start(reference){
    if(typeof reference==='number'){
      if(!Number.isSafeInteger(reference)||reference<=0)return null;
      const t=new Date(reference*1000);if(!Number.isFinite(t.getTime()))return null;
      const last=new Date(Date.UTC(t.getUTCFullYear(),t.getUTCMonth()-2,0)).getUTCDate();
      return Date.UTC(t.getUTCFullYear(),t.getUTCMonth()-3,Math.min(t.getUTCDate(),last),t.getUTCHours(),t.getUTCMinutes(),t.getUTCSeconds())/1000;
    }
    if(!/^\d{4}-\d{2}-\d{2}$/.test(reference||''))return null;
    const [y,m,d]=reference.split('-').map(Number),last=new Date(Date.UTC(y,m-3,0)).getUTCDate();
    return new Date(Date.UTC(y,m-4,Math.min(d,last))).toISOString().slice(0,10);
  }
  const first=p=>p.poleStartTime||p.structureStartTime||p.adjustmentStartTime||p.anchorTime||p.confirmedBarTime||p.barTime;
  function within(p,reference){const from=start(reference),begin=first(p),end=p.confirmedBarTime||p.barTime||begin;return !!(from&&begin&&end&&from<=begin&&begin<=end&&end<=reference);}
  const filter=(items,reference)=>(items||[]).filter(p=>within(p,reference));
  const format=t=>typeof t==='number'?new Date(t*1000).toLocaleString('ko-KR',{hour12:false}):t;
  return {start,first,within,filter,format};
});
