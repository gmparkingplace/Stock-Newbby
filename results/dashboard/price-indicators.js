/* Price overlays use the selected frame and never collect data or change strategy rules. */
(function(){
  'use strict';
  const math=typeof module!=='undefined'&&module.exports?require('./technical-indicators.js'):TechnicalIndicators;
  const periods=[20,60,120,200],colors=['#2962ff','#FF6D00','#7c3aed','#0f766e'];
  const definitions={};
  for(const kind of ['sma','ema','wma'])definitions[kind]={label:kind.toUpperCase()+' 20·60·120·200',names:periods.map(n=>kind.toUpperCase()+' '+n),
    help:'파랑 20봉 · 주황 60봉 · 보라 120봉 · 초록 200봉입니다. '+(kind==='sma'?'종가의 단순평균입니다.':kind==='ema'?'최근 가격 비중을 높이는 지수평균입니다.':'오래된 봉부터 1~기간 길이 가중치를 적용한 평균입니다.')+' 전략 A/F는 기존 SMA 20·60을 사용합니다.'};
  definitions.bollinger={label:'볼린저 20·2',names:['상단','중심선','하단'],help:'초록 상·하단 · 보라 중심선입니다. 20봉 종가 평균 ± 표준편차 2배이며, 밴드 폭은 변동성을 나타냅니다.'};
  definitions.donchian={label:'돈치안 채널 20',names:['20봉 고가','중심선','20봉 저가'],help:'빨강 상단 · 회색 중심 · 파랑 하단입니다. 현재 봉을 포함한 최근 20봉 고가·저가와 두 값의 중간입니다. 현재 봉을 제외하는 C/F 돌파 기준과 다릅니다.'};
  const channel=kind=>kind==='bollinger'||kind==='donchian';
  function build(frame,kind,index){
    const bars=frame?.candles||[],definition=definitions[kind],count=channel(kind)?3:4;
    if(!definition||!bars[index])return {kind,status:kind==='none'?'hidden':'unavailable',basisTime:null,values:Array(count).fill(null),series:Array.from({length:count},()=>[])};
    const computed=math.calculate(frame);
    // SMA20/60 keep the source values used by strategy A/F. Long averages are local overlays.
    const arrays=channel(kind)?['upper','middle','lower'].map(k=>computed[kind].map(v=>v?.[k])):periods.map(n=>{
      if(kind==='sma'&&n<=60){const map=new Map((frame.lines?.['sma'+n]||[]).map(p=>[String(p.time),p.value]));return bars.map(b=>map.get(String(b.time)));}
      return computed[kind+n];
    });
    const values=arrays.map(a=>math.known(a[index])?a[index]:null),available=values.filter(math.known).length;
    return {kind,label:definition.label,basisTime:bars[index].time,values,names:definition.names,unit:'price',
      periodBars:channel(kind)?20:200,parameters:kind==='bollinger'?{period:20,multiplier:2,stddev:'population'}:kind==='donchian'?{period:20,includeCurrent:true,offset:0}:{periods, ...(kind==='wma'?{weights:'linear-oldest-1-newest-period'}:{})},
      calculationVersion:math.version,seedPolicy:kind==='ema'?'sma-period':null,
      status:available===count?'ready':available?'partial-data':'insufficient-data',provisional:index===bars.length-1&&frame.confirmed===false,
      series:arrays.map(a=>math.series(bars,a,index))};
  }
  if(typeof module!=='undefined'&&module.exports){module.exports={build,definitions};return;}
  const $=id=>document.getElementById(id);let kind='sma',bands=[],longAverages=[],last='';
  function current(){
    const f=frameOf(curSym()),{series,...summary}=build(f,kind,asOfIdx());
    const fetched=f?.fetchedAt||LIVE_META[metaKey(S.symbol,S.tf)]?.fetchedAt||null,age=Date.now()-Date.parse(fetched);
    const paused=Boolean(S.lastErr)||Boolean(summary.provisional&&(!S.autoRef||document.hidden||!Number.isFinite(age)||age<0||age>90000));
    return {...summary,symbol:S.symbol,timeframe:S.tf,sourceFetchedAt:fetched,sourcePaused:paused,status:paused&&['ready','partial-data'].includes(summary.status)?'paused':summary.status};
  }
  function readout(){
    const s=current();$('priceIndicatorReadout').hidden=kind==='none';$('priceIndicatorHelp').hidden=false;
    if(kind==='none'){$('priceIndicatorHelp').textContent='가격 지표를 숨긴 상태입니다.';last=JSON.stringify(s);return;}
    $('priceIndicatorDate').textContent=s.basisTime==null?'—':fmtT(s.basisTime);
    for(let i=0;i<4;i++){
      $('priceIndicatorCell'+i).hidden=channel(kind)&&i===3;
      $('priceIndicatorLabel'+i).textContent=definitions[kind].names[i]||'—';$('priceIndicatorLabel'+i).style.color=channel(kind)?'':colors[i];
      $('priceIndicatorValue'+i).textContent=s.values[i]==null?'자료 부족':fmtP(s.values[i]);
    }
    $('priceIndicatorStatus').textContent=s.status==='paused'?'자료 보류':s.status==='partial-data'?'일부 자료 부족':s.status!=='ready'?'계산 자료 부족':s.provisional?'진행 중 · 잠정':'확정봉 기준';
    for(const id of ['priceIndicatorDate','priceIndicatorValue0','priceIndicatorValue1','priceIndicatorValue2','priceIndicatorValue3','priceIndicatorStatus'])$(id).title=$(id).textContent;
    $('priceIndicatorHelp').textContent=definitions[kind].help;last=JSON.stringify(s);
  }
  function render(){
    if(!bands.length)return;readout();
    const data=build(frameOf(curSym()),kind,asOfIdx()),moving=['sma','ema','wma'].includes(kind);
    [sma20S,sma60S,...longAverages].forEach((series,i)=>{
      series.applyOptions({visible:moving,color:colors[i],title:moving?definitions[kind].names[i]:''});
      series.setData(moving?data.series[i]:[]);
    });
    const channelColors=kind==='donchian'?['#d32f2f','#64748b','#1859C9']:['#0f766e','#7c3aed','#0f766e'];
    bands.forEach((series,i)=>{series.applyOptions({visible:channel(kind),color:channelColors[i],title:channel(kind)?definitions[kind].names[i]:''});series.setData(channel(kind)?data.series[i]:[]);});
  }
  function tick(){if(bands.length&&JSON.stringify(current())!==last)readout();}
  window.PriceIndicators={current,render,tick,series:()=>channel(kind)?bands:[sma20S,sma60S,...longAverages]};
  document.addEventListener('DOMContentLoaded',()=>{
    longAverages=colors.slice(2).map(color=>chart.addSeries(LightweightCharts.LineSeries,{color,lineWidth:1,priceLineVisible:false,lastValueVisible:false,visible:false}));
    bands=['#0f766e','#7c3aed','#0f766e'].map((color,i)=>chart.addSeries(LightweightCharts.LineSeries,{color,lineWidth:i===1?1:2,lineStyle:i===1?2:0,priceLineVisible:false,lastValueVisible:false,visible:false}));
    $('priceIndicatorChoice').onchange=e=>{kind=e.target.value;render();};
    document.addEventListener('visibilitychange',tick);render();
  });
})();
