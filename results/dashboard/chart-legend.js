(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.ChartLegend=factory();})(typeof self!=='undefined'?self:this,function(){
  'use strict';
  const observations=[
    {id:'uptrend',color:'#69d39b',label:'상승 흐름'},
    {id:'breaklow',color:'#ff777f',label:'최근 10봉 저점 아래'},
    {id:'watch',color:'#f1b65d',label:'최근 고점 접근 · 주시'},
    {id:'rebound',color:'#65cdb6',label:'반등 시도'},
    {id:'support',color:'#75aaff',label:'저점 부근 · 지지 확인 중'},
    {id:'flat',color:'#a4afc0',label:'관망'},
    {id:'unknown',color:'#8996aa',label:'자료 부족'}
  ];
  return {observations,colors:Object.fromEntries(observations.map(p=>[p.id,p.color]))};
});
