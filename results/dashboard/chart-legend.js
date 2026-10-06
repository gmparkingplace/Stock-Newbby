(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.ChartLegend=factory();})(typeof self!=='undefined'?self:this,function(){
  'use strict';
  const observations=[
    {id:'uptrend',color:'#2E7D32',label:'상승 흐름'},
    {id:'breaklow',color:'#C62828',label:'최근 10봉 저점 아래'},
    {id:'watch',color:'#B26A00',label:'최근 고점 접근 · 주시'},
    {id:'rebound',color:'#00695C',label:'반등 시도'},
    {id:'support',color:'#1859C9',label:'저점 부근 · 지지 확인 중'},
    {id:'flat',color:'#536675',label:'관망'},
    {id:'unknown',color:'#9AA5B0',label:'자료 부족'}
  ];
  return {observations,colors:Object.fromEntries(observations.map(p=>[p.id,p.color]))};
});
