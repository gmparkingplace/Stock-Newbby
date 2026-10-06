(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.VolumeProfile=factory();})(typeof self!=='undefined'?self:this,function(){
 function build(candles,index){
  const cs=candles.slice(0,index+1).filter(c=>[c.low,c.high,c.close,c.volume].every(Number.isFinite)&&c.low>0&&c.high>=c.low&&c.close>=c.low&&c.close<=c.high&&c.volume>=0);
  if(cs.length<10)return null;
  const low=Math.min(...cs.map(c=>c.low)),high=Math.max(...cs.map(c=>c.high));
  const n=high===low?1:12,step=(high-low)/n;
  const bins=Array.from({length:n},(_,i)=>({low:low+i*step,high:low+(i+1)*step,volume:0}));
  for(const c of cs){const i=step?Math.min(n-1,Math.max(0,Math.floor(((c.high+c.low+c.close)/3-low)/step))):0;bins[i].volume+=c.volume;}
  const total=bins.reduce((a,b)=>a+b.volume,0),max=Math.max(...bins.map(b=>b.volume));
  return {version:'vp-1',method:'hlc3',binCount:n,from:cs[0].time,to:cs.at(-1).time,count:cs.length,total,bins:bins.map(b=>({...b,share:total?b.volume/total:0,peak:total>0&&b.volume===max}))};
 }
 return {build};
});
